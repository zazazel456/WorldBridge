"""Auxiliary files of a Legacy Console Edition save that are not NBT: rewritten for the target platform.

``data/largeMapDataMappings.dat`` (``DirectoryLevelStorage::prepareLevel`` / ``saveMapIdLookup`` of the game) is
the only one whose layout depends on the platform.  Every integer is big endian on every platform, but the
player id (``PlayerUID``) is written as ``sizeof(PlayerUID)`` raw bytes, and that size is not the same everywhere::

    int32  count
    count x { PlayerUID uid, int32 n, n x { int64 key, int32 value } }
    byte   used[...]      bit field of the map ids in use (32 bytes; 1024 on the PS4)

Real saves: Xbox 360 / Windows64 an 8 byte XUID, PS3 / Vita / PS4 28 bytes (online id, 2 zero bytes, the 6 bytes
of the console user's id, the rest), Wii U 20 bytes.  A file read with another size makes the game read garbage
counts: neoLegacy then loops "-- -1 (0xffffffffffffffff) = -1" for gigabytes of log and never starts the world.
"""

from __future__ import annotations

import re
import struct
from typing import Callable, Dict, List, Optional, Sequence, Tuple

MAPPINGS_FILE = "data/largeMapDataMappings.dat"

# bytes of a PlayerUID in the file, by platform (measured on real saves; None: not seen in a real save)
UID_LEN: Dict[str, Optional[int]] = {
    "win64": 8, "xbox360": 8, "ps3": 28, "vita": 28, "ps4": 28, "wiiu": 20, "xboxone": None, "switch": None,
}
_FAMILY = {"win64": "xuid", "xbox360": "xuid", "ps3": "sony", "vita": "sony", "ps4": "sony", "wiiu": "wiiu"}
_TRAILER = {"ps4": 1024}
_DEFAULT_TRAILER = 32
_MAX_ENTRIES = 4096
_SONY_NAME = re.compile(r"^[PN]_([0-9A-Fa-f]{12})_\d{8}_?(.*)$")

Entry = Tuple[bytes, List[Tuple[bytes, bytes]]]  # (uid, [(key, value), ...]) raw big endian


def trailer_size(platform: str) -> int:
    return _TRAILER.get(platform, _DEFAULT_TRAILER)


def parse_mappings(blob: bytes, uid_len: int) -> Optional[Tuple[List[Entry], bytes]]:
    """The entries and the used-ids bit field of a file written with ``uid_len`` byte player ids, or None when
    the bytes do not follow that layout (counts out of range, entries running past the end)."""
    n = len(blob)
    if n < 4:
        return None
    count = struct.unpack_from(">I", blob, 0)[0]
    if count > _MAX_ENTRIES:
        return None
    pos = 4
    entries: List[Entry] = []
    for _ in range(count):
        if pos + uid_len + 4 > n:
            return None
        uid = blob[pos:pos + uid_len]
        pos += uid_len
        k = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if k > _MAX_ENTRIES or pos + 12 * k > n:
            return None
        pairs = [(blob[pos + 12 * i:pos + 12 * i + 8], blob[pos + 12 * i + 8:pos + 12 * i + 12]) for i in range(k)]
        pos += 12 * k
        entries.append((uid, pairs))
    return entries, blob[pos:]


def _parse_any(blob: bytes, src: str) -> Optional[Tuple[List[Entry], bytes, int]]:
    """Parse with the id size of ``src``, else with the other known sizes (a platform whose layout was never
    seen in a real save, or a file written by another build).  A layout that leaves a bit field of the size
    the game writes (32 bytes, 1024 on the PS4) wins over one that leaves anything else."""
    own = UID_LEN.get(src)
    lens = ([own] if own else []) + [n for n in (8, 28, 20) if n != own]
    fallback = None
    for ln in lens:
        r = parse_mappings(blob, ln)
        if r is None:
            continue
        if len(r[1]) in (32, 1024):
            return r[0], r[1], ln
        if fallback is None and ln == own:
            fallback = (r[0], r[1], ln)
    return fallback


def build_mappings(entries: Sequence[Entry], used: bytes, platform: str) -> bytes:
    out = bytearray(struct.pack(">I", len(entries)))
    for uid, pairs in entries:
        out += uid + struct.pack(">I", len(pairs))
        for k, v in pairs:
            out += k + v
    size = trailer_size(platform)
    out += (used + bytes(size))[:size]
    return bytes(out)


def empty_mappings(platform: str) -> bytes:
    """No player has a large map: valid for every PlayerUID size (the id is never read)."""
    return build_mappings([], b"", platform)


# ---------------------------------------------------------------- player ids of the files
def _src_key(family: str, uid: bytes):
    if family == "xuid":
        return int.from_bytes(uid, "big")
    if family == "sony":
        return uid[18:24].hex()
    if family == "wiiu":
        return uid[:16].hex()
    return None


def _name_key(family: str, fname: str):
    """The id a player file name stands for: XUID number, the 12 hex digits of ``P_<12 hex>_...``, the 32 hex
    digits of a Wii U user."""
    base = fname.rsplit("/", 1)[-1]
    if base.endswith(".dat"):
        base = base[:-4]
    if family == "xuid":
        return int(base) if base.isdigit() and int(base) < (1 << 64) else None
    if family == "sony":
        m = _SONY_NAME.match(base)
        return m.group(1).lower() if m else None
    if family == "wiiu":
        return base.lower() if re.fullmatch(r"[0-9A-Fa-f]{32}", base) else None
    return None


def _build_uid(family: str, length: int, fname: str) -> Optional[bytes]:
    base = fname.rsplit("/", 1)[-1]
    if base.endswith(".dat"):
        base = base[:-4]
    key = _name_key(family, base)
    if key is None:
        return None
    if family == "xuid":
        return key.to_bytes(8, "big")
    if family == "sony":
        m = _SONY_NAME.match(base)
        online = m.group(2).encode("ascii", "ignore")[:15]
        return (online.ljust(16, b"\0") + b"\0\0" + bytes.fromhex(key)).ljust(length, b"\0")
    if family == "wiiu":
        return (bytes.fromhex(key) + bytes(4))[:length]
    return None


def convert_mappings(blob: bytes, src: str, dst: str, players: Sequence[Tuple[str, str]] = ()) -> Tuple[bytes, int, int]:
    """``data/largeMapDataMappings.dat`` of a ``src`` save as ``dst`` loads it.

    ``players``: (name of a player file of the source, name of the file written for the target), the host first.
    The id of a player is rebuilt from the target file name (XUID / console user id); the lookup of the game is
    by that id, so an entry of a player that the target does not know is dropped.  Returns (bytes, entries kept,
    entries dropped).  The target platforms whose id size was never seen in a real save get an empty table.
    """
    parsed = _parse_any(blob, src)
    if parsed is None:
        return empty_mappings(dst), 0, 0
    entries, used, ulen = parsed
    dlen = UID_LEN.get(dst)
    if dlen is None:
        return empty_mappings(dst), 0, len(entries)
    sfam = _FAMILY.get(src) or next((f for p, f in _FAMILY.items() if UID_LEN.get(p) == ulen), None)
    dfam = _FAMILY.get(dst)
    # the target uid of every source key
    targets: Dict[object, Tuple[str, object]] = {}
    for sname, dname in players:
        k = _name_key(sfam, sname) if sfam else None
        if k is None or k in targets:
            continue
        targets[k] = (dname, _name_key(dfam, dname))
    kept: Dict[bytes, List[Tuple[bytes, bytes]]] = {}
    order: List[bytes] = []
    dropped = 0
    for uid, pairs in entries:
        k = _src_key(sfam, uid) if sfam else None
        t = targets.get(k)
        if t is None:
            dropped += 1
            continue
        dname, dkey = t
        if dfam == sfam and dkey == k and ulen == dlen:
            new_uid: Optional[bytes] = uid                    # same console family, same user: as it was
        else:
            new_uid = _build_uid(dfam, dlen, dname)
        if new_uid is None:
            dropped += 1
            continue
        if new_uid not in kept:
            kept[new_uid] = []
            order.append(new_uid)
        have = {kk for kk, _ in kept[new_uid]}
        kept[new_uid].extend((kk, vv) for kk, vv in pairs if kk not in have)
    out = [(u, kept[u]) for u in order]
    return build_mappings(out, used, dst), len(out), dropped

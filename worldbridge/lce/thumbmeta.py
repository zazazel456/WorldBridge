"""The settings the LCE games keep in the text chunk of the save's thumbnail.

neoLegacy / the PS4 read the "host options" of a world, not from ``level.dat``, but from a ``tEXt`` chunk of the
thumbnail PNG (``thumbnails/thumbData.png`` on Windows64, ``THUMB`` on the PS4 / Xbox One / Switch, ``THUMB`` next to
``ICON0.PNG`` on the PS3)::

    4J_SEED 2340570047136252143 | 4J_HOSTOPTIONS 3c8a | 4J_TEXTUREPACK 0 | 4J_EXTRADATA ... | 4J_#LOADS 4

(one chunk holding ``key NUL value NUL`` pairs).  A thumbnail without it starts the world with every option 0: the
difficulty Peaceful (the hostile mobs of the save vanish, measured in game), no PvP, no TNT, no fire spread.  The
bits are read off ``CMinecraftApp::GetGameHostOption`` of neoLegacy and checked against the real chunks of a PS3
(0x3c8a) and a PS4 (0x103c89) save.
"""

from __future__ import annotations

import struct
import zlib
from typing import Dict, Optional

from .. import nbt

_SIG = b"\x89PNG\r\n\x1a\n"

# bit fields of the host options (eGameHostOption)
DIFFICULTY = 0x3                 # 0 peaceful .. 3 hard
GAMERTAGS = 0x8
GAMETYPE_SHIFT = 4               # 2 bits
FLAT = 0x40                      # level type
STRUCTURES = 0x80
BONUS_CHEST = 0x100
HAS_BEEN_IN_CREATIVE = 0x200
PVP = 0x400
TRUST_PLAYERS = 0x800
TNT = 0x1000
FIRE_SPREADS = 0x2000
WORLD_SIZE_SHIFT = 20            # 3 bits: 1 classic, 2 small, 3 medium, 4 large (0: unknown)
DEFAULT_FLAGS = GAMERTAGS | PVP | TRUST_PLAYERS | TNT | FIRE_SPREADS      # what a new world has

_SIZE_CODE = {54: 1, 64: 2, 192: 3, 320: 4}


def read_texts(png: Optional[bytes]) -> Dict[str, str]:
    """The ``4J_*`` pairs of the thumbnail (empty when it has none or is not a PNG)."""
    out: Dict[str, str] = {}
    if not png or png[:8] != _SIG:
        return out
    i = 8
    while i + 8 <= len(png):
        n, typ = struct.unpack(">I4s", png[i:i + 8])
        body = png[i + 8:i + 8 + n]
        if typ == b"tEXt" and body.startswith(b"4J_"):
            parts = body.split(b"\0")
            for k in range(0, len(parts) - 1, 2):
                out[parts[k].decode("latin1")] = parts[k + 1].decode("latin1")
        if typ == b"IEND":
            break
        i += 12 + n
    return out


def host_options(level, world_size: int, base: Optional[int] = None) -> int:
    """The host options of a world with this ``level.dat`` ``Data``: ``base`` (the options of the source's own
    thumbnail, whose switches are kept) with the fields the level and the target decide set."""
    v = DEFAULT_FLAGS if base is None else base
    diff = nbt.get(level, "Difficulty")
    if diff is None:
        diff = 1 if base is None else v & DIFFICULTY            # the game's default for a new world: easy
    v = (v & ~DIFFICULTY) | (max(0, min(3, int(diff))) & DIFFICULTY)
    gt = max(0, min(2, int(nbt.get(level, "GameType", 0) or 0)))
    v = (v & ~(3 << GAMETYPE_SHIFT)) | (gt << GAMETYPE_SHIFT)
    flat = str(nbt.get(level, "generatorName", "default") or "").lower() == "flat"
    v = (v | FLAT) if flat else (v & ~FLAT)
    v = (v | STRUCTURES) if int(nbt.get(level, "MapFeatures", 1) if nbt.get(level, "MapFeatures") is not None else 1) \
        else (v & ~STRUCTURES)
    v = (v | BONUS_CHEST) if int(nbt.get(level, "spawnBonusChest", 0) or 0) else (v & ~BONUS_CHEST)
    v = (v | HAS_BEEN_IN_CREATIVE) if int(nbt.get(level, "hasBeenInCreative", 0) or 0) else (v & ~HAS_BEEN_IN_CREATIVE)
    v = (v & ~(7 << WORLD_SIZE_SHIFT)) | (_SIZE_CODE.get(world_size, 0) << WORLD_SIZE_SHIFT)
    return v


def _chunk(typ: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)


def with_metadata(png: bytes, level, world_size: int, seed: int) -> bytes:
    """``png`` with the 4J text chunk of the world: the source's own pairs kept (extra data, load count), the seed,
    the host options and the texture pack set for this world."""
    if png[:8] != _SIG:
        return png
    old = read_texts(png)
    base = None
    try:
        base = int(old["4J_HOSTOPTIONS"], 16)
    except (KeyError, ValueError):
        pass
    pairs = dict(old)
    pairs["4J_SEED"] = str(int(seed))
    pairs["4J_HOSTOPTIONS"] = "%x" % host_options(level, world_size, base)
    pairs.setdefault("4J_TEXTUREPACK", "0")
    order = ["4J_SEED", "4J_HOSTOPTIONS", "4J_TEXTUREPACK"] + [k for k in pairs if k not in
                                                              ("4J_SEED", "4J_HOSTOPTIONS", "4J_TEXTUREPACK")]
    body = b"".join(k.encode("latin1") + b"\0" + pairs[k].encode("latin1") + b"\0" for k in order)[:-1]
    out = [_SIG]
    i, put = 8, False
    while i + 8 <= len(png):
        n, typ = struct.unpack(">I4s", png[i:i + 8])
        raw = png[i:i + 12 + n]
        i += 12 + n
        if typ == b"tEXt" and raw[8:11] == b"4J_":
            continue
        out.append(raw)
        if typ == b"IHDR" and not put:
            out.append(_chunk(b"tEXt", body))
            put = True
    return b"".join(out)

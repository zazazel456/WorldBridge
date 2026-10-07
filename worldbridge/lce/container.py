"""Legacy Console Edition save container ("ConsoleSaveFileOriginal").

On disk (``saveData.ms`` / ``savegame.dat`` / ``GAMEDATA``)::

    compressed:    [u32 0][u32 decompressed size][platform compressed listing]
    uncompressed:  the listing itself (PS3)
    Xbox 360:      [BE u32 size][BE u64 decompressed size][XMemCompress LZX listing][00]
                   then a few bytes of slack (zeros or leftovers) up to the end of the file

The listing (see Minecraft.World/FileHeader.cpp)::

    u32 offset of the file table
    u32 number of files            (byte size of the table for version 1)
    u16 original save version
    u16 save version
    ... file data ...
    file table: 144 byte entries  { wchar name[64]; u32 length; u32 offset; u64 mtime }
                (136 byte entries without mtime for version 1)

The Xbox 360 layout is the one of every real ``savegame.dat`` checked (TU0 to TU75, loose or inside a
CON package; 22 saves): the storage layer compresses the listing itself.  The first u32 counts the whole
file up to the end of the LZX frames plus one zero byte (12 + frames + 1, every sample matches to the
byte); the u64 is the sum of the frames' raw sizes, i.e. the listing size; the slack after it (4 to 500
bytes in real files) is not part of the save.  WorldBridge up to 0.2.x wrote Xbox 360 saves as
``[u32 0][BE u32 size]`` + LZX instead; those are still read.

Endianness is big endian on Xbox 360 / PS3 / Wii U and little endian on
Windows64 / PS Vita / PS4 / Xbox One / Switch.

PS4 and Xbox One use "split saves": region files are stored outside of the
main container in ``GAMEDATA_DDDDXXZZ`` files (zero run-length compressed,
regions of 16x16 chunks).
"""

from __future__ import annotations

import os
import re
import struct
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import compression as comp
from . import stfs as _stfs


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    endian: str  # '<' or '>'
    container: str  # 'zlib' | 'lzx' | 'none' | 'vita'
    chunk: str  # 'zlib' | 'lzx' | 'ps3'
    split: bool = False  # region files outside of the container
    default_file: str = "savegame.dat"


PLATFORMS: Dict[str, Platform] = {
    p.key: p
    for p in (
        Platform("win64", "Windows64 – neoLegacy (TU31)", "<", "zlib", "zlib", False, "saveData.ms"),
        Platform("xbox360", "Xbox 360 (savegame.dat, Xenia)", ">", "lzx", "lzx", False, "savegame.dat"),
        Platform("ps3", "PlayStation 3 (GAMEDATA, RPCS3)", ">", "none", "ps3", False, "GAMEDATA"),
        Platform("wiiu", "Wii U (Cemu)", ">", "zlib", "zlib", False, "savegame.dat"),
        Platform("vita", "PlayStation Vita (Vita3K)", "<", "vita", "zlib", False, "GAMEDATA.bin"),
        Platform("ps4", "PlayStation 4 (split save)", "<", "zlib", "zlib", True, "GAMEDATA"),
        Platform("xboxone", "Xbox One (split save)", "<", "zlib", "zlib", True, "GAMEDATA"),
        Platform("switch", "Nintendo Switch", "<", "zlib", "zlib", False, "GAMEDATA"),
    )
}

ENTRY_V2 = 144
ENTRY_V1 = 136
HEADER_SIZE = 12
X360_HEADER = 12  # BE u32 size (header included) + BE u64 decompressed size
_MAX_LISTING = 1 << 31
# Above this size the Xbox 360 container is written with LZX uncompressed blocks instead of the
# pure-Python compressor (minutes for tens of MB, for a few percent: the region chunks inside are
# already compressed one by one).
X360_REAL_LZX_MAX = 1 << 20

_SPLIT_RE = re.compile(r"^GAMEDATA_([0-9A-Fa-f]{8})$")


class LCEFormatError(Exception):
    pass


@dataclass
class SaveContainer:
    platform: Platform
    original_version: int = 8
    version: int = 8
    files: Dict[str, bytes] = field(default_factory=dict)
    # split region files: (dimension 0/1/2, rx, rz) -> decompressed region bytes
    split_regions: Dict[Tuple[int, int, int], bytes] = field(default_factory=dict)
    timestamps: Dict[str, int] = field(default_factory=dict)
    thumbnail: Optional[bytes] = None
    display_name: Optional[str] = None
    source_path: str = ""

    @property
    def endian(self) -> str:
        return self.platform.endian

    # ------------------------------------------------------------ listing
    @staticmethod
    def parse_listing(blob: bytes, endian: str) -> Tuple[int, int, Dict[str, bytes], Dict[str, int]]:
        if len(blob) < HEADER_SIZE:
            raise LCEFormatError("listing too small")
        table_off, count = struct.unpack_from(endian + "II", blob, 0)
        orig_ver, ver = struct.unpack_from(endian + "hh", blob, 8)
        if not (HEADER_SIZE <= table_off <= len(blob)):
            raise LCEFormatError("bad table offset")
        files: Dict[str, bytes] = {}
        stamps: Dict[str, int] = {}
        if ver <= 1:
            entry, n = ENTRY_V1, count // ENTRY_V1
        else:
            entry, n = ENTRY_V2, count
        if n > 100000 or table_off + n * entry > len(blob):
            raise LCEFormatError("bad file count")
        enc = "utf-16-le" if endian == "<" else "utf-16-be"
        for i in range(n):
            p = table_off + i * entry
            raw = blob[p : p + 128]
            name = raw.decode(enc, "replace")
            name = name.split("\x00", 1)[0]
            length, offset = struct.unpack_from(endian + "II", blob, p + 128)
            mtime = struct.unpack_from(endian + "q", blob, p + 136)[0] if entry == ENTRY_V2 else 0
            if not name:
                continue
            if offset + length > table_off or offset < HEADER_SIZE and length:
                raise LCEFormatError(f"file {name!r} out of bounds")
            if any(ord(ch) < 0x20 for ch in name):
                raise LCEFormatError("bad file name")
            files[name] = bytes(blob[offset : offset + length])
            stamps[name] = mtime
        return orig_ver, ver, files, stamps

    def build_listing(self) -> bytes:
        e = self.endian
        body = bytearray(HEADER_SIZE)
        entries = []
        for name, data in self.files.items():
            off = len(body)
            body += data
            entries.append((name, off, len(data)))
        table_off = len(body)
        enc = "utf-16-le" if e == "<" else "utf-16-be"
        now = int(time.time() * 1000)
        for name, off, length in entries:
            nb = name.encode(enc)[:126]
            body += nb + b"\x00" * (128 - len(nb))
            body += struct.pack(e + "IIq", length, off, self.timestamps.get(name) or now)
        struct.pack_into(e + "IIhh", body, 0, table_off, len(entries), self.original_version, self.version)
        return bytes(body)

    # ------------------------------------------------------------ reading
    @classmethod
    def load(cls, path: str, platform_hint: Optional[str] = None) -> "SaveContainer":
        path = os.path.abspath(path)
        main = find_main_file(path)
        if main is None:
            raise LCEFormatError(f"No Legacy Console Edition save found in {path}")
        with open(main, "rb") as f:
            raw = f.read()
        thumb = None
        display = None
        if raw[:4] in (b"CON ", b"LIVE", b"PIRS"):
            pkg = _stfs.STFS(raw)
            display = pkg.display_name or None
            thumb = pkg.thumbnail
            name = next((n for n in pkg.files if n.lower() == "savegame.dat"), None)
            if name is None:
                raise LCEFormatError("STFS package does not contain savegame.dat")
            raw = pkg.read_file(name)
            platform_hint = platform_hint or "xbox360"
        cont = cls._decode(raw, main, platform_hint)
        cont.source_path = main
        cont.thumbnail = cont.thumbnail or thumb or _find_thumbnail(main)
        cont.display_name = display
        if cont.platform.split or _has_split_files(os.path.dirname(main)):
            cont._load_split(os.path.dirname(main))
        return cont

    @classmethod
    def _decode(cls, raw: bytes, path: str, hint: Optional[str]) -> "SaveContainer":
        candidates: List[Tuple[str, bytes, str]] = []  # (container kind, listing, endian)
        errors = []
        x360 = x360_header(raw)
        if x360 is not None:
            csize, dsize = x360
            try:
                blob = comp.xmem_decompress(raw[X360_HEADER:csize], dsize)
                if len(blob) == dsize:
                    candidates.append(("lzx", blob, ">"))
                else:
                    errors.append(f"lzx: {len(blob)} bytes instead of {dsize}")
            except Exception as ex:  # noqa: BLE001
                errors.append(f"lzx: {ex}")
        if len(raw) >= 8 and struct.unpack_from("<I", raw, 0)[0] == 0:
            size_be = struct.unpack_from(">I", raw, 4)[0]
            size_le = struct.unpack_from("<I", raw, 4)[0]
            body = raw[8:]
            if body[:1] == b"\x78":
                try:
                    blob = comp.zlib_decompress(body)
                    candidates.append(("zlib", blob, "<" if len(blob) == size_le else ">"))
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"zlib: {ex}")
            if not candidates and 0 < size_le < 1 << 31:
                try:
                    blob = comp.vita_decode(body)
                    if len(blob) == size_le:
                        candidates.append(("vita", blob, "<"))
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"vita: {ex}")
            if not candidates and 0 < size_be < 1 << 31:
                try:
                    blob = comp.xmem_decompress(body, size_be)
                    candidates.append(("lzx", blob, ">"))
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"lzx: {ex}")
        candidates.append(("none", raw, ">"))
        candidates.append(("none", raw, "<"))

        for kind, blob, endian in candidates:
            for e in (endian, "<" if endian == ">" else ">"):
                try:
                    orig, ver, files, stamps = cls.parse_listing(blob, e)
                except (LCEFormatError, struct.error) as ex:
                    errors.append(f"{kind}/{e}: {ex}")
                    continue
                if not files:
                    continue
                plat = _guess_platform(kind, e, path, hint)
                return cls(PLATFORMS[plat], orig, ver, files, timestamps=stamps)
        raise LCEFormatError("Unrecognised LCE save container (" + "; ".join(errors[-4:]) + ")")

    def _load_split(self, folder: str):
        for fn in sorted(os.listdir(folder)):
            m = _SPLIT_RE.match(fn)
            if not m:
                continue
            idx = int(m.group(1), 16)
            dim = (idx >> 16) & 0xFF
            rx = _s8((idx >> 8) & 0xFF)
            rz = _s8(idx & 0xFF)
            with open(os.path.join(folder, fn), "rb") as f:
                data = f.read()
            if len(data) < 4:
                continue
            self.split_regions[(dim, rx, rz)] = split_decompress(data)
        if self.split_regions and not self.platform.split:
            self.platform = PLATFORMS["ps4" if self.platform.key not in ("xboxone",) else self.platform.key]

    # ------------------------------------------------------------ writing
    def encode(self) -> bytes:
        listing = self.build_listing()
        kind = self.platform.container
        if kind == "none":
            return listing
        if kind == "zlib":
            return struct.pack(self.endian + "II", 0, len(listing)) + comp.zlib_compress(listing)
        if kind == "vita":
            return struct.pack("<II", 0, len(listing)) + comp.vita_encode(listing)
        if kind == "lzx":
            # the layout of real Xbox 360 saves (see the module docstring): the size counts the
            # header, the frames and a zero byte; then 4 zero bytes, the least slack seen in real files
            body = comp.xmem_compress(listing, max_real=X360_REAL_LZX_MAX) + b"\x00"
            return struct.pack(">IQ", X360_HEADER + len(body), len(listing)) + body + bytes(4)
        raise ValueError(kind)

    def save(self, folder: str, filename: Optional[str] = None) -> str:
        os.makedirs(folder, exist_ok=True)
        out = os.path.join(folder, filename or self.platform.default_file)
        with open(out, "wb") as f:
            f.write(self.encode())
        for (dim, rx, rz), data in self.split_regions.items():
            idx = (dim << 16) | ((rx & 0xFF) << 8) | (rz & 0xFF)
            with open(os.path.join(folder, "GAMEDATA_%08x" % idx), "wb") as f:
                f.write(split_compress(data))
        return out


# ---------------------------------------------------------------- split helpers


def _s8(v: int) -> int:
    return v - 256 if v >= 128 else v


def split_decompress(data: bytes) -> bytes:
    """ConsoleSaveFileSplit::RegionFileReference::Decompress."""
    size = struct.unpack_from("<I", data, 0)[0]
    out = bytearray()
    n = len(data)
    i = 4
    find = data.find
    while i < n:
        j = find(b"\x00", i)
        if j < 0:
            out += data[i:]
            break
        out += data[i:j]
        if j + 1 >= n:
            break
        k = data[j + 1]
        if k == 0:
            run = ((data[j + 2] << 8) | data[j + 3]) + 256
            i = j + 4
        else:
            run = k
            i = j + 2
        out += bytes(run)
    if size and len(out) != size:
        out = out[:size] if len(out) > size else out + bytes(size - len(out))
    return bytes(out)


def split_compress(data: bytes) -> bytes:
    out = bytearray(struct.pack("<I", len(data)))
    n = len(data)
    i = 0
    find = data.find
    while i < n:
        j = find(b"\x00", i)
        if j < 0:
            out += data[i:]
            break
        out += data[i:j]
        k = j
        while k < n and data[k] == 0 and k - j < 65791:
            k += 1
        run = k - j
        if run < 256:
            out += bytes((0, run))
        else:
            r = run - 256
            out += bytes((0, 0, (r >> 8) & 0xFF, r & 0xFF))
        i = k
    return bytes(out)


# ---------------------------------------------------------------- detection


def x360_header(raw: bytes) -> Optional[Tuple[int, int]]:
    """(end of the compressed data, decompressed size) when ``raw`` starts like a real Xbox 360
    savegame.dat (BE u32 size counted from the start of the file, BE u64 decompressed size,
    XMemCompress frames), else None.  The compressed data is ``raw[12:end]``.
    The sizes must fit the file and the first LZX frame must fit the compressed data.  Never matches
    the other containers: they start with ``u32 0`` (zlib, Vita, older WorldBridge Xbox 360) or with
    a listing whose file count makes the u64 huge (PS3 / uncompressed Windows64)."""
    return _x360_header(raw, len(raw))


def _x360_header(head: bytes, file_size: int) -> Optional[Tuple[int, int]]:
    if len(head) < X360_HEADER + 5:
        return None
    csize, dsize = struct.unpack_from(">IQ", head, 0)
    if not (X360_HEADER < csize <= file_size and 0 < dsize < _MAX_LISTING):
        return None
    # first XMemCompress frame: [0xFF, u16 raw size, u16 size] (last frame) or [u16 size] (32 KB)
    p = X360_HEADER
    if head[p] == 0xFF:
        raw_len, clen = struct.unpack_from(">HH", head, p + 1)
        hdr = 5
        if raw_len == 0:
            return None
    else:
        clen = struct.unpack_from(">H", head, p)[0]
        hdr = 2
    if clen == 0 or p + hdr + clen > csize:
        return None
    return csize, dsize


MAIN_NAMES = ("saveData.ms", "savegame.dat", "GAMEDATA", "GAMEDATA.bin", "SAVEDATA")


def _has_split_files(folder: str) -> bool:
    try:
        return any(_SPLIT_RE.match(f) for f in os.listdir(folder))
    except OSError:
        return False


def find_main_file(path: str) -> Optional[str]:
    if os.path.isfile(path):
        return path
    if not os.path.isdir(path):
        return None
    names = {n.lower(): n for n in os.listdir(path)}
    for cand in MAIN_NAMES:
        if cand.lower() in names:
            return os.path.join(path, names[cand.lower()])
    # renamed copies of an Xbox 360 savegame.dat (savegame-first.dat, savegame_old.dat ...)
    for low in sorted(names):
        if low.startswith("savegame") and low.endswith(".dat") and os.path.isfile(os.path.join(path, names[low])):
            return os.path.join(path, names[low])
    # Xbox 360 CON packages / single unknown file
    for n in sorted(os.listdir(path)):
        p = os.path.join(path, n)
        if os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    head = f.read(4)
            except OSError:
                continue
            if head in (b"CON ", b"LIVE", b"PIRS"):
                return p
    # a Xenia / extracted Xbox 360 save folder: <root>/Save<date>.bin/savegame.dat (one level down,
    # only in "*.bin" folders and only when there is exactly one)
    found = []
    for n in sorted(os.listdir(path)):
        sub = os.path.join(path, n)
        if n.lower().endswith(".bin") and os.path.isdir(sub):
            inner = {m.lower(): m for m in os.listdir(sub)}
            if "savegame.dat" in inner and os.path.isfile(os.path.join(sub, inner["savegame.dat"])):
                found.append(os.path.join(sub, inner["savegame.dat"]))
    if len(found) == 1:
        return found[0]
    return None


def _find_thumbnail(main: str) -> Optional[bytes]:
    folder = os.path.dirname(main)
    for rel in ("thumbnails/thumbData.png", "THUMB", "ICON0.PNG", "icon0.png", "thumbData.png"):
        p = os.path.join(folder, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                d = f.read()
            i = d.find(b"\x89PNG")
            if i >= 0:
                return d[i:]
    return None


def _guess_platform(kind: str, endian: str, path: str, hint: Optional[str]) -> str:
    if hint and hint in PLATFORMS:
        return hint
    folder = os.path.dirname(path)
    base = os.path.basename(path).lower()
    if kind == "lzx":
        return "xbox360"
    if kind == "vita":
        return "vita"
    if kind == "none":
        return "ps3" if endian == ">" else "win64"
    # zlib
    if endian == ">":
        return "wiiu"
    if base.endswith(".ms"):
        return "win64"
    if _has_split_files(folder):
        return "xboxone" if os.path.exists(os.path.join(folder, "wd_displayname.txt")) else "ps4"
    if os.path.exists(os.path.join(folder, "sce_sys")):
        return "ps4"
    if os.path.exists(os.path.splitext(path)[0] + ".sub"):
        return "switch"
    return "win64"


def looks_like_lce(path: str) -> bool:
    main = find_main_file(path)
    if main is None:
        return False
    try:
        with open(main, "rb") as f:
            head = f.read(32)
    except OSError:
        return False
    if head[:4] in (b"CON ", b"LIVE", b"PIRS"):
        return True
    if len(head) < 12:
        return False
    if struct.unpack_from("<I", head, 0)[0] == 0:
        return True  # compressed container
    try:
        size = os.path.getsize(main)
    except OSError:
        return False
    if _x360_header(head, size) is not None:
        return True  # real Xbox 360 savegame.dat
    # uncompressed listing: plausible header
    for e in "<>":
        off, cnt = struct.unpack_from(e + "II", head, 0)
        _o, v = struct.unpack_from(e + "hh", head, 8)
        if 0 < v < 20 and 0 < cnt < 100000 and off > 12:
            if off + min(cnt, 1) * ENTRY_V1 <= size:
                return True
    return False

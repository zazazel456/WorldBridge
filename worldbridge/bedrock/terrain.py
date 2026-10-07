"""Direct edits of the Bedrock terrain written by Amulet.

* Height maps: Amulet leaves the height map of every chunk at 0.  Bedrock uses it for lighting,
  mob spawning and - when it upgrades a pre-1.18 chunk - for the blending between the old terrain
  and the one it generates around it: with 0 everywhere the new chunks meet the old ones with a
  vertical wall.
* Blocks: a few things are blocks in Bedrock but entities elsewhere (item frames).
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

import amulet_nbt as an
import numpy as np

from ..model import Progress
from ..i18n import tr

SUBCHUNK = 0x2F
DATA2D = 0x2D
DATA3D = 0x2B
AIR = "minecraft:air"


# ------------------------------------------------------------------ sub chunks


class Storage:
    __slots__ = ("idx", "palette")

    def __init__(self, idx: np.ndarray, palette: List[an.CompoundTag]):
        self.idx = idx          # 4096 palette indices, xzy order (x << 8 | z << 4 | y)
        self.palette = palette


class SubChunk:
    def __init__(self, version: int, y_index: Optional[int], storages: List[Storage]):
        self.version = version
        self.y_index = y_index
        self.storages = storages

    # -------------------------------------------------------------- decode
    @classmethod
    def decode(cls, data: bytes) -> Optional["SubChunk"]:
        if not data or data[0] not in (8, 9):
            return None  # legacy (pre 1.2.13) layouts: never written by Amulet
        version = data[0]
        count = data[1]
        pos = 2
        y_index = None
        if version == 9:
            y_index = struct.unpack_from("b", data, 2)[0]
            pos = 3
        storages = []
        for _ in range(count):
            header = data[pos]
            pos += 1
            bits = header >> 1
            if bits == 0:
                idx = np.zeros(4096, np.int64)
                n_pal = 1
            else:
                per = 32 // bits
                words = (4096 + per - 1) // per
                arr = np.frombuffer(data, "<u4", words, pos).astype(np.uint64)
                pos += words * 4
                i = np.arange(4096)
                idx = ((arr[i // per] >> ((i % per) * bits).astype(np.uint64)) & np.uint64((1 << bits) - 1)).astype(np.int64)
                n_pal = struct.unpack_from("<i", data, pos)[0]
                pos += 4
            ctx = an.ReadContext()
            pal = an.load_array(data[pos:], count=n_pal, compressed=False, little_endian=True, read_context=ctx,
                                string_decoder=an.utf8_escape_decoder)
            pos += ctx.offset
            storages.append(Storage(idx, [p.compound for p in pal]))
        return cls(version, y_index, storages)

    # -------------------------------------------------------------- encode
    def encode(self) -> bytes:
        out = bytearray([self.version, len(self.storages)])
        if self.version == 9:
            out += struct.pack("b", self.y_index or 0)
        for st in self.storages:
            n = len(st.palette)
            bits = next(b for b in (1, 2, 3, 4, 5, 6, 8, 16) if (1 << b) >= max(n, 2))
            per = 32 // bits
            words = (4096 + per - 1) // per
            arr = np.zeros(words, np.uint64)
            i = np.arange(4096)
            np.bitwise_or.at(arr, i // per, st.idx.astype(np.uint64) << ((i % per) * bits).astype(np.uint64))
            out.append(bits << 1)
            out += arr.astype("<u4").tobytes()
            out += struct.pack("<i", n)
            for p in st.palette:
                out += an.NamedTag(p, "").save_to(compressed=False, little_endian=True, string_encoder=an.utf8_escape_encoder)
        return bytes(out)


def _name(p: an.CompoundTag) -> str:
    try:
        return p["name"].py_str
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ height maps


def _column_heights(subs: Dict[int, SubChunk]) -> np.ndarray:
    """Per column (z, x): 1 + y of the highest non-air block of the main layer, or the lowest y."""
    heights = np.full((16, 16), -(1 << 15), np.int32)
    todo = np.ones((16, 16), bool)
    for sy in sorted(subs, reverse=True):
        st = subs[sy].storages[0] if subs[sy].storages else None
        if st is None:
            continue
        solid = np.array([_name(p) != AIR for p in st.palette], bool)
        if not solid.any():
            continue
        grid = solid[st.idx].reshape(16, 16, 16)  # x, z, y
        any_col = grid.any(axis=2)                # x, z
        top = 15 - np.argmax(grid[:, :, ::-1], axis=2)
        hit = any_col.T & todo                    # z, x
        heights[hit] = (sy * 16 + top.T + 1)[hit]
        todo &= ~any_col.T
        if not todo.any():
            break
    return heights


def fix_height_maps(db, progress: Optional[Progress] = None, min_y: Dict[int, int] = None) -> int:
    """Rewrite the height map of every chunk (Data2D / Data3D) from its blocks.

    The keys of a chunk start with its x and z (then the dimension, for the Nether and the End), so in
    the database's order the records of one column of chunks come together: they are read one column
    at a time, and the memory needed does not grow with the size of the world.  The sub chunks are
    decoded on every core (parallel.py); the iteration sees the database as it was when it started,
    so the new height maps are written along the way."""
    from ..parallel import ordered_map

    fixed = 0
    for i, new in enumerate(ordered_map(_column_maps, min_y, _columns(db), batch=16)):
        for key, value in new:
            db.put(key, value)
            fixed += 1
        if progress is not None and i % 1024 == 0:
            progress.update(0.5, tr("Height maps {i}", i=i))
    return fixed


def _columns(db):
    """The records that matter of every column of chunks, one column at a time: a list of
    (prefix, tag, height map record, {sub chunk y: record})."""
    column: Optional[bytes] = None
    subs_of: Dict[bytes, Dict[int, bytes]] = {}
    maps: Dict[bytes, Tuple[int, bytes]] = {}
    for k, v in db.iterate():
        k = bytes(k)
        n = len(k)
        sub = n in (10, 14) and k[-2] == SUBCHUNK
        if not sub and not (n in (9, 13) and k[-1] in (DATA2D, DATA3D)):
            continue
        if k[:8] != column:
            if maps:
                yield [(prefix, tag, value, subs_of.get(prefix)) for prefix, (tag, value) in maps.items()]
            subs_of, maps = {}, {}
            column = k[:8]
        if sub:
            subs_of.setdefault(k[:-2], {})[struct.unpack("b", k[-1:])[0]] = bytes(v)
        else:
            maps[k[:-1]] = (k[-1], bytes(v))
    if maps:
        yield [(prefix, tag, value, subs_of.get(prefix)) for prefix, (tag, value) in maps.items()]


def _column_maps(min_y, column) -> List[Tuple[bytes, bytes]]:
    """Worker function (parallel.py): the height map records of a column that change."""
    out = []
    for prefix, tag, value, subs_raw in column:
        new = _height_map(prefix, tag, value, subs_raw, min_y)
        if new is not None:
            out.append((prefix + bytes([tag]), new))
    return out


def _height_map(prefix: bytes, tag: int, value: bytes, subs_raw: Optional[Dict[int, bytes]],
                min_y: Optional[Dict[int, int]]) -> Optional[bytes]:
    """The chunk's height map record recomputed from its sub chunks (None: nothing to change)."""
    if not subs_raw or len(value) < 512:
        return None
    subs = {}
    for sy, raw in subs_raw.items():
        try:
            sc = SubChunk.decode(raw)
        except Exception:  # noqa: BLE001
            sc = None
        if sc is not None:
            subs[sy] = sc
    if not subs:
        return None
    dim = struct.unpack_from("<i", prefix, 8)[0] if len(prefix) == 12 else 0
    base = 0 if tag == DATA2D else (min_y or {}).get(dim, -64 if dim == 0 else 0)
    h = _column_heights(subs)
    h = np.where(h == -(1 << 15), base, h) - base  # stored relative to the bottom of the world
    new = np.clip(h, 0, 32767).astype("<i2").tobytes()  # index z * 16 + x
    return new + value[512:] if new != value[:512] else None


# ------------------------------------------------------------------ single blocks


LEGACY_SUB_BYTES = 1 + 4096 + 2048   # pre-1.2.13 sub chunk: version, block ids, block data (xzy order)
STONE_ID = 1


def legacy_block_at(raw: bytes, n: int) -> Optional[Tuple[int, int]]:
    """(block id, data) of index ``n`` (x << 8 | z << 4 | y) of a pre-1.2.13 sub chunk record."""
    if not raw or raw[0] in (8, 9) or len(raw) < LEGACY_SUB_BYTES:
        return None
    return raw[1 + n], (raw[4097 + (n >> 1)] >> ((n & 1) * 4)) & 15


def _is_val_palette(palette) -> bool:
    """1.2.13 - 1.12 palettes: {name, val} (numeric data), no block states."""
    return any("val" in p and "states" not in p for p in palette)


def _plain_stone(entry) -> bool:
    """The stone block itself (not granite, diorite...): a stand-in written where Java has no block."""
    if _name(entry) != "minecraft:stone":
        return False
    try:
        if "val" in entry:
            return int(entry["val"].py_int) == 0
        st = entry["states"] if "states" in entry else {}
        return "stone_type" not in st or str(st["stone_type"].py_str) == "stone"
    except Exception:  # noqa: BLE001
        return False


def set_blocks(db, prefix_of, blocks: Dict[Tuple[int, int, int], tuple],
               only_if_air: bool = True, replace_stone: bool = False) -> List[Tuple[int, int, int]]:
    """Put blocks at world positions; returns the positions really changed.

    ``prefix_of(cx, cz)``: the LevelDB key prefix of that chunk (dimension included).  A block is
    (name, states) or (name, states, numeric id): states ``{"block_data": n}`` is a block of a
    version before 1.13 (PyMCTranslate's form), written as ``{name, val}`` in 1.2.13 - 1.12 palettes
    and as id + data in the older sub chunks; a block that does not suit the sub chunk's format
    (block states in a numeric chunk or the reverse) is not placed.  With ``only_if_air`` a block
    goes only where there is air (and plain stone, with ``replace_stone``: the stand-in a Java
    world converted before frames became air has under every frame)."""
    groups: Dict[Tuple[int, int, int], List] = {}
    for (x, y, z), st in blocks.items():
        groups.setdefault((x >> 4, y >> 4, z >> 4), []).append(((x & 15, y & 15, z & 15), (x, y, z), st))
    done = []
    for (cx, sy, cz), items in groups.items():
        key = prefix_of(cx, cz) + bytes([SUBCHUNK]) + struct.pack("b", sy)
        raw = db.get(key)
        if raw is None:
            continue
        raw = bytes(raw)
        if raw and raw[0] not in (8, 9):
            new = _set_legacy(raw, items, only_if_air, replace_stone, done)
            if new is not None:
                db.put(key, new)
            continue
        sc = SubChunk.decode(raw)
        if sc is None or not sc.storages:
            continue
        st0 = sc.storages[0]
        val_palette = _is_val_palette(st0.palette)
        version = None
        for p in st0.palette:
            if "version" in p:
                version = p["version"]
                break
        changed = False
        for (lx, ly, lz), pos, block in items:
            name, states = block[0], block[1]
            if (set(states) == {"block_data"}) != val_palette:
                continue
            n = lx << 8 | lz << 4 | ly
            here = st0.palette[int(st0.idx[n])]
            if only_if_air and _name(here) != AIR and not (replace_stone and _plain_stone(here)):
                continue
            if val_palette:
                entry = an.CompoundTag({"name": an.StringTag(name), "val": an.ShortTag(int(states["block_data"].py_int))})
            else:
                entry = an.CompoundTag({"name": an.StringTag(name), "states": an.CompoundTag(states)})
                if version is not None:
                    entry["version"] = version
            key_bytes = an.NamedTag(entry, "").save_to(little_endian=True)
            pi = None
            for j, p in enumerate(st0.palette):
                if an.NamedTag(p, "").save_to(little_endian=True) == key_bytes:
                    pi = j
                    break
            if pi is None:
                st0.palette.append(entry)
                pi = len(st0.palette) - 1
            st0.idx[n] = pi
            done.append(pos)
            changed = True
        if changed:
            db.put(key, sc.encode())
    return done


def _set_legacy(raw: bytes, items, only_if_air: bool, replace_stone: bool, done: list) -> Optional[bytes]:
    """The blocks of a pre-1.2.13 sub chunk (id + data nibbles): only blocks with a numeric id."""
    if len(raw) < LEGACY_SUB_BYTES:
        return None
    buf = bytearray(raw)
    changed = False
    for (lx, ly, lz), pos, block in items:
        states = block[1]
        if len(block) < 3 or block[2] is None or set(states) != {"block_data"}:
            continue
        n = lx << 8 | lz << 4 | ly
        if only_if_air and buf[1 + n] != 0 and not (replace_stone and legacy_block_at(raw, n) == (STONE_ID, 0)):
            continue
        buf[1 + n] = int(block[2]) & 255
        data = int(states["block_data"].py_int) & 15
        j = 4097 + (n >> 1)
        shift = (n & 1) * 4
        buf[j] = (buf[j] & (0xF0 >> shift)) | (data << shift)
        done.append(pos)
        changed = True
    return bytes(buf) if changed else None

"""Decoding / encoding of Legacy Console Edition chunk payloads.

Formats (first bytes of the decompressed payload):

* ``0x0A``         NBT chunk ("Level" compound) - saves with original version < 8
* version 8..11    4J compressed storage (CompressedTileStorage /
                   SparseDataStorage / SparseLightStorage), 2 x 128 high halves
* version 12, 13   "Aquatic" grid paletted format, 16 x 16 high sections,
                   16 bit block values (id << 4 | data, bit 15 = waterlogged)

References: Minecraft.World/{OldChunkStorage,LevelChunk,CompressedTileStorage,
SparseLightStorage,SparseDataStorage}.cpp from the LCE source, the
Team-Lodestone documentation and zugebot/LegacyEditor.
"""

from __future__ import annotations

import struct
from typing import List, Tuple

import numpy as np

from .. import nbt
from ..model import NumericChunk

HALF = 128

# ---------------------------------------------------------------------------
# index helpers


def _get_index_table() -> np.ndarray:
    """CompressedTileStorage::getIndex(block, tile) for all 512 x 64 pairs."""
    b = np.arange(512)[:, None]
    t = np.arange(64)[None, :]
    idx = ((b & 0x180) << 6) | ((b & 0x060) << 4) | ((b & 0x01F) << 2)
    idx = idx | ((t & 0x30) << 7) | ((t & 0x0C) << 5) | (t & 0x03)
    return idx.astype(np.int64)


_IDX = _get_index_table()  # java order index = x<<11 | z<<7 | y (128 high)
_ARANGE64 = np.arange(64)


def java128_to_yzx(flat: np.ndarray) -> np.ndarray:
    """Java McRegion ordering (x<<11|z<<7|y, 128 high) -> [y, z, x]."""
    return flat.reshape(16, 16, HALF).transpose(2, 1, 0)


def yzx_to_java128(arr: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(arr.transpose(2, 1, 0)).reshape(-1)


def nibbles_to_array(raw: bytes, count: int) -> np.ndarray:
    a = np.frombuffer(raw, np.uint8, count // 2)
    out = np.empty(count, np.uint8)
    out[0::2] = a & 0x0F
    out[1::2] = a >> 4
    return out


def array_to_nibbles(arr: np.ndarray) -> bytes:
    a = arr.astype(np.uint8).reshape(-1)
    return ((a[0::2] & 0x0F) | ((a[1::2] & 0x0F) << 4)).astype(np.uint8).tobytes()


# ---------------------------------------------------------------------------
# CompressedTileStorage


def decode_tile_storage(buf: bytes) -> np.ndarray:
    """-> flat uint8 array (32768) in java order."""
    if len(buf) < 1024:
        return np.zeros(32768, np.uint8)
    pad = np.zeros(len(buf) + 32768 + 1024, np.uint8)
    pad[: len(buf)] = np.frombuffer(buf, np.uint8)
    idx = np.frombuffer(buf[:1024], "<u2").astype(np.int64)
    typ = idx & 3
    out = np.zeros((512, 64), np.uint8)
    off = 1024 + ((idx >> 1) & 0x7FFE)
    zero = (typ == 3) & ((idx & 4) != 0)
    out[zero] = ((idx[zero] >> 8) & 0xFF)[:, None]
    eight = (typ == 3) & ((idx & 4) == 0)
    if eight.any():
        out[eight] = pad[off[eight][:, None] + _ARANGE64]
    for k in (0, 1, 2):
        m = typ == k
        if not m.any():
            continue
        bpt = 1 << k
        ntypes = 1 << bpt
        o = off[m][:, None]
        tile_types = pad[o + np.arange(ntypes)]
        packed = pad[o + ntypes + np.arange(8 * bpt)]
        shift = 3 - k
        byte_i = (_ARANGE64 >> shift) & (62 >> shift)
        bit = (_ARANGE64 & (7 >> k)) * bpt
        vals = (packed[:, byte_i] >> bit) & (ntypes - 1)
        out[m] = np.take_along_axis(tile_types, vals.astype(np.int64), axis=1)
    flat = np.zeros(32768, np.uint8)
    flat[_IDX] = out
    return flat


def encode_tile_storage(flat: np.ndarray) -> bytes:
    """flat java-order uint8[32768] -> CompressedTileStorage bytes
    (0 bit blocks for uniform 4x4x4 cells, 8 bit otherwise; the game
    re-packs it on load)."""
    m = flat[_IDX]  # (512, 64)
    uniform = (m == m[:, :1]).all(axis=1)
    idx = np.zeros(512, np.int64)
    idx[uniform] = 7 | (m[uniform, 0].astype(np.int64) << 8)
    nu = np.nonzero(~uniform)[0]
    offs = np.arange(nu.size, dtype=np.int64) * 64
    idx[nu] = 3 | ((offs & 0x7FFE) << 1)
    return idx.astype("<u2").tobytes() + m[nu].tobytes()


# ---------------------------------------------------------------------------
# SparseLightStorage / SparseDataStorage


def decode_sparse(buf: bytes, count: int) -> np.ndarray:
    """-> [y(128), z, x] uint8 nibble values."""
    pi = np.frombuffer(buf[:128], np.uint8).astype(np.int64)
    planes = np.frombuffer(buf[128 : 128 + count * 128], np.uint8).reshape(-1, 128) if count else np.zeros((0, 128), np.uint8)
    vals = np.zeros((128, 256), np.uint8)
    valid = pi < planes.shape[0]
    if valid.any():
        p = planes[pi[valid]]
        v = np.empty((p.shape[0], 256), np.uint8)
        v[:, 0::2] = p & 0x0F
        v[:, 1::2] = p >> 4
        vals[valid] = v
    vals[pi == 129] = 15
    # xz index = x*16 + z
    return vals.reshape(128, 16, 16).transpose(0, 2, 1)


def encode_sparse(arr: np.ndarray, allow_15: bool) -> bytes:
    """[y(128), z, x] nibble array -> count + plane indices + planes."""
    v = np.ascontiguousarray(arr.transpose(0, 2, 1)).reshape(128, 256).astype(np.uint8)
    all0 = (v == 0).all(axis=1)
    all15 = (v == 15).all(axis=1) if allow_15 else np.zeros(128, bool)
    pi = np.zeros(128, np.uint8)
    planes: List[bytes] = []
    for y in range(128):
        if all0[y]:
            pi[y] = 128
        elif all15[y]:
            pi[y] = 129
        else:
            pi[y] = len(planes)
            row = v[y]
            planes.append(((row[0::2] & 0x0F) | ((row[1::2] & 0x0F) << 4)).astype(np.uint8).tobytes())
    return struct.pack(">i", len(planes)) + pi.tobytes() + b"".join(planes)


# ---------------------------------------------------------------------------
# chunk level


class LCEChunk:
    """Decoded LCE chunk (numeric LCE ids)."""

    __slots__ = (
        "version", "cx", "cz", "last_update", "inhabited", "blocks", "data", "sky", "block_light",
        "heightmap", "terrain_populated", "biomes", "entities", "tile_entities", "tile_ticks", "waterlogged",
        "biome_at",
    )

    def __init__(self):
        self.version = 8
        self.cx = self.cz = 0
        self.last_update = 0
        self.inhabited = 0
        self.blocks = np.zeros((256, 16, 16), np.uint16)
        self.data = np.zeros((256, 16, 16), np.uint8)
        self.sky = None
        self.block_light = None
        self.heightmap = None
        self.terrain_populated = 2046
        self.biomes = None
        self.entities: list = []
        self.tile_entities: list = []
        self.tile_ticks: list = []
        self.waterlogged = None
        self.biome_at = None          # where the 256 biome bytes are in the payload (binary formats)


def _read_tail_nbt(payload: bytes, pos: int, c: LCEChunk):
    if pos >= len(payload):
        return
    try:
        tag, _ = nbt.load_with_offset(payload, pos)
    except Exception:  # noqa: BLE001
        return
    root = tag.tag
    c.entities = list(nbt.get_tag(root, "Entities") or [])
    c.tile_entities = list(nbt.get_tag(root, "TileEntities") or [])
    c.tile_ticks = list(nbt.get_tag(root, "TileTicks") or [])


def decode_chunk(payload: bytes) -> LCEChunk:
    if payload[:1] == b"\x0a":
        return _decode_nbt(payload)
    version = struct.unpack_from(">h", payload, 0)[0]
    if 8 <= version <= 11:
        return _decode_compressed(payload, version)
    if version in (12, 13):
        return _decode_aquatic(payload, version)
    raise ValueError(f"unknown LCE chunk format version {version}")


def _decode_nbt(payload: bytes) -> LCEChunk:
    root = nbt.load(payload, compressed=False).tag
    lvl = nbt.get_tag(root, "Level") or root
    c = LCEChunk()
    c.version = 7
    c.cx = int(nbt.get(lvl, "xPos", 0))
    c.cz = int(nbt.get(lvl, "zPos", 0))
    c.last_update = int(nbt.get(lvl, "LastUpdate", 0))
    blocks = np.frombuffer(bytes(nbt.get_tag(lvl, "Blocks").py_data.astype(np.uint8)), np.uint8)
    halves = max(1, blocks.size // 32768)

    def get_arr(key, fill=0):
        t = nbt.get_tag(lvl, key)
        if t is None:
            return None
        return np.frombuffer(bytes(t.py_data.astype(np.uint8)), np.uint8)

    data = get_arr("Data")
    sky = get_arr("SkyLight")
    bl = get_arr("BlockLight")
    for h in range(min(2, halves)):
        ys = slice(h * 128, h * 128 + 128)
        c.blocks[ys] = java128_to_yzx(blocks[h * 32768 : (h + 1) * 32768])
        if data is not None and data.size >= (h + 1) * 16384:
            c.data[ys] = java128_to_yzx(nibbles_to_array(data[h * 16384 : (h + 1) * 16384].tobytes(), 32768))
        if sky is not None and sky.size >= (h + 1) * 16384:
            if c.sky is None:
                c.sky = np.full((256, 16, 16), 15, np.uint8)
            c.sky[ys] = java128_to_yzx(nibbles_to_array(sky[h * 16384 : (h + 1) * 16384].tobytes(), 32768))
        if bl is not None and bl.size >= (h + 1) * 16384:
            if c.block_light is None:
                c.block_light = np.zeros((256, 16, 16), np.uint8)
            c.block_light[ys] = java128_to_yzx(nibbles_to_array(bl[h * 16384 : (h + 1) * 16384].tobytes(), 32768))
    hm = get_arr("HeightMap")
    c.heightmap = hm[:256].copy() if hm is not None and hm.size >= 256 else None
    bio = get_arr("Biomes")
    c.biomes = bio[:256].reshape(16, 16).copy() if bio is not None and bio.size >= 256 else None
    tp = nbt.get(lvl, "TerrainPopulatedFlags")
    if tp is None:
        tp = 2046 if nbt.get(lvl, "TerrainPopulated", 1) else 0
    c.terrain_populated = int(tp)
    c.entities = list(nbt.get_tag(lvl, "Entities") or [])
    c.tile_entities = list(nbt.get_tag(lvl, "TileEntities") or [])
    c.tile_ticks = list(nbt.get_tag(lvl, "TileTicks") or [])
    return c


def _decode_compressed(payload: bytes, version: int) -> LCEChunk:
    c = LCEChunk()
    c.version = version
    p = 2
    c.cx, c.cz, c.last_update = struct.unpack_from(">iiq", payload, p)
    p += 16
    if version >= 9:
        c.inhabited = struct.unpack_from(">q", payload, p)[0]
        p += 8

    def tile():
        nonlocal p
        size = struct.unpack_from(">i", payload, p)[0]
        p += 4
        buf = payload[p : p + max(size, 0)]
        p += max(size, 0)
        return decode_tile_storage(buf) if size > 0 else np.zeros(32768, np.uint8)

    def sparse():
        nonlocal p
        count = struct.unpack_from(">i", payload, p)[0]
        p += 4
        n = 128 + count * 128
        arr = decode_sparse(payload[p : p + n], count)
        p += n
        return arr

    lo, hi = tile(), tile()
    c.blocks[:128] = java128_to_yzx(lo)
    c.blocks[128:] = java128_to_yzx(hi)
    c.data[:128] = sparse()
    c.data[128:] = sparse()
    c.sky = np.empty((256, 16, 16), np.uint8)
    c.sky[:128] = sparse()
    c.sky[128:] = sparse()
    c.block_light = np.empty((256, 16, 16), np.uint8)
    c.block_light[:128] = sparse()
    c.block_light[128:] = sparse()
    c.heightmap = np.frombuffer(payload[p : p + 256], np.uint8).copy()
    p += 256
    c.terrain_populated = struct.unpack_from(">h", payload, p)[0]
    p += 2
    c.biome_at = p
    c.biomes = np.frombuffer(payload[p : p + 256], np.uint8).reshape(16, 16).copy()
    p += 256
    _read_tail_nbt(payload, p, c)
    return c


# --- Aquatic -------------------------------------------------------------

_AQ_FORMATS = {  # fmt -> (palette size, bits, has liquid layer)
    0x2: (2, 1, False), 0x3: (2, 1, True),
    0x4: (4, 2, False), 0x5: (4, 2, True),
    0x6: (8, 3, False), 0x7: (8, 3, True),
    0x8: (16, 4, False), 0x9: (16, 4, True),
}
# tile p of a 4x4x4 grid: p = bx<<4 | bz<<2 | by
_P = np.arange(64)
_PBX, _PBZ, _PBY = _P >> 4, (_P >> 2) & 3, _P & 3


def _aq_grid(data: bytes, gp: int, fmt: int) -> Tuple[np.ndarray, np.ndarray]:
    """-> (blocks[64], liquid[64] or None) raw u16 values."""
    if fmt in (0xE, 0xF):
        blocks = np.frombuffer(data, "<u2", 64, gp).astype(np.uint16)
        liquid = np.frombuffer(data, "<u2", 64, gp + 128).astype(np.uint16) if fmt == 0xF else None
        return blocks, liquid
    psize, bits, has_liq = _AQ_FORMATS[fmt]
    palette = np.frombuffer(data, "<u2", psize, gp).astype(np.uint16)
    seg = gp + psize * 2
    planes = np.frombuffer(data, np.uint8, bits * 8, seg).reshape(bits, 8)
    bitsarr = np.unpackbits(planes, axis=1)  # (bits, 64) MSB first
    idx = np.zeros(64, np.int64)
    for b in range(bits):
        idx |= bitsarr[b].astype(np.int64) << b
    blocks = palette[np.minimum(idx, psize - 1)]
    liquid = None
    if has_liq:
        lplanes = np.frombuffer(data, np.uint8, bits * 8, seg + bits * 8).reshape(bits, 8)
        lb = np.unpackbits(lplanes, axis=1)
        lidx = np.zeros(64, np.int64)
        for b in range(bits):
            lidx |= lb[b].astype(np.int64) << b
        liquid = palette[np.minimum(lidx, psize - 1)]
    return blocks, liquid


def _decode_aquatic(payload: bytes, version: int) -> LCEChunk:
    c = LCEChunk()
    c.version = version
    p = 2
    if version == 13:
        p += 2  # max grid count
    c.cx, c.cz, c.last_update, c.inhabited = struct.unpack_from(">iiqq", payload, p)
    p += 24
    units = struct.unpack_from(">H", payload, p)[0]
    p += 2
    jump = struct.unpack_from(">16H", payload, p)
    p += 32
    sizes = struct.unpack_from(">16B", payload, p)
    p += 16
    base0 = p
    raw = np.zeros((256, 16, 16), np.uint16)  # [y, z, x]
    liquid = np.zeros((256, 16, 16), np.uint16)
    has_liquid = False
    for s in range(16):
        if sizes[s] == 0:
            continue
        base = base0 + jump[s]
        gdata = base + 128
        if gdata > len(payload):
            break
        hdr = np.frombuffer(payload, "<u2", 64, base)
        for gidx in range(64):
            v = int(hdr[gidx])
            gx, gz, gy = gidx >> 4, (gidx >> 2) & 3, gidx & 3
            fmt = v >> 12
            if fmt in (0, 1):
                blocks = np.full(64, v & 0x0FFF, np.uint16)
                if fmt == 1:
                    blocks |= 0x8000
                liq = None
            else:
                if fmt not in _AQ_FORMATS and fmt not in (0xE, 0xF):
                    continue
                try:
                    blocks, liq = _aq_grid(payload, gdata + (v & 0x0FFF) * 4, fmt)
                except ValueError:
                    continue
            ys = s * 16 + gy * 4 + _PBY
            zs = gz * 4 + _PBZ
            xs = gx * 4 + _PBX
            raw[ys, zs, xs] = blocks
            if liq is not None:
                liquid[ys, zs, xs] = liq
                has_liquid = True
    c.blocks = ((raw >> 4) & 0x7FF).astype(np.uint16)
    c.data = (raw & 0x0F).astype(np.uint8)
    wl = (raw & 0x8000) != 0
    if has_liquid:
        lid = (liquid >> 4) & 0x7FF
        wl |= (lid == 8) | (lid == 9)
    c.waterlogged = wl if wl.any() else None
    p = base0 + units * 0x100

    def sparse():
        nonlocal p
        count = struct.unpack_from(">i", payload, p)[0]
        p += 4
        n = 128 + count * 128
        arr = decode_sparse(payload[p : p + n], count)
        p += n
        return arr

    try:
        c.sky = np.empty((256, 16, 16), np.uint8)
        c.sky[:128] = sparse()
        c.sky[128:] = sparse()
        c.block_light = np.empty((256, 16, 16), np.uint8)
        c.block_light[:128] = sparse()
        c.block_light[128:] = sparse()
        c.heightmap = np.frombuffer(payload[p : p + 256], np.uint8).copy()
        p += 256
        c.terrain_populated = struct.unpack_from(">h", payload, p)[0]
        p += 2
        c.biome_at = p
        c.biomes = np.frombuffer(payload[p : p + 256], np.uint8).reshape(16, 16).copy()
        p += 256
        _read_tail_nbt(payload, p, c)
    except (struct.error, ValueError):
        c.sky = c.block_light = None
        tail = payload.rfind(b"\x0a\x00\x00")
        if tail >= 0:
            _read_tail_nbt(payload, tail, c)
    return c


# ---------------------------------------------------------------------------
# encoding


def _tail_nbt(c: LCEChunk) -> bytes:
    root = nbt.CompoundTag(
        {
            "Entities": nbt.compound_list(c.entities),
            "TileEntities": nbt.compound_list(c.tile_entities),
            "TileTicks": nbt.compound_list(c.tile_ticks),
        }
    )
    return nbt.dump(root, "")


def _heightmap(c: LCEChunk) -> np.ndarray:
    mask = c.blocks != 0
    top = 256 - np.argmax(mask[::-1], axis=0)
    hm = np.where(mask.any(axis=0), top, 0)
    return np.minimum(hm, 255).astype(np.uint8).reshape(-1)  # index z*16+x


def encode_chunk(c: LCEChunk, version: int = 8) -> bytes:
    if version == 7:
        return _encode_nbt(c)
    if 8 <= version <= 11:
        return _encode_compressed(c, version)
    raise ValueError(f"writing LCE chunk version {version} is not supported")


def _light(c: LCEChunk):
    sky = c.sky if c.sky is not None else np.full((256, 16, 16), 15, np.uint8)
    bl = c.block_light if c.block_light is not None else np.zeros((256, 16, 16), np.uint8)
    return sky, bl


def _encode_compressed(c: LCEChunk, version: int) -> bytes:
    out = bytearray(struct.pack(">hiiq", version, c.cx, c.cz, c.last_update))
    if version >= 9:
        out += struct.pack(">q", c.inhabited)
    blocks = np.clip(c.blocks, 0, 255).astype(np.uint8)
    for h in (0, 1):
        ts = encode_tile_storage(yzx_to_java128(blocks[h * 128 : h * 128 + 128]))
        out += struct.pack(">i", len(ts)) + ts
    sky, bl = _light(c)
    for h in (0, 1):
        out += encode_sparse(c.data[h * 128 : h * 128 + 128], False)
    for h in (0, 1):
        out += encode_sparse(sky[h * 128 : h * 128 + 128], True)
    for h in (0, 1):
        out += encode_sparse(bl[h * 128 : h * 128 + 128], True)
    hm = c.heightmap if c.heightmap is not None and len(c.heightmap) == 256 else _heightmap(c)
    out += np.asarray(hm, np.uint8).tobytes()
    out += struct.pack(">h", c.terrain_populated)
    bio = c.biomes if c.biomes is not None else np.ones((16, 16), np.uint8)
    out += bio.astype(np.uint8).reshape(-1).tobytes()
    out += _tail_nbt(c)
    return bytes(out)


def _encode_nbt(c: LCEChunk) -> bytes:
    sky, bl = _light(c)
    blocks = np.clip(c.blocks, 0, 255).astype(np.uint8)
    b = np.concatenate([yzx_to_java128(blocks[:128]), yzx_to_java128(blocks[128:])])
    d = array_to_nibbles(np.concatenate([yzx_to_java128(c.data[:128]), yzx_to_java128(c.data[128:])]))
    s = array_to_nibbles(np.concatenate([yzx_to_java128(sky[:128]), yzx_to_java128(sky[128:])]))
    l = array_to_nibbles(np.concatenate([yzx_to_java128(bl[:128]), yzx_to_java128(bl[128:])]))
    bio = c.biomes if c.biomes is not None else np.ones((16, 16), np.uint8)
    lvl = nbt.CompoundTag(
        {
            "xPos": nbt.IntTag(c.cx),
            "zPos": nbt.IntTag(c.cz),
            "LastUpdate": nbt.LongTag(c.last_update),
            "Blocks": nbt.ByteArrayTag(np.frombuffer(b.tobytes(), np.int8)),
            "Data": nbt.ByteArrayTag(np.frombuffer(d, np.int8)),
            "SkyLight": nbt.ByteArrayTag(np.frombuffer(s, np.int8)),
            "BlockLight": nbt.ByteArrayTag(np.frombuffer(l, np.int8)),
            "HeightMap": nbt.ByteArrayTag(np.frombuffer((c.heightmap if c.heightmap is not None and len(c.heightmap) == 256
                                                          else _heightmap(c)).astype(np.uint8).tobytes(), np.int8)),
            "TerrainPopulatedFlags": nbt.ShortTag(c.terrain_populated),
            "Biomes": nbt.ByteArrayTag(np.frombuffer(bio.astype(np.uint8).tobytes(), np.int8)),
            "Entities": nbt.compound_list(c.entities),
            "TileEntities": nbt.compound_list(c.tile_entities),
            "TileTicks": nbt.compound_list(c.tile_ticks),
        }
    )
    return nbt.dump(nbt.CompoundTag({"Level": lvl}), "")

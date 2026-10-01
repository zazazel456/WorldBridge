import struct

import numpy as np

from worldbridge.lce import chunk as ch
from worldbridge.lce.world import lce_to_numeric

from . import lcestudio_format12 as ref


def _build_v12(ids, data, wlog):
    jump = [0] * 16
    sizes = [0] * 16
    secblob = bytearray()
    for s in range(16):
        sec = ref._encode_section(ids, data, wlog, s)
        if sec is None:
            continue
        padded = sec + b"\x00" * ((-len(sec)) % 0x100)
        jump[s] = len(secblob)
        sizes[s] = len(padded) // 0x100
        secblob += padded
    out = bytearray(struct.pack(">H", 12))
    out += struct.pack(">iiqq", 3, -2, 0, 0)
    out += struct.pack(">H", len(secblob) // 0x100)
    out += struct.pack(">16H", *jump) + struct.pack(">16B", *sizes) + secblob
    # light: 4 sparse storages (all 15 sky / all 0 block), heightmap, flags, biomes, NBT
    full15 = np.full((128, 16, 16), 15, np.uint8)
    zero = np.zeros((128, 16, 16), np.uint8)
    for arr in (full15, full15, zero, zero):
        out += ch.encode_sparse(arr, True)
    out += bytes(256) + struct.pack(">h", 2046) + bytes([4]) * 256
    out += b"\x0a\x00\x00\x00"
    return bytes(out)


def test_aquatic_decode_matches_reference():
    rng = np.random.default_rng(5)
    ids = np.zeros((16, 256, 16), np.uint16)  # LCEStudio uses [x, y, z]
    data = np.zeros((16, 256, 16), np.uint8)
    wlog = np.zeros((16, 256, 16), bool)
    ids[:, :60, :] = 1
    ids[:, 60, :] = rng.choice([2, 3, 12, 258, 270, 300], (16, 16))
    data[:, 60, :] = rng.integers(0, 4, (16, 16))
    ids[3, 61, 4] = 35
    data[3, 61, 4] = 14
    wlog[5, 60, 5] = True
    ids[0, 100:120, 0] = rng.integers(0, 400, 20)
    payload = _build_v12(ids, data, wlog)
    c = ch.decode_chunk(payload)
    assert (c.cx, c.cz) == (3, -2)
    assert np.array_equal(c.blocks, ids.transpose(1, 2, 0))
    assert np.array_equal(c.data, data.transpose(1, 2, 0))
    assert c.waterlogged[60, 5, 5]
    n = lce_to_numeric(c)
    assert n.blocks.max() <= 255  # aquatic ids replaced by 1.12 fallbacks
    assert any(s.startswith("minecraft:kelp") or s.startswith("minecraft:seagrass") for s in n.modern_blocks.values())

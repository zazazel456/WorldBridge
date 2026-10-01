"""Cross-check the vectorised LCE storage codecs against literal ports of the
4J C++ code (CompressedTileStorage::setData/getData, SparseLightStorage)."""
import random
import struct

import numpy as np

from worldbridge.lce import chunk as ch


def get_index(block, tile):
    index = ((block & 0x180) << 6) | ((block & 0x060) << 4) | ((block & 0x01F) << 2)
    index |= ((tile & 0x30) << 7) | ((tile & 0x0C) << 5) | (tile & 0x03)
    return index


def ref_set_data(data):
    """Literal port of CompressedTileStorage::setData (compressing path)."""
    block_idx = [0] * 512
    mem = 0
    for i in range(512):
        used = set(data[get_index(i, j)] for j in range(64))
        count = len(used)
        if count == 1:
            block_idx[i] = 3 | 4
        elif count == 2:
            block_idx[i] = 0
            mem += 10
        elif count <= 4:
            block_idx[i] = 1
            mem += 20
        elif count <= 16:
            block_idx[i] = 2
            mem += 48
        else:
            block_idx[i] = 3
            mem = (mem + 3) & 0xFFFC
            mem += 64
    mem += 1024
    buf = bytearray(mem)
    pucdata = 1024
    off = 0
    new_idx = [0] * 512
    for i in range(512):
        t = block_idx[i] & 3
        new_idx[i] = t
        if t == 3:
            if block_idx[i] & 4:
                new_idx[i] = 3 | 4 | (data[get_index(i, 0)] << 8)
            else:
                off = (off + 3) & 0xFFFC
                for j in range(64):
                    buf[pucdata + off + j] = data[get_index(i, j)]
                new_idx[i] |= (off & 0x7FFE) << 1
                off += 64
        else:
            mappings = [255] * 256
            bpt = 1 << t
            ntypes = 1 << bpt
            datasize = 8 << t
            shift = 3 - t
            mbits = 7 >> t
            mbytes = 62 >> shift
            tt = pucdata + off
            rep = tt + ntypes
            for k in range(ntypes):
                buf[tt + k] = 255
            new_idx[i] |= (off & 0x7FFE) << 1
            off += ntypes + datasize
            cnt = 0
            for j in range(64):
                tile = data[get_index(i, j)]
                if mappings[tile] == 255:
                    mappings[tile] = cnt
                    buf[tt + cnt] = tile
                    cnt += 1
                idx = (j >> shift) & mbytes
                bit = (j & mbits) * bpt
                buf[rep + idx] |= mappings[tile] << bit
    struct.pack_into("<512H", buf, 0, *new_idx)
    return bytes(buf)


def make_data(rng):
    d = np.zeros(32768, np.uint8)
    for i in range(512):
        kind = rng.randint(0, 5)
        vals = {0: [1], 1: [1, 2], 2: [3, 4, 5], 3: list(range(10, 22)), 4: list(range(30, 90)), 5: [0]}[kind]
        for j in range(64):
            d[get_index(i, j)] = rng.choice(vals)
    return d


def test_tile_storage_vs_reference():
    rng = random.Random(7)
    for _ in range(3):
        d = make_data(rng)
        ref = ref_set_data(d.tolist())
        assert np.array_equal(ch.decode_tile_storage(ref), d)
        mine = ch.encode_tile_storage(d)
        assert np.array_equal(ch.decode_tile_storage(mine), d)


def test_sparse_roundtrip():
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 16, (128, 16, 16)).astype(np.uint8)
    arr[5] = 0
    arr[6] = 15
    for allow in (True, False):
        enc = ch.encode_sparse(arr, allow)
        count = struct.unpack(">i", enc[:4])[0]
        assert np.array_equal(ch.decode_sparse(enc[4:], count), arr)


def test_sparse_matches_java_order():
    """plane byte k holds xz=2k (low nibble) and 2k+1 (high), xz = x*16+z."""
    arr = np.zeros((128, 16, 16), np.uint8)
    arr[3, 2, 1] = 7  # y=3, z=2, x=1 -> xz = 1*16+2 = 18 -> byte 9 low nibble
    enc = ch.encode_sparse(arr, False)
    planes = enc[4 + 128:]
    assert enc[4 + 3] == 0 and planes[9] == 7


def test_chunk_roundtrip():
    c = ch.LCEChunk()
    rng = np.random.default_rng(2)
    c.cx, c.cz = -3, 5
    c.blocks[:70] = rng.integers(0, 200, (70, 16, 16))
    c.blocks[200] = 7
    c.data[:70] = rng.integers(0, 16, (70, 16, 16))
    c.sky = rng.integers(0, 16, (256, 16, 16)).astype(np.uint8)
    c.block_light = np.zeros((256, 16, 16), np.uint8)
    c.biomes = np.full((16, 16), 4, np.uint8)
    for v in (7, 8, 9):
        c2 = ch.decode_chunk(ch.encode_chunk(c, v))
        assert (c2.cx, c2.cz) == (-3, 5)
        assert np.array_equal(c2.blocks, c.blocks)
        assert np.array_equal(c2.data, c.data)
        assert np.array_equal(c2.sky, c.sky)
        assert np.array_equal(c2.biomes, c.biomes)

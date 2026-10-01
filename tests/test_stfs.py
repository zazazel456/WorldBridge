"""Xbox 360 STFS packages: the files, the name and the thumbnail are read back from packages built
here with the block placement written out in closed form (independent of the reader's layout)."""
import random
import struct

import pytest

from worldbridge.lce.stfs import STFS

BASE = 0xA000


def _pos(b, t):
    """Position of data block b (in blocks from the data area) with tables of t blocks."""
    l0 = b // 170 + 1
    l1 = 0 if b < 170 else b // 28900 + 1
    return b + t * (l0 + l1)


def _package(files, t, backup, name="Mondo àè", thumb=b"\x89PNG\r\n\x1a\nxyz"):
    """files: [(name, bytes)]; t = 1 or 2 blocks per table; backup: current tables in the 2nd copy."""
    blocks, entries, nxt = [], [], {}
    listing_blocks = 1
    start = listing_blocks
    for fname, data in files:
        n = max(1, -(-len(data) // 0x1000))
        entries.append((fname, start, n, len(data)))
        for i in range(n):
            nxt[start + i] = start + i + 1 if i < n - 1 else 0xFFFFFF
        start += n
    total = start
    listing = bytearray(0x1000)
    for i, (fname, first, n, size) in enumerate(entries):
        e = bytearray(0x40)
        e[:len(fname)] = fname.encode()
        e[0x28] = len(fname)
        e[0x29:0x2C] = n.to_bytes(3, "little")
        e[0x2C:0x2F] = n.to_bytes(3, "little")
        e[0x2F:0x32] = first.to_bytes(3, "little")
        struct.pack_into(">I", e, 0x34, size)
        listing[i * 0x40:(i + 1) * 0x40] = e
    nxt[0] = 0xFFFFFF
    data_blocks = [bytes(listing)]
    for _, data in files:
        for o in range(0, max(len(data), 1), 0x1000):
            data_blocks.append(data[o:o + 0x1000].ljust(0x1000, b"\0"))
    size = _pos(total - 1, t) + 1 + 4 * t
    buf = bytearray(BASE + size * 0x1000)
    buf[:4] = b"CON "
    struct.pack_into(">I", buf, 0x340, 0x971A)
    buf[0x411:0x411 + 0x80] = name.encode("utf-16-be").ljust(0x80, b"\0")
    struct.pack_into(">I", buf, 0x1712, len(thumb))
    buf[0x171A:0x171A + len(thumb)] = thumb
    buf[0x37B] = (0 if t == 2 else 1) | (2 if backup and t == 2 else 0)
    struct.pack_into("<H", buf, 0x37C, listing_blocks)
    buf[0x37E:0x381] = (0).to_bytes(3, "little")
    struct.pack_into(">I", buf, 0x395, total)
    for b, blk in enumerate(data_blocks):
        o = BASE + _pos(b, t) * 0x1000
        buf[o:o + 0x1000] = blk
    copy = 1 if backup and t == 2 else 0
    for b in range(total):                                   # level-0 entries: status and next block
        l0 = _pos(170 * (b // 170), t) - t + copy
        o = BASE + l0 * 0x1000 + (b % 170) * 0x18
        buf[o + 0x14] = 0x80
        buf[o + 0x15:o + 0x18] = nxt.get(b, 0xFFFFFF).to_bytes(3, "big")
        if copy:                                             # garbage in the stale primary copy
            p = o - 0x1000
            buf[p + 0x15:p + 0x18] = b"\x12\x34\x56"
    if total > 170:                                          # level-1 table: which copy of each L0
        l1 = _pos(170, t) - 2 * t
        for g in range(-(-total // 170)):
            o = BASE + l1 * 0x1000 + g * 0x18
            buf[o + 0x14] = 0x80 | (0x40 if copy else 0)
            if copy:
                buf[BASE + (l1 + 1) * 0x1000 + g * 0x18 + 0x14] = 0xC0
    return bytes(buf)


@pytest.mark.parametrize("t", [1, 2])
@pytest.mark.parametrize("backup", [False, True])
@pytest.mark.parametrize("sizes", [[500], [300_000], [900_000, 70_000]])
def test_stfs_reads_files_name_and_thumbnail(t, backup, sizes):
    rnd = random.Random(sum(sizes) + t)
    files = [("savegame.dat" if i == 0 else f"extra{i}.bin", bytes(rnd.getrandbits(8) for _ in range(n)))
             for i, n in enumerate(sizes)]
    pkg = STFS(_package(files, t, backup))
    assert sorted(pkg.files) == sorted(n for n, _ in files)
    for fname, data in files:
        assert pkg.read_file(fname) == data
    assert pkg.display_name == "Mondo àè"
    assert pkg.thumbnail == b"\x89PNG\r\n\x1a\nxyz"


def test_not_stfs():
    with pytest.raises(ValueError):
        STFS(b"\0" * 0x2000)

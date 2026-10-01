"""Java Edition region files (.mcr McRegion / .mca Anvil)."""

from __future__ import annotations

import gzip
import os
import struct
import time
import zlib
from typing import Dict, Iterator, Optional, Tuple

SECTOR = 4096


def region_chunks(path: str) -> Iterator[Tuple[int, int]]:
    """The chunks a region file holds, from its 4 KiB header only (listing a big world must not
    read gigabytes of chunk data)."""
    with open(path, "rb") as f:
        head = f.read(SECTOR)
    if len(head) < SECTOR:
        return
    for i, off in enumerate(struct.unpack(">1024I", head)):
        if off:
            yield i % 32, i // 32


class ChunkIndex:
    """Where the chunks of a dimension are: one entry per region file (its path and the chunks it holds,
    as a 1024-bit mask), not one per chunk, so a world of millions of chunks costs a few hundred bytes
    per region.  ``get((cx, cz))`` gives ``(path, lx, lz)`` like a dictionary of chunks would."""

    def __init__(self):
        self.regions: Dict[Tuple[int, int], Tuple[str, int]] = {}
        self._n = 0

    def add_region(self, rx: int, rz: int, path: str) -> None:
        mask = 0
        for lx, lz in region_chunks(path):
            mask |= 1 << (lx + lz * 32)
        if mask:
            self.regions[(rx, rz)] = (path, mask)
            self._n += bin(mask).count("1")

    def get(self, key: Tuple[int, int], default=None):
        cx, cz = key
        entry = self.regions.get((cx >> 5, cz >> 5))
        if entry is None or not (entry[1] >> ((cx & 31) + (cz & 31) * 32)) & 1:
            return default
        return entry[0], cx & 31, cz & 31

    def __contains__(self, key) -> bool:
        return self.get(key) is not None

    def __iter__(self) -> Iterator[Tuple[int, int]]:
        for (rx, rz), (_path, mask) in self.regions.items():
            for i in range(1024):
                if (mask >> i) & 1:
                    yield rx * 32 + (i & 31), rz * 32 + (i >> 5)

    def keys(self) -> Iterator[Tuple[int, int]]:
        return iter(self)

    def __len__(self) -> int:
        return self._n


class JavaRegion:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        self.offsets = struct.unpack_from(">1024I", self.data, 0) if len(self.data) >= 8192 else (0,) * 1024

    def chunks(self) -> Iterator[Tuple[int, int]]:
        for i, off in enumerate(self.offsets):
            if off:
                yield i % 32, i // 32

    def read(self, lx: int, lz: int) -> Optional[bytes]:
        off = self.offsets[lx + lz * 32]
        if not off:
            return None
        p = (off >> 8) * SECTOR
        if p + 5 > len(self.data):
            return None
        length, ctype = struct.unpack_from(">IB", self.data, p)
        if ctype & 0x80:  # external .mcc (1.15+)
            base = os.path.splitext(self.path)[0]
            parts = os.path.basename(base).split(".")
            rx, rz = int(parts[1]), int(parts[2])
            ext = os.path.join(os.path.dirname(self.path), f"c.{rx * 32 + lx}.{rz * 32 + lz}.mcc")
            if not os.path.exists(ext):
                return None
            with open(ext, "rb") as f:
                body = f.read()
            ctype &= 0x7F
        else:
            body = self.data[p + 5 : p + 4 + length]
        try:
            if ctype == 1:
                return gzip.decompress(body)
            if ctype == 2:
                return zlib.decompress(body)
            if ctype == 3:
                return body
            if ctype == 4:
                try:
                    import lz4.block  # type: ignore

                    return lz4.block.decompress(body)
                except Exception:  # noqa: BLE001
                    return None
        except (OSError, zlib.error):
            return None
        return None


class RegionWriter:
    """Accumulates chunks and writes one region file."""

    def __init__(self):
        self.chunks: Dict[Tuple[int, int], bytes] = {}

    def put(self, lx: int, lz: int, nbt_bytes: bytes):
        self.chunks[(lx, lz)] = zlib.compress(nbt_bytes, 6)

    def put_compressed(self, lx: int, lz: int, comp: bytes):
        """A chunk already compressed with zlib (level 6, as ``put``)."""
        self.chunks[(lx, lz)] = comp

    def write(self, path: str):
        offsets = [0] * 1024
        stamps = [0] * 1024
        body = bytearray()
        sector = 2
        now = int(time.time())
        for (lx, lz), comp in sorted(self.chunks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            blob = struct.pack(">IB", len(comp) + 1, 2) + comp
            count = (len(blob) + SECTOR - 1) // SECTOR
            if count > 255:
                continue  # too large for the classic format
            blob += b"\x00" * (count * SECTOR - len(blob))
            i = lx + lz * 32
            offsets[i] = (sector << 8) | count
            stamps[i] = now
            body += blob
            sector += count
        with open(path, "wb") as f:
            f.write(struct.pack(">1024I", *offsets))
            f.write(struct.pack(">1024I", *stamps))
            f.write(body)

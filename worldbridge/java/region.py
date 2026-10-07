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
                raw = gzip.decompress(body)
            elif ctype == 2:
                raw = zlib.decompress(body)
            elif ctype == 3:
                raw = body
            elif ctype == 4:
                raw = decompress_lz4(body)
            else:
                return None
            if raw and raw[:2] == b"\x1f\x8b":  # compressed twice (MCEdit 2 wrote zlib around gzip)
                raw = gzip.decompress(raw)
            return raw
        except (OSError, zlib.error, ValueError):
            return None


_LZ4_HEADER = struct.Struct("<8sBiii")  # magic, token, compressed length, original length, checksum


def decompress_lz4(data: bytes) -> Optional[bytes]:
    """A chunk saved with ``region-file-compression=lz4`` (Java 1.20.5+): the LZ4 block stream of
    lz4-java (``LZ4BlockOutputStream``), not a bare LZ4 block."""
    try:
        import lz4.block  # type: ignore
    except ImportError:
        return None
    out = []
    i = 0
    while i + _LZ4_HEADER.size <= len(data):
        magic, token, clen, olen, _check = _LZ4_HEADER.unpack_from(data, i)
        i += _LZ4_HEADER.size
        method = token & 0xF0
        if magic != b"LZ4Block" or clen < 0 or olen < 0:
            raise ValueError("corrupted LZ4 block")
        if olen == 0:                       # the stream's end mark
            break
        if method == 0x10:                  # stored
            out.append(data[i : i + olen])
        elif method == 0x20:
            out.append(lz4.block.decompress(data[i : i + clen], uncompressed_size=olen))
        else:
            raise ValueError("corrupted LZ4 block")
        i += clen
    return b"".join(out)


class RegionWriter:
    """Accumulates chunks and writes one region file.

    ``external``: a chunk over 1 MiB goes to its own ``c.X.Z.mcc`` file, as Java 1.15+ stores it;
    older games cannot read those, and such a chunk is left out (listed in ``dropped``)."""

    def __init__(self, external: bool = False):
        self.chunks: Dict[Tuple[int, int], bytes] = {}
        self.external = external
        self.dropped: list = []

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
            if count > 255:  # too large for a region file
                if not self.external:
                    self.dropped.append((lx, lz))
                    continue
                rx, rz = (int(v) for v in os.path.basename(path).split(".")[1:3])
                with open(os.path.join(os.path.dirname(path) or ".", f"c.{rx * 32 + lx}.{rz * 32 + lz}.mcc"), "wb") as m:
                    m.write(comp)
                blob = struct.pack(">IB", 1, 2 | 0x80)
                count = 1
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

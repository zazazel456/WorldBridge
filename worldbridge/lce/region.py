"""LCE region files (``r.X.Z.mcr`` inside the save container).

Layout (Minecraft.World/RegionFile.cpp)::

    4096 bytes   offsets     1024 x u32 (sector << 8 | sector count), save endian
    4096 bytes   timestamps  1024 x u32
    sectors      chunk:  u32 compressed length (bit31 = RLE used)
                         u32 decompressed length
                         compressed bytes

Chunk payload compression: platform compressor + 4J RLE
(zlib on most platforms, [u32 BE size][raw deflate] on PS3, LZX on Xbox 360).
"""

from __future__ import annotations

import struct
import time
import zlib
from typing import Dict, Iterator, Optional, Tuple

from . import compression as comp

SECTOR = 4096


def decompress_payload(data: bytes, rle: bool, method: Optional[str], decomp_len: int) -> bytes:
    """Undo the platform compression (+ RLE) of one chunk.

    ``method`` may be None to auto-detect."""
    methods = [method] if method else []
    for m in ("zlib", "ps3", "lzx"):
        if m not in methods:
            methods.append(m)
    last_err = None
    for m in methods:
        try:
            if m == "zlib":
                if data[:1] != b"\x78":
                    raise ValueError("no zlib header")
                raw = comp.zlib_decompress(data)
            elif m == "ps3":
                raw = comp.ps3_decompress(data)
            elif m == "lzx":
                raw = comp.xmem_decompress(data)
            else:
                raise ValueError(m)
            out = comp.rle_decode(raw) if rle else raw
            if decomp_len and len(out) < decomp_len:
                raise ValueError("short chunk")
            return out[:decomp_len] if decomp_len else out
        except Exception as ex:  # noqa: BLE001
            last_err = ex
    raise ValueError(f"cannot decompress chunk: {last_err}")


def compress_payload(payload: bytes, method: str) -> bytes:
    rle = comp.rle_encode(payload)
    if method == "zlib":
        return comp.zlib_compress(rle)
    if method == "ps3":
        return comp.ps3_compress(rle)
    if method == "lzx":
        return comp.xmem_compress(rle)
    raise ValueError(method)


def region_entries(region: bytes, endian: str, width: int = 32) -> Iterator[Tuple[int, int, int, int, bool, int]]:
    """Yield (local_x, local_z, payload offset, payload length, rle, decompressed_len), without
    copying the payloads (the index of a whole save)."""
    if len(region) < 2 * SECTOR:
        return
    offsets = struct.unpack_from(endian + "1024I", region, 0)
    nsec = len(region) // SECTOR
    for idx in range(1024):
        off = offsets[idx]
        if not off:
            continue
        sector, count = off >> 8, off & 0xFF
        if sector < 2 or sector + count > nsec + 1:
            continue
        p = sector * SECTOR
        if p + 8 > len(region):
            continue
        length, dlen = struct.unpack_from(endian + "II", region, p)
        rle = bool(length & 0x80000000)
        length &= 0x3FFFFFFF
        if length == 0 or p + 8 + length > len(region):
            continue
        x, z = idx % 32, idx // 32
        if x >= width or z >= width:
            continue
        yield x, z, p + 8, length, rle, dlen


def iter_region_chunks(region: bytes, endian: str, width: int = 32) -> Iterator[Tuple[int, int, bytes, bool, int]]:
    """Yield (local_x, local_z, compressed_bytes, rle, decompressed_len)."""
    for x, z, p, length, rle, dlen in region_entries(region, endian, width):
        yield x, z, region[p:p + length], rle, dlen


def build_region(chunks: Dict[Tuple[int, int], tuple], endian: str) -> bytes:
    """chunks: (local_x, local_z) -> (compressed bytes, decompressed length[, RLE used (default yes)])."""
    offsets = [0] * 1024
    stamps = [0] * 1024
    body = bytearray()
    sector = 2
    now = int(time.time())
    for (x, z), entry in sorted(chunks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        data, dlen = entry[0], entry[1]
        rle = entry[2] if len(entry) > 2 else True
        blob = struct.pack(endian + "II", (0x80000000 if rle else 0) | len(data), dlen) + data
        count = (len(blob) + SECTOR - 1) // SECTOR
        if count >= 256:
            raise ValueError("chunk too large for a region sector run")
        blob += b"\x00" * (count * SECTOR - len(blob))
        idx = x + z * 32
        offsets[idx] = (sector << 8) | count
        stamps[idx] = now
        body += blob
        sector += count
    head = struct.pack(endian + "1024I", *offsets) + struct.pack(endian + "1024I", *stamps)
    return head + bytes(body)

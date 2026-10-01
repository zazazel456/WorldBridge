"""Compression codecs used by Legacy Console Edition saves.

Implemented from the 4J source (Minecraft.World/compression.cpp):

* 4J RLE  - used on every region chunk before the platform compressor
* zlib    - Windows64, Wii U, PS4, Xbox One, Switch, PS Vita chunks
* PS3     - ``[u32 BE size][raw deflate]`` (EdgeZLib)
* LZX     - XMemCompress, Xbox 360 (vendored pure python codec)
* Vita    - zero run length encoding used for the whole Vita save container
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from .vendor import lzx_codec as _lzx

# ---------------------------------------------------------------- 4J RLE


def rle_decode(data: bytes, expected: int = 0) -> bytes:
    """Inverse of Compression::CompressRLE.

    0..254            -> literal byte
    255, k (k<3)      -> k+1 copies of 255
    255, k (k>=3), b  -> k+1 copies of b
    """
    out = bytearray()
    n = len(data)
    i = 0
    find = data.find
    while i < n:
        j = find(b"\xff", i)
        if j < 0:
            out += data[i:]
            break
        if j > i:
            out += data[i:j]
        if j + 1 >= n:
            break
        k = data[j + 1]
        if k < 3:
            out += b"\xff" * (k + 1)
            i = j + 2
        else:
            if j + 2 >= n:
                break
            out += bytes((data[j + 2],)) * (k + 1)
            i = j + 3
    return bytes(out)


def rle_encode(data: bytes) -> bytes:
    """Compression::CompressRLE (vectorised with numpy, byte-identical)."""
    if not data:
        return b""
    a = np.frombuffer(data, np.uint8)
    n = a.size
    # run boundaries
    change = np.nonzero(a[1:] != a[:-1])[0] + 1
    starts = np.concatenate(([0], change))
    lengths = np.diff(np.concatenate((starts, [n])))
    values = a[starts]
    # split runs longer than 256
    if lengths.max() > 256:
        reps = (lengths + 255) // 256
        values = np.repeat(values, reps)
        new_len = np.full(values.size, 256, np.int64)
        last = np.cumsum(reps) - 1
        new_len[last] = lengths - (reps - 1) * 256
        lengths = new_len
    lengths = lengths.astype(np.int64)
    is_ff = values == 255
    literal = (lengths <= 3) & ~is_ff  # emitted as `len` plain bytes
    short_ff = (lengths <= 3) & is_ff  # 255, len-1
    size = np.where(literal, lengths, np.where(short_ff, 2, 3))
    offs = np.concatenate(([0], np.cumsum(size)[:-1]))
    total = int(size.sum())
    out = np.empty(total, np.uint8)
    # literals
    lit_off = offs[literal]
    lit_len = lengths[literal]
    if lit_len.size:
        idx = np.repeat(lit_off, lit_len) + (np.arange(int(lit_len.sum())) - np.repeat(np.cumsum(lit_len) - lit_len, lit_len))
        out[idx] = np.repeat(values[literal], lit_len)
    # markers
    mk = ~literal
    mo = offs[mk]
    out[mo] = 255
    out[mo + 1] = (lengths[mk] - 1).astype(np.uint8)
    long_ = mk & ~short_ff
    out[offs[long_] + 2] = values[long_]
    return out.tobytes()


# ---------------------------------------------------------------- Vita zero-RLE


def vita_decode(data: bytes) -> bytes:
    out = bytearray()
    n = len(data)
    i = 0
    find = data.find
    while i < n:
        j = find(b"\x00", i)
        if j < 0:
            out += data[i:]
            break
        out += data[i:j]
        if j + 1 >= n:
            break
        out += bytes(data[j + 1])
        i = j + 2
    return bytes(out)


def vita_encode(data: bytes) -> bytes:
    out = bytearray()
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
        while k < n and data[k] == 0 and k - j < 255:
            k += 1
        out += bytes((0, k - j))
        i = k
    return bytes(out)


# ---------------------------------------------------------------- zlib / deflate


def zlib_decompress(data: bytes, size_hint: int = 0) -> bytes:
    d = zlib.decompressobj()
    try:
        return d.decompress(data) + d.flush()
    except zlib.error:
        # some saves carry trailing garbage / truncated adler: salvage
        d = zlib.decompressobj()
        out = bytearray()
        try:
            for i in range(0, len(data), 4096):
                out += d.decompress(data[i : i + 4096])
        except zlib.error:
            pass
        if not out:
            raise
        return bytes(out)


def zlib_compress(data: bytes, level: int = 6) -> bytes:
    return zlib.compress(data, level)


def raw_inflate(data: bytes) -> bytes:
    d = zlib.decompressobj(-15)
    return d.decompress(data) + d.flush()


def raw_deflate(data: bytes, level: int = 6) -> bytes:
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def ps3_decompress(data: bytes) -> bytes:
    """EdgeZLib stream: [u32 BE uncompressed size][raw deflate]."""
    if data[:1] == b"\x78":  # tolerate plain zlib
        return zlib_decompress(data)
    return raw_inflate(data[4:])


def ps3_compress(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + raw_deflate(data)


# ---------------------------------------------------------------- LZX (Xbox 360)

_WINDOW = 0x20000
_SLOTS = _lzx._num_position_slots(_WINDOW)
_EXTRA, _BASE = _lzx._build_pos_tables(_SLOTS)


def _xmem_frames(body: bytes):
    payload = bytearray()
    raw_total = 0
    off, n = 0, len(body)
    while off < n:
        if body[off] == 0xFF:
            if off + 5 > n:
                break
            raw = struct.unpack_from(">H", body, off + 1)[0]
            clen = struct.unpack_from(">H", body, off + 3)[0]
            off += 5
        else:
            if off + 2 > n:
                break
            raw = 0x8000
            clen = struct.unpack_from(">H", body, off)[0]
            off += 2
        if clen == 0:
            break
        payload += body[off : off + clen]
        off += clen
        raw_total += raw
    return bytes(payload), raw_total


def xmem_decompress(body: bytes, out_len: int = 0) -> bytes:
    """Decode an XMemCompress framed LZX stream (no container header)."""
    payload, raw_total = _xmem_frames(body)
    if not out_len:
        out_len = raw_total
    return bytes(_lzx.lzx_decompress_chunk(payload, out_len, _SLOTS, _EXTRA, _BASE))


def xmem_compress(data: bytes) -> bytes:
    return _lzx.xmem_compress(data)

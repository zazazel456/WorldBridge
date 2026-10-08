"""The world icon of a Java world.

A Java server loads ``<world>/icon.png`` as the server list icon and refuses anything that is not a
64 x 64 PNG ("Couldn't load server icon: Must be 64 pixels wide").  The icon of a source world is
whatever it was: a Bedrock ``world_icon.jpeg`` (640 x 360), an LCE thumbnail, a PNG of any size.
``java_icon`` returns it as a 64 x 64 PNG, or None when it cannot be decoded.
"""

from __future__ import annotations

import struct
import zlib
from typing import Optional

import numpy as np

SIZE = 64
_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)], axis=1).tobytes()
    return (_SIG + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def png_size(data: bytes) -> Optional[tuple]:
    if len(data) >= 24 and data[:8] == _SIG and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def decode_png(data: bytes) -> Optional[np.ndarray]:
    """An 8 bit, non interlaced PNG as an RGBA array [h, w, 4] (None: another flavour)."""
    if png_size(data) is None:
        return None
    pos, idat, plte, trns, hdr = 8, [], None, None, None
    while pos + 8 <= len(data):
        n, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = np.frombuffer(body, np.uint8).reshape(-1, 3)
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    if hdr is None or not idat:
        return None
    w, h, depth, ctype, _comp, _flt, interlace = hdr
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or interlace or chans is None or w <= 0 or h <= 0:
        return None
    raw = np.frombuffer(zlib.decompress(b"".join(idat)), np.uint8)
    stride = w * chans
    if raw.size < h * (stride + 1):
        return None
    raw = raw[:h * (stride + 1)].reshape(h, stride + 1)
    out = np.zeros((h, stride), np.int32)
    for y in range(h):
        f, line = int(raw[y, 0]), raw[y, 1:].astype(np.int32)
        prev = out[y - 1] if y else np.zeros(stride, np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:                                     # Sub / Average / Paeth depend on the pixel to the left
            cur = np.zeros(stride, np.int32)
            for i in range(stride):
                a = cur[i - chans] if i >= chans else 0
                b = prev[i]
                c = prev[i - chans] if i >= chans else 0
                if f == 1:
                    p = a
                elif f == 3:
                    p = (a + b) >> 1
                elif f == 4:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                else:
                    return None
                cur[i] = (line[i] + p) & 255
        out[y] = cur
    px = out.astype(np.uint8).reshape(h, w, chans)
    if ctype == 0:
        rgb, a = np.repeat(px, 3, axis=2), np.full((h, w, 1), 255, np.uint8)
    elif ctype == 2:
        rgb, a = px, np.full((h, w, 1), 255, np.uint8)
    elif ctype == 3:
        if plte is None:
            return None
        idx = px[:, :, 0]
        rgb = plte[np.minimum(idx, len(plte) - 1)]
        alpha = np.full(len(plte), 255, np.uint8)
        if trns:
            alpha[:len(trns)] = np.frombuffer(trns, np.uint8)[:len(plte)]
        a = alpha[np.minimum(idx, len(plte) - 1)][:, :, None]
    elif ctype == 4:
        rgb, a = np.repeat(px[:, :, :1], 3, axis=2), px[:, :, 1:]
    else:
        rgb, a = px[:, :, :3], px[:, :, 3:]
    return np.concatenate([rgb, a], axis=2).astype(np.uint8)


def _square64(rgba: np.ndarray) -> np.ndarray:
    """Centre crop to a square, then box average (or repeat) to 64 x 64."""
    h, w = rgba.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    sq = rgba[y0:y0 + s, x0:x0 + s].astype(np.float64)
    ys = np.minimum((np.arange(SIZE + 1) * s) // SIZE, s)
    ys[-1] = s
    out = np.zeros((SIZE, SIZE, 4), np.float64)
    if s >= SIZE:
        for i in range(SIZE):
            rows = sq[ys[i]:max(ys[i + 1], ys[i] + 1)]
            for j in range(SIZE):
                out[i, j] = rows[:, ys[j]:max(ys[j + 1], ys[j] + 1)].mean(axis=(0, 1))
    else:
        idx = (np.arange(SIZE) * s) // SIZE
        out = sq[idx][:, idx]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def _qt_rgba(data: bytes) -> Optional[np.ndarray]:
    """Any image Qt reads (JPEG ...) as RGBA, when PySide6 is installed."""
    try:
        from PySide6.QtGui import QImage
    except Exception:  # noqa: BLE001
        return None
    img = QImage.fromData(data)
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = np.frombuffer(bytes(img.constBits()), np.uint8)
    return buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()


def java_icon(data: Optional[bytes]) -> Optional[bytes]:
    """The icon as a 64 x 64 PNG (a PNG of that size is kept as it is), None when it is not an image."""
    if not data:
        return None
    if png_size(data) == (SIZE, SIZE):
        return data
    try:
        rgba = decode_png(data)
    except Exception:  # noqa: BLE001
        rgba = None
    if rgba is None:
        try:
            rgba = _qt_rgba(data)
        except Exception:  # noqa: BLE001
            rgba = None
    if rgba is None or min(rgba.shape[:2]) < 1:
        return None
    return encode_png(_square64(rgba))

"""BTA's NBT dialect.

BTA forked the NBT library: tag 11 is a *short* array, 12 a double array and 13 a long array, all
three little-endian (vanilla: 11 int array, 12 long array, big-endian).  Documents are read into
plain Python values (dict / list / int / float / str / numpy arrays), which is all the converter
needs and much faster than building tag objects for every chunk.
"""

from __future__ import annotations

import gzip
import struct
from typing import Any, Dict, Optional

import numpy as np


class BtaNbtError(ValueError):
    pass


_MAX_LEN = 64 * 1024 * 1024
_S_B, _S_H, _S_I, _S_Q, _S_F, _S_D = (struct.Struct(f) for f in (">b", ">h", ">i", ">q", ">f", ">d"))


def _utf(raw: bytes) -> str:
    """Java modified UTF-8 (NUL as C0 80, supplementary characters as surrogate pairs)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.replace(b"\xc0\x80", b"\x00").decode("utf-8", "surrogatepass")
        try:
            return s.encode("utf-16", "surrogatepass").decode("utf-16")
        except UnicodeError:
            return raw.decode("utf-8", "replace")


class _Reader:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def take(self, n: int) -> bytes:
        p = self.pos
        if n < 0 or p + n > len(self.buf):
            raise BtaNbtError("unexpected end of NBT data")
        self.pos = p + n
        return self.buf[p:p + n]

    def s(self, st: struct.Struct):
        p = self.pos
        if p + st.size > len(self.buf):
            raise BtaNbtError("unexpected end of NBT data")
        self.pos = p + st.size
        return st.unpack_from(self.buf, p)[0]

    def string(self) -> str:
        n = struct.unpack_from(">H", self.take(2))[0]
        return _utf(self.take(n))

    def length(self) -> int:
        n = self.s(_S_I)
        if n < 0 or n > _MAX_LEN:
            raise BtaNbtError(f"bad NBT array length {n}")
        return n

    def payload(self, t: int, depth: int = 0) -> Any:
        if depth > 512:
            raise BtaNbtError("NBT nesting too deep")
        if t == 1:
            return self.s(_S_B)
        if t == 2:
            return self.s(_S_H)
        if t == 3:
            return self.s(_S_I)
        if t == 4:
            return self.s(_S_Q)
        if t == 5:
            return self.s(_S_F)
        if t == 6:
            return self.s(_S_D)
        if t == 7:
            return np.frombuffer(self.take(self.length()), np.int8)
        if t == 8:
            return self.string()
        if t == 9:
            et = self.s(_S_B)
            n = self.s(_S_I)
            if n < 0 or n > 16 * 1024 * 1024:
                raise BtaNbtError(f"bad list length {n}")
            if n and et == 0:
                raise BtaNbtError("list of TAG_End with elements")
            return [self.payload(et, depth + 1) for _ in range(n)]
        if t == 10:
            out: Dict[str, Any] = {}
            while True:
                ct = self.s(_S_B)
                if ct == 0:
                    return out
                name = self.string()
                out[name] = self.payload(ct, depth + 1)
        if t == 11:  # BTA short array (little-endian)
            n = self.length()
            return np.frombuffer(self.take(n * 2), "<i2")
        if t == 12:  # BTA double array
            n = self.length()
            return np.frombuffer(self.take(n * 8), "<f8")
        if t == 13:  # BTA long array
            n = self.length()
            return np.frombuffer(self.take(n * 8), "<i8")
        raise BtaNbtError(f"unknown BTA NBT tag type {t}")


def loads(raw: bytes) -> Dict[str, Any]:
    """Root compound of an uncompressed BTA NBT document."""
    r = _Reader(raw)
    if r.s(_S_B) != 10:
        raise BtaNbtError("root tag is not a compound")
    r.string()
    return r.payload(10)


def load_gzip(path: str) -> Dict[str, Any]:
    with open(path, "rb") as f:
        raw = f.read()
    try:
        raw = gzip.decompress(raw)
    except OSError as ex:
        raise BtaNbtError(f"{path}: not a gzip NBT file ({ex})") from ex
    return loads(raw)


# ------------------------------------------------------------------ lenient getters
# BTA sometimes stores the same field with different widths across versions: numbers are read
# whatever their NBT type (like the typed getters of the game's CompoundTag).


def _num(d: Optional[dict], key: str):
    if not isinstance(d, dict):
        return None
    v = d.get(key)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return None


def _wrap32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def gi(d: Optional[dict], key: str, default: int = 0) -> int:
    v = _num(d, key)
    if v is None:
        return default
    if isinstance(v, float):
        if v != v:
            return 0
        return max(-(1 << 31), min((1 << 31) - 1, int(v)))
    return _wrap32(v)


def gl(d: Optional[dict], key: str, default: int = 0) -> int:
    v = _num(d, key)
    if v is None:
        return default
    return int(v) if not isinstance(v, float) or v == v else 0


def gf(d: Optional[dict], key: str, default: float = 0.0) -> float:
    v = _num(d, key)
    return default if v is None else float(v)


def gb(d: Optional[dict], key: str, default: bool = False) -> bool:
    v = _num(d, key)
    return default if v is None else gi(d, key) != 0


def gs(d: Optional[dict], key: str, default: str = "") -> str:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, str) else default


def gc(d: Optional[dict], key: str) -> Optional[dict]:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else None


def glist(d: Optional[dict], key: str) -> Optional[list]:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, list) else None


def num(v, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

"""Thin helpers around :mod:`amulet_nbt` so the rest of the code never has to
care about the exact library API."""

from __future__ import annotations

import gzip
import zlib
from typing import Iterable, Optional, Tuple

import amulet_nbt as _n

from amulet_nbt import (  # noqa: F401  (re-exported)
    ByteArrayTag,
    ByteTag,
    CompoundTag,
    DoubleTag,
    FloatTag,
    IntArrayTag,
    IntTag,
    ListTag,
    LongArrayTag,
    LongTag,
    NamedTag,
    NBTError,
    ShortTag,
    StringTag,
)


def load(data: bytes, little_endian: bool = False, compressed: Optional[bool] = None) -> NamedTag:
    """Load one NBT document from ``data``.

    ``compressed`` = None auto-detects gzip / zlib."""
    if compressed is None:
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        elif data[:1] == b"\x78":
            try:
                data = zlib.decompress(data)
            except zlib.error:
                pass
    elif compressed:
        data = gzip.decompress(data)
    if little_endian:  # Bedrock: game-written records hold raw bytes in some strings (actor storage keys)
        return _n.load(data, compressed=False, little_endian=True, string_decoder=_n.utf8_escape_decoder)
    return _n.load(data, compressed=False, little_endian=little_endian)


def load_with_offset(data: bytes, offset: int = 0, little_endian: bool = False, escape: bool = False) -> Tuple[NamedTag, int]:
    """Load one NBT document starting at ``offset``; returns (tag, end_offset)."""
    ctx = _n.ReadContext()
    kw = {"string_decoder": _n.utf8_escape_decoder} if escape else {}
    tag = _n.load(memoryview(data)[offset:], compressed=False, little_endian=little_endian, read_context=ctx, **kw)
    return tag, offset + ctx.offset


def dump(tag, name: str = "", little_endian: bool = False, compressed: bool = False, escape: bool = False) -> bytes:
    """``escape`` writes strings with amulet's utf8-escape encoder (raw bytes in
    strings, needed for Bedrock actor storage keys)."""
    if isinstance(tag, NamedTag):
        named = tag
    else:
        named = NamedTag(tag, name)
    if escape:
        raw = named.to_nbt(compressed=False, little_endian=little_endian, string_encoder=_n.utf8_escape_encoder)
    else:
        raw = named.to_nbt(compressed=False, little_endian=little_endian)
    if compressed:
        return gzip.compress(raw, 6)
    return raw


def escape_string(raw: bytes) -> StringTag:
    return StringTag(_n.utf8_escape_decoder(raw))


def get(tag: CompoundTag, key: str, default=None):
    """Return the python value of ``tag[key]`` or ``default``."""
    try:
        v = tag[key]
    except (KeyError, TypeError):
        return default
    return getattr(v, "py_data", v)


def state_name(entry, default: str = "minecraft:air") -> str:
    """Block name of a palette entry.  Up to 1.21: a compound with "Name" (and "Properties").  Java
    26.x: a plain string for a block without properties, {"id", "properties"} for the others, and
    in a list mixing the two kinds every string is wrapped as {"": name}."""
    v = getattr(entry, "py_data", entry)
    if isinstance(v, str):
        return v
    for key in ("Name", "id", ""):
        name = get(entry, key)
        if name is not None:
            return str(name)
    return default


def state_props(entry):
    """The properties compound of a palette entry (see ``state_name``), or None."""
    for key in ("Properties", "properties"):
        t = get_tag(entry, key)
        if t is not None:
            return t
    return None


def get_tag(tag: CompoundTag, key: str, default=None):
    try:
        return tag[key]
    except (KeyError, TypeError):
        return default


def compound_list(items: Iterable[CompoundTag]) -> ListTag:
    lst = ListTag([], 10)
    for it in items:
        lst.append(it)
    return lst


def copy(tag):
    """Deep copy of an NBT tag."""
    return _n.load(NamedTag(tag, "").to_nbt(compressed=False), compressed=False).tag

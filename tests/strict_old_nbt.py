"""NBT reader with the rules of Minecraft Alpha / Beta: only tag types 1-10 exist (int arrays
arrived with Anvil 1.2, long arrays with 1.12) and an unknown type makes the whole file unreadable."""
import gzip
import struct


class Unreadable(Exception):
    pass


def _payload(t, buf, pos, path, maxtype):
    def take(n):
        nonlocal pos
        if pos + n > len(buf):
            raise Unreadable(f"EOF in {path}")
        b = buf[pos:pos + n]
        pos += n
        return b

    if not 1 <= t <= maxtype:
        raise Unreadable(f"tag type {t} in {path}")
    fmt = {1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}.get(t)
    if fmt:
        return (t, struct.unpack(fmt, take(struct.calcsize(fmt)))[0]), pos
    if t == 7:
        n = struct.unpack(">i", take(4))[0]
        return (t, take(n)), pos
    if t == 8:
        n = struct.unpack(">H", take(2))[0]
        return (t, take(n).decode("utf-8")), pos
    if t in (11, 12):
        n = struct.unpack(">i", take(4))[0]
        take(n * (4 if t == 11 else 8))
        return (t, None), pos
    if t == 9:
        et, n = struct.unpack(">bi", take(5))
        items = []
        for i in range(n):
            v, pos = _payload(et, buf, pos, f"{path}[{i}]", maxtype)
            items.append(v)
        return (t, items), pos
    d = {}
    while True:
        ct = take(1)[0]
        if ct == 0:
            return (t, d), pos
        n = struct.unpack(">H", take(2))[0]
        name = take(n).decode("utf-8")
        d[name], pos = _payload(ct, buf, pos, f"{path}.{name}", maxtype)


def load(raw: bytes, gz: bool = True, maxtype: int = 10) -> dict:
    """{name: (type, value)} of the root compound."""
    if gz:
        raw = gzip.decompress(raw)
    if raw[0] != 10:
        raise Unreadable("root is not a compound")
    n = struct.unpack(">H", raw[1:3])[0]
    (_t, v), _pos = _payload(10, raw, 3 + n, "", maxtype)
    return v

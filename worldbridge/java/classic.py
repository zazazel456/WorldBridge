"""Minecraft Classic levels (rd-132211 … 0.30): ``level.dat`` / ``*.mine``.

Formats handled:

* pre-0.0.13  raw gzip of 256x64x256 block bytes
* version 1   magic 0x271BB788, 1, name, creator, time, width, height, depth, blocks
* version 2   magic 0x271BB788, 2, Java serialised ``com.mojang.minecraft.level.Level``
"""

from __future__ import annotations

import gzip
import struct
from typing import Any, Dict, List, Optional

import numpy as np

from .. import nbt
from ..model import WorldInfo
from .finite import CLASSIC_CLOTH, FiniteWorld

MAGIC = 0x271BB788


class _JavaStream:
    """Minimal java.io.ObjectInputStream reader (enough for Classic levels)."""

    def __init__(self, data: bytes):
        self.d = data
        self.p = 0
        self.handles: List[Any] = []

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def read(self, fmt):
        v = struct.unpack_from(">" + fmt, self.d, self.p)
        self.p += struct.calcsize(">" + fmt)
        return v[0] if len(v) == 1 else v

    def utf(self):
        n = self.read("H")
        s = self.d[self.p : self.p + n].decode("utf-8", "replace")
        self.p += n
        return s

    def content(self):
        tc = self.u8()
        if tc == 0x70:  # NULL
            return None
        if tc == 0x71:  # REFERENCE
            return self.handles[self.read("i") - 0x7E0000]
        if tc == 0x74:  # STRING
            s = self.utf()
            self.handles.append(s)
            return s
        if tc == 0x7C:  # LONGSTRING
            n = self.read("q")
            s = self.d[self.p : self.p + n].decode("utf-8", "replace")
            self.p += n
            self.handles.append(s)
            return s
        if tc == 0x72 or tc == 0x7D:  # CLASSDESC
            self.p -= 1
            return self.classdesc()
        if tc == 0x75:  # ARRAY
            desc = self.classdesc()
            n = self.read("i")
            name = desc["name"]
            idx = len(self.handles)
            self.handles.append(None)
            et = name[1]
            if et == "B":
                arr = np.frombuffer(self.d, np.uint8, n, self.p).copy()
                self.p += n
            elif et in "IFJDSCZ":
                fmt = {"I": "i", "F": "f", "J": "q", "D": "d", "S": "h", "C": "H", "Z": "?"}[et]
                arr = [self.read(fmt) for _ in range(n)]
            else:
                arr = [self.content() for _ in range(n)]
            self.handles[idx] = arr
            return arr
        if tc == 0x73:  # OBJECT
            desc = self.classdesc()
            obj: Dict[str, Any] = {"__class__": desc["name"] if desc else None}
            self.handles.append(obj)
            chain = []
            d = desc
            while d:
                chain.append(d)
                d = d["super"]
            for d in reversed(chain):
                for typ, fname, _cls in d["fields"]:
                    obj[fname] = self.value(typ)
                if d["flags"] & 0x01:  # SC_WRITE_METHOD: custom data until ENDBLOCKDATA
                    obj.setdefault("__annotations__", []).extend(self.annotations())
            return obj
        if tc == 0x77:  # BLOCKDATA
            n = self.u8()
            b = self.d[self.p : self.p + n]
            self.p += n
            return b
        if tc == 0x7A:
            n = self.read("i")
            b = self.d[self.p : self.p + n]
            self.p += n
            return b
        if tc == 0x7E:  # ENUM
            desc = self.classdesc()
            idx = len(self.handles)
            self.handles.append(None)
            name = self.content()
            self.handles[idx] = name
            return name
        if tc == 0x78:
            return "__END__"
        raise ValueError(f"unsupported java serialisation tag 0x{tc:02x}")

    def annotations(self):
        out = []
        while True:
            v = self.content()
            if v == "__END__":
                return out
            out.append(v)

    def classdesc(self):
        tc = self.u8()
        if tc == 0x70:
            return None
        if tc == 0x71:
            return self.handles[self.read("i") - 0x7E0000]
        if tc != 0x72:
            raise ValueError("proxy class descriptors are not supported")
        name = self.utf()
        self.read("q")
        desc = {"name": name, "fields": [], "flags": 0, "super": None}
        self.handles.append(desc)
        desc["flags"] = self.u8()
        for _ in range(self.read("H")):
            typ = chr(self.u8())
            fname = self.utf()
            cls = self.content() if typ in "[L" else None
            desc["fields"].append((typ, fname, cls))
        self.annotations()
        desc["super"] = self.classdesc()
        return desc

    def value(self, typ):
        if typ == "B":
            return self.read("b")
        if typ == "C":
            return self.read("H")
        if typ == "D":
            return self.read("d")
        if typ == "F":
            return self.read("f")
        if typ == "I":
            return self.read("i")
        if typ == "J":
            return self.read("q")
        if typ == "S":
            return self.read("h")
        if typ == "Z":
            return self.read("?")
        return self.content()


def _to_java_ids(blocks: np.ndarray):
    src = blocks.astype(np.uint16)
    b = src.copy()
    data = np.zeros(b.shape, np.uint8)
    for cid, color in CLASSIC_CLOTH.items():
        m = src == cid
        if m.any():
            b[m] = 35
            data[m] = color
    b[src > 49] = 0
    return b, data


def load_classic(path: str) -> FiniteWorld:
    raw = gzip.open(path).read()
    info = WorldInfo()
    name = "Classic World"
    spawn: Optional[tuple] = None
    if len(raw) == 256 * 64 * 256 and struct.unpack_from(">I", raw, 0)[0] != MAGIC:
        w, l, h = 256, 256, 64
        blocks = np.frombuffer(raw, np.uint8)
    else:
        magic, ver = struct.unpack_from(">IB", raw, 0)
        if magic != MAGIC:
            raise ValueError("not a Minecraft Classic level")
        if ver == 1:
            p = 5
            n = struct.unpack_from(">H", raw, p)[0]
            name = raw[p + 2 : p + 2 + n].decode("utf-8", "replace")
            p += 2 + n
            n = struct.unpack_from(">H", raw, p)[0]
            p += 2 + n + 8
            w, l, h = struct.unpack_from(">hhh", raw, p)
            p += 6
            blocks = np.frombuffer(raw, np.uint8, w * l * h, p)
        else:
            js = _JavaStream(raw[5:])
            if js.read("H") != 0xACED:
                raise ValueError("bad serialisation stream")
            js.read("H")
            obj = js.content()
            w, l, h = int(obj["width"]), int(obj["height"]), int(obj["depth"])
            blocks = np.asarray(obj["blocks"], np.uint8)
            name = obj.get("name") or name
            if "xSpawn" in obj:
                spawn = (int(obj["xSpawn"]), int(obj["ySpawn"]), int(obj["zSpawn"]))
    vol = blocks[: w * l * h].reshape(h, l, w)  # classic index: (y * height + z) * width + x
    b, data = _to_java_ids(vol)
    info.level = nbt.CompoundTag({"LevelName": nbt.StringTag(name), "GameType": nbt.IntTag(1)})
    if spawn is None:
        spawn = (w // 2, h // 2 + 2, l // 2)
    info.level["SpawnX"], info.level["SpawnY"], info.level["SpawnZ"] = (nbt.IntTag(v) for v in spawn)
    info.source_description = "Java Edition Classic"
    return FiniteWorld(b, data, info)


class ClassicWorld(FiniteWorld):
    def __init__(self, path: str):
        w = load_classic(path)
        self.__dict__.update(w.__dict__)

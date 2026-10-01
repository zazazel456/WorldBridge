"""Java Edition 26.3 block states: definitions from the vanilla data generator, interned states
with integer ids, and the vanilla state facts / block tags used to rebuild neighbour shapes.

Every state is validated against the vanilla definitions when created, so an invalid mapping fails
loudly instead of writing a block that Minecraft would throw away.
"""

from __future__ import annotations

import gzip
import os
import threading
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

_DATA = os.path.join(os.path.dirname(__file__), "data")


def _open(name: str):
    p = os.path.join(_DATA, name)
    if name.endswith(".gz"):
        return gzip.open(p, "rt", encoding="utf-8")
    return open(p, encoding="utf-8")


class Def:
    __slots__ = ("name", "props", "values", "defaults", "index")

    def __init__(self, name: str, props: Tuple[str, ...], values: Tuple[Tuple[str, ...], ...], defaults: Tuple[str, ...]):
        self.name = name
        self.props = props
        self.values = values
        self.defaults = defaults
        self.index = {p: i for i, p in enumerate(props)}


def _load_defs() -> Dict[str, Def]:
    defs: Dict[str, Def] = {}
    with _open("blocks-26.3.txt") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("|")
            name = parts[0]
            props: List[str] = []
            values: List[Tuple[str, ...]] = []
            defaults: List[str] = []
            if parts[1]:
                for ps in parts[1].split(";"):
                    k, v = ps.split("=", 1)
                    props.append(k)
                    values.append(tuple(v.split(",")))
                defaults = [d.split("=", 1)[1] for d in parts[2].split(",")]
            defs[name] = Def(name, tuple(props), tuple(values), tuple(defaults))
    return defs


DEFS = _load_defs()


class InvalidState(ValueError):
    pass


class BlockState:
    __slots__ = ("defn", "values", "key", "id", "name")

    def __init__(self, defn: Def, values: Tuple[str, ...], key: str, sid: int):
        self.defn = defn
        self.values = values
        self.key = key
        self.id = sid
        self.name = defn.name

    def has(self, prop: str) -> bool:
        return prop in self.defn.index

    def get(self, prop: str) -> Optional[str]:
        i = self.defn.index.get(prop)
        return None if i is None else self.values[i]

    def with_(self, prop: str, value: str) -> "BlockState":
        i = self.defn.index.get(prop)
        if i is None:
            raise InvalidState(f"Block {self.name} has no property '{prop}'")
        if self.values[i] == value:
            return self
        if value not in self.defn.values[i]:
            raise InvalidState(f"Block {self.name} property {prop} does not allow '{value}'")
        v = list(self.values)
        v[i] = value
        return _intern(self.defn, tuple(v))

    def is_(self, name: str) -> bool:
        return self.name == name

    @property
    def is_air(self) -> bool:
        return self.name in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")

    def properties(self) -> List[Tuple[str, str]]:
        return list(zip(self.defn.props, self.values))

    def __repr__(self) -> str:
        return self.key


_LOCK = threading.Lock()
_INTERN: Dict[str, BlockState] = {}
_BY_ID: List[BlockState] = []


def _make_key(defn: Def, values: Tuple[str, ...]) -> str:
    if not values:
        return defn.name
    return defn.name + "[" + ",".join(f"{p}={v}" for p, v in zip(defn.props, values)) + "]"


def _intern(defn: Def, values: Tuple[str, ...]) -> BlockState:
    key = _make_key(defn, values)
    s = _INTERN.get(key)
    if s is not None:
        return s
    with _LOCK:
        s = _INTERN.get(key)
        if s is None:
            s = BlockState(defn, values, key, len(_BY_ID))
            _BY_ID.append(s)
            _INTERN[key] = s
    return s


def state(name: str, *kv: str, **props: str) -> BlockState:
    """``state("chest", facing="north")`` (or ``state("chest", "facing", "north")``): unspecified
    properties take the vanilla default."""
    if ":" not in name:
        name = "minecraft:" + name
    defn = DEFS.get(name)
    if defn is None:
        raise InvalidState(f"Unknown 26.3 block: {name}")
    if len(kv) % 2:
        raise InvalidState(f"Odd property list for {name}")
    items = list(zip(kv[0::2], kv[1::2])) + list(props.items())
    values = list(defn.defaults)
    for k, v in items:
        i = defn.index.get(k)
        if i is None:
            raise InvalidState(f"Block {name} has no property '{k}'")
        if v not in defn.values[i]:
            raise InvalidState(f"Block {name} property {k} does not allow '{v}'")
        values[i] = v
    return _intern(defn, tuple(values))


def by_id(sid: int) -> BlockState:
    return _BY_ID[sid]


def count() -> int:
    return len(_BY_ID)


AIR = state("air")
BEDROCK = state("bedrock")

# ------------------------------------------------------------------ vanilla facts and tags
DOWN, UP, NORTH, SOUTH, WEST, EAST = range(6)
_FACTS: Optional[Dict[str, Tuple[int, bool, bool, bool, str]]] = None
_TAGS: Optional[Dict[str, frozenset]] = None


def _canonical(key: str) -> str:
    b = key.find("[")
    if b < 0:
        return key
    return key[:b] + "[" + ",".join(sorted(key[b + 1:-1].split(","))) + "]"


def _facts_table() -> Dict[str, Tuple[int, bool, bool, bool, str]]:
    global _FACTS
    if _FACTS is None:
        t: Dict[str, Tuple[int, bool, bool, bool, str]] = {}
        with _open("statedata-26.3.txt.gz") as f:
            for line in f:
                p = line.rstrip("\n").split("|")
                if len(p) >= 6:
                    t[_canonical(p[0])] = (int(p[1]), p[2] == "1", p[3] == "1", p[4] == "1", p[5])
        _FACTS = t
    return _FACTS


def tags() -> Dict[str, frozenset]:
    global _TAGS
    if _TAGS is None:
        t: Dict[str, frozenset] = {}
        with _open("tags-26.3.txt") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.strip():
                    name, members = line.split("|", 1)
                    t[name] = frozenset(m for m in members.split(",") if m)
        _TAGS = t
    return _TAGS


_facts_cache: Dict[int, Tuple[int, bool, bool, bool, str]] = {}


def facts(s: BlockState) -> Tuple[int, bool, bool, bool, str]:
    f = _facts_cache.get(s.id)
    if f is None:
        f = _facts_table().get(_canonical(s.key))
        if f is None:
            raise InvalidState(f"No vanilla state data for {s.key}")
        _facts_cache[s.id] = f
    return f


def has_facts(s: BlockState) -> bool:
    return _canonical(s.key) in _facts_table()


def sturdy(s: BlockState, direction: int) -> bool:
    return bool(facts(s)[0] & (1 << direction))


def full_cube(s: BlockState) -> bool:
    return facts(s)[1]


def conductor(s: BlockState) -> bool:
    return facts(s)[2]


def signal_source(s: BlockState) -> bool:
    return facts(s)[3]


def instrument(s: BlockState) -> str:
    return facts(s)[4]


def in_tag(s: BlockState, tag: str) -> bool:
    t = tags().get(tag)
    if t is None:
        raise KeyError(f"tag not exported: {tag}")
    return s.name in t


def lut(pred, size: Optional[int] = None) -> np.ndarray:
    """Boolean table over the state ids created so far."""
    n = size if size is not None else count()
    return np.fromiter((pred(_BY_ID[i]) for i in range(n)), bool, n)


def palette_tag(s: BlockState, name: Optional[str] = None):
    """Palette entry in the pre-26 layout ("Name" / "Properties")."""
    from .. import nbt

    t = nbt.CompoundTag({"Name": nbt.StringTag(name or s.name)})
    if s.values:
        t["Properties"] = nbt.CompoundTag({p: nbt.StringTag(v) for p, v in zip(s.defn.props, s.values)})
    return t


def all_names() -> Sequence[str]:
    return sorted(DEFS)

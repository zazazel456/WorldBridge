"""Composition: the converted world holds only GROUPS of chunks of the source world, each group placed
at its own destination (to bring parts of a big world closer, e.g. to fit a finite LCE / Pocket Edition map).

API (everything the GUI needs)::

    group = Group(dim=OVERWORLD, chunks=frozenset({(100, 40), (101, 40)}), offset=(-100, -40))   # offset in chunks
    layout = Layout([group, ...])
    layout.problems(bounds)          # list of readable problems ([] = valid); bounds: convert.layout_bounds(target, layout)
    layout.dest(dim, cx, cz)         # (cx', cz') where a source chunk lands, None: it is not in any group (not written)
    layout.source_chunks()           # {dim: set of source chunks}: what is read
    layout.placed()                  # {dim: set of destination chunks}: what the border (ring...) goes around
    layout.save(path) / Layout.load(path) / Layout.from_dict(data) / layout.to_dict()
    Selection(layout=layout)         # the conversion: ``TargetSpec(selection=Selection(layout=layout))``

``Layout.centred(chunks, (x, z))`` is what ``--move-to`` is: one group per dimension whose bounding-box centre lands on the
block (x, z) (the Nether's point is that divided by 8).  Offsets are whole chunks, in the dimension's own coordinates
(a Nether group's offset is in Nether chunks).  File format (``--layout FILE.json``)::

    {"groups": [{"dimension": "overworld", "chunks": [[100, 40], [101, 40]], "offset": [-100, -40]},
                {"dimension": "nether", "chunks": "3,4;3,5", "offset": [0, 0]}]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .i18n import tr
from .model import NETHER, OVERWORLD, THE_END

Chunk = Tuple[int, int]
Box = Tuple[int, int, int, int]                    # chunks [x0, x1) × [z0, z1)

DIM_NAMES = {OVERWORLD: "overworld", NETHER: "nether", THE_END: "end"}
_DIM_BY_NAME = {"overworld": OVERWORLD, "nether": NETHER, "end": THE_END, "the_end": THE_END}
MAX_PROBLEMS = 12                                  # listed per kind (the rest is counted)


def parse_chunks(value) -> Set[Chunk]:
    """``[[x, z], ...]`` or ``"x,z;x,z"`` -> a set of chunks."""
    out: Set[Chunk] = set()
    if isinstance(value, str):
        for part in value.replace("\n", ";").split(";"):
            if part.strip():
                x, z = part.split(",")
                out.add((int(x), int(z)))
        return out
    for p in value:
        if len(p) != 2:
            raise ValueError(f"{p!r}")
        out.add((int(p[0]), int(p[1])))
    return out


@dataclass(frozen=True)
class Group:
    dim: int
    chunks: frozenset
    offset: Chunk                                  # whole chunks, added to every chunk of the group
    name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "chunks", frozenset((int(x), int(z)) for x, z in self.chunks))
        object.__setattr__(self, "offset", (int(self.offset[0]), int(self.offset[1])))

    def dest(self, cx: int, cz: int) -> Chunk:
        return cx + self.offset[0], cz + self.offset[1]

    def placed(self) -> Set[Chunk]:
        dx, dz = self.offset
        return {(x + dx, z + dz) for x, z in self.chunks}

    def label(self) -> str:
        return self.name or tr("group {n} chunks of the {dim}", n=len(self.chunks), dim=DIM_NAMES.get(self.dim, str(self.dim)))


@dataclass
class Layout:
    groups: List[Group] = field(default_factory=list)

    def __post_init__(self):
        self._maps: Dict[int, Dict[Chunk, Chunk]] = {}
        self._for = -1

    # ------------------------------------------------------------------ lookup
    def _map(self, dim: int) -> Dict[Chunk, Chunk]:
        """source chunk -> offset, for one dimension (the first group wins for a chunk in two: see problems())."""
        if self._for != len(self.groups):                  # groups added since
            self._maps, self._for = {}, len(self.groups)
        m = self._maps.get(dim)
        if m is None:
            m = {}
            for g in self.groups:
                if g.dim == dim:
                    for c in g.chunks:
                        m.setdefault(c, g.offset)
            self._maps[dim] = m
        return m

    def offset(self, dim: int, cx: int, cz: int) -> Optional[Chunk]:
        """The offset (in chunks) of the group holding a source chunk; None: no group has it."""
        return self._map(dim).get((cx, cz))

    def dest(self, dim: int, cx: int, cz: int) -> Optional[Chunk]:
        o = self.offset(dim, cx, cz)
        return None if o is None else (cx + o[0], cz + o[1])

    def groups_of(self, dim: int) -> List[Group]:
        return [g for g in self.groups if g.dim == dim]

    def dimensions(self) -> List[int]:
        return sorted({g.dim for g in self.groups if g.chunks})

    def source_chunks(self) -> Dict[int, Set[Chunk]]:
        out: Dict[int, Set[Chunk]] = {}
        for g in self.groups:
            out.setdefault(g.dim, set()).update(g.chunks)
        return out

    def placed(self) -> Dict[int, Set[Chunk]]:
        out: Dict[int, Set[Chunk]] = {}
        for g in self.groups:
            out.setdefault(g.dim, set()).update(g.placed())
        return out

    def default_spawn(self) -> Optional[Tuple[int, int]]:
        """A block inside the first Overworld group (its destination chunk nearest to the centre): where a player
        that stood outside every group starts."""
        gs = [g for g in self.groups_of(OVERWORLD) if g.chunks]
        if not gs:
            return None
        cs = sorted(gs[0].placed())
        cx = (min(c[0] for c in cs) + max(c[0] for c in cs)) / 2
        cz = (min(c[1] for c in cs) + max(c[1] for c in cs)) / 2
        x, z = min(cs, key=lambda c: ((c[0] - cx) ** 2 + (c[1] - cz) ** 2, c))
        return x * 16 + 8, z * 16 + 8

    # ------------------------------------------------------------------ validation
    def problems(self, bounds: Optional[Dict[int, Box]] = None) -> List[str]:
        """What stops the layout from being converted, as readable lines ([] = valid): an empty group, a source chunk in two
        groups, two groups landing on the same destination chunk, destinations outside the finite map.  ``bounds``:
        per dimension the destination chunks ``[x0, x1) × [z0, z1)`` the target can hold (``convert.layout_bounds``);
        a dimension without an entry is unlimited."""
        out: List[str] = []
        if not self.groups:
            return [tr("The layout has no group.")]
        for g in self.groups:
            if not g.chunks:
                out.append(tr("{group} is empty.", group=g.label()))
        for dim in self.dimensions():
            seen: Dict[Chunk, int] = {}
            dups: List[Tuple[Chunk, int, int]] = []
            hit: Dict[Chunk, int] = {}
            clash: List[Tuple[Chunk, int, int]] = []
            for i, g in enumerate(self.groups):
                if g.dim != dim:
                    continue
                dx, dz = g.offset
                for c in g.chunks:
                    if c in seen and seen[c] != i:
                        dups.append((c, seen[c], i))
                    seen.setdefault(c, i)
                    d = (c[0] + dx, c[1] + dz)
                    if d in hit and hit[d] != i:
                        clash.append((d, hit[d], i))
                    hit.setdefault(d, i)
            name = DIM_NAMES.get(dim, str(dim))
            for c, a, b in sorted(dups)[:MAX_PROBLEMS]:
                out.append(tr("{dim}: the source chunk {x}, {z} is in two groups ({a} and {b}).", dim=name, x=c[0], z=c[1],
                              a=self.groups[a].label(), b=self.groups[b].label()))
            for d, a, b in sorted(clash)[:MAX_PROBLEMS]:
                out.append(tr("{dim}: the groups {a} and {b} overlap at the destination chunk {x}, {z}.", dim=name,
                              x=d[0], z=d[1], a=self.groups[a].label(), b=self.groups[b].label()))
            more = max(0, len(dups) - MAX_PROBLEMS) + max(0, len(clash) - MAX_PROBLEMS)
            if more:
                out.append(tr("{dim}: {n} more chunks with the same problem.", dim=name, n=more))
            box = (bounds or {}).get(dim)
            if box is not None:
                x0, x1, z0, z1 = box
                bad = sorted(d for d in hit if not (x0 <= d[0] < x1 and z0 <= d[1] < z1))
                if bad:
                    out.append(tr("{dim}: {n} chunks land outside the map (chunks x {x0}..{x1m}, z {z0}..{z1m}), e.g. {x}, {z}.",
                                  dim=name, n=len(bad), x0=x0, x1m=x1 - 1, z0=z0, z1m=z1 - 1, x=bad[0][0], z=bad[0][1]))
        return out

    # ------------------------------------------------------------------ files
    def to_dict(self) -> dict:
        return {"groups": [dict({"dimension": DIM_NAMES.get(g.dim, str(g.dim)),
                                 "chunks": [list(c) for c in sorted(g.chunks)],
                                 "offset": list(g.offset)}, **({"name": g.name} if g.name else {}))
                           for g in self.groups]}

    @classmethod
    def from_dict(cls, data) -> "Layout":
        """Raises ValueError with a readable message when the structure is wrong (the content is checked by problems())."""
        if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
            raise ValueError(tr('expected an object with a "groups" list'))
        groups = []
        for i, g in enumerate(data["groups"], 1):
            try:
                dim = _DIM_BY_NAME[str(g.get("dimension", "overworld")).strip().lower()]
                off = g["offset"]
                groups.append(Group(dim, frozenset(parse_chunks(g["chunks"])), (int(off[0]), int(off[1])),
                                    str(g.get("name", ""))))
            except (KeyError, TypeError, ValueError, AttributeError, IndexError):
                raise ValueError(tr("group {n}: expected \"dimension\" (overworld, nether, end), \"chunks\" "
                                    "([[x, z], ...] or \"x,z;x,z\") and \"offset\" ([dx, dz])", n=i))
        return cls(groups)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "Layout":
        try:
            with open(path, encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except json.JSONDecodeError as ex:
            raise ValueError(tr("{path}: not valid JSON ({error})", path=path, error=ex))

    # ------------------------------------------------------------------ --move-to
    @classmethod
    def centred(cls, chunks: Dict[int, Iterable[Chunk]], dest: Chunk) -> "Layout":
        """One group per dimension: the centre of its bounding box lands on the block ``dest`` (the Nether: that point
        divided by 8) -- the behaviour of ``--move-to``."""
        bx, bz = dest
        groups = []
        for dim, cs in chunks.items():
            cs = frozenset(cs)
            if not cs:
                continue
            xs, zs = [c[0] for c in cs], [c[1] for c in cs]
            ccx, ccz = (min(xs) + max(xs)) >> 1, (min(zs) + max(zs)) >> 1
            scale = 8 if dim == NETHER else 1
            groups.append(Group(dim, cs, ((bx // scale >> 4) - ccx, (bz // scale >> 4) - ccz)))
        return cls(groups)

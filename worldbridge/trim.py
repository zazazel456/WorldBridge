"""World trim: find the chunks nobody has really used and leave them out.

Minecraft Java (1.6.1+) and Legacy Console Edition store in every chunk ``InhabitedTime``: the
game ticks (20 per second) players have spent within range of that chunk.  A chunk that was only
generated while flying past has (almost) none, so dropping it frees space and lets Minecraft
generate it again with the current terrain.

Defaults follow the community consensus:

* MCA Selector guides (Pufferfish, GGServers, Falix, ...): delete ``InhabitedTime < 1 minute``;
  higher thresholds "can be destructive for a small gain in disk space";
* Aternos' Thanos (run on millions of hosted worlds) never removes force-loaded chunks nor chunks
  whose InhabitedTime cannot be read, and lists "trees / builds cut off at the border" as its known
  issue - hence a protective ring of kept chunks around every used chunk;
* the spawn area, which every player crosses, is kept as well.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import nbt
from .i18n import N_, language, tr
from .model import ConversionError, NETHER, OVERWORLD, Progress, THE_END, copy_tree

Chunk = Tuple[int, int]
TICKS_PER_SECOND = 20
_REGION_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")
_INHABITED = b"\x04\x00\x0dInhabitedTime"


@dataclass
class TrimOptions:
    min_ticks: int = 60 * TICKS_PER_SECOND   # keep chunks inhabited for at least this long (1 minute)
    ring: int = 1                            # kept chunks around every used chunk
    spawn_radius: int = 2                    # chunks around the world spawn that are always kept
    keep_forced: bool = True                 # /forceload chunks
    keep_unknown: bool = True                # chunks whose InhabitedTime cannot be read

    def describe(self) -> str:
        return tr("InhabitedTime < {time} → removed · protective ring {ring} chunks · spawn ±{spawn} chunks",
                  time=format_ticks(self.min_ticks), ring=self.ring, spawn=self.spawn_radius)


DEFAULTS = TrimOptions()


def format_ticks(t: int) -> str:
    s = t / TICKS_PER_SECOND
    if s >= 3600 and s % 3600 == 0:
        return f"{int(s // 3600)} h"
    if s >= 60 and s % 60 == 0:
        return f"{int(s // 60)} min"
    return f"{s:g} s"


def parse_duration(text: str) -> int:
    """"1m", "90s", "2h", "1 minute", "1200" (ticks) -> ticks."""
    t = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(t|ticks?|s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?)?", t)
    if not m:
        raise ValueError(tr("invalid duration: {text} (e.g. 1m, 30s, 2h or a number of ticks)", text=repr(text)))
    v = float(m.group(1))
    unit = (m.group(2) or "t")[0]
    return int(round(v * {"t": 1, "s": TICKS_PER_SECOND, "m": 60 * TICKS_PER_SECOND, "h": 3600 * TICKS_PER_SECOND}[unit]))


# ------------------------------------------------------------------ scanning
@dataclass
class TrimScan:
    """InhabitedTime of every chunk (None = not recorded / unreadable), per dimension."""

    kind: str
    inhabited: Dict[int, Dict[Chunk, Optional[int]]] = field(default_factory=dict)
    forced: Dict[int, Set[Chunk]] = field(default_factory=dict)
    spawn: Tuple[int, int, int] = (0, 64, 0)
    can_copy: bool = False            # a trimmed copy can be written in the same format
    path: str = ""                    # the world's folder (the detected root, not the level.dat that may have been given)

    def total(self) -> int:
        return sum(len(v) for v in self.inhabited.values())


class TrimUnavailable(ConversionError):
    pass


def _inhabited_of(raw: Optional[bytes]) -> Optional[int]:
    if raw is None:
        return None
    i = raw.find(_INHABITED)
    if i < 0 or i + len(_INHABITED) + 8 > len(raw):
        return None
    return struct.unpack_from(">q", raw, i + len(_INHABITED))[0]


def _java_base(world: str, dim: int) -> str:
    from .java.modern import _folder

    return os.path.dirname(_folder(world, dim, "region"))


def _forced_java(world: str, dim: int) -> Set[Chunk]:
    """Force-loaded chunks: data/chunks.dat ("Forced" longs, 1.14 - 1.21.4) or chunk_tickets.dat
    (1.21.5+, tickets of type forced)."""
    out: Set[Chunk] = set()
    base = _java_base(world, dim)
    for root, _dirs, files in os.walk(os.path.join(base, "data")):
        for fn in files:
            if fn not in ("chunks.dat", "chunk_tickets.dat"):
                continue
            try:
                tag = nbt.load(open(os.path.join(root, fn), "rb").read()).tag
            except Exception:  # noqa: BLE001
                continue
            _collect_forced(tag, out)
    return out


def _collect_forced(t, out: Set[Chunk]) -> None:
    if isinstance(t, nbt.CompoundTag):
        forced = t.get("Forced") if "Forced" in t else None
        if isinstance(forced, nbt.LongArrayTag):
            for v in forced:
                v = int(v) & 0xFFFFFFFFFFFFFFFF
                x, z = v & 0xFFFFFFFF, v >> 32
                out.add((x - (1 << 32) if x >= 1 << 31 else x, z - (1 << 32) if z >= 1 << 31 else z))
        pos = t.get("chunk_pos") if "chunk_pos" in t else None
        if isinstance(pos, nbt.IntArrayTag) and len(pos) == 2 and "forced" in str(nbt.get(t, "type", "")):
            out.add((int(pos[0]), int(pos[1])))
        for v in t.values():
            _collect_forced(v, out)
    elif isinstance(t, nbt.ListTag):
        for v in t:
            _collect_forced(v, out)


def scan(path: str, progress: Optional[Progress] = None) -> TrimScan:
    """Reads InhabitedTime of every chunk of a world (Java 1.6.1+ or Legacy Console Edition)."""
    from . import detect as det
    from .mapview import open_map

    progress = progress or Progress()
    d = det.detect(path)
    if d is None:
        raise TrimUnavailable(tr("World format not recognised."))
    why = {"bedrock": N_("Bedrock Edition does not record the time spent in chunks (InhabitedTime)."),
           "pe_old": N_("Pocket Edition 0.x does not record the time spent in chunks."),
           "bta": N_("Better than Adventure (based on Beta 1.7.3) does not record the time spent in chunks."),
           "indev": N_("Indev worlds are not divided into chunks."), "classic": N_("Classic worlds are not divided into chunks."),
           "archive": N_("Extract the archive first: the trim works on a folder.")}.get(d.kind)
    if d.kind == "java_numeric" and d.subkind != "anvil":
        why = N_("InhabitedTime exists since Java 1.6.1: Alpha / Beta / McRegion worlds do not record it.")
    if why:
        raise TrimUnavailable(tr(why))
    m = open_map(d.path, progress)
    try:
        res = TrimScan(d.kind, spawn=tuple(int(v) for v in m.spawn), path=d.path)
        if d.kind in ("java_modern", "java_numeric"):
            _scan_java(d.path, res, progress)
            res.can_copy = True
        elif d.kind == "lce":
            _scan_hub(m, res, progress)
        else:
            raise TrimUnavailable(tr("Trim not available for {world}.", world=d.description))
    finally:
        m.close()
    known = [t for dims in res.inhabited.values() for t in dims.values() if t is not None]
    if not known or max(known) <= 0:
        raise TrimUnavailable(tr("This world does not record the time spent in chunks (InhabitedTime always 0): the "
                                 "trim would delete everything."))
    return res


def _scan_java(world: str, res: TrimScan, progress: Progress) -> None:
    from .java.modern import _folder
    from .java.region import JavaRegion

    jobs = []
    for dim in (OVERWORLD, NETHER, THE_END):
        folder = _folder(world, dim, "region")
        if os.path.isdir(folder):
            for fn in os.listdir(folder):
                m = _REGION_RE.match(fn)
                if m and os.path.getsize(os.path.join(folder, fn)) >= 8192:
                    jobs.append((dim, int(m.group(1)), int(m.group(2)), os.path.join(folder, fn)))
    for i, (dim, rx, rz, p) in enumerate(jobs):
        progress.check()
        out = res.inhabited.setdefault(dim, {})
        try:
            reg = JavaRegion(p)
        except OSError:
            continue
        for lx, lz in reg.chunks():
            out[(rx * 32 + lx, rz * 32 + lz)] = _inhabited_of(reg.read(lx, lz))
        progress.update((i + 1) / max(1, len(jobs)), tr("Reading InhabitedTime: region {i}/{n}", i=i + 1, n=len(jobs)))
    for dim in list(res.inhabited):
        res.forced[dim] = _forced_java(world, dim)


def _scan_hub(m, res: TrimScan, progress: Progress) -> None:
    world = m.world
    dims = world.dimensions()
    total = sum(len(world.chunk_coords(d)) for d in dims) or 1
    done = 0
    for dim in dims:
        out = res.inhabited.setdefault(dim, {})
        for cx, cz in world.chunk_coords(dim):
            progress.check()
            try:
                c = world.read_chunk(dim, cx, cz)
            except Exception:  # noqa: BLE001
                c = None
            out[(cx, cz)] = None if c is None else int(getattr(c, "inhabited_time", 0) or 0)
            done += 1
            if done % 64 == 0:
                progress.update(done / total, tr("Reading InhabitedTime: chunk {i}/{n}", i=done, n=total))


# ------------------------------------------------------------------ choosing what stays
def keep_set(scan_: TrimScan, dim: int, opt: TrimOptions = DEFAULTS) -> Set[Chunk]:
    """Chunks of ``dim`` that stay: used ones (plus forced / unknown / spawn), grown by the ring."""
    chunks = scan_.inhabited.get(dim, {})
    keep = {c for c, t in chunks.items() if (t is None and opt.keep_unknown) or (t is not None and t >= opt.min_ticks)}
    if opt.keep_forced:
        keep |= scan_.forced.get(dim, set()) & chunks.keys()
    if dim == OVERWORLD and opt.spawn_radius >= 0:
        sx, sz = scan_.spawn[0] >> 4, scan_.spawn[2] >> 4
        r = opt.spawn_radius
        keep |= {(x, z) for x in range(sx - r, sx + r + 1) for z in range(sz - r, sz + r + 1)} & chunks.keys()
    if opt.ring > 0 and keep:
        r = opt.ring
        grown = set(keep)
        for cx, cz in keep:
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    grown.add((cx + dx, cz + dz))
        keep = grown & chunks.keys()
    return keep


def plan(scan_: TrimScan, opt: TrimOptions = DEFAULTS) -> Dict[int, Set[Chunk]]:
    return {dim: keep_set(scan_, dim, opt) for dim in scan_.inhabited}


def summary(scan_: TrimScan, keep: Dict[int, Set[Chunk]]) -> str:
    tot = scan_.total()
    kept = sum(len(v) for v in keep.values())
    pct = 100 * (tot - kept) / tot if tot else 0
    sep = "." if language() == "it" else ","
    num = lambda n: f"{n:,}".replace(",", sep)  # noqa: E731
    return tr("kept {kept} of {total} chunks · removed {removed} ({pct}%)", kept=num(kept), total=num(tot),
              removed=num(tot - kept), pct=f"{pct:.0f}")


# ------------------------------------------------------------------ writing a trimmed copy
def prune_region_raw(path: str, keep_local: Set[Chunk]) -> Tuple[int, int]:
    """Drops the chunks of a region file that are not in ``keep_local`` ((lx, lz) pairs), copying
    the kept ones byte for byte (compression type, external .mcc files and timestamps preserved).
    Returns (kept, removed)."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 8192:
        return 0, 0
    offsets = list(struct.unpack_from(">1024I", data, 0))
    stamps = list(struct.unpack_from(">1024I", data, 4096))
    m = re.match(r"^r\.(-?\d+)\.(-?\d+)\.", os.path.basename(path))
    rx, rz = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    folder = os.path.dirname(path)
    new_off = [0] * 1024
    new_stamp = [0] * 1024
    body = bytearray()
    sector = 2
    kept = removed = 0
    for i, off in enumerate(offsets):
        if not off:
            continue
        lx, lz = i % 32, i // 32
        start, count = (off >> 8) * 4096, off & 0xFF
        external = start + 5 <= len(data) and data[start + 4] & 0x80
        mcc = os.path.join(folder, f"c.{rx * 32 + lx}.{rz * 32 + lz}.mcc")
        if (lx, lz) not in keep_local:
            removed += 1
            if external and os.path.exists(mcc):
                os.remove(mcc)
            continue
        if start + 4 > len(data):
            continue
        length = struct.unpack_from(">I", data, start)[0]
        blob = data[start:start + 4 + length] if not external else data[start:start + 5]
        count = max(1, (len(blob) + 4095) // 4096)
        body += blob + b"\x00" * (count * 4096 - len(blob))
        new_off[i] = (sector << 8) | count
        new_stamp[i] = stamps[i]
        sector += count
        kept += 1
    if not removed:
        return kept, 0
    if not kept:
        os.remove(path)
        return 0, removed
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(struct.pack(">1024I", *new_off))
        f.write(struct.pack(">1024I", *new_stamp))
        f.write(body)
    os.replace(tmp, path)
    return kept, removed


def prune_java_raw(world: str, keep: Dict[int, Set[Chunk]], progress: Optional[Progress] = None) -> int:
    """Removes from a Java world every chunk not in ``keep`` (region, entities and poi files).
    Dimensions missing from ``keep`` are left untouched."""
    from .java.modern import _folder

    removed = 0
    for dim, chunks in keep.items():
        for sub in ("region", "entities", "poi"):
            folder = _folder(world, dim, sub)
            if not os.path.isdir(folder):
                continue
            for fn in sorted(os.listdir(folder)):
                m = re.match(r"^r\.(-?\d+)\.(-?\d+)\.mc[ar]$", fn)
                if not m:
                    continue
                if progress:
                    progress.check()
                rx, rz = int(m.group(1)), int(m.group(2))
                local = {(cx - rx * 32, cz - rz * 32) for cx, cz in chunks if cx >> 5 == rx and cz >> 5 == rz}
                _k, r = prune_region_raw(os.path.join(folder, fn), local)
                if sub == "region":
                    removed += r
    return removed


def check_output(src: str, out: str) -> None:
    """The folder of a trimmed copy must be new (or empty) and outside the world (``ConversionError``)."""
    from .convert import check_output_folder

    check_output_folder(src, out)
    if os.path.exists(out) and os.listdir(out):
        raise ConversionError(tr("The output folder is not empty: {path}", path=out))


def trimmed_copy(src: str, out: str, keep: Dict[int, Set[Chunk]], progress: Optional[Progress] = None) -> int:
    """A trimmed copy of a Java world (the source is never modified).  Returns the chunks removed."""
    progress = progress or Progress()
    check_output(src, out)
    progress.stage(tr("Copying the world"), 0.0, 0.4)
    copy_tree(src, out, progress, ignore=shutil.ignore_patterns("session.lock"))
    progress.stage(tr("Removing the unused chunks"), 0.4, 1.0)
    n = prune_java_raw(out, keep, progress)
    progress.done()
    return n


def folder_size(path: str) -> int:
    total = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def selection_for(keep: Dict[int, Set[Chunk]], dims: Iterable[int]) -> Dict[int, Set[Chunk]]:
    """Selection for a conversion: every scanned dimension restricted to its kept chunks."""
    return {d: set(keep.get(d, set())) for d in dims}


def trim_dims(scan_: TrimScan) -> List[int]:
    """The scanned dimensions, the Overworld first (then the Nether and the End)."""
    return sorted(scan_.inhabited, key=lambda d: {OVERWORLD: 0, NETHER: 1, THE_END: 2}.get(d, 3))

"""BTA world -> Minecraft Java 26.3 world (1.18.2 format upgraded by the game on first load)."""

from __future__ import annotations

import os
import struct
import time
import zlib
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .. import nbt
from ..model import ConversionError, Progress
from ..i18n import tr
from . import stats
from .chunks import ChunkConverter, Stage1
from .palette import Palette
from .postprocess import PostProcessor
from .world import (BtaWorld, DIMENSION_NAMES, DRIFT, NETHER, OVERWORLD, auto_shift, ocean_y, read_chunk, to_wb_dim)
from .writer import NETHER_END, Layout, overworld, write_chunk

_OUT_DIRS = {OVERWORLD: "region", NETHER: os.path.join("DIM-1", "region"), DRIFT: os.path.join("DIM1", "region")}


@dataclass
class BtaOptions:
    palette_file: Optional[str] = None
    y_offset: Optional[int] = None         # None = automatic (sea level to y 63)
    world_name: Optional[str] = None
    workers: int = 0                        # 0 = CPUs (max 8)
    chunks: Optional[Dict[int, Set[Tuple[int, int]]]] = None   # WorldBridge dim -> chunks; None = all
    spawn: Optional[Tuple[int, int, int]] = None               # BTA coordinates
    player_links: Optional[list] = None


# ------------------------------------------------------------------ region writer
def write_region(path: str, rx: int, rz: int, chunks: Dict[Tuple[int, int], Tuple[bytes, int]]) -> None:
    """Anvil region file; chunks over 255 sectors go to an external c.X.Z.mcc like vanilla."""
    offsets = [0] * 1024
    stamps = [0] * 1024
    body = bytearray()
    sector = 2
    folder = os.path.dirname(path)
    for (lx, lz), (comp, stamp) in sorted(chunks.items(), key=lambda kv: kv[0][0] + kv[0][1] * 32):
        i = lx + lz * 32
        total = len(comp) + 5
        count = (total + 4095) // 4096
        if count >= 256:
            with open(os.path.join(folder, f"c.{rx * 32 + lx}.{rz * 32 + lz}.mcc"), "wb") as f:
                f.write(comp)
            blob = struct.pack(">IB", 1, 2 | 0x80)
            count = 1
        else:
            blob = struct.pack(">IB", len(comp) + 1, 2) + comp
        blob += b"\x00" * (count * 4096 - len(blob))
        offsets[i] = (sector << 8) | count
        stamps[i] = stamp
        body += blob
        sector += count
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(struct.pack(">1024i", *[o if o < 1 << 31 else o - (1 << 32) for o in offsets]))
        f.write(struct.pack(">1024i", *stamps))
        f.write(body)
    os.replace(tmp, path)


# ------------------------------------------------------------------ one region (runs in a worker)
_WORLDS: Dict[str, BtaWorld] = {}


class _Task:
    """Per-region state: an LRU cache of first-pass chunks (neighbours are needed twice)."""

    def __init__(self, world: BtaWorld, dim: int, palette: Palette):
        self.world = world
        self.dim = dim
        self.converter = ChunkConverter(palette, dim)
        self.cache: "OrderedDict[Tuple[int, int], Stage1]" = OrderedDict()
        self.missing: Set[Tuple[int, int]] = set()

    def stage1(self, cx: int, cz: int) -> Optional[Stage1]:
        k = (cx, cz)
        s = self.cache.get(k)
        if s is not None:
            self.cache.move_to_end(k)
            return s
        if k in self.missing:
            return None
        try:
            level = self.world.read_level(self.dim, cx, cz)
            if level is None:
                self.missing.add(k)
                return None
            c = read_chunk(level)
            if c.x != cx or c.z != cz:  # BTA relocates misplaced chunks on load: do the same
                c.x, c.z = cx, cz
                stats.inc("chunks.relocated")
            stats.begin_capture()
            try:
                s = self.converter.convert(c)
            finally:
                captured = stats.end_capture()
            s.stats = dict(captured)
        except Exception as ex:  # noqa: BLE001
            self.missing.add(k)
            stats.inc("chunks.unreadable")
            stats.inc(f"chunks.unreadable_detail.{type(ex).__name__}")
            return None
        self.cache[k] = s
        if len(self.cache) > 250:
            self.cache.popitem(last=False)
        return s


def convert_region(world_dir: str, dim: int, rx: int, rz: int, out_path: str, palette_file: Optional[str],
                   layout: Layout, selected: Optional[Set[Tuple[int, int]]] = None) -> Tuple[int, Dict[str, int]]:
    """Converts one BTA region file; returns (chunks written, report counters)."""
    stats.reset()
    world = _WORLDS.get(world_dir)
    if world is None:
        world = _WORLDS[world_dir] = BtaWorld(world_dir)
    palette = Palette.load(palette_file)
    task = _Task(world, dim, palette)
    own = world.region(dim, rx, rz)
    if own is None:
        return 0, {}
    chunks: Dict[Tuple[int, int], Tuple[bytes, int]] = {}
    for lz in range(32):
        for lx in range(32):
            if not own.offsets[lx + lz * 32]:
                continue
            cx, cz = rx * 32 + lx, rz * 32 + lz
            if selected is not None and (cx, cz) not in selected:
                continue
            original = task.stage1(cx, cz)
            if original is None:
                continue
            out = original.copy_for_output()
            PostProcessor(original, out, task.stage1).run()
            root = write_chunk(out, original.ticks_on_unload, layout)
            chunks[(lx, lz)] = (zlib.compress(nbt.dump(root, ""), 6), world.timestamp(dim, cx, cz))
            stats.merge(original.stats)
            stats.inc(f"chunks.converted.{DIMENSION_NAMES[dim]}")
    if chunks:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        write_region(out_path, rx, rz, chunks)
    return len(chunks), stats.snapshot()


# ------------------------------------------------------------------ whole world
def self_test(palette: Palette) -> List[str]:
    """Maps every BTA block with every metadata and every item: the errors (invalid 26.3 states)."""
    from . import blockmap, items
    from .blockmap import MapCtx

    errors = []
    ctx = MapCtx(palette)
    for bid in sorted(blockmap.TABLE):
        for meta in range(256):
            try:
                blockmap.map_block(bid, meta, ctx)
            except Exception as ex:  # noqa: BLE001
                errors.append(tr("block {id}:{meta} ({name}): {error}", id=bid, meta=meta, name=blockmap.bta_name(bid), error=ex))
                break
    for iid, d in items.ITEMS.items():
        if d.id not in items.items_26():
            errors.append(tr("item {id}: {name} does not exist in 26.3", id=iid, name=d.id))
    return errors


def convert_world(src: str, out_dir: str, opt: BtaOptions, progress: Optional[Progress] = None) -> Tuple[int, Dict[str, int]]:
    progress = progress or Progress()
    stats.reset()
    try:
        palette = Palette.load(opt.palette_file)
    except OSError as ex:
        raise ConversionError(tr("Unreadable palette file: {error}", error=ex)) from ex
    errors = self_test(palette)
    if errors:
        raise ConversionError(tr("The palette gives blocks that are not valid in 26.3: {errors}", errors="; ".join(errors[:5])))
    world = BtaWorld(src)
    progress.log(tr("BTA world “{name}” (save version {version})", name=world.name, version=world.save_version))
    if world.save_version and world.save_version < 19134:
        progress.warn(tr("The world was last saved with an old BTA version ({version}): for the best result open it and "
                         "save it once in BTA 8.0.1 before converting it.", version=world.save_version))
    wtype = world.world_type(OVERWORLD)
    shift = opt.y_offset if opt.y_offset is not None else auto_shift(wtype)
    if not 0 <= shift <= 128:
        raise ConversionError(tr("The vertical shift (--y-offset) must be between 0 and 128."))
    oy = ocean_y(wtype)
    progress.log(tr("Overworld of type “{type}” (sea at y {sea}): lowered by {shift} blocks, so the sea matches the "
                    "vanilla one (y 63)", type=wtype or tr("unknown"), sea=oy if oy > 0 else "?", shift=shift)
                 + (" (--y-offset)" if opt.y_offset is not None else ""))
    jobs = []
    for dim in world.dimensions():
        wbd = to_wb_dim(dim)
        if opt.chunks is not None and not opt.chunks.get(wbd):
            continue
        layout = overworld(shift) if dim == OVERWORLD else NETHER_END
        for (rx, rz) in world.regions(dim):
            sel = None
            if opt.chunks is not None:
                sel = {(cx, cz) for cx, cz in opt.chunks[wbd] if cx >> 5 == rx and cz >> 5 == rz}
                if not sel:
                    continue
            out_path = os.path.join(out_dir, _OUT_DIRS[dim], f"r.{rx}.{rz}.mca")
            jobs.append((os.path.abspath(src), dim, rx, rz, out_path, opt.palette_file, layout, sel))
    if not jobs:
        raise ConversionError(tr("No chunks to convert (empty selection or a world without regions)."))
    os.makedirs(out_dir, exist_ok=True)
    workers = opt.workers or min(8, os.cpu_count() or 1)
    workers = max(1, min(workers, len(jobs)))
    total = 0
    per_dim: Dict[int, int] = {}
    merged: Dict[str, int] = {}
    t0 = time.time()

    def done_job(job, n, st):
        nonlocal total
        total += n
        per_dim[job[1]] = per_dim.get(job[1], 0) + n
        for k, v in st.items():
            merged[k] = merged.get(k, 0) + v

    progress.update(0.0, tr("Regions {i}/{n}", i=0, n=len(jobs)))
    if workers == 1:
        for i, job in enumerate(jobs):
            progress.check()
            n, st = convert_region(*job)
            done_job(job, n, st)
            progress.update((i + 1) / len(jobs), tr("Regions {i}/{n} · {chunks} chunks", i=i + 1, n=len(jobs), chunks=total))
    else:
        import multiprocessing as mp

        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
            futures = {ex.submit(convert_region, *job): job for job in jobs}
            pending = set(futures)
            finished = 0
            try:
                while pending:
                    done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    progress.check()
                    for f in done:
                        n, st = f.result()
                        done_job(futures[f], n, st)
                        finished += 1
                        progress.update(finished / len(jobs), tr("Regions {i}/{n} · {chunks} chunks", i=finished, n=len(jobs), chunks=total))
            except BaseException:
                ex.shutdown(wait=False, cancel_futures=True)
                raise
    stats.reset()
    stats.merge(merged)
    stats.add("overworld.y_shift", shift)
    has_end = per_dim.get(DRIFT, 0) > 0
    n_players = write_level(world, out_dir, palette, opt.world_name, has_end, shift, opt.spawn, opt.player_links)
    report = stats.snapshot()
    with open(os.path.join(out_dir, "worldbridge-bta-report.txt"), "w", encoding="utf-8") as f:
        f.write(f"chunks converted: {total} ({time.time() - t0:.1f} s)\n")
        for k, v in report.items():
            f.write(f"{k} = {v}\n")
    for dim, n in sorted(per_dim.items()):
        progress.log("  " + tr("{dim}: {n} chunks", dim=DIMENSION_NAMES[dim], n=n) + (" " + tr("(becomes The End)") if dim == DRIFT else ""))
    if n_players:
        progress.log(tr("Players: {n} playerdata files written.", n=n_players))
    _summary_warnings(report, progress)
    return total, report


def write_level(*args, **kw):
    from .level import write_level as _wl

    return _wl(*args, **kw)


def _summary_warnings(report: Dict[str, int], progress: Progress) -> None:
    unreadable = report.get("chunks.unreadable", 0)
    if unreadable:
        progress.warn(tr("{n} unreadable BTA chunks were not converted.", n=unreadable))
    unknown_blocks = sum(v for k, v in report.items() if k.startswith("block.unknown."))
    if unknown_blocks:
        progress.warn(tr("{n} unknown block types (ids not of BTA 8.0.1) became air.", n=unknown_blocks))
    spilled = report.get("items.spilled_as_entities", 0)
    if spilled:
        progress.log(tr("{n} items without an equivalent slot were left on the ground (they do not despawn).", n=spilled))
    dropped = sum(v for k, v in report.items() if k.startswith("entities.dropped."))
    if dropped:
        progress.log(tr("{n} entities without a vanilla equivalent (projectiles, fireflies, butterflies…) not converted.", n=dropped))
    statues = report.get("statues.to_armor_stands", 0)
    if statues:
        progress.log(tr("{n} statues became armour stands.", n=statues))

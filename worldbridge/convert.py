"""Conversion orchestration: any supported source -> any supported target."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import amulet_bridge as ab
from .i18n import N_, tr
from . import detect as det
from .model import (NETHER, OVERWORLD, THE_END, UNKNOWN_BIOME, BiomeFiller, ConversionCancelled, ConversionError, NumericChunk,
                    Progress, WorldSource, copy_tree)
from .selection import Selection, apply_to_info, prune_bedrock, prune_java, resolve_links


# versions whose content (blocks, items, mobs) can be targeted inside each old Java format
OLD_LIMITS = {"alpha": ("alpha", "b1.2"), "mcregion": ("b1.3", "b1.4", "b1.5", "b1.6", "b1.7", "b1.8", "1.0", "1.1")}


def old_version_label(v: str) -> str:
    return {"alpha": "Alpha 1.2.x", "b1.2": "Beta 1.0 – 1.2_02", "b1.3": "Beta 1.3", "b1.4": "Beta 1.4",
            "1.0": "1.0", "1.1": "1.1"}.get(v, "Beta " + v[1:] if v.startswith("b") else v)


@dataclass
class TargetSpec:
    family: str  # 'lce' | 'java' | 'bedrock' | 'pe_old'
    # java: 'auto'     latest version, best route chosen automatically (default)
    #       'dfu'      numeric Anvil world upgraded by the game itself (any version 1.9 -> latest)
    #       'numeric'  Anvil 1.2 - 1.12 limited to ``java_version_limit`` blocks
    #       'mcregion' Beta 1.3 - 1.1
    #       'alpha'    Infdev / Alpha - Beta 1.2
    #       'amulet'   pre-converted to the exact ``version`` (1.13+)
    java_mode: str = "auto"
    java_version_limit: Optional[str] = None
    version: Optional[Tuple[int, ...]] = None
    lce_platform: str = "win64"
    lce_profile: str = ""   # "" = the platform's own (Windows64: neoLegacy TU31 only)
    lce_world_size: int = 0  # 0 = default for the platform (320 on Windows64 / 8th gen, 54 on 7th gen)
    lce_offset: Tuple[int, int] = (0, 0)
    lce_center_on_spawn: bool = False
    lce_player_id: Optional[str] = None
    world_name: Optional[str] = None
    y_offset: int = 0
    # the game's blending (Java / Bedrock 1.18+): worlds that come from a pre-1.18 world are written
    # as pre-1.18 chunks, so that Minecraft blends terrain + biomes with newly generated chunks and
    # fills the new depth below y=0 when the world is opened
    blend: bool = True
    # WorldBridge's own border for the games that do not blend (terrain/policy.py): the ring of the
    # game's terrain (Java Alpha 1.2 - 1.17, neoLegacy; Nether and End too) and the filling of the
    # small finite worlds (PE 0.x, LCE 54 / 64 chunks)
    ring: bool = True
    # chunks / spawn / players chosen in the "Mappa" and "Giocatori" tabs (None = everything)
    selection: Optional[Selection] = None
    # Better than Adventure sources: palette file (painted woods...) and how far the overworld
    # moves down (None = automatic: BTA's sea level lands on vanilla's y 63)
    bta_palette: Optional[str] = None
    bta_y_offset: Optional[int] = None
    # world trim: convert only the chunks players really used (InhabitedTime), see worldbridge.trim
    trim: Optional[object] = None
    # 128 high targets (Alpha, Beta, Java 1.0 - 1.1, PE 0.x): ground above their ceiling is
    # "compress"ed (mountains lowered keeping their surface, see worldbridge.heightfit) or "cut"
    tall_terrain: str = "compress"
    # Caves & Cliffs worlds into games whose world starts at y 0 (worldbridge.depthfit): "auto" (flat or
    # low worlds are kept, the others cut), "cut" (the underground goes), "keep" (the world moves up by
    # 64) or the lowest y kept (a negative number)
    depth: object = "auto"
    # dimensions not converted: the game generates them anew (NETHER, THE_END)
    regen: Tuple[int, ...] = ()

    def describe(self) -> str:
        if self.family == "lce":
            from .lce.container import PLATFORMS
            from .lce.world import PROFILES

            from .lce.world import resolve_profile

            if self.lce_platform == "win64":
                return f"Legacy Console Edition – {PLATFORMS[self.lce_platform].label}"
            prof = PROFILES[resolve_profile(self.lce_platform, self.lce_profile)]
            return f"Legacy Console Edition – {PLATFORMS[self.lce_platform].label} – {tr(prof.label)}"
        if self.family == "bedrock":
            return f"Bedrock Edition {ab.version_str(self.version or ab.latest('bedrock'))}"
        if self.family == "pe_old":
            return "Pocket Edition 0.8 (chunks.dat)"
        if self.java_mode == "amulet":
            return f"Java Edition {ab.version_str(self.version or ab.latest('java'))}"
        if self.java_mode in ("alpha", "mcregion") and self.java_version_limit:
            return f"Java Edition {old_version_label(self.java_version_limit)}"
        return {"auto": "Java Edition " + tr("{version} (latest)", version=ab.version_str(ab.latest('java'))),
                "dfu": tr("Java Edition 1.9 → latest (upgraded by the game)"), "mcregion": "Java Edition 1.0 (McRegion)",
                "alpha": "Java Edition Beta 1.0 – 1.2_02"}.get(self.java_mode, f"Java Edition {self.java_version_limit or '1.12.2'}")


@dataclass
class ConversionResult:
    output: str
    chunks: int = 0
    seconds: float = 0.0
    warnings: list = field(default_factory=list)


AMULET_KINDS = ("java_modern", "bedrock")
BLEND_JAVA = (1, 17, 0)     # last Java version before the 1.18 height/biome change (DataVersion 2724)
BLEND_BEDROCK = (1, 17, 40)  # last Bedrock version before Caves & Cliffs part II
CAVES_CLIFFS = (1, 18, 0)


def _source_is_pre118(d: det.Detected) -> bool:
    """True for worlds whose chunks predate Caves & Cliffs (0-255 height, 2D biomes)."""
    if d.kind not in AMULET_KINDS:
        return True
    try:
        if d.kind == "bedrock":
            root = ab.read_bedrock_level_dat(d.path)
            v = ab.gv.bedrock(int(x.py_data) for x in (ab.nbt.get_tag(root, "lastOpenedWithVersion") or []))[:3]
            return bool(v) and v < CAVES_CLIFFS
        from .java.modern import chunk_data_version

        dv = chunk_data_version(d.path)
        return dv is not None and dv < 2825
    except Exception:  # noqa: BLE001
        return False


def _java_upgrade_only(d: det.Detected, t: TargetSpec) -> bool:
    """True when a Java 1.13+ world goes to its own version or a newer one (the game upgrades it)."""
    from .java.modern import chunk_data_version, level_data_version

    try:
        target_dv = ab.java_data_version(t.version or ab.latest("java"))
        dvs = [v for v in (chunk_data_version(d.path), level_data_version(d.path)) if v]
    except Exception:  # noqa: BLE001
        return False
    return bool(dvs) and max(dvs) <= target_dv


def _write_version(platform: str, version, blend: bool, old_source: bool):
    """Version actually written by Amulet (pre-1.18 when the game must blend)."""
    v = tuple(version)
    if blend and old_source and v >= CAVES_CLIFFS:
        return BLEND_BEDROCK if platform == "bedrock" else BLEND_JAVA
    return v


def source_sea(d: det.Detected, info) -> Optional[int]:
    """y of the sea surface of the game that generated the source (None: unknown / no sea)."""
    if d.kind == "pe_old":
        return 63
    if d.kind == "java_numeric" and d.subkind == "alpha":
        return 63
    if d.kind == "java_numeric" and d.subkind == "mcregion":
        # McRegion is Beta 1.3 - 1.1: game modes (and the new generator) came with Beta 1.8
        return 62 if "GameType" in info.level else 63
    if d.kind in ("classic", "indev", "bta"):
        return None
    return 62


def target_sea(t: TargetSpec) -> int:
    from .terrain import ring as ring_mod

    return 63 if (ring_mod.beta_sea(t) or t.family == "pe_old") else 62


def shift_info_y(info, dy: int) -> None:
    """Players and spawn point up / down with a world moved by ``dy`` blocks."""
    from . import nbt as _nbt

    lvl = info.level
    seen = set()
    for p in list(info.players.values()) + ([lvl["Player"]] if "Player" in lvl else []):
        if id(p) in seen:
            continue
        seen.add(id(p))
        pos = _nbt.get_tag(p, "Pos")
        if pos is not None and len(pos) == 3:
            p["Pos"] = _nbt.pos_list(pos[0], float(pos[1].py_data) + dy, pos[2])
    if "SpawnY" in lvl:
        lvl["SpawnY"] = _nbt.IntTag(int(_nbt.get(lvl, "SpawnY")) + dy)
    sp = _nbt.get_tag(lvl, "spawn")
    if sp is not None and _nbt.get_tag(sp, "pos") is not None and len(sp["pos"]) == 3:
        x, y, z = (int(v) for v in sp["pos"].np_array.tolist())
        sp["pos"] = _nbt.IntArrayTag(np.array([x, y + dy, z], np.int32))


def finite_chunks(writer) -> list:
    """Every overworld chunk of a finite target's map, in the coordinates of the source."""
    if hasattr(writer, "bounds") and hasattr(writer, "opt"):          # LCE
        lo, hi = writer.bounds(OVERWORLD)
        ox, oz = writer.opt.offset_x, writer.opt.offset_z
        return [(x + ox, z + oz) for x in range(lo, hi) for z in range(lo, hi)]
    ox, oz = writer.origin                                              # PE 0.x: 16 x 16 chunks
    return [(ox + x, oz + z) for x in range(16) for z in range(16)]


def world_seed(level) -> int:
    """The world seed: RandomSeed, or WorldGenSettings.seed (1.16+; 26.1+ keeps it in
    data/minecraft/world_gen_settings.dat, read into the same place)."""
    seed = ab.nbt.get(level, "RandomSeed")
    if seed is None:
        wgs = ab.nbt.get_tag(level, "WorldGenSettings")
        seed = ab.nbt.get(wgs, "seed") if wgs is not None else None
    return int(seed or 0)


def target_ceiling(t: TargetSpec) -> Optional[int]:
    """First y the target cannot store, for the targets lower than the hub (256)."""
    if t.family == "pe_old" or (t.family == "java" and t.java_mode in ("mcregion", "alpha")):
        return 128
    return None


def _region_order(c: Tuple[int, int]) -> Tuple[int, int, int, int]:
    return c[0] >> 5, c[1] >> 5, c[1], c[0]


def _is_amulet_target(t: TargetSpec) -> bool:
    return t.family == "bedrock" or (t.family == "java" and t.java_mode == "amulet")


def open_source(d: det.Detected, progress: Progress, tmp: str, for_amulet_target: bool = False,
                selection: Optional[Selection] = None, depth=None) -> WorldSource:
    """Return a hub WorldSource for ``d`` (may convert through Amulet)."""
    if d.kind == "lce":
        from .lce.world import LCEWorld

        return LCEWorld(d.path, progress=progress)
    if d.kind == "java_numeric":
        from .java.numeric import JavaNumericWorld

        return JavaNumericWorld(d.path, progress=progress)
    if d.kind == "indev":
        from .java.finite import IndevWorld

        return IndevWorld(d.path)
    if d.kind == "classic":
        from .java.classic import ClassicWorld

        return ClassicWorld(d.path)
    if d.kind == "pe_old":
        from .bedrock.pe_old import PEOldWorld

        return PEOldWorld(d.path)
    if d.kind in AMULET_KINDS:
        from .java.numeric import JavaNumericWorld
        from .extra import attach_source_extras

        hub = os.path.join(tmp, "hub_in")
        progress.log(tr("Translating the blocks to the numeric Java 1.12.2 format with Amulet…"))
        ab.amulet_convert(d.path, hub, "java", (1, 12, 2), progress, selection, depth)
        world = JavaNumericWorld(hub, progress=progress)
        # block entities and entities come again from the original world (extra.py), at their old
        # height: they go where Amulet's pass moved their blocks (depthfit)
        attach_source_extras(world, d, progress, depth)
        _depth_players(world.info, depth, progress)
        read = world.read_chunk

        def read_chunk(dim, cx, cz):
            # Amulet does not compute light (it leaves everything at 15): the writers recompute it
            c = read(dim, cx, cz)
            if c is not None:
                c.sky_light = c.block_light = None
            return c

        world.read_chunk = read_chunk
        return world
    raise ConversionError(tr("Source format not supported: {kind}", kind=d.kind))


def _pairs_chests_itself(t: TargetSpec) -> bool:
    """Targets that pair every chest with any chest next to it (and have trapped chests, Java 1.5+)."""
    if t.family == "lce":
        return True
    if t.family == "java" and t.java_mode == "numeric":
        lim = t.java_version_limit
        try:
            return lim is None or tuple(int(v) for v in str(lim).split(".")) >= (1, 5)
        except ValueError:
            return False
    return False


def _reads_in_workers(d: det.Detected, fit) -> bool:
    """The source can be read in worker processes (parallel.py): its reader holds no handle a forked
    process cannot use (Bedrock's LevelDB), and no step needs the chunks in their order (the
    compression of the mountains moves entities with what the previous chunks left)."""
    return fit is None and d.kind != "bedrock"


_UNSET = object()


@dataclass
class _Done:
    """One chunk through the pipeline, as the main loop merges it."""

    dim: int
    pos: Tuple[int, int] = (0, 0)             # where it lands (moved chunks: their new place)
    written: bool = False                     # something to write (the source chunk was readable)
    encoded: bool = False                     # ``rec`` is the writer's record (else ``chunk`` goes to the writer)
    rec: object = None
    chunk: object = None
    obs: object = None                        # blocks the rings look at (edge chunks)
    unreadable: int = 0
    emptied: int = 0                          # nothing left of the chunk in the target's height (depthfit)
    cut_tiles: int = 0                        # block entities / entities cut with their blocks (depthfit)
    cut_entities: int = 0
    empty_chests: int = 0
    rows: int = 0
    top: object = None                        # Relocation.top, when this chunk has the destination
    msgs: List[str] = field(default_factory=list)


class _Pipeline:
    """What happens to every chunk of the conversion between the source and the writer: chest rows,
    heights, painted biomes, moves, chests drawn, the writer's encoding.  ``run`` does it on every
    core (parallel.py: the workers inherit this object) and gives the chunks back in order; nothing
    the rest of the conversion reads is changed in a worker, it comes back in ``_Done`` and ``merge``
    applies it: the result is the one of the plain loop."""

    def __init__(self, src: WorldSource, progress: Progress, rows, fit, shift_here: int, biomes, move,
                 writer, observe: Dict[int, set], drawn_tiles: bool, filler: bool = False, depth=None):
        self.src, self.progress = src, progress
        self.depth = depth
        # BiomeFiller in the main loop: only chunks with every biome known are encoded here (the filler
        # reads them back from the writer when it needs them), the others go to it as they are
        self.filler = filler
        self.rows, self.fit, self.shift_here, self.biomes, self.move = rows, fit, shift_here, biomes, move
        self.writer = writer if hasattr(writer, "encode") else None
        self.observe = observe
        self.drawn_tiles = drawn_tiles
        self._msgs: Optional[List[str]] = None

    # ---------------------------------------------------------------- one chunk
    def prepare(self, dim: int, cx: int, cz: int) -> _Done:
        out = _Done(dim, (cx, cz))
        try:
            c = self.src.read_chunk(dim, cx, cz)
        except (ConversionCancelled, KeyboardInterrupt):
            raise
        except Exception:  # noqa: BLE001
            c = None
        if c is not None and self.rows is not None:
            before = self.rows.changed
            self.rows.fix(dim, c)                   # rows of double chests: every pair drawn
            out.rows, self.rows.changed = self.rows.changed - before, before
        if c is None:
            # a chunk the depth cut left without blocks is not a damaged one (None: it holds nothing)
            had = self.depth.emptied.get((cx, cz)) if self.depth is not None and dim == OVERWORLD else None
            if had is None:
                out.unreadable = 1
            elif had:
                out.emptied = 1
                emptied_extras = getattr(self.src, "emptied_extras", None)      # lost with their chunk's blocks
                if emptied_extras is not None:
                    out.cut_tiles, out.cut_entities = emptied_extras(dim, cx, cz)
            return out
        out.cut_tiles, out.cut_entities = c.cut_extras
        if self.fit is not None and dim == OVERWORLD:
            c = self.fit.apply(c)
        if self.shift_here:
            from .java.numeric import _shift_chunk_y

            _shift_chunk_y(c, self.shift_here)
        if self.biomes:
            bid = self.biomes.get(dim, {}).get((cx, cz))
            if bid is not None:
                c.biomes = np.full((16, 16), bid, np.uint8)       # painted on the map tab
        if self.move.active:
            saved, self.move.top = self.move.top, _UNSET
            self.move.numeric_chunk(dim, c)
            if self.move.top is not _UNSET:
                out.top = (self.move.top,)          # this chunk holds the destination's column
            self.move.top = saved
        if self.drawn_tiles:
            from .tiles import ensure_drawn_tiles

            out.empty_chests = ensure_drawn_tiles(c)
        out.pos, out.written, out.chunk = (c.cx, c.cz), True, c
        return out

    def finish(self, out: _Done) -> _Done:
        """The rings' copy of an edge chunk, then the writer's encoding (when it runs here)."""
        c = out.chunk
        if c is None:
            return out
        if out.pos in self.observe.get(out.dim, ()):
            obs = NumericChunk(c.cx, c.cz, c.height, blocks=c.blocks.copy(), data=c.data.copy())
            out.obs = obs
        if self.writer is not None:
            if self.filler and c.biomes is not None and (c.biomes == UNKNOWN_BIOME).any():
                return out                          # the filler needs it whole
            out.rec, out.encoded, out.chunk = self.writer.encode(out.dim, c), True, None
        return out

    def merge(self, out: _Done) -> None:
        if self.rows is not None:
            self.rows.changed += out.rows
        if out.top is not None:
            self.move.top = out.top[0]
        for m in out.msgs:
            if m.startswith("⚠ "):
                self.progress.warn(m[2:])
            else:
                self.progress.log(m)

    # ---------------------------------------------------------------- every chunk
    def _capture(self) -> None:
        """In a worker: the messages of the readers (a damaged chunk...) go back with the chunk."""
        if self._msgs is None:
            self._msgs = []
            self.progress._on_log = self._msgs.append
            self.progress._on_progress = None

    def _taken(self, out: _Done) -> _Done:
        if self._msgs:
            out.msgs, self._msgs[:] = list(self._msgs), []
        return out

    def run(self, items: List[Tuple[int, int, int]], reads_in_workers: bool):
        from .parallel import ordered_map

        if reads_in_workers:
            return ordered_map(_pipeline_whole, self, items, batch=8)
        if self.writer is not None:
            # the source is read here, in order; the workers encode
            prepared = (self.prepare(dim, cx, cz) for dim, cx, cz in items)
            return ordered_map(_pipeline_finish, self, prepared, batch=8)
        return (self.finish(self.prepare(dim, cx, cz)) for dim, cx, cz in items)


def _pipeline_whole(pipe: _Pipeline, item) -> _Done:
    """Worker function (parallel.py): one chunk from the source to the writer's record."""
    from .parallel import in_worker

    if in_worker():
        pipe._capture()
    return pipe._taken(pipe.finish(pipe.prepare(*item)))


def _pipeline_finish(pipe: _Pipeline, out: _Done) -> _Done:
    """Worker function (parallel.py): the writer's encoding of a chunk read in the main process."""
    from .parallel import in_worker

    if in_worker():
        pipe._capture()
    return pipe._taken(pipe.finish(out))


def _lce_layout(t: TargetSpec, spawn, src_size: int = 0) -> Tuple[int, int, int]:
    """The LCE map: its size in chunks and the source chunk that becomes its chunk 0."""
    from .lce.world import platform_sizes

    ox, oz = t.lce_offset
    if t.lce_center_on_spawn:
        ox, oz = spawn[0] >> 4, spawn[2] >> 4
    cap = max(platform_sizes(t.lce_platform))
    size = t.lce_world_size or (min(src_size, cap) if src_size in (54, 64, 192, 320) else cap)
    return min(size, cap), ox, oz                     # the old consoles cannot load a bigger world


# the finite maps' sources that are finite themselves (small): they are read whole
_FINITE_SOURCES = ("lce", "classic", "indev", "pe_old")
# around a finite map, the chunks read anyway: the ring of the map's edge (up to terrain.ring.MAX_RING
# = 12 chunks wide, widened twice by 2) sees the same converted world as without the cut
_AREA_MARGIN = 18


def _finite_area(t: TargetSpec, spawn) -> Optional[Dict[int, Tuple[int, int, int, int]]]:
    """LCE and PE 0.x maps are finite: per dimension, the chunks ``[x0, x1) × [z0, z1)`` (where they
    land, before moving back to the source's coordinates) that reach the map, with a margin for the
    ring; None for the other targets, which take the whole world."""
    if t.family == "pe_old":
        ox, oz = (spawn[0] >> 4) - 8, (spawn[2] >> 4) - 8
        areas = {OVERWORLD: (ox, ox + 16, oz, oz + 16)}             # PEOldWriter: 16 x 16 chunks
    elif t.family == "lce":
        from .lce.world import map_area

        size, ox, oz = _lce_layout(t, spawn)
        from .lce.world import PROFILES, resolve_profile

        end = PROFILES[resolve_profile(t.lce_platform, t.lce_profile)].end_size
        areas = {dim: map_area(dim, size, ox, oz, end) for dim in (OVERWORLD, NETHER, THE_END)}
    else:
        return None
    m = _AREA_MARGIN
    return {dim: (x0 - m, x1 + m, z0 - m, z1 + m) for dim, (x0, x1, z0, z1) in areas.items()}


def _area_selection(sel: Selection, area: Dict[int, Tuple[int, int, int, int]], move) -> Selection:
    """``sel`` restricted to the chunks of the source that land in ``area``."""
    import dataclasses

    chunks = {}
    for dim, (x0, x1, z0, z1) in area.items():
        dx, dz = move.delta(dim)
        box = {(x - dx, z - dz) for x in range(x0, x1) for z in range(z0, z1)}
        if sel.chunks is not None:
            box &= sel.chunks.get(dim, set())
        chunks[dim] = box
    return dataclasses.replace(sel, chunks=chunks)


def _within(coords: List[Tuple[int, int]], box: Optional[Tuple[int, int, int, int]], delta: Tuple[int, int]) -> list:
    """The chunks of ``coords`` that land (moved by ``delta``) inside ``box``."""
    if box is None:
        return []
    x0, x1, z0, z1 = box
    dx, dz = delta
    return [c for c in coords if x0 <= c[0] + dx < x1 and z0 <= c[1] + dz < z1]


def _make_writer(t: TargetSpec, out: str, progress: Progress, src: WorldSource, spawn=None):
    """``spawn``: the spawn of the converted world when it is not the source's (chunks moved)."""
    spawn = spawn or src.info.spawn
    if t.family == "lce":
        from .lce.world import LCEWriteOptions, LCEWriter

        src_size = int(ab.nbt.get(src.info.level, "XZSize", 0) or 0) if hasattr(src, "container") else 0
        size, ox, oz = _lce_layout(t, spawn, src_size)
        return LCEWriter(out, LCEWriteOptions(platform=t.lce_platform, profile=t.lce_profile, world_size=size,
                                              offset_x=ox, offset_z=oz, world_name=t.world_name,
                                              host_player_id=t.lce_player_id), progress)
    if t.family == "pe_old":
        from .bedrock.pe_old import PEOldWriter

        sx, _sy, sz = spawn
        return PEOldWriter(out, progress, world_name=t.world_name, origin=((sx >> 4) - 8, (sz >> 4) - 8))
    from .java.numeric import JavaNumericWriter, JavaWriteOptions

    if t.family == "java" and t.java_mode in ("mcregion", "alpha"):
        lim = t.java_version_limit
        if lim is not None and lim not in OLD_LIMITS[t.java_mode]:
            raise ValueError(tr("--java-limit {limit} is not valid for the {format} format: use {choices}",
                                limit=lim, format=t.java_mode, choices=", ".join(OLD_LIMITS[t.java_mode])))
        opt = JavaWriteOptions(kind=t.java_mode, version_limit=lim, world_name=t.world_name, y_offset=t.y_offset)
    elif t.family == "java" and t.java_mode == "numeric":
        opt = JavaWriteOptions(kind="anvil", version_limit=t.java_version_limit, world_name=t.world_name, y_offset=t.y_offset)
    else:  # dfu hub or temporary hub for Amulet targets
        opt = JavaWriteOptions(kind="anvil", world_name=t.world_name, y_offset=t.y_offset)
    return JavaNumericWriter(out, opt, progress)


def validate_target(t: TargetSpec) -> None:
    """Refuses, before anything is read, the options the target cannot honour (``ConversionError``)."""
    if t.family == "lce":
        from .lce.container import PLATFORMS
        from .lce.world import platform_profiles, platform_sizes

        if t.lce_platform not in PLATFORMS:
            raise ConversionError(tr("Unknown LCE platform: {platform} (choose from {choices})", platform=t.lce_platform,
                                     choices=", ".join(PLATFORMS)))
        if t.lce_world_size and t.lce_world_size not in platform_sizes(t.lce_platform):
            raise ConversionError(tr("{size} chunks is not a world size {platform} has: use {choices}",
                                     size=t.lce_world_size, platform=t.lce_platform,
                                     choices=", ".join(str(v) for v in platform_sizes(t.lce_platform))))
        if t.lce_profile and t.lce_profile not in platform_profiles(t.lce_platform):
            raise ConversionError(tr("{profile} is not a console version {platform} has: use {choices}",
                                     profile=t.lce_profile, platform=t.lce_platform,
                                     choices=", ".join(platform_profiles(t.lce_platform))))
    elif t.family == "java" and t.java_version_limit:
        lim = t.java_version_limit
        if t.java_mode in OLD_LIMITS:
            choices = OLD_LIMITS[t.java_mode]
        elif t.java_mode == "numeric":
            choices = _numeric_limits()
        else:
            return
        if lim not in choices:
            raise ConversionError(tr("--java-limit {limit} is not valid for the {format} format: use {choices}",
                                     limit=lim, format=t.java_mode, choices=", ".join(choices)))


def _numeric_limits() -> Tuple[str, ...]:
    from .blocks import _V

    return tuple(v for v in _V if v.startswith("1."))


def check_output_folder(src_path: str, out_dir: str) -> None:
    """The output folder cannot be inside the source world (the working copy would copy itself) nor the
    source inside the output folder (``ConversionError``)."""
    if os.path.isfile(out_dir):
        raise ConversionError(tr("The output path is a file, not a folder: {path}", path=out_dir))
    src = os.path.realpath(src_path)
    if not os.path.isdir(src):
        return
    out = os.path.realpath(out_dir)
    try:
        common = os.path.commonpath([src, out])
    except ValueError:                                   # another drive
        return
    if common == src:
        raise ConversionError(tr("The output folder cannot be inside the source world: {path}", path=out_dir))
    if common == out:
        raise ConversionError(tr("The source world cannot be inside the output folder: {path}", path=src_path))


def convert(src_path: str, out_dir: str, target: TargetSpec, progress: Optional[Progress] = None) -> ConversionResult:
    progress = progress or Progress()
    t0 = time.time()
    validate_target(target)
    check_output_folder(src_path, out_dir)
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise ConversionError(tr("The output folder is not empty: {path}", path=out_dir))
    created_out = not os.path.exists(out_dir)
    parent = os.path.dirname(os.path.abspath(out_dir)) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".worldbridge_", dir=parent)
    extra_tmp: List[str] = []                         # temporary folders elsewhere (next to the source)
    try:
        progress.stage(tr("Analysing the source world"), 0.0, 0.03)
        d = det.detect(src_path)
        if d is None:
            raise ConversionError(tr("World format not recognised. Choose the world folder or the save file."))
        if d.kind != "archive":
            check_output_folder(d.path, out_dir)      # the world's folder when the save file or level.dat was given
        if d.kind == "archive":
            folder = det.extract_archive(d.path, os.path.join(tmp, "archive"))
            d = det.detect(folder)
            if d is None:
                raise ConversionError(tr("The archive does not contain a recognised world."))
        progress.log(tr("Source: {description}  ({path})", description=d.description, path=d.path))
        if d.kind in AMULET_KINDS:
            # never open the original with Amulet / LevelDB (locks, logs, session.lock)
            progress.log(tr("Working copy of the source world (the original is never opened for writing)…"))
            near = det.snapshot_parent(d.path, tmp)
            if near is not None:
                extra_tmp.append(near)
            d = det.Detected(d.kind, d.description,
                             det.snapshot(d.path, near or os.path.join(tmp, "source"), link=d.kind == "java_modern"),
                             d.subkind)
        if target.trim is not None:
            _apply_trim(d, target, progress)
        if d.kind == "bta":
            return _convert_bta(d, out_dir, target, progress, t0)
        progress.log(tr("Target: {target}  ({path})", target=target.describe(), path=out_dir))
        if target.version is None and _is_amulet_target(target):
            target.version = ab.latest("bedrock" if target.family == "bedrock" else "java")

        sel = target.selection or Selection()
        if sel.chunks is not None:
            progress.log(tr("Selection: {n} chunks", n=sel.count()))
        if target.regen:
            sel.drop |= set(target.regen)
            if len(target.regen) > 1:
                progress.log(tr("Nether and End: not converted, the game generates them anew when first entered."))
            else:
                progress.log(tr("{dim}: not converted, the game generates it anew when first entered.",
                                dim=_DIM_NAME[next(iter(target.regen))]))
        from .incomplete import incomplete_chunks

        excl = incomplete_chunks(d.kind, d.path, sel.chunks)
        if excl:
            sel.exclude = excl
            n = sum(len(v) for v in excl.values())
            progress.log(tr("{n} chunks the game had not finished (at the edge of the explored area: only planned or "
                            "bare rock) are not converted: the game or the ring generates them properly.", n=n))
        old_source = _source_is_pre118(d)
        same_edition = (not sel.biomes and sel.move_to is None and target.family in ("java", "bedrock")
                        and d.kind == ("bedrock" if target.family == "bedrock" else "java_modern")
                        and (target.family != "java" or target.java_mode in ("auto", "amulet", "dfu")))
        # ---- same edition, old world -> newer version: the game upgrades (and blends) it itself
        if (same_edition and target.blend and old_source
                and tuple(target.version or ab.latest("bedrock" if target.family == "bedrock" else "java")) >= CAVES_CLIFFS):
            progress.stage(tr("Copying the world (Minecraft will upgrade it with its own blending)"), 0.05, 0.95)
            copy_tree(d.path, out_dir, progress)
            if sel.active:
                _edit_copy(d, out_dir, target, sel, progress)
            progress.log(tr("The world is pre-1.18: it is kept as it is; when it is opened, Minecraft runs its own "
                            "upgrade, blending terrain and biomes."))
            progress.done()
            return ConversionResult(out_dir, 0, time.time() - t0, list(progress.warnings))
        # ---- Java 1.13+ -> the same or a newer Java: the game's own upgrade keeps every block, item
        # component, book, mob and setting, which no translation does as well (before 1.18 the game
        # does not blend the border: there the ring needs the translation route)
        if (same_edition and target.family == "java" and _java_upgrade_only(d, target)
                and (not target.ring or tuple(target.version or ab.latest("java")) >= CAVES_CLIFFS)):
            progress.stage(tr("Copying the world (Minecraft will upgrade it when it is opened)"), 0.05, 0.95)
            copy_tree(d.path, out_dir, progress)
            if sel.active:
                _edit_copy(d, out_dir, target, sel, progress)
            progress.log(tr("The target version is the same as the world's or newer: the world is kept as it is, and "
                            "Minecraft upgrades it with its own upgrade when it is opened."))
            progress.done()
            return ConversionResult(out_dir, 0, time.time() - t0, list(progress.warnings))

        # ---- direct Amulet -> Amulet (keeps every modern block)
        direct = d.kind in AMULET_KINDS and (_is_amulet_target(target) or (target.family == "java" and target.java_mode in ("dfu", "auto")))
        if direct:
            if target.family == "java" and target.java_mode in ("dfu", "auto"):
                target.java_mode = "amulet"
                target.version = ab.latest("java")
            res = _direct_amulet(d, out_dir, target, progress, tmp, old_source, sel)
            res.seconds = time.time() - t0
            res.warnings = list(progress.warnings)
            return res

        progress.stage(tr("Reading the source world"), 0.03, 0.35 if d.kind in AMULET_KINDS else 0.05)
        from . import depthfit

        depth = depthfit.plan(target, d.kind in AMULET_KINDS and not old_source, d.path, progress)
        src_sel = sel
        if d.kind in AMULET_KINDS and target.family in ("lce", "pe_old"):
            # a finite map: only the part of the world that reaches it goes through Amulet
            from .extra import read_amulet_info
            from .relocate import Relocation

            info = read_amulet_info(d)
            apply_to_info(info, Selection(spawn=sel.spawn), target.family)
            mv = Relocation(sel)
            src_sel = _area_selection(sel, _finite_area(target, mv.spawn(info) if mv.active else info.spawn), mv)
            progress.log(tr("Finite map: only the chunks that reach it (with a margin for its edge) are translated."))
        src = open_source(d, progress, tmp, _is_amulet_target(target), src_sel, depth)
        apply_to_info(src.info, sel, target.family, progress)
        _warn_single_player(src.info, target, sel, progress)
        if target.family == "java" and target.java_mode == "auto":
            # Mojang's own upgrade (DataFixerUpper) is the most faithful route for numeric worlds;
            # Aquatic-era LCE saves contain 1.13 blocks, which need the explicit Amulet route.
            aquatic = getattr(getattr(src, "container", None), "original_version", 0) >= 11
            target.java_mode = "amulet" if aquatic else "dfu"
            if aquatic:
                target.version = ab.latest("java")
            progress.log(tr("Java route: explicit conversion to the latest version") if aquatic else
                         tr("Java route: numeric world upgraded by Minecraft itself when opened"))
        from .terrain import policy
        from .terrain import ring as ring_mod

        s_sea, t_sea = source_sea(d, src.info), target_sea(target)
        if not target.y_offset and s_sea is not None and s_sea != t_sea:
            # Alpha 1.2 - Beta 1.7.3 and Pocket Edition 0.x have the sea surface at y 63, every
            # later game at y 62: the world moves by one block, so its sea, beaches and rivers
            # meet the ones the game generates around it
            target.y_offset = t_sea - s_sea
            progress.log(tr("Sea level: y {source} in the source world, y {target_sea} in {target}: the converted world "
                            "is raised by one block (player and spawn included).", source=s_sea, target_sea=t_sea,
                            target=target.describe()) if t_sea > s_sea else
                         tr("Sea level: y {source} in the source world, y {target_sea} in {target}: the converted world "
                            "is lowered by one block (player and spawn included).", source=s_sea, target_sea=t_sea,
                            target=target.describe()))
        # writers without their own vertical shift (LCE, PE): the chunks are moved here
        shift_here = target.y_offset if target.family in ("lce", "pe_old") else 0
        amulet_target = _is_amulet_target(target)
        hub_dir = os.path.join(tmp, "hub_out") if amulet_target else out_dir
        dims = src.dimensions()
        # region by region: each source region file is read once and each written region is finished
        # before the next, whatever the size of the world (in column order, a world wider than the
        # writers' region cache would read and rewrite the same files over and over)
        coords = {dim: sorted(sel.filter(dim, src.chunk_coords(dim)), key=_region_order) for dim in dims}
        from .relocate import Relocation

        move = Relocation(sel)
        if move.active:
            progress.log(move.describe())
        outside: Dict[int, int] = {}
        area = None if d.kind in _FINITE_SOURCES else _finite_area(target, move.spawn(src.info) if move.active else src.info.spawn)
        if area is not None:
            # a finite map (LCE, PE 0.x): the chunks that cannot reach it are not even read
            n_dim = {dim: len(v) for dim, v in coords.items()}
            coords = {dim: _within(cs, area.get(dim), move.delta(dim)) for dim, cs in coords.items()}
            outside = {dim: n - len(coords[dim]) for dim, n in n_dim.items() if n > len(coords[dim])}
        # where the chunks land in the converted world (the same as ``coords`` unless they are moved)
        placed = {dim: move.coords(dim, cs) for dim, cs in coords.items()}
        writer = _make_writer(target, hub_dir, progress, src, move.spawn(src.info) if move.active else None)
        if target.family == "lce" and d.kind == "lce" and placed.get(THE_END):
            # LCE → LCE: every End chunk of the source is kept (the game wrote them, in the End of its version)
            xs, zs = zip(*placed[THE_END])
            writer.opt.keep_end = (min(xs), max(xs) + 1, min(zs), max(zs) + 1)
        if outside and hasattr(writer, "skipped_outside"):
            for dim, n in outside.items():                 # counted with the ones the writer leaves out
                writer.skipped_outside[dim] += n
        total = sum(len(v) for v in coords.values()) or 1
        start = 0.35 if d.kind in AMULET_KINDS else 0.05
        end = 0.6 if amulet_target else 0.97
        done = 0
        # Amulet would turn LCE's "not computed yet" biome (255) into plains: fill it from the
        # nearest real biomes instead (LCE and numeric Java targets keep 255: the game recomputes it).
        filler = BiomeFiller(writer.stored_biomes) if amulet_target else None
        # the border between the converted world and the terrain the game generates (docs/SEAMLESS_BORDERS.md)
        plan = policy.decide(target, old_source, d.kind, getattr(writer, "opt", None))
        if plan.kind == "ring" and target.family == "java":
            from .java.numeric import generator_name

            wtype = generator_name(src.info.level)
            if wtype == "flat":
                plan = policy.Plan("game", tr("Superflat world: the game continues the same flat terrain past the "
                                              "edge, no ring needed."))
            elif not ring_mod.supported(target, wtype):
                plan = policy.Plan("missing", tr(CUSTOMIZED))
        if plan.kind == "missing":
            progress.warn(plan.text)
        elif plan.text:
            progress.log(plan.text)
        ring = None
        seed = world_seed(src.info.level)
        if plan.kind == "ring" and coords.get(OVERWORLD) and target.family == "lce":
            from .terrain.neogen import NeoGenerator

            opt = writer.opt
            kind = str(ab.nbt.get(src.info.level, "generatorName", "default") or "default").lower()
            gen = NeoGenerator(seed, xz_size=opt.world_size, large_biomes=kind == "largebiomes",
                               offset=(opt.offset_x, opt.offset_z))
            # the chunks are moved up or down before the ring sees them (shift_here)
            ring = ring_mod.Ring(gen, target_sea(target), placed[OVERWORLD], seed=seed)
        elif plan.kind == "ring" and coords.get(OVERWORLD):
            from .java.numeric import generator_name

            gen, sea = ring_mod.generator(target, seed, generator_name(src.info.level))
            ring = ring_mod.Ring(gen, sea, placed[OVERWORLD], dy=target.y_offset, seed=seed)
        elif plan.kind == "fill":
            from .terrain.filler import FillGenerator

            sea = target_sea(target)
            ring = ring_mod.Ring(FillGenerator(seed, sea=sea), sea, placed.get(OVERWORLD, []),
                                 fill=finite_chunks(writer), seed=seed)
            end = start + (end - start) * 0.5                  # the other half: the rest of the map
        rings3d = _make_rings3d(target, seed, placed, plan)
        progress.stage(tr("Converting {n} chunks", n=total), start, end)
        fit = None
        ceiling = target_ceiling(target)
        if (ceiling and target.tall_terrain == "compress" and getattr(src, "max_height", 256) > ceiling
                and coords.get(OVERWORLD)):
            from .heightfit import HeightFit

            mid = start + (end - start) * 0.15
            progress.stage(tr("Terrain heights"), start, mid)
            fit = HeightFit(ceiling - target.y_offset)
            ow = coords[OVERWORLD]
            for i, (cx, cz) in enumerate(ow):
                progress.check()
                try:
                    c = src.read_chunk(OVERWORLD, cx, cz)
                except (ConversionCancelled, KeyboardInterrupt):
                    raise
                except Exception:  # noqa: BLE001
                    c = None
                if c is not None:
                    fit.observe(c)
                if i % 64 == 0:
                    progress.update(i / len(ow), tr("Terrain heights {i}/{n}", i=i, n=len(ow)))
            if fit.needed:
                progress.log(tr("Mountains up to y {top}: the part above y {knee} is compressed (to {ratio} %) to stay "
                                "under the y {limit} limit; surface, trees and buildings come down whole.",
                                top=fit.max_ground, knee=fit.knee, ratio=f"{fit.ratio * 100:.0f}", limit=ceiling - 1))
            else:
                fit = None
            progress.stage(tr("Converting {n} chunks", n=total), mid, end)
        written = unreadable = emptied = cut_tiles = cut_entities = empty_chests = 0
        rows = None
        if _pairs_chests_itself(target):
            from .chestfix import ChestRows

            rows = ChestRows(src.read_chunk)
        observe = {dim: set(r3.edge_chunks) for dim, r3 in rings3d.items()}
        if ring is not None:
            observe.setdefault(OVERWORLD, set()).update(ring.edge_chunks)
        pipe = _Pipeline(src, progress, rows, fit, shift_here, sel.biomes if not amulet_target else None,
                         move, writer, observe, not amulet_target, filler is not None, depth)
        written_ow = set()
        track_ow = ring is not None and plan.kind == "fill"      # only the fill needs them (finite maps)
        cur_dim = None
        items = ((dim, cx, cz) for dim in dims for cx, cz in coords[dim])
        for res in pipe.run(list(items) if total < 64 else items, _reads_in_workers(d, fit)):
            progress.check()
            if res.dim != cur_dim:
                if filler is not None and cur_dim is not None:
                    for fdim, fc in filler.flush():
                        writer.add_chunk(fdim, fc)
                cur_dim = res.dim
            pipe.merge(res)
            unreadable += res.unreadable
            emptied += res.emptied
            cut_tiles += res.cut_tiles
            cut_entities += res.cut_entities
            empty_chests += res.empty_chests
            if res.obs is not None:
                if ring is not None:
                    ring.observe(res.dim, res.obs)
                if res.dim in rings3d:
                    rings3d[res.dim].observe(res.dim, res.obs)
            if res.written:
                if res.encoded:
                    writer.store(res.rec, res.dim)
                    written += 1
                    if track_ow and res.dim == OVERWORLD:
                        written_ow.add(res.pos)
                else:
                    c = res.chunk
                    if filler is not None:
                        c = filler.process(res.dim, c)
                    if c is not None:
                        writer.add_chunk(res.dim, c)
                        written += 1
                        if track_ow and res.dim == OVERWORLD:
                            written_ow.add((c.cx, c.cz))
            done += 1
            if done % 16 == 0 or done == total:
                progress.update(done / total, tr("Chunk {done}/{total}", done=done, total=total))
        if filler is not None:
            for fdim, fc in filler.flush():
                writer.add_chunk(fdim, fc)
        if ring is not None:
            if plan.kind == "fill":
                ring.converted |= written_ow                   # unreadable chunks are filled as well
                ring.fill = sorted(set(ring.fill) - written_ow)
                span = (end, 0.97)
            else:
                span = (end, end + 0.01)
            progress.stage(tr("Terrain around the converted world ({target})", target=target.describe()), *span)
            n_ring = 0
            for rc in ring.chunks(progress):
                progress.check()
                writer.add_chunk(OVERWORLD, rc, shift=False)
                n_ring += 1
            if plan.kind == "fill":
                progress.log(tr("Finite world filled: {n} chunks of natural terrain around the converted world, meeting "
                                "its edge (up to {width} chunks); trees and ores are added by the game.",
                                n=n_ring, width=ring.ring))
            elif n_ring:
                progress.log(tr("Ring: {n} chunks of the game's terrain (seed {seed}) around the converted world, "
                                "raised or lowered smoothly to meet its edge, 3 to {width} chunks wide depending on the "
                                "height difference; {trees} trees like those of the edge, the rest (the biomes' trees, "
                                "ores, lakes) is added by the game.", n=n_ring, seed=ring.seed, width=ring.ring,
                                trees=ring.planted))
            end = span[1]
        for dim, r3 in rings3d.items():
            progress.stage(_ring_name(dim), end, min(end + 0.01, 0.97))
            n3 = 0
            for rc in r3.chunks(progress):
                progress.check()
                writer.add_chunk(dim, rc, shift=False)
                n3 += 1
            if n3:
                progress.log(_ring3d_text(dim, n3, r3))
        if rows is not None and rows.changed:
            progress.log(tr("{n} chests in rows of side-by-side double chests become trapped chests, one pair in two: "
                            "the target game joins every chest with any chest next to it and would not draw half of "
                            "the pairs. Every chest keeps its contents.", n=rows.changed))
        if empty_chests:
            progress.warn(tr("{n} chests had no contents (block entity) in the source world or in the translation: "
                             "they were written empty, so at least they are visible.", n=empty_chests))
        _warn_emptied(progress, emptied)
        _warn_cut_extras(progress, cut_tiles, cut_entities)
        if unreadable:
            progress.warn(tr("{n} chunks of the source world were unreadable (damaged or truncated) and were skipped: "
                             "Minecraft will generate them again.", n=unreadable))
        if shift_here:
            shift_info_y(src.info, shift_here)
        if fit is not None:
            from .heightfit import move_players_and_spawn

            move_players_and_spawn(src.info, fit)
            if fit.lost_tiles:
                progress.warn(tr("Mountain compression: {n} block entities (chests, spawners…) were inside the removed "
                                 "rock and were lost.", n=fit.lost_tiles))
        _regen_players(src.info, target.regen, progress)
        move.apply_info(src.info, progress)
        progress.stage(tr("Writing the final files"), end, end + 0.02)
        out_path = writer.finish(src.info)
        src.close()

        if amulet_target:
            platform = "bedrock" if target.family == "bedrock" else "java"
            wver = _write_version(platform, target.version, target.blend, True)
            if wver != tuple(target.version):
                progress.log(tr("Blending: the chunks are written in the {format} format (pre-Caves & Cliffs); opening the "
                                "world in {version}, Minecraft blends terrain and biomes with the new terrain and "
                                "generates the part below y=0.", format=ab.version_str(wver),
                                version=ab.version_str(target.version)))
            progress.stage(tr("Translating to {target} (Amulet)", target=target.describe()), 0.62, 0.9)
            # the biomes painted on the map tab: after the translation, where every biome of the target exists
            painted = Selection(biomes={dm: {move.coords(dm, [c])[0]: b for c, b in v.items()}
                                        for dm, v in sel.biomes.items()}) if sel.biomes else None
            ab.amulet_convert(hub_dir, out_dir, platform, wver, progress, painted)
            if ring is not None and plan.kind == "ring" and platform == "java" and ring.written:
                ring_mod.mark_proto_chunks(out_dir, ring.written, ring_mod.ring_status(target))
            if platform == "java":
                for dim, r3 in rings3d.items():
                    _mark_ring3d(out_dir, r3)
            progress.stage(tr("Finishing (level.dat, modern blocks, entities)"), 0.9, 0.99)
            # modern blocks first: Amulet must reopen the world with the level.dat it wrote itself
            ab.apply_modern_blocks(out_dir, getattr(writer, "modern", {}), getattr(writer, "waterlogged", {}), progress)
            if platform == "bedrock":
                ab.write_bedrock_level_dat(out_dir, src.info, wver)
            else:
                ab.write_java_level_dat(out_dir, src.info, target.version)
            from .extra import inject_target_extras

            inject_target_extras(hub_dir, out_dir, target, src.info, progress, wver)
            out_path = out_dir
        elif target.family == "java" and target.java_mode == "dfu":
            n_modern = sum(len(v) for v in getattr(writer, "modern", {}).values())
            if n_modern:
                progress.warn(
                    tr("{n} Update Aquatic blocks (LCE) were replaced with 1.12 equivalents: choose a specific "
                       "(pre-converted) Java version to keep them identical.", n=n_modern)
                )
        progress.done()
        return ConversionResult(out_path, written, time.time() - t0, list(progress.warnings))
    except BaseException:
        # cancelled or failed: an output folder this run created and left empty goes away with it
        if created_out and os.path.isdir(out_dir) and not os.listdir(out_dir):
            try:
                os.rmdir(out_dir)
            except OSError:
                pass
        raise
    finally:
        for folder in [tmp] + extra_tmp:
            shutil.rmtree(folder, ignore_errors=True)


def _apply_trim(d: det.Detected, target: TargetSpec, progress: Progress) -> None:
    """World trim before converting: the selection becomes the chunks that are really used."""
    from . import trim

    progress.stage(tr("World trim: reading the time spent in the chunks (InhabitedTime)"), 0.0, 0.03)
    try:
        sc = trim.scan(d.path, progress)
    except trim.TrimUnavailable as ex:
        raise ConversionError(tr("World trim not available: {error}", error=ex)) from ex
    keep = trim.plan(sc, target.trim)
    sel = target.selection or Selection()
    if sel.chunks is not None:  # trim inside the chunks chosen on the map
        keep = {dim: keep.get(dim, set()) & chunks for dim, chunks in sel.chunks.items()}
    sel.chunks = keep
    target.selection = sel
    progress.log(f"World trim ({target.trim.describe()}): {trim.summary(sc, keep)}")


def bta_target_error(target: TargetSpec) -> Optional[str]:
    """Why ``target`` is not available for a Better than Adventure source (None = fine)."""
    if target.family != "java":
        return tr("A Better than Adventure world converts only to Minecraft Java 26.3 (BTA's blocks become blocks of "
                  "the latest Java version).")
    if target.java_mode not in ("auto", "dfu") and not (target.java_mode == "amulet"
                                                          and tuple(target.version or ab.latest("java")) == ab.latest("java")):
        return tr("Better than Adventure converts only to the latest Java version (26.3): choose "
                  "“latest – best route automatically”.")
    return None


def _convert_bta(d: det.Detected, out_dir: str, target: TargetSpec, progress: Progress, t0: float) -> ConversionResult:
    """Better than Adventure -> Java 26.3 (1.18.2 chunks upgraded and blended by the game)."""
    from .bta import TARGET
    from .bta.convert import BtaOptions, convert_world
    from .bta.world import from_wb_dim

    err = bta_target_error(target)
    if err:
        raise ConversionError(err)
    progress.log(tr("Target: Java Edition {version} (1.18.2 format upgraded by Minecraft when opened)  ({path})",
                    version=TARGET, path=out_dir))
    sel = target.selection or Selection()
    links = None
    if sel.players is not None:
        resolve_links(sel.players, "java", progress)
        links = sel.players
    chunks = None
    if sel.chunks is not None:
        chunks = {dim: set(v) for dim, v in sel.chunks.items() if from_wb_dim(dim) is not None}
        progress.log(tr("Selection: {n} chunks", n=sel.count()))
    opt = BtaOptions(palette_file=target.bta_palette, y_offset=target.bta_y_offset, world_name=target.world_name,
                     chunks=chunks, spawn=sel.spawn, player_links=links)
    progress.stage(tr("Converting Better than Adventure → Java 26.3"), 0.03, 0.97)
    n, _report = convert_world(d.path, out_dir, opt, progress)
    progress.stage(tr("Writing the final files"), 0.97, 0.99)
    progress.log(tr("Open the world with Minecraft Java 26.3: on first start the game upgrades it (it may ask for a "
                    "backup) and blends the new terrain with the converted chunks."))
    progress.done()
    return ConversionResult(out_dir, n, time.time() - t0, list(progress.warnings))


def _direct_amulet(d: det.Detected, out_dir: str, target: TargetSpec, progress: Progress, tmp: str,
                   old_source: bool = False, sel: Optional[Selection] = None) -> ConversionResult:
    from .extra import direct_extras, read_amulet_info

    platform = "bedrock" if target.family == "bedrock" else "java"
    sel = sel or Selection()
    info = read_amulet_info(d)
    apply_to_info(info, sel, target.family, progress)
    _regen_players(info, target.regen, progress)
    _warn_single_player(info, target, sel, progress)
    if target.world_name:
        info.level["LevelName"] = ab.nbt.StringTag(target.world_name)
    from .terrain import policy

    plan = policy.decide(target, old_source)
    if plan.kind == "missing":
        progress.warn(plan.text)
    wver = _write_version(platform, target.version, target.blend, old_source)
    if wver != tuple(target.version):
        progress.log(tr("Blending: pre-1.18 source world, the chunks are written in the {format} format and Minecraft "
                        "blends them with the new terrain when the world is opened.", format=ab.version_str(wver)))
    ring_here = plan.kind == "ring" and platform == "java"
    progress.stage(tr("Converting with Amulet to {target}", target=target.describe()), 0.03, 0.75 if ring_here else 0.9)
    from . import depthfit

    depth = depthfit.plan(target, not old_source, d.path, progress)
    from .relocate import Relocation

    move = Relocation(sel)
    n = ab.amulet_convert(d.path, out_dir, platform, wver, progress, sel, depth, move if move.active else None)
    _depth_players(info, depth, progress)
    if depth is not None:
        _warn_emptied(progress, sum(1 for had in depth.emptied.values() if had))
    move.apply_info(info, progress)
    if move.active:
        sel = move.moved_selection()
    progress.stage(tr("Finishing (level.dat, entities, containers)"), 0.75 if ring_here else 0.9, 0.8 if ring_here else 0.99)
    if platform == "bedrock":
        ab.write_bedrock_level_dat(out_dir, info, wver)
    else:
        ab.write_java_level_dat(out_dir, info, target.version)
    direct_extras(d, out_dir, target, info, progress, wver, move if move.active else None, depth)
    if depth is not None:
        _warn_cut_extras(progress, depth.lost_tiles, depth.lost_entities)
    if sel.filters:  # entities/block entities are only attached to written chunks, but be sure
        (prune_bedrock if platform == "bedrock" else prune_java)(out_dir, sel)
    # the ring comes last: the selection would remove it, and the source's entities and block
    # entities must not land in its chunks
    if ring_here:
        from .java.numeric import generator_name

        wtype = generator_name(info.level)
        if wtype != "flat" and _ring_after_amulet(out_dir, target, info, wver, tmp, progress, wtype) is None:
            progress.warn(tr(CUSTOMIZED))
    if platform == "java" and target.ring and tuple(target.version or (99,)) < CAVES_CLIFFS:
        _rings3d_after_amulet(out_dir, target, info, wver, tmp, progress)
    progress.done()
    return ConversionResult(out_dir, n or 0)


def _warn_emptied(progress: Progress, n: int) -> None:
    """Chunks of a Caves & Cliffs world that have nothing left in the target's height (0 - 255)."""
    if n:
        progress.warn(tr("{n} chunks were left empty by the height limit: everything in them lies outside the target "
                         "game's world (y 0 to 255), mostly below y 0. To keep what lies below y 0 use --depth keep "
                         "(the world rises by 64 blocks) or a lower Y, e.g. --depth -32 (in the app: Underground of "
                         "1.18+ worlds).", n=n))


def _warn_cut_extras(progress: Progress, n_tiles: int, n_ents: int) -> None:
    """Block entities / entities of a Caves & Cliffs world whose blocks did not fit the target's
    0 - 255 (underground or mountain tops cut, rock removed by the compression): lost with them."""
    if n_tiles or n_ents:
        progress.warn(tr("Height limit: {tiles} block entities (chests, signs, spawners…) and {entities} entities stood "
                         "on blocks that were cut (under the kept underground, above y 255 or inside the rock removed "
                         "from the mountains) and were lost with them.", tiles=n_tiles, entities=n_ents))


def _depth_players(info, depth, progress: Progress) -> None:
    """The overworld's players and spawn point follow a Caves & Cliffs world moved into 0 - 255
    (depthfit): up with the kept underground, down with the compressed mountains."""
    from .model import dimension_of

    if depth is None:
        return
    if depth.dy:
        progress.log(tr("Underground: kept from y {bottom}, the world rises by {dy} blocks.", bottom=depth.bottom, dy=depth.dy))
    from .java.oldcontent import level_spawn

    lv = info.level
    x, y, z = level_spawn(lv)                        # SpawnX/Y/Z, or Java 1.21.9+'s spawn: {pos}
    for k, v in zip(("SpawnX", "SpawnY", "SpawnZ"), (x, int(round(depth.point(x + 0.5, y, z + 0.5))), z)):
        lv[k] = ab.nbt.IntTag(v)
    sp = ab.nbt.get_tag(lv, "spawn")
    if isinstance(sp, ab.nbt.CompoundTag) and ab.nbt.get_tag(sp, "pos") is not None:
        del lv["spawn"]                              # the plain keys above are the spawn now
    for p in info.players.values():
        pos = ab.nbt.get_tag(p, "Pos")
        if pos is None or len(pos) != 3 or dimension_of(p) != OVERWORLD:
            continue
        x, y, z = (float(v.py_data) for v in pos)
        p["Pos"] = ab.nbt.pos_list(x, depth.point(x, y, z), z)


def _regen_players(info, regen, progress: Progress) -> None:
    """Players standing in a dimension the game generates anew go back to the world's spawn (they
    would appear inside its new rock)."""
    from .model import dimension_of

    if not regen:
        return
    moved = 0
    for p in info.players.values():
        if dimension_of(p) not in regen:
            continue
        old = ab.nbt.get(p, "Dimension", 0)
        p["Dimension"] = ab.nbt.StringTag("minecraft:overworld") if isinstance(old, str) else ab.nbt.IntTag(0)
        lv = info.level
        if all(k in lv for k in ("SpawnX", "SpawnY", "SpawnZ")):
            p["Pos"] = ab.nbt.ListTag([ab.nbt.DoubleTag(int(ab.nbt.get(lv, "SpawnX")) + 0.5),
                                       ab.nbt.DoubleTag(float(ab.nbt.get(lv, "SpawnY"))),
                                       ab.nbt.DoubleTag(int(ab.nbt.get(lv, "SpawnZ")) + 0.5)], 6)
        moved += 1
    if moved:
        progress.log(tr("{n} players were in the regenerated dimension: they go back to the Overworld spawn.", n=moved))


_DIM_NAME = {NETHER: "Nether", THE_END: "End"}
CUSTOMIZED = N_("\"Customized\" world: its generator has settings of its own that WorldBridge does not reproduce, "
                "so a step will remain where the converted world ends.")


def _ring_name(dim: int) -> str:
    return tr("Nether ring") if dim == NETHER else tr("End ring")
_DIM_REGION = {NETHER: os.path.join("DIM-1", "region"), THE_END: os.path.join("DIM1", "region")}


def _make_rings3d(target: TargetSpec, seed: int, coords, plan) -> dict:
    """The rings of the converted Nether and End (terrain/ring3d.py), when the target has their
    generator: dimension -> Ring3D."""
    from .terrain import ring3d

    out = {}
    if target.family != "java" or not getattr(target, "ring", True) or plan.kind == "off":
        return out
    for dim in (NETHER, THE_END):
        if not coords.get(dim):
            continue
        g = ring3d.generator(target, seed, dim)
        if g is None:
            continue
        gen, noise_only = g
        out[dim] = ring3d.Ring3D(gen, dim, coords[dim], dy=target.y_offset, seed=seed, noise_only=noise_only)
    return out


def _ring3d_text(dim: int, n: int, r3) -> str:
    what = tr("rock, lava and caverns") if dim == NETHER else tr("end stone islands")
    if r3.noise_only:
        rest = tr("surfaces and biomes, caves and decoration are added by the game")
    elif dim == NETHER:
        rest = tr("glowstone, fire, lava springs and fortresses are added by the game")
    else:
        rest = tr("the decoration (chorus plants, End cities) is added by the game")
    return tr("{ring}: {n} chunks of the game's terrain (seed {seed}) around the converted world, {width} chunks wide: "
              "{what} pass smoothly from those of the converted edge to the game's; {rest}.", ring=_ring_name(dim), n=n,
              seed=r3.seed, width=r3.width, what=what, rest=rest)


def _mark_ring3d(world_dir: str, r3) -> None:
    """The ring's Nether / End chunks of a 1.13 - 1.17 world: the status the game finishes them from
    (1.14+: "noise", with the biomes left to the game; 1.13: "base", with the End's biomes)."""
    from .terrain import ring as ring_mod

    if not r3.written:
        return
    if r3.noise_only:
        ring_mod.mark_proto_chunks(world_dir, r3.written, "noise", _DIM_REGION[r3.dim], biomes="drop")
    else:
        biomes = r3.gen.biome if r3.dim == THE_END and hasattr(r3.gen, "biome") else None
        ring_mod.mark_proto_chunks(world_dir, r3.written, "base", _DIM_REGION[r3.dim], biomes=biomes)


def _merge_ring_regions(ring_out: str, out_dir: str, sub: str, written) -> None:
    """The ring's chunks join the world's regions (never over a converted chunk)."""
    from .java.region import JavaRegion, RegionWriter

    region = os.path.join(out_dir, sub)
    by_region: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for cx, cz in written:
        by_region.setdefault((cx >> 5, cz >> 5), []).append((cx & 31, cz & 31))
    for (rx, rz), locs in by_region.items():
        src_path = os.path.join(ring_out, sub, f"r.{rx}.{rz}.mca")
        if not os.path.isfile(src_path):
            continue
        dst_path = os.path.join(region, f"r.{rx}.{rz}.mca")
        out = RegionWriter()
        if os.path.isfile(dst_path):
            dst = JavaRegion(dst_path)
            for lx, lz in dst.chunks():
                raw = dst.read(lx, lz)
                if raw is not None:
                    out.put(lx, lz, raw)
        new = JavaRegion(src_path)
        for lx, lz in locs:
            if (lx, lz) not in out.chunks:
                raw = new.read(lx, lz)
                if raw is not None:
                    out.put(lx, lz, raw)
        if any(len(c) + 5 > 255 * 4096 for c in out.chunks.values()):
            continue
        os.makedirs(region, exist_ok=True)
        out.write(dst_path)


def _region_coords(world_dir: str, sub: str) -> set:
    from .java.region import JavaRegion

    region = os.path.join(world_dir, sub)
    coords = set()
    for fn in os.listdir(region) if os.path.isdir(region) else []:
        m = re.match(r"^r\.(-?\d+)\.(-?\d+)\.mca$", fn)
        if m:
            rx, rz = int(m.group(1)), int(m.group(2))
            coords.update((rx * 32 + lx, rz * 32 + lz) for lx, lz in JavaRegion(os.path.join(region, fn)).chunks())
    return coords


def _rings3d_after_amulet(out_dir: str, target: TargetSpec, info, wver, tmp: str, progress: Progress) -> None:
    """The Nether's and End's rings of a world Amulet converted straight to Java 1.13 - 1.17."""
    from .java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
    from .terrain import policy

    seed = world_seed(info.level)
    coords = {dim: _region_coords(out_dir, _DIM_REGION[dim]) for dim in (NETHER, THE_END)}
    rings = _make_rings3d(target, seed, coords, policy.Plan("ring", ""))
    for dim, r3 in rings.items():
        progress.stage(tr("Converted Nether edge (reading)") if dim == NETHER else tr("Converted End edge (reading)"), 0.9, 0.92)
        hub = os.path.join(tmp, f"ring3d_edges_{dim}")
        ab.amulet_convert(out_dir, hub, "java", (1, 12, 2), progress, Selection(chunks={dim: set(r3.edge_chunks)}))
        edges = JavaNumericWorld(hub)
        for cx, cz in r3.edge_chunks:
            try:
                c = edges.read_chunk(dim, cx, cz)
            except Exception:  # noqa: BLE001
                c = None
            if c is not None:
                r3.observe(dim, c)
        progress.stage(_ring_name(dim), 0.92, 0.96)
        ring_hub = os.path.join(tmp, f"ring3d_hub_{dim}")
        writer = JavaNumericWriter(ring_hub, JavaWriteOptions(kind="anvil"), progress)
        n = 0
        for rc in r3.chunks(progress):
            progress.check()
            writer.add_chunk(dim, rc, shift=False)
            n += 1
        if not n:
            continue
        writer.finish(info)
        ring_out = os.path.join(tmp, f"ring3d_out_{dim}")
        ab.amulet_convert(ring_hub, ring_out, "java", wver, progress)
        _mark_ring3d(ring_out, r3)
        _merge_ring_regions(ring_out, out_dir, _DIM_REGION[dim], r3.written)
        progress.log(_ring3d_text(dim, n, r3))


def _ring_after_amulet(out_dir: str, target: TargetSpec, info, wver, tmp: str, progress: Progress,
                       world_type: str) -> Optional[int]:
    """The ring of a world Amulet converted straight to Java 1.14 - 1.17: its border chunks are read
    back (as 1.12 numeric chunks), the ring is generated, translated by Amulet and added to the world's
    regions with the "surface" status (the game carves and decorates it).  None: no generator."""
    from .java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
    from .java.region import JavaRegion, RegionWriter
    from .terrain import ring as ring_mod

    if not ring_mod.supported(target, world_type):
        return None
    region = os.path.join(out_dir, "region")
    coords = set()
    for fn in os.listdir(region) if os.path.isdir(region) else []:
        m = re.match(r"^r\.(-?\d+)\.(-?\d+)\.mca$", fn)
        if m:
            rx, rz = int(m.group(1)), int(m.group(2))
            coords.update((rx * 32 + lx, rz * 32 + lz) for lx, lz in JavaRegion(os.path.join(region, fn)).chunks())
    if not coords:
        return 0
    seed = world_seed(info.level)
    gen, sea = ring_mod.generator(target, seed, world_type)
    ring = ring_mod.Ring(gen, sea, coords, seed=seed)
    progress.stage(tr("Edge of the converted world (reading)"), 0.8, 0.83)
    edge_hub = os.path.join(tmp, "ring_edges")
    ab.amulet_convert(out_dir, edge_hub, "java", (1, 12, 2), progress,
                      Selection(chunks={OVERWORLD: set(ring.edge_chunks)}))
    edges = JavaNumericWorld(edge_hub)
    for cx, cz in ring.edge_chunks:
        try:
            c = edges.read_chunk(OVERWORLD, cx, cz)
        except Exception:  # noqa: BLE001
            c = None
        if c is not None:
            ring.observe(OVERWORLD, c)
    progress.stage(tr("Terrain around the converted world ({target})", target=target.describe()), 0.83, 0.87)
    ring_hub = os.path.join(tmp, "ring_hub")
    writer = JavaNumericWriter(ring_hub, JavaWriteOptions(kind="anvil"), progress)
    n = 0
    for rc in ring.chunks(progress):
        progress.check()
        writer.add_chunk(OVERWORLD, rc, shift=False)
        n += 1
    if not n:
        return 0
    writer.finish(info)
    ring_out = os.path.join(tmp, "ring_out")
    progress.stage(tr("Translating the terrain around the world (Amulet)"), 0.87, 0.9)
    ab.amulet_convert(ring_hub, ring_out, "java", wver, progress)
    ring_mod.mark_proto_chunks(ring_out, ring.written, ring_mod.ring_status(target))
    # the ring's chunks join the world's regions (never over a converted chunk)
    by_region: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for cx, cz in ring.written:
        by_region.setdefault((cx >> 5, cz >> 5), []).append((cx & 31, cz & 31))
    for (rx, rz), locs in by_region.items():
        src_path = os.path.join(ring_out, "region", f"r.{rx}.{rz}.mca")
        if not os.path.isfile(src_path):
            continue
        dst_path = os.path.join(region, f"r.{rx}.{rz}.mca")
        out = RegionWriter()
        if os.path.isfile(dst_path):
            dst = JavaRegion(dst_path)
            for lx, lz in dst.chunks():
                raw = dst.read(lx, lz)
                if raw is not None:
                    out.put(lx, lz, raw)
        new = JavaRegion(src_path)
        for lx, lz in locs:
            if (lx, lz) not in out.chunks:
                raw = new.read(lx, lz)
                if raw is not None:
                    out.put(lx, lz, raw)
        if any(len(c) + 5 > 255 * 4096 for c in out.chunks.values()):
            continue
        os.makedirs(region, exist_ok=True)
        out.write(dst_path)
    progress.log(tr("Ring: {n} chunks of the game's terrain (seed {seed}) around the converted world, raised or lowered "
                    "smoothly to meet its edge, 3 to {width} chunks wide depending on the height difference; caves, "
                    "trees, ores and lakes are added by the game.", n=n, seed=seed, width=ring.ring))
    return n


def _warn_single_player(info, target: TargetSpec, sel: Selection, progress: Progress) -> None:
    if sel.players is not None and len(info.players) > 1 and target.family in ("bedrock", "pe_old"):
        progress.warn(tr("{target}: only the main player ({player}) is transferred; the other selected players are "
                         "ignored.", target=target.describe(), player=next(iter(info.players))))


def _edit_copy(d: det.Detected, out_dir: str, target: TargetSpec, sel: Selection, progress: Progress) -> None:
    """Chunk selection / spawn / players on a world copied as it is (pre-1.18 -> latest route)."""
    from .extra import read_amulet_info
    from .selection import edit_bedrock_copy, edit_java_copy

    info = read_amulet_info(d)
    apply_to_info(info, sel, target.family, progress)
    if target.family == "bedrock":
        n = prune_bedrock(out_dir, sel)
        edit_bedrock_copy(out_dir, sel, info, progress)
    else:
        n = prune_java(out_dir, sel)
        edit_java_copy(out_dir, sel, info, progress)
    if n:
        progress.log(tr("Selection: {n} unselected chunks removed.", n=n))

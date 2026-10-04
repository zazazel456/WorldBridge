"""Bridge to Amulet Core / PyMCTranslate for Java 1.13+ and Bedrock worlds.

Amulet is used for what it does best: translating block states between
every Java and Bedrock version.  Level metadata, players, block entity
contents and entities are handled by WorldBridge itself (see
:mod:`worldbridge.bedrock.extra` and :mod:`worldbridge.java.modern`).
"""

from __future__ import annotations

import functools
import logging
import os
import struct
import time
from typing import Dict, List, Optional, Tuple

from . import gameversion as gv
from . import nbt
from .i18n import N_, tr
from .model import NETHER, OVERWORLD, THE_END, ConversionError, Progress, WorldInfo

log = logging.getLogger(__name__)

AMULET_DIMS = {OVERWORLD: "minecraft:overworld", NETHER: "minecraft:the_nether", THE_END: "minecraft:the_end"}
DIM_FROM_AMULET = {v: k for k, v in AMULET_DIMS.items()}


def _quiet():
    # Amulet/PyMCTranslate log (harmless) translation misses with full tracebacks
    logging.disable(logging.ERROR)
    for name in ("amulet", "PyMCTranslate", "amulet_nbt"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    _patch_amulet_biomes()


_PATCHED = False


def _patch_amulet_biomes():
    """Fix Amulet Core 1.9 biome orientation for Java 1.2 - 1.14 (2D biomes).

    Amulet stores 2D biomes as ``[x][z]`` (see ``Biomes.convert_to_3d`` and the Bedrock
    interface, which transposes), but its Java numeric / 1.13-1.14 interfaces reshape the
    on-disk array (index ``z * 16 + x``) without transposing.  Converting a Java 1.2 - 1.14
    world to Java 1.15+ or Bedrock therefore mirrored every biome along the x = z diagonal.
    """
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    import numpy
    from amulet_nbt import AbstractBaseArrayTag, ByteArrayTag, IntArrayTag

    try:
        from amulet.level.interfaces.chunk.anvil.anvil_1467 import Anvil1467Interface
        from amulet.level.interfaces.chunk.anvil.anvil_na import AnvilNAInterface
    except ImportError:  # pragma: no cover - other Amulet layout
        return

    def na_decode(self, chunk, data, floor_cy, height_cy):
        biomes = self.get_layer_obj(data, self.Biomes, pop_last=True)
        if isinstance(biomes, AbstractBaseArrayTag) and biomes.np_array.size == 256:
            chunk.biomes = biomes.np_array.astype(numpy.uint32).reshape((16, 16)).T.copy()

    def na_encode(self, chunk, data, floor_cy, height_cy):
        chunk.biomes.convert_to_2d()
        self.set_layer_obj(data, self.Biomes, ByteArrayTag(numpy.asarray(chunk.biomes).astype(numpy.uint8).T.ravel()))

    def i1467_encode(self, chunk, data, floor_cy, height_cy):
        if chunk.status.value > -0.7:
            chunk.biomes.convert_to_2d()
            self.set_layer_obj(data, self.Biomes, IntArrayTag(numpy.asarray(chunk.biomes).astype(numpy.uint32).T.ravel()))

    AnvilNAInterface._decode_biomes = na_decode
    AnvilNAInterface._encode_biomes = na_encode
    Anvil1467Interface._encode_biomes = i1467_encode

    # interface instances are created (and their bound decoders registered) when Amulet is
    # imported: re-bind the biome coders of the existing instances, keeping their order.
    import gc

    for obj in gc.get_objects():
        if not isinstance(obj, AnvilNAInterface):
            continue
        for attr in ("_BaseDecoderEncoder__decoders", "_BaseDecoderEncoder__encoders"):
            coders = getattr(obj, attr, None)
            if not isinstance(coders, dict):
                continue
            rebuilt = {}
            for fn in coders:
                name = getattr(getattr(fn, "__func__", None), "__name__", "")
                if getattr(fn, "__self__", None) is obj and name in ("_decode_biomes", "_encode_biomes", "na_decode",
                                                                      "na_encode", "i1467_encode"):
                    fn = getattr(obj, "_decode_biomes" if "decode" in name else "_encode_biomes")
                rebuilt[fn] = None
            setattr(obj, attr, rebuilt)


@functools.lru_cache(maxsize=1)
def translation_manager():
    _quiet()
    import PyMCTranslate

    return PyMCTranslate.new_translation_manager()


def versions(platform: str) -> List[Tuple[int, ...]]:
    tm = translation_manager()
    return sorted(tuple(v) for v in tm.version_numbers(platform))


def latest(platform: str) -> Tuple[int, ...]:
    return versions(platform)[-1]


def resolve_version(platform: str, v) -> Tuple[Tuple[int, ...], bool]:
    """The known ``platform`` version a requested one is written as: (version, exact).

    "26.3" and "1.21" mean 26.3.0 and 1.21.0 (PyMCTranslate would take (26, 3) for the newest
    version before 26.3.0); a release PyMCTranslate does not list (1.21.11, 1.21.51) is written as
    the newest one before it, whose data the game upgrades.  ValueError: no such version."""
    v = tuple(int(x) for x in v)
    if platform == "bedrock":
        v = gv.bedrock(v)
    if len(v) < 3:
        v = (v + (0, 0, 0))[:3]
    known = versions(platform)
    if v in known:
        return v, True
    older = [k for k in known if k <= v and k[:2] == v[:2]]
    if not older:
        raise ValueError(version_str(v))
    return older[-1], False


def version_str(v) -> str:
    return ".".join(str(x) for x in v)


def java_data_version(v) -> int:
    return translation_manager().get_version("java", tuple(v)).data_version


def load_format_version(path: str):
    """The game version a world was last saved with (as Amulet reads it)."""
    from amulet.level.load import load_format

    _quiet()
    v = load_format(path).version
    return tuple(v) if isinstance(v, (tuple, list)) else None


def load_level(path: str):
    _quiet()
    import amulet

    return amulet.load_level(path)


def make_wrapper(path: str, platform: str, version):
    _quiet()
    if platform == "bedrock":
        from amulet.level.formats.leveldb_world import LevelDBFormat

        w = LevelDBFormat(path)
    else:
        w = _classic_layout_anvil()(path)
    w.create_and_open(platform, tuple(version), overwrite=True)
    return w


CAVES_CLIFFS_DV = 2825  # 1.18: overworld from y -64 to 319


@functools.lru_cache(maxsize=1)
def _classic_layout_anvil():
    """AnvilFormat that always writes the classic folder layout (region/, DIM-1/, DIM1/).

    For Java 26.1+ targets the chunks are written with the target DataVersion
    while the folders + level.dat stay in the pre-26.1 layout: Minecraft
    itself migrates the layout the first time the world is opened."""
    import shutil as _sh

    from amulet.level.formats.anvil_world import AnvilFormat
    from amulet_nbt import CompoundTag, IntTag, LongTag, StringTag

    class ClassicLayoutAnvil(AnvilFormat):
        def _create(self, overwrite, bounds=None, **kwargs):
            if os.path.isdir(self.path):
                if overwrite:
                    _sh.rmtree(self.path)
                else:
                    raise ConversionError(f"A world already exists at {self.path}")
            self._version = self.translation_manager.get_version(self.platform, self.version).data_version
            data = CompoundTag({
                "version": IntTag(19133), "DataVersion": IntTag(self._version),
                "LastPlayed": LongTag(int(time.time() * 1000)), "LevelName": StringTag("WorldBridge")})
            if self._version >= 2709:  # the heights of every dimension, also when Amulet reopens the world
                data["WorldGenSettings"] = CompoundTag({"dimensions": CompoundTag({
                    d: CompoundTag({"type": StringTag(d)})
                    for d in ("minecraft:overworld", "minecraft:the_nether", "minecraft:the_end")})})
            self.root_tag = CompoundTag({"Data": data})
            for sub in ("region", os.path.join("DIM-1", "region"), os.path.join("DIM1", "region")):
                os.makedirs(os.path.join(self.path, sub), exist_ok=True)
            self.root_tag.save_to(os.path.join(self.path, "level.dat"))
            self._reload_world()

        def _get_dimenion_bounds(self, dimension):
            # Amulet reads the heights from the level.dat's WorldGenSettings (1.18 - 1.21) or from
            # data/minecraft/world_gen_settings.dat (26.1+); the new world has neither yet, and
            # without them it falls back to 0 - 255: everything under y 0 and over y 255 was lost
            from amulet.api.selection import SelectionBox, SelectionGroup

            if self._version >= CAVES_CLIFFS_DV and dimension == "minecraft:overworld":
                return SelectionGroup(SelectionBox((-30_000_000, -64, -30_000_000), (30_000_000, 320, 30_000_000)))
            return SelectionGroup(SelectionBox((-30_000_000, 0, -30_000_000), (30_000_000, 256, 30_000_000)))

    return ClassicLayoutAnvil


# Blocks that an older version does not know: Amulet writes them as air (holes in the deepslate
# layer and in mangrove swamps, air pockets where kelp and seagrass grew).  The closest old block
# instead, by name: a Java 1.12 block, translated on to the target when that is newer (1.13 - 1.18,
# Bedrock before 1.19 ...).
_SOIL = ("mud", "packed_mud", "muddy_mangrove_roots", "rooted_dirt", "dirt_with_roots")
_WATERY = ("kelp", "seagrass", "bubble_column", "coral", "sea_pickle")
_THIN = ("flower", "grass", "fern", "bush", "roots", "vine", "lichen", "sprout", "fungus", "_bud", "cluster",
         "candle", "carpet", "petals", "dripleaf", "sapling", "propagule", "spore", "rail", "lantern", "chain",
         "rod", "head", "skull", "banner", "sign", "torch", "button", "pressure_plate", "pointed_dripstone",
         "sculk_vein", "frogspawn", "egg", "scaffolding", "light", "structure_void", "barrier", "air", "moss_carpet",
         "cobweb", "pot", "pickle", "hanging", "conduit", "bell", "grindstone", "lectern", "campfire", "anvil",
         "leaf_litter", "eyeblossom", "clump", "ghast")
_BY_KEYWORD = (("deepslate_", None), ("copper_ore", "stone"), ("_ore", "stone"), ("log", "log"), ("stem", "log"),
               ("wood", "log"), ("hyphae", "log"), ("leaves", "leaves"), ("wart_block", "red_nether_brick"),
               ("planks", "planks"), ("stairs", "stone_stairs"), ("slab", "stone_slab"), ("wall", "cobblestone_wall"),
               ("fence_gate", "fence_gate"), ("fence", "fence"), ("trapdoor", "trapdoor"), ("door", "wooden_door"),
               ("glass", "glass"), ("bricks", "stonebrick"), ("brick", "stonebrick"), ("mud", "dirt"),
               ("dirt", "dirt"), ("moss_block", "grass"), ("moss", "mossy_cobblestone"), ("nylium", "netherrack"),
               ("soul_soil", "soul_sand"), ("honey", "slime"), ("nest", "log"), ("hive", "planks"),
               ("shroomlight", "glowstone"), ("froglight", "glowstone"), ("cobbled", "cobblestone"),
               ("snow", "snow"), ("ice", "ice"), ("gravel", "gravel"), ("sand", "sand"), ("sculk", "stone"),
               ("calcite", ("stone", 3)), ("tuff", ("stone", 5)), ("dripstone", ("stone", 1)),
               ("basalt", ("stone", 5)), ("blackstone", "cobblestone"), ("resin", ("hardened_clay", 0)),
               ("creaking", "log"), ("crafter", "crafting_table"))


# newer blocks and plants with a better stand-in than PyMCTranslate's (stone, dandelion)
_STAND_IN = {"bamboo": "fence", "bamboo_mosaic": "planks", "bamboo_mosaic_slab": "wooden_slab",
             "bamboo_mosaic_stairs": "oak_stairs", "bush": ("tallgrass", 1), "firefly_bush": ("tallgrass", 1),
             "short_dry_grass": "deadbush", "tall_dry_grass": "deadbush"}


def _legacy_fallback(name: str, dead: bool = False):
    """A Java 1.12 block name (or (name, data)) for a newer block, None = leave it out (air)."""
    n = name.split(":", 1)[-1]
    if n in _SOIL:
        return "dirt"                        # mud is soil: never stone
    if n.endswith("coral_block"):
        return ("stone", 0) if dead or n.startswith("dead_") else ("wool", 6)
    if any(k in n for k in _WATERY):
        return "water"
    if n.startswith("deepslate_") and n.endswith("_ore"):
        return n[len("deepslate_"):] if n != "deepslate_copper_ore" else "stone"
    if any(k in n for k in _THIN):
        return None
    for key, repl in _BY_KEYWORD:
        if key in n and repl:
            return repl
    return "stone"


def _install_legacy_fallback(version_obj=None) -> None:
    """Patch the block translators (every translation manager Amulet creates) so that blocks the
    target does not know become their closest old block instead of air."""
    import amulet_nbt as an
    from amulet.api.block import Block
    from PyMCTranslate.py3.api.version.translators.block import BlockTranslator

    if getattr(BlockTranslator, "_wb_fallback", False):
        return
    orig = BlockTranslator.from_universal

    def old_block(self, repl, a, kw):
        """The Java 1.12 block ``repl`` (name or (name, data)) in this translator's version."""
        name, data = repl if isinstance(repl, tuple) else (repl, 0)
        old = Block("minecraft", name, {"block_data": an.IntTag(data)})
        ver = self._parent_version
        if ver.platform == "java" and tuple(ver.version_number) < (1, 13):
            return (old, None, False)
        # a newer target: the old block, translated on to it
        j12 = self._translation_manager.get_version("java", (1, 12, 2))
        got = orig(self, j12.block.to_universal(old)[0], *a, **kw)
        return got if isinstance(got[0], Block) and got[0].base_name != "air" else None

    def from_universal(self, block, *a, **kw):
        out = orig(self, block, *a, **kw)
        try:
            res = out[0]
            if not isinstance(res, Block):
                return out
            src = block.base_name
            kind = str(block.properties.get("plant_type", "")).strip('"') if src == "plant" else ""
            own = kind or src
            # blocks PyMCTranslate gives a poor stand-in for (bamboo -> stone, bushes -> dandelions)
            repl = _STAND_IN.get(own)
            if repl is not None and res.base_name != own:
                got = old_block(self, repl, a, kw)
                return got if got is not None else out
            if res.base_name == "air" and src not in ("air", "cave_air", "void_air"):
                dead = str(block.properties.get("dead", "")).strip('"').lower() in ("true", "1", "1b")
                repl = _legacy_fallback(src, dead)
                if repl is not None:
                    got = old_block(self, repl, a, kw)
                    if got is not None:
                        return got
        except Exception:  # noqa: BLE001
            pass
        return out

    BlockTranslator.from_universal = from_universal
    BlockTranslator._wb_fallback = True


# the ground of the Overworld at y 0 - 4 of a world that went down to y -64: a floor of bedrock,
# ragged like the old games' (y <= random(5)), where the ground is natural
_FLOOR_NATURAL = {"air", "cave_air", "stone", "deepslate", "tuff", "granite", "diorite", "andesite", "dirt", "gravel",
                  "water", "lava", "calcite", "smooth_basalt", "dripstone_block", "clay", "sand", "sandstone",
                  "bedrock", "infested_stone", "infested_deepslate", "amethyst_block", "budding_amethyst",
                  "moss_block", "sculk", "raw_iron_block", "raw_copper_block"}


def floor_bedrock(chunk, cx: int, cz: int) -> None:
    """Bedrock at y 0 (and ragged above, up to y 4) in a chunk whose world is cut at y 0."""
    import numpy as np
    from amulet.api.block import Block

    if 0 not in chunk.blocks.sub_chunks:
        return
    sc = chunk.blocks.get_sub_chunk(0)                                   # x, y, z
    pal = chunk.block_palette
    natural = np.zeros(len(pal) + 1, bool)
    for i in range(len(pal)):
        n = pal[i].base_name
        natural[i] = n in _FLOOR_NATURAL or n.endswith("_ore")
    bed = pal.get_add_block(Block("universal_minecraft", "bedrock"))
    rng = np.random.default_rng([cx & 0xFFFFFFFF, cz & 0xFFFFFFFF, 0xBED])
    ragged = np.arange(5)[None, :, None] <= rng.integers(0, 5, (16, 5, 16))
    low = sc[:, :5, :]
    ok = natural[np.minimum(low, len(natural) - 1)] & ragged              # ragged[:, 0] is always True
    low[ok] = bed


def paint_biome(level, chunk, biome_id: int) -> None:
    """The whole chunk becomes one biome (an id of worldbridge.biomes)."""
    import numpy as np
    from amulet.api.chunk.biomes import BiomesShape

    from .biomes import BIOMES, JAVA_17, modern_name

    bid = int(biome_id)
    tm = level.translation_manager
    if bid in JAVA_17:                                   # numeric Java 1.12 biome
        ver = tm.get_version("java", (1, 12, 2))
        universal = ver.biome.to_universal(ver.biome.unpack(bid))
    elif bid < 1000:                                     # added in 1.13 - 1.17
        universal = tm.get_version("java", (1, 17, 1)).biome.to_universal("minecraft:" + BIOMES[bid][0])
    else:                                                # 1.18+ only (up to the latest Java's biomes)
        universal = tm.get_version("java", latest("java")).biome.to_universal("minecraft:" + modern_name(bid))
    idx = chunk.biome_palette.get_add_biome(universal)
    b = chunk.biomes
    if b.dimension == BiomesShape.Shape3D:
        cys = list((b.to_raw()[2] or {}).keys()) or list(range(-4, 20))
        chunk.biomes = {cy: np.full((4, 4, 4), idx, np.uint32) for cy in cys}
    else:
        chunk.biomes = np.full((16, 16), idx, np.uint32)
    chunk.changed = True


def amulet_convert(src_path: str, dst_path: str, platform: str, version, progress: Progress, selection=None,
                   depth=None, move=None) -> int:
    """Translate every chunk of ``src_path`` (or only the chunks of ``selection``) into a new
    world at ``dst_path``; returns the chunk count.  ``depth``: a depthfit.DepthFit that moves a
    Caves & Cliffs overworld into 0 - 255 (its underground kept, its mountains compressed).

    The translation runs on every core, from a Java or Bedrock world into Java or Bedrock: see
    ``_amulet_parallel``."""
    level = load_level(src_path)
    total = 0
    if selection is not None and getattr(selection, "filters", False):
        by_name = {name: dim for dim, name in AMULET_DIMS.items()}
        orig = level.level_wrapper.all_chunk_coords

        def only_selected(dimension, *a, **kw):
            dim = by_name.get(dimension)
            for cx, cz in orig(dimension, *a, **kw):
                if dim is not None and selection.wants(dim, cx, cz):
                    yield cx, cz

        level.level_wrapper.all_chunk_coords = only_selected
    _install_legacy_fallback()
    # a world that goes down to y -64 written to a game whose world starts at y 0: the cut ground gets
    # the bedrock floor the old games have
    try:
        deep = level.level_wrapper.bounds("minecraft:overworld").min[1] < 0
    except Exception:  # noqa: BLE001
        deep = False
    floor = deep and tuple(version)[:2] < (1, 18)
    if depth is not None and not (deep and floor):
        depth = None
    if depth is not None:
        depth.used = True
    painted = {AMULET_DIMS[d]: v for d, v in (getattr(selection, "biomes", None) or {}).items() if v}
    job = _AmuletJob(src_path, platform, version, depth, floor, painted, move)
    if platform in ("java", "bedrock") and (_java_world(src_path) or _bedrock_world(src_path)):
        from .parallel import can_fork, workers

        if workers() > 1 and can_fork():
            try:
                coords = {dname: list(level.level_wrapper.all_chunk_coords(dname)) for dname in level.dimensions}
            except Exception:  # noqa: BLE001
                coords = None
            if coords is not None and sum(len(v) for v in coords.values()) >= PARALLEL_MIN_CHUNKS:
                level.close()
                return _amulet_parallel(job, coords, dst_path, progress)
    if depth is not None and depth.fit is not None:
        # pass 1: the ground height of every column, to know how much the mountains come down
        coords = list(level.level_wrapper.all_chunk_coords("minecraft:overworld"))
        for i, (cx, cz) in enumerate(coords):
            try:
                depth.observe(level.level_wrapper.load_chunk(cx, cz, "minecraft:overworld"))
            except Exception:  # noqa: BLE001
                pass
            if i % 64 == 0:
                progress.update(i / max(1, len(coords)), tr("Terrain heights {i}/{n}", i=i, n=len(coords)))
    job.hook(level)
    try:
        wrapper = make_wrapper(dst_path, platform, version)
        try:
            for i, n in level.save_iter(wrapper):
                total = n
                if n:
                    progress.update(i / n, tr("Translating blocks (Amulet) {i}/{n}", i=i, n=n))
        finally:
            wrapper.close()
    finally:
        level.close()
    return total


PARALLEL_MIN_CHUNKS = 256


def _java_world(path: str) -> bool:
    """A Java world (files that any number of processes can read, unlike Bedrock's LevelDB)."""
    return os.path.isfile(os.path.join(path, "level.dat")) and not os.path.isdir(os.path.join(path, "db"))


def _bedrock_world(path: str) -> bool:
    """A Bedrock world: one process per LevelDB, so each worker opens a copy of its own (its tables
    are hard links, see detect.snapshot)."""
    return os.path.isdir(os.path.join(path, "db"))


class _AmuletJob:
    """What happens to every chunk Amulet reads (the same in this process and in the workers)."""

    def __init__(self, src, platform, version, depth, floor, painted, move):
        self.src, self.platform, self.version = src, platform, tuple(version)
        self.depth, self.floor, self.painted, self.move = depth, floor, painted, move

    def hook(self, level) -> None:
        depth, floor, painted, move = self.depth, self.floor, self.painted, self.move
        if not (floor or painted or move is not None):
            return
        by_dim = {name: dim for dim, name in AMULET_DIMS.items()}
        load = level.level_wrapper.load_chunk

        def transformed(cx, cz, dimension, *a, **kw):
            chunk = load(cx, cz, dimension, *a, **kw)
            if depth is not None and dimension == "minecraft:overworld":
                depth.apply(chunk)
            if floor and dimension == "minecraft:overworld":
                floor_bedrock(chunk, cx, cz)
            bid = painted.get(dimension, {}).get((cx, cz))
            if bid is not None:
                paint_biome(level, chunk, bid)
            if move is not None and dimension in by_dim:
                move.amulet_chunk(by_dim[dimension], chunk)       # worldbridge.relocate
            return chunk

        level.level_wrapper.load_chunk = transformed


# ---------------------------------------------------------------- Amulet on every core

_AM_STATE = None
_UNSET = object()


def _partition(job: _AmuletJob, coords: Dict[str, list], n: int) -> List[Dict[str, list]]:
    """The chunks split among ``n`` workers by the region file they are written to (moved chunks:
    their new region), so that no region is written by two of them; the biggest regions first, each
    to the least busy worker."""
    by_dim = {name: dim for dim, name in AMULET_DIMS.items()}
    regions: Dict[tuple, list] = {}
    for dname, cs in coords.items():
        dx, dz = (0, 0)
        if job.move is not None and dname in by_dim:
            dx, dz = job.move.delta(by_dim[dname])
        for cx, cz in cs:
            regions.setdefault((dname, (cx + dx) >> 5, (cz + dz) >> 5), []).append((cx, cz))
    parts: List[Dict[str, list]] = [{} for _ in range(n)]
    load = [0] * n
    for key in sorted(regions, key=lambda k: (-len(regions[k]), k)):
        k = load.index(min(load))
        parts[k].setdefault(key[0], []).extend(regions[key])
        load[k] += len(regions[key])
    return [p for p in parts if p]


def _amulet_part(k: int):
    """Worker (forked): part ``k`` of the chunks, pass 1 (the ground's heights) or the translation
    into its own folder."""
    job, parts, mode, out, counter, views = _AM_STATE
    want = parts[k]
    # its own view of the source (hard links): Amulet rewrites the world's session.lock when it opens
    # it, and a reader whose lock another process overwrote gets no chunks at all
    level = load_level(views[k])
    try:
        level.level_wrapper.all_chunk_coords = lambda dimension, *a, **kw: iter(want.get(dimension, ()))
        depth = job.depth
        if mode == "observe":
            for cx, cz in want.get("minecraft:overworld", ()):
                try:
                    depth.observe(level.level_wrapper.load_chunk(cx, cz, "minecraft:overworld"))
                except Exception:  # noqa: BLE001
                    pass
                with counter.get_lock():
                    counter.value += 1
            f = depth.fit
            return f.heights, f.built, f.trunks, f.max_ground, depth.observed
        moved = depth.fit.moved_columns if depth is not None and depth.fit is not None else 0
        if job.move is not None:
            job.move.top = _UNSET
        job.hook(level)
        wrapper = make_wrapper(os.path.join(out, str(k)), job.platform, job.version)
        total = last = 0
        try:
            for i, n in level.save_iter(wrapper):
                total = n
                with counter.get_lock():
                    counter.value += i - last
                last = i
        finally:
            wrapper.close()
        starts = moved_d = None
        if depth is not None and depth.fit is not None:
            starts, moved_d = depth.fit._starts, depth.fit.moved_columns - moved
        top = job.move.top if job.move is not None else _UNSET
        return total, starts, moved_d, (None if top is _UNSET else (top,))
    finally:
        level.close()


def _start_part_worker(state) -> None:
    """Initializer of the workers started from the fork server (LevelDB jobs): the state and the
    changes to Amulet that a forked worker would inherit."""
    global _AM_STATE
    _AM_STATE = state
    _quiet()
    _install_legacy_fallback()


def _run_parts(job, parts, mode, out, progress: Progress, total: int, label: str, views: List[str]) -> list:
    global _AM_STATE
    import concurrent.futures as cf

    from .parallel import process_context

    # Bedrock (LevelDB) in the workers: started from the fork server (parallel.process_context)
    leveldb = job.platform == "bedrock" or _bedrock_world(job.src)
    ctx = process_context(leveldb)
    counter = ctx.Value("q", 0)
    state = (job, parts, mode, out, counter, views)
    if leveldb:
        pool = cf.ProcessPoolExecutor(max_workers=len(parts), mp_context=ctx, initializer=_start_part_worker,
                                      initargs=(state,))
    else:
        _AM_STATE = state
        pool = cf.ProcessPoolExecutor(max_workers=len(parts), mp_context=ctx)
    try:
        futures = [pool.submit(_amulet_part, k) for k in range(len(parts))]
        _AM_STATE = None
        while True:
            done, _ = cf.wait(futures, timeout=0.3)
            n = counter.value
            progress.update(n / max(1, total), f"{tr(label)} {n}/{total}")
            if len(done) == len(futures):
                break
        return [f.result() for f in futures]
    except BaseException:
        for p in list(getattr(pool, "_processes", {}).values()):   # cancelled: the workers stop now
            p.terminate()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        _AM_STATE = None
        pool.shutdown(wait=True)


def _amulet_parallel(job: _AmuletJob, coords: Dict[str, list], dst_path: str, progress: Progress) -> int:
    """``amulet_convert`` on every core: each worker process opens the source world itself and writes
    its share of the regions (``_partition``) into a folder of its own; the region files are then
    moved into ``dst_path``.  The compression of the mountains (DepthFit) needs the heights of the
    whole world first: that pass runs on every core too, and its results are put together here
    before the translation starts, so every chunk is moved exactly as in one process."""
    import shutil
    import tempfile

    from .parallel import workers

    from . import detect as det

    parts = _partition(job, coords, workers())
    total = sum(len(v) for v in coords.values())
    views_dir = tempfile.mkdtemp(prefix=".worldbridge_views_", dir=os.path.dirname(os.path.abspath(job.src)) or ".")
    try:
        # Java: every file a hard link; Bedrock: the tables only (LevelDB writes its log and manifest)
        java = _java_world(job.src)
        views = [det.snapshot(job.src, os.path.join(views_dir, str(k)), link=java) for k in range(len(parts))]
        return _amulet_parts(job, parts, coords, total, dst_path, progress, views)
    finally:
        shutil.rmtree(views_dir, ignore_errors=True)


def _amulet_parts(job, parts, coords, total, dst_path, progress, views) -> int:
    import shutil
    import tempfile

    depth = job.depth
    if depth is not None and depth.fit is not None:
        n_ow = len(coords.get("minecraft:overworld", ()))
        for heights, built, trunks, max_ground, observed in _run_parts(job, parts, "observe", None, progress, n_ow,
                                                                       N_("Terrain heights"), views):
            f = depth.fit
            f.heights.update(heights)
            f.built.update(built)
            f.trunks.update(trunks)
            f.max_ground = max(f.max_ground, max_ground)
            depth.observed += observed
    parent = os.path.dirname(os.path.abspath(dst_path)) or "."
    os.makedirs(parent, exist_ok=True)
    out = tempfile.mkdtemp(prefix=".worldbridge_parts_", dir=parent)
    try:
        saved = 0
        for k, (n, starts, moved, top) in enumerate(_run_parts(job, parts, "save", out, progress, total,
                                                               N_("Translating blocks (Amulet)"), views)):
            saved += n
            if starts:
                depth.fit._starts.update(starts)
                depth.fit.moved_columns += moved
            if top is not None:
                job.move.top = top[0]
        if job.platform == "bedrock":
            _merge_bedrock_parts(out, len(parts), dst_path)
            return saved
        # every region belongs to one part; the other files (level.dat...) are the first part's
        for k in range(len(parts)):
            base = os.path.join(out, str(k))
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    rel = os.path.relpath(os.path.join(root, fn), base)
                    dst = os.path.join(dst_path, rel)
                    if os.path.exists(dst):
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    os.replace(os.path.join(root, fn), dst)
        return saved
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _chunk_record(key: bytes) -> bool:
    """A record of one chunk (x, z[, dimension], tag[, sub chunk]): each part writes its own chunks."""
    return len(key) in (9, 10, 13, 14)


def _merge_bedrock_parts(out: str, n: int, dst_path: str) -> None:
    """The parts' LevelDB worlds (``out/0`` ... ``out/n-1``) into one at ``dst_path``: the first part's
    world is moved there, the others' records are added to it.  The chunks of every part are its own
    (``_partition``); the other records (the world's own) are the first part's.  Amulet writes no
    actors here (WorldBridge adds the entities afterwards, extra.py), so no actor id is shared."""
    import shutil

    from leveldb import LevelDB

    first = os.path.join(out, "0")
    os.makedirs(dst_path, exist_ok=True)
    for name in os.listdir(first):
        shutil.move(os.path.join(first, name), os.path.join(dst_path, name))
    db = LevelDB(os.path.join(dst_path, "db"))
    try:
        for k in range(1, n):
            part = LevelDB(os.path.join(out, str(k), "db"))
            try:
                batch: Dict[bytes, bytes] = {}
                for key, value in part.iterate():
                    key = bytes(key)
                    if not _chunk_record(key):
                        try:
                            db.get(key)
                            continue                    # the world's own record: the first part's
                        except KeyError:
                            pass
                    batch[key] = bytes(value)
                    if len(batch) >= 4096:
                        db.putBatch(batch)
                        batch = {}
                if batch:
                    db.putBatch(batch)
            finally:
                part.close()
    finally:
        db.close()


def describe(path: str) -> Optional[str]:
    try:
        from amulet.level.load import load_format

        _quiet()
        f = load_format(path)
        desc = f"{f.platform.capitalize()} {version_str(f.version) if isinstance(f.version, tuple) else f.version}"
        return desc
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------- modern block patching


def apply_modern_blocks(dst_path: str, modern: Dict[int, Dict[Tuple[int, int, int], str]],
                        waterlogged: Dict[int, List[Tuple[int, int, int]]], progress: Progress) -> int:
    """Place Java 1.13+ block states (from LCE Aquatic saves) into a converted world."""
    total = sum(len(v) for v in modern.values()) + sum(len(v) for v in waterlogged.values())
    if not total:
        return 0
    from amulet.api.block import Block

    level = load_level(dst_path)
    done = 0
    try:
        ver = ("java", (1, 13, 2))
        for dim, blocks in modern.items():
            dname = AMULET_DIMS[dim]
            for (x, y, z), state in blocks.items():
                try:
                    level.set_version_block(x, y, z, dname, ver, Block.from_string_blockstate(state))
                except Exception:  # noqa: BLE001
                    pass
                done += 1
                if done % 2000 == 0:
                    progress.update(done / total, tr("Aquatic blocks {i}/{n}", i=done, n=total))
        for dim, positions in waterlogged.items():
            dname = AMULET_DIMS[dim]
            for x, y, z in positions:
                try:
                    blk_, be = level.get_version_block(x, y, z, dname, ver)
                    if isinstance(blk_, Block) and blk_.base_name not in ("water", "air"):
                        props = dict(blk_.properties)
                        if "waterlogged" in props or True:
                            from amulet_nbt import StringTag

                            props["waterlogged"] = StringTag("true")
                            nb = Block(blk_.namespace, blk_.base_name, props)
                            level.set_version_block(x, y, z, dname, ver, nb, be)
                except Exception:  # noqa: BLE001
                    pass
                done += 1
        level.save()
    finally:
        level.close()
    return done


# --------------------------------------------------------------------- level.dat writers


# Minecraft upgrades the player inside level.dat from the level's DataVersion, not from the
# player's own: a level and its player have to be written for the same version.
LEGACY_LEVEL_DV = 1343   # Java 1.12.2: the level and players rebuilt in the numeric layout
SPAWN_COMPOUND_DV = 4548  # Java 1.21.9: spawn: {dimension, pos, yaw, pitch} replaces SpawnX/Y/Z


def write_java_level_dat(path: str, info: WorldInfo, target_version) -> None:
    """The level.dat (and the linked players' playerdata) of a Java world opened by
    ``target_version``, which upgrades it with its data fixers.

    * a Java 1.13+ source no newer than the target keeps its own level and players, with its
      DataVersion: the game upgrades them exactly as it would the original world;
    * a Bedrock source (players made by bedrock.extra.bedrock_player_to_java) is written as a
      Java 1.15.2 level, so its players' items keep their modern names;
    * everything else is a Java 1.12.2 level with players in the numeric layout."""
    from .java.numeric import JavaWriteOptions, build_java_level, write_java_players

    target_dv = java_data_version(target_version)
    level_dv = int(nbt.get(info.level, "DataVersion", 0) or 0)
    players = "playerdata"
    if 1451 <= level_dv <= target_dv:
        data, host = _source_java_level(info, level_dv)
        if host is not None:  # 26.1+: the single player lives in players/data/<singleplayer_uuid>.dat
            players = PLAYERS_26
            uid, p = host
            os.makedirs(os.path.join(path, players), exist_ok=True)
            with open(os.path.join(path, players, f"{uid}.dat"), "wb") as f:
                f.write(nbt.dump(nbt.CompoundTag(p), "", compressed=True))
    else:
        host = next(iter(info.players.values()), None)
        host_dv = int(nbt.get(host, "DataVersion", 0) or 0) if host is not None else 0
        # the level fields are rebuilt in the 1.12 layout: the game turns them into
        # WorldGenSettings only from data older than 1.16 (data version 2550)
        dv = host_dv if 1451 <= host_dv < 2550 and host_dv <= target_dv else LEGACY_LEVEL_DV
        data = build_java_level(info, JavaWriteOptions(kind="anvil", player_dv=dv))
        data["DataVersion"] = nbt.IntTag(dv)
        data["Version"] = nbt.CompoundTag({"Id": nbt.IntTag(dv), "Name": nbt.StringTag(""), "Snapshot": nbt.ByteTag(0)})
        if dv >= 1506 and str(nbt.get(data, "generatorName", "")).lower() == "flat":
            data["generatorOptions"] = _flat_options()  # what the 1.13 fixes make of the classic flat world
    with open(os.path.join(path, "level.dat"), "wb") as f:
        f.write(nbt.dump(nbt.CompoundTag({"Data": data}), "", compressed=True))
    # playerdata files are upgraded from their own DataVersion
    write_java_players(path, info, JavaWriteOptions(kind="anvil", player_dv=target_dv), players)


PLAYERS_26 = os.path.join("players", "data")


def _source_java_level(info: WorldInfo, level_dv: int):
    """A Java 1.13+ source's own level, with the selected spawn, name and host player; and, for a
    26.1+ level (``singleplayer_uuid``), the host as (uuid, compound) for players/data instead."""
    import uuid as _uuid

    from .selection import set_player_uuid, uuid_int_array

    data = nbt.copy(info.level)
    for key in info.derived_level_keys:  # read from 26.1+'s data/minecraft/*.dat (copied as they are)
        data.pop(key, None)              # or added in the 1.21.10 layout for the other targets
    if level_dv >= SPAWN_COMPOUND_DV and "spawn" not in data and "SpawnX" in data:
        pos = [int(nbt.get(data, k, 0)) for k in ("SpawnX", "SpawnY", "SpawnZ")]
        data["spawn"] = nbt.CompoundTag({"dimension": nbt.StringTag("minecraft:overworld"),
                                         "pos": nbt.IntArrayTag(pos), "yaw": nbt.FloatTag(0.0),
                                         "pitch": nbt.FloatTag(0.0)})
        for k in ("SpawnX", "SpawnY", "SpawnZ", "SpawnAngle"):
            data.pop(k, None)
    data.pop("Player", None)
    host = None
    if info.players:
        key = next(iter(info.players))
        p = nbt.copy(info.players[key])
        ln = info.player_links.get(key)
        if ln is not None and getattr(ln, "uuid", None):
            set_player_uuid(p, ln.uuid)
        sp = nbt.get_tag(data, "singleplayer_uuid")
        if sp is None:
            data["Player"] = p
        else:
            if ln is not None and getattr(ln, "uuid", None):
                uid = ln.uuid
                data["singleplayer_uuid"] = uuid_int_array(uid)
            else:
                vals = [int(v) & 0xFFFFFFFF for v in sp]
                uid = str(_uuid.UUID(int=(vals[0] << 96) | (vals[1] << 64) | (vals[2] << 32) | vals[3]))
            host = (uid, p)
    return data, host


def _flat_options() -> nbt.CompoundTag:
    layers = [("minecraft:bedrock", 1), ("minecraft:dirt", 2), ("minecraft:grass_block", 1)]
    return nbt.CompoundTag({
        "layers": nbt.ListTag([nbt.CompoundTag({"block": nbt.StringTag(b), "height": nbt.IntTag(h)})
                               for b, h in layers], 10),
        "biome": nbt.StringTag("minecraft:plains"),
        "structures": nbt.CompoundTag({"village": nbt.CompoundTag()})})


BEDROCK_GAMETYPE = {0: 0, 1: 1, 2: 2, 3: 1}


def write_bedrock_level_dat(path: str, info: WorldInfo, version) -> None:
    """Merge the source level information into the Bedrock level.dat created by Amulet."""
    p = os.path.join(path, "level.dat")
    root = nbt.CompoundTag()
    storage = 10
    if os.path.exists(p):
        with open(p, "rb") as f:
            raw = f.read()
        try:
            storage = struct.unpack_from("<i", raw, 0)[0]
            root = nbt.load(raw[8:], little_endian=True, compressed=False).tag
        except Exception:  # noqa: BLE001
            root = nbt.CompoundTag()
    src = info.level
    v = gv.bedrock_stored(version)          # 26.50 is [1, 26, 50, 0, 0] to the game
    root["LevelName"] = nbt.StringTag(info.name)
    root["lastOpenedWithVersion"] = nbt.ListTag([nbt.IntTag(i) for i in v], 3)
    root["MinimumCompatibleClientVersion"] = nbt.ListTag([nbt.IntTag(i) for i in v], 3)
    root["StorageVersion"] = nbt.IntTag(10 if v[:3] >= (1, 18, 0) else 9 if v[:3] >= (1, 16, 0) else 8)
    seed = nbt.get(src, "RandomSeed")
    if seed is None:
        wgs = nbt.get_tag(src, "WorldGenSettings")
        seed = nbt.get(wgs, "seed", 0) if wgs is not None else 0
    root["RandomSeed"] = nbt.LongTag(int(seed or 0))
    sx, sy, sz = info.spawn
    root["SpawnX"], root["SpawnY"], root["SpawnZ"] = nbt.IntTag(sx), nbt.IntTag(sy), nbt.IntTag(sz)
    gt = int(nbt.get(src, "GameType", 0) or 0)
    root["GameType"] = nbt.IntTag(BEDROCK_GAMETYPE.get(gt, 0))
    diff = nbt.get(src, "Difficulty")
    root["Difficulty"] = nbt.IntTag(2 if diff is None else int(diff))  # 0 is Peaceful, not "missing"
    gen = str(nbt.get(src, "generatorName", "default") or "default").lower()
    root["Generator"] = nbt.IntTag(2 if gen == "flat" else 1)
    t = int(nbt.get(src, "Time", 0) or 0)
    root["Time"] = nbt.LongTag(int(nbt.get(src, "DayTime", t) or t))
    root["currentTick"] = nbt.LongTag(t)
    root["LastPlayed"] = nbt.LongTag(int(time.time()))
    cheats = 1 if nbt.get(src, "allowCommands", 0) else 0
    root["commandsEnabled"] = nbt.ByteTag(cheats)
    root["cheatsEnabled"] = nbt.ByteTag(cheats)
    # defaults for players joining the world (Amulet's template denies doors, containers, fighting)
    from .bedrock.extra import abilities_tag

    root["abilities"] = abilities_tag({"attackmobs": 1, "attackplayers": 1, "build": 1, "doorsandswitches": 1,
                                       "flying": 0, "instabuild": 0, "invulnerable": 0, "lightning": 0,
                                       "mayfly": 0, "mine": 1, "op": 0, "opencontainers": 1, "teleport": 0})
    root["permissionsLevel"] = nbt.IntTag(0)
    root["playerPermissionsLevel"] = nbt.IntTag(1)  # member; the world's owner is operator
    root["hasBeenLoadedInCreative"] = nbt.ByteTag(1 if gt == 1 else 0)
    root["rainLevel"] = nbt.FloatTag(1.0 if nbt.get(src, "raining", 0) else 0.0)
    root["lightningLevel"] = nbt.FloatTag(1.0 if nbt.get(src, "thundering", 0) else 0.0)
    rules = nbt.get_tag(src, "GameRules")
    if isinstance(rules, nbt.CompoundTag):  # the rules both editions have (keepInventory...)
        from .gamerules import bedrock_rules

        for k, v in bedrock_rules(rules).items():
            root[k] = v
    root.setdefault("NetworkVersion", nbt.IntTag(0))
    root.setdefault("Platform", nbt.IntTag(2))
    root.setdefault("SpawnMobs", nbt.ByteTag(1))
    root.setdefault("spawnMobs", nbt.ByteTag(1))
    root.setdefault("experiments", nbt.CompoundTag())
    payload = nbt.dump(root, "", little_endian=True)
    with open(p, "wb") as f:
        f.write(struct.pack("<ii", max(storage, 8), len(payload)) + payload)
    with open(os.path.join(path, "levelname.txt"), "w", encoding="utf-8") as f:
        f.write(info.name)
    if info.thumbnail_png:
        with open(os.path.join(path, "world_icon.jpeg"), "wb") as f:
            f.write(info.thumbnail_png)


def read_bedrock_level_dat(path: str) -> nbt.CompoundTag:
    with open(os.path.join(path, "level.dat"), "rb") as f:
        raw = f.read()
    return nbt.load(raw[8:], little_endian=True, compressed=False).tag


def bedrock_info_to_java(root: nbt.CompoundTag) -> nbt.CompoundTag:
    """Bedrock level.dat -> Java-style Data compound (hub convention)."""
    out = nbt.CompoundTag()
    out["LevelName"] = nbt.StringTag(str(nbt.get(root, "LevelName", "Bedrock World")))
    out["RandomSeed"] = nbt.LongTag(int(nbt.get(root, "RandomSeed", 0) or 0))
    for k in ("SpawnX", "SpawnY", "SpawnZ"):
        out[k] = nbt.IntTag(int(nbt.get(root, k, 64 if k == "SpawnY" else 0) or 0))
    if int(out["SpawnY"].py_data) > 320 or int(out["SpawnY"].py_data) < 0:
        out["SpawnY"] = nbt.IntTag(64)
    gt = int(nbt.get(root, "GameType", 0) or 0)
    out["GameType"] = nbt.IntTag(gt if gt in (0, 1, 2) else 0)
    diff = nbt.get(root, "Difficulty")
    out["Difficulty"] = nbt.ByteTag(2 if diff is None else int(diff))  # 0 is Peaceful, not "missing"
    out["Time"] = nbt.LongTag(int(nbt.get(root, "currentTick", 0) or 0))
    out["DayTime"] = nbt.LongTag(int(nbt.get(root, "Time", 0) or 0))
    out["generatorName"] = nbt.StringTag("flat" if int(nbt.get(root, "Generator", 1) or 1) == 2 else "default")
    out["allowCommands"] = nbt.ByteTag(1 if nbt.get(root, "commandsEnabled", 0) else 0)
    out["raining"] = nbt.ByteTag(1 if float(nbt.get(root, "rainLevel", 0) or 0) > 0 else 0)
    out["thundering"] = nbt.ByteTag(1 if float(nbt.get(root, "lightningLevel", 0) or 0) > 0 else 0)
    from .gamerules import java_rules_from_bedrock

    rules = java_rules_from_bedrock(root)
    if len(rules):
        out["GameRules"] = rules
    return out


def ensure(cond: bool, msg: str):
    if not cond:
        raise ConversionError(msg)

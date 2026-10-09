"""Edition independent in-memory model used as the hub between formats.

Every "legacy" (numeric block id) format is read into / written from these
objects.  The conventions are those of Java Edition 1.12.2 (DataVersion 1343):

* block ids are the numeric Java ids (0..4095) + a 4 bit data value
* entity / block entity ids are namespaced 1.11+ names ("minecraft:pig")
* item stacks use string ids ("minecraft:stone") + ``Damage``

Blocks that do not exist in Java 1.12 (e.g. Update Aquatic blocks stored by
Legacy Console Edition TU69+) are kept in :attr:`NumericChunk.modern_blocks`
as Java 1.13+ block state strings so that they can be re-applied when the
target format supports them.
"""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np

from . import nbt
from .i18n import N_, tr

# Dimension identifiers (Java numeric ids)
OVERWORLD = 0
NETHER = -1
THE_END = 1
# the dimensions' names for messages (translate with tr() where shown)
DIM_LABEL = {OVERWORLD: N_("Overworld"), NETHER: N_("Nether"), THE_END: N_("End")}


def dimension_of(player) -> int:
    """A player's dimension as a number: old worlds store -1 / 0 / 1, Java 1.16+ "minecraft:the_nether"…"""
    v = nbt.get(player, "Dimension", 0)
    if isinstance(v, str):
        return {"minecraft:the_nether": NETHER, "minecraft:the_end": THE_END}.get(v, OVERWORLD)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return OVERWORLD
DIMENSIONS = (OVERWORLD, NETHER, THE_END)


def y_shifts(user: int, sea: int) -> Dict[int, int]:
    """The vertical shift of every dimension: ``user`` (--y-offset) moves the whole world, ``sea`` (the automatic
    adjustment of the sea level: 62 <-> 63) only the overworld - the Nether (lava sea at y 31) and the End have no
    sea level, and a Nether raised by one block would push its bedrock roof (y 127) out of a 128 high target."""
    return {d: user + (sea if d == OVERWORLD else 0) for d in DIMENSIONS}
DIMENSION_NAMES = {OVERWORLD: "Overworld", NETHER: "Nether", THE_END: "The End"}


class ConversionCancelled(Exception):
    pass


class ConversionError(Exception):
    pass


# Java 1.12 block ids: how much light a block absorbs (15 = opaque) and emits
LIGHT_OPACITY = np.full(4096, 15, np.int16)
LIGHT_OPACITY[[0, 6, 20, 26, 27, 28, 31, 32, 37, 38, 39, 40, 44, 50, 51, 53, 54, 55, 59, 63, 64, 65, 66, 67, 68, 69,
               70, 71, 72, 75, 76, 77, 78, 83, 85, 90, 92, 93, 94, 95, 96, 101, 102, 104, 105, 106, 107, 108, 109,
               111, 113, 114, 115, 116, 117, 118, 119, 122, 126, 127, 128, 130, 131, 132, 134, 135, 136, 138, 139,
               140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 154, 156, 157, 160, 163, 164, 166, 167,
               171, 175, 176, 177, 178, 180, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195,
               196, 197, 198, 199, 200, 203, 205, 207, 217]] = 0
LIGHT_OPACITY[[18, 161, 30]] = 1
LIGHT_OPACITY[[8, 9, 79, 212]] = 3
LIGHT_EMISSION = np.zeros(4096, np.int16)
for _ids, _lv in (((10, 11, 51, 89, 91, 119, 124, 138, 169), 15), ((50, 198), 14), ((62,), 13),
                  ((90,), 11), ((74,), 9), ((76, 130), 7), ((213,), 3), ((39, 117, 122), 1)):
    LIGHT_EMISSION[list(_ids)] = _lv


def _spread_light(light: np.ndarray, opacity: np.ndarray) -> np.ndarray:
    """Flood the light 14 steps in the six directions, each block taking away max(1, opacity)."""
    cost = np.maximum(opacity, 1)
    solid = opacity >= 15
    light = light.astype(np.int16)
    for _ in range(14):
        m = np.zeros_like(light)
        m[1:] = np.maximum(m[1:], light[:-1])
        m[:-1] = np.maximum(m[:-1], light[1:])
        m[:, 1:] = np.maximum(m[:, 1:], light[:, :-1])
        m[:, :-1] = np.maximum(m[:, :-1], light[:, 1:])
        m[:, :, 1:] = np.maximum(m[:, :, 1:], light[:, :, :-1])
        m[:, :, :-1] = np.maximum(m[:, :, :-1], light[:, :, 1:])
        new = np.where(solid, light, np.maximum(light, m - cost))
        if np.array_equal(new, light):
            break
        light = new
    return np.clip(light, 0, 15).astype(np.uint8)


@dataclass
class NumericChunk:
    cx: int
    cz: int
    height: int = 256
    # [y, z, x] arrays
    blocks: np.ndarray = None
    data: np.ndarray = None
    block_light: Optional[np.ndarray] = None
    sky_light: Optional[np.ndarray] = None
    biomes: Optional[np.ndarray] = None  # [z, x] uint8 (Java 1.12 biome ids)
    entities: List[nbt.CompoundTag] = field(default_factory=list)
    tile_entities: List[nbt.CompoundTag] = field(default_factory=list)
    tile_ticks: List[nbt.CompoundTag] = field(default_factory=list)
    last_update: int = 0
    inhabited_time: int = 0
    terrain_populated: bool = True
    # (x, y, z) local -> java 1.13+ block state string, for blocks that have no
    # 1.12 numeric equivalent.  The numeric arrays contain the closest 1.12 block.
    modern_blocks: Dict[Tuple[int, int, int], str] = field(default_factory=dict)
    # (x, y, z) local positions that are waterlogged (1.13+ concept)
    waterlogged: Optional[np.ndarray] = None
    # LCE pass-through (kept when writing LCE again so LCE -> LCE is lossless)
    lce_terrain_flags: Optional[int] = None
    lce_heightmap: Optional[np.ndarray] = None
    # block entities and entities of the source dropped with their blocks (worldbridge.depthfit)
    cut_extras: Tuple[int, int] = (0, 0)
    # blocks, block entities and entities above the ceiling of a 128 high target that were cut
    # (worldbridge.heightfit)
    cut_above: Tuple[int, int, int] = (0, 0, 0)

    def __post_init__(self):
        if self.blocks is None:
            self.blocks = np.zeros((self.height, 16, 16), np.uint16)
        if self.data is None:
            self.data = np.zeros((self.height, 16, 16), np.uint8)

    # between processes (parallel.py) the NBT travels as NBT: amulet_nbt's own pickling forgets the
    # element type of an empty list (an empty "Items" would come back as a list of bytes)
    _TAG_LISTS = ("entities", "tile_entities", "tile_ticks")

    def __getstate__(self):
        state = dict(self.__dict__)
        try:
            root = nbt.CompoundTag({k: nbt.ListTag(list(state[k]), 10) for k in self._TAG_LISTS})
            state["_nbt"] = nbt.dump(root, escape=True)
        except Exception:  # noqa: BLE001  (something that is not a compound: pickled as it is)
            return state
        for k in self._TAG_LISTS:
            del state[k]
        return state

    def __setstate__(self, state):
        raw = state.pop("_nbt", None)
        self.__dict__.update(state)
        if raw is not None:
            root = nbt.load_with_offset(raw, 0, escape=True)[0].tag
            for k in self._TAG_LISTS:
                self.__dict__[k] = list(root[k])

    @classmethod
    def empty(cls, cx: int, cz: int, height: int = 256) -> "NumericChunk":
        return cls(cx, cz, height)

    def resize(self, height: int) -> None:
        """Change the vertical size (crop or pad with air)."""
        if height == self.height:
            return

        def fit(arr, fill=0):
            if arr is None:
                return None
            out = np.full((height,) + arr.shape[1:], fill, arr.dtype)
            n = min(height, arr.shape[0])
            out[:n] = arr[:n]
            return out

        self.blocks = fit(self.blocks)
        self.data = fit(self.data)
        self.block_light = fit(self.block_light)
        self.sky_light = fit(self.sky_light, 15)
        self.waterlogged = fit(self.waterlogged, False)
        if height < self.height:
            self.modern_blocks = {k: v for k, v in self.modern_blocks.items() if k[1] < height}
            self.tile_entities = [t for t in self.tile_entities if nbt.get(t, "y", 0) < height]
        self.height = height

    def highest_nonair(self) -> int:
        ys = np.nonzero(self.blocks.reshape(self.height, -1).any(axis=1))[0]
        return int(ys[-1]) if len(ys) else -1

    def heightmap(self) -> np.ndarray:
        """[z, x] first y above the highest non-air block."""
        mask = self.blocks != 0
        any_ = mask.any(axis=0)
        top = self.height - np.argmax(mask[::-1], axis=0)
        return np.where(any_, top, 0).astype(np.int32)

    def compute_sky_light(self) -> np.ndarray:
        """Sky light from the blocks: straight down from the sky, then spread sideways into
        overhangs and cave mouths (within the chunk).  Old games (Beta, Java <= 1.12 with
        LightPopulated, LCE) trust the stored light: a wrong one makes nights bright as day."""
        op = LIGHT_OPACITY[np.asarray(self.blocks, np.int64)]
        sky = np.clip(15 - np.cumsum(op[::-1], axis=0)[::-1], 0, 15).astype(np.int16)
        return _spread_light(sky, op)

    def compute_block_light(self) -> np.ndarray:
        """Light of torches, lava, glowstone… spread through the chunk."""
        b = np.asarray(self.blocks, np.int64)
        return _spread_light(LIGHT_EMISSION[b].astype(np.int16), LIGHT_OPACITY[b])


@dataclass
class WorldInfo:
    """Level wide information, Java 1.12 style ``level.dat`` ``Data`` compound."""

    level: nbt.CompoundTag = field(default_factory=nbt.CompoundTag)
    # player name/uuid/xuid -> player compound (Java 1.12 style)
    players: Dict[str, nbt.CompoundTag] = field(default_factory=dict)
    # other files to carry over verbatim when converting within the same family
    # (e.g. LCE map_*.dat) path -> bytes
    extra_files: Dict[str, bytes] = field(default_factory=dict)
    source_description: str = ""
    # LCE sources: platform key of the save (the layout of some auxiliary files depends on it)
    source_platform: str = ""
    thumbnail_png: Optional[bytes] = None
    # key -> selection.PlayerLink chosen in the "Giocatori" tab (nickname / UUID in the target)
    player_links: Dict[str, object] = field(default_factory=dict)
    # keys added to ``level`` from elsewhere so every writer finds them where Java 1.12 - 1.21.10
    # kept them (Java 1.21.11+ / 26.x sources: game rules, difficulty, weather, generation
    # settings); a Java target that keeps the source's own level.dat removes them
    derived_level_keys: List[str] = field(default_factory=list)
    # worldbridge.pets.PetPlan: what happens to the owners of the tamed animals (set by the conversion)
    pet_plan: object = None

    @property
    def name(self) -> str:
        return nbt.get(self.level, "LevelName", "World") or "World"

    @property
    def spawn(self) -> Tuple[int, int, int]:
        sp = nbt.get_tag(self.level, "spawn")  # 1.21.9+: spawn:{pos:[I;x,y,z], ...}
        if sp is not None and "SpawnX" not in self.level:
            pos = nbt.get_tag(sp, "pos")
            if pos is not None and len(pos) == 3:
                return tuple(int(v) for v in pos)
        return (
            int(nbt.get(self.level, "SpawnX", 0)),
            int(nbt.get(self.level, "SpawnY", 64)),
            int(nbt.get(self.level, "SpawnZ", 0)),
        )


class WorldSource:
    """A readable world in the hub model."""

    info: WorldInfo
    max_height: int = 256

    def dimensions(self) -> List[int]:
        raise NotImplementedError

    def chunk_coords(self, dim: int) -> List[Tuple[int, int]]:
        raise NotImplementedError

    def read_chunk(self, dim: int, cx: int, cz: int) -> Optional[NumericChunk]:
        raise NotImplementedError

    def iter_chunks(self, dim: int) -> Iterator[NumericChunk]:
        for cx, cz in self.chunk_coords(dim):
            c = self.read_chunk(dim, cx, cz)
            if c is not None:
                yield c

    def close(self):
        pass


class Progress:
    """Thread safe progress/cancel/log sink shared between engine and UI."""

    def __init__(self, on_progress: Callable[[float, str], None] = None, on_log: Callable[[str], None] = None):
        self._on_progress = on_progress
        self._on_log = on_log
        self._cancel = threading.Event()
        self.warnings: List[str] = []
        self._stage = ""
        self._span = (0.0, 1.0)

    # --- staging: a stage maps its local 0..1 onto a sub range of the bar
    def stage(self, name: str, start: float, end: float):
        self._stage = name
        self._span = (start, end)
        self.update(0.0)
        self.log(name)

    def update(self, frac: float, msg: str = ""):
        self.check()
        a, b = self._span
        if self._on_progress:
            self._on_progress(a + (b - a) * max(0.0, min(1.0, frac)), msg or self._stage)

    def done(self, msg: str = ""):
        """The end of a successful run: the bar reaches 100% whatever stage span was last set."""
        self._span = (0.0, 1.0)
        self.update(1.0, msg or tr("Completed"))

    def log(self, msg: str):
        if self._on_log:
            self._on_log(msg)

    def warn(self, msg: str):
        if msg not in self.warnings:
            self.warnings.append(msg)
            self.log("⚠ " + msg)

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise ConversionCancelled()


def copy_tree(src: str, dst: str, progress: Progress, ignore=None) -> None:
    """``shutil.copytree`` into ``dst`` (existing folders are merged) that reports its progress file by
    file and can be cancelled between two files."""
    total = sum(len(files) for _r, _d, files in os.walk(src)) or 1
    count = [0]

    def copy(s, d):
        progress.check()
        shutil.copy2(s, d)
        count[0] += 1
        if count[0] % 16 == 0 or count[0] == total:
            progress.update(count[0] / total, tr("Copying files {done}/{total}", done=count[0], total=total))

    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore, copy_function=copy)


UNKNOWN_BIOME = 255


def _nearest_fill(grid: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Fill unknown cells of a 2D grid with the value of the nearest known cell."""
    ky, kx = np.nonzero(known)
    uy, ux = np.nonzero(~known)
    if not len(ky) or not len(uy):
        return grid
    out = grid.copy()
    step = 4096
    for i in range(0, len(uy), step):
        dy = uy[i:i + step, None] - ky[None, :]
        dx = ux[i:i + step, None] - kx[None, :]
        nearest = np.argmin(dy * dy + dx * dx, axis=1)
        out[uy[i:i + step], ux[i:i + step]] = grid[ky[nearest], kx[nearest]]
    return out


class BiomeFiller:
    """Replaces the 'not computed yet' biome (255) with the nearest known biome.

    Chunks whose biomes are entirely unknown are held back and filled from the
    surrounding chunks once the whole dimension has been read.  ``lookup(dim, cx, cz)`` gives the
    biomes of a chunk already written (None: not written): with it, nothing is kept per chunk and
    the neighbours are read back only for the held back chunks, so a world of any size costs the
    same memory; without it, the biomes of every chunk are kept here."""

    def __init__(self, lookup=None):
        self.lookup = lookup
        self.known = {}      # (dim, cx, cz) -> 16x16 biomes (only fully known chunks)
        self.pending = []    # (dim, chunk)

    def process(self, dim: int, c: NumericChunk):
        if c.biomes is None:
            return c
        unknown = c.biomes == UNKNOWN_BIOME
        if not unknown.any():
            if self.lookup is None:
                self.known[(dim, c.cx, c.cz)] = c.biomes
            return c
        if unknown.all():
            self.pending.append((dim, c))
            return None
        c.biomes = _nearest_fill(c.biomes, ~unknown)
        if self.lookup is None:
            self.known[(dim, c.cx, c.cz)] = c.biomes
        return c

    def _known(self, key, held):
        if key not in self.known:
            # a held back chunk is never a source, even once written (as without ``lookup``)
            self.known[key] = None if key in held else self.lookup(*key)
        return self.known[key]

    def flush(self):
        """Yield the held back chunks with biomes taken from the nearest known chunks."""
        held = {(dim, c.cx, c.cz) for dim, c in self.pending} if self.lookup is not None else ()
        get = (lambda key: self._known(key, held)) if self.lookup is not None else self.known.get
        for dim, c in self.pending:
            src = None
            for r in range(1, 9):
                ring = [(dx, dz) for dx in range(-r, r + 1) for dz in range(-r, r + 1) if max(abs(dx), abs(dz)) == r]
                parts = []
                for dx, dz in ring:
                    b = get((dim, c.cx + dx, c.cz + dz))
                    if b is not None:
                        parts.append((dx, dz, b))
                if parts:
                    src = parts
                    break
            if src is None:
                # isolated chunk: the dimension's default biome (plains / nether / the end)
                c.biomes = np.full((16, 16), {NETHER: 8, THE_END: 9}.get(dim, 1), np.uint8)
            else:
                # build a 3x3-chunk mosaic around the target and fill from it
                big = np.full((16 * 17, 16 * 17), UNKNOWN_BIOME, np.uint8)
                o = 16 * 8
                for dx, dz, b in src:
                    big[o + dz * 16:o + dz * 16 + 16, o + dx * 16:o + dx * 16 + 16] = b
                filled = _nearest_fill(big, big != UNKNOWN_BIOME)
                c.biomes = filled[o:o + 16, o:o + 16].copy()
            yield dim, c
        self.pending = []
        if self.lookup is not None:
            self.known = {}

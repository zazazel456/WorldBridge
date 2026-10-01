"""Reading a BTA save: level.dat, per-dimension region folders, chunks and player files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..java.region import JavaRegion
from . import nbtio
from .nbtio import gc, gi, gl, glist, gs
from ..i18n import tr

# BTA dimension ids
OVERWORLD, NETHER, DRIFT = 0, 1, 2
BTA_DIMENSIONS = (OVERWORLD, NETHER, DRIFT)
DIMENSION_NAMES = {OVERWORLD: "overworld", NETHER: "nether", DRIFT: "drift"}
_REGION = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mc[ra]$")


def to_wb_dim(dim: int) -> int:
    """BTA dimension -> WorldBridge dimension (the Drift becomes The End)."""
    from ..model import NETHER as WB_NETHER, OVERWORLD as WB_OVERWORLD, THE_END

    return {OVERWORLD: WB_OVERWORLD, NETHER: WB_NETHER, DRIFT: THE_END}[dim]


def from_wb_dim(dim: int) -> Optional[int]:
    from ..model import NETHER as WB_NETHER, OVERWORLD as WB_OVERWORLD, THE_END

    return {WB_OVERWORLD: OVERWORLD, WB_NETHER: NETHER, THE_END: DRIFT}.get(dim)


def ocean_y(world_type: str) -> int:
    """Sea level (first y above the ocean surface) of a BTA 8.0.1 overworld type; -1 if unknown."""
    t = world_type[10:] if world_type.startswith("minecraft:") else world_type
    if t in ("overworld.extended", "overworld.woods"):
        return 128
    if t == "overworld.islands":
        return 160
    if t in ("overworld.default", "overworld.amplified", "overworld.retro", "overworld.winter", "overworld.hell",
             "overworld.paradise", "overworld.classic", "overworld.indev", "overworld.beta_173"):
        return 64
    if t in ("overworld.floating", "overworld.inland", "overworld.skyblock", "empty", "debug", "flat", "overworld.flat"):
        return 0
    return -1


def auto_shift(world_type: str) -> int:
    """How far the overworld moves down so BTA's sea sits at vanilla's y 63 (at most 65: BTA's
    bedrock floor must stay inside the world)."""
    oy = ocean_y(world_type)
    return min(65, oy - 63) if oy > 0 else 0


def looks_like_bta(path: str) -> bool:
    """A BTA save: level.dat plus McRegion files in ``dimensions/<n>/region`` (BTA 7.1+) or a
    ``region`` folder of .mcr files with a save version newer than vanilla McRegion's 19132."""
    if not os.path.isdir(path):
        return False
    if not any(os.path.isfile(os.path.join(path, n)) for n in ("level.dat", "level.dat_old")):
        return False
    dims = os.path.join(path, "dimensions")
    if os.path.isdir(dims):
        for n in os.listdir(dims):
            if n.isdigit() and os.path.isdir(os.path.join(dims, n, "region")):
                return True
    reg = os.path.join(path, "region")
    if os.path.isdir(reg) and any(n.endswith(".mcr") for n in os.listdir(reg)) and \
            not any(n.endswith(".mca") for n in os.listdir(reg)):
        try:
            data = gc(_level(path), "Data") or {}
        except Exception:  # noqa: BLE001
            return False
        return gi(data, "version") >= 19133
    return False


def _level(path: str) -> dict:
    for name in ("level.dat", "level.dat_old"):
        f = os.path.join(path, name)
        if os.path.isfile(f):
            try:
                return nbtio.load_gzip(f)
            except nbtio.BtaNbtError:
                if name == "level.dat_old":
                    raise
    raise FileNotFoundError(tr("No level.dat in {path}", path=path))


@dataclass
class BtaChunk:
    """A BTA chunk normalised from any chunk format version (legacy, 1, 2, 3)."""

    x: int
    z: int
    blocks: np.ndarray                  # uint16 [256 y, 16 z, 16 x], ids & 16383
    data: np.ndarray                    # uint8  [256, 16, 16]
    biomes: np.ndarray                  # int16  [32 (y >> 3), 16 z, 16 x] -> biome_names, -1 = unset
    biome_names: List[str]
    entities: List[dict] = field(default_factory=list)
    tile_entities: List[dict] = field(default_factory=list)
    terrain_populated: bool = False
    ticks_on_unload: int = -1
    version: int = -1

    def biome_at(self, lx: int, y: int, lz: int) -> Optional[str]:
        i = int(self.biomes[y >> 3, lz, lx])
        return None if i < 0 else self.biome_names[i]


def read_chunk(level: dict) -> BtaChunk:
    """Parses the "Level" compound of a BTA chunk (dispatch on "Version" like ChunkLoaderLegacy)."""
    version = gi(level, "Version", -1)
    blocks = np.zeros((256, 16, 16), np.uint16)
    data = np.zeros((256, 16, 16), np.uint8)
    biomes = np.full((32, 16, 16), -1, np.int16)
    registry: Dict[int, str] = {}
    reg = gc(gc(level, "Registries"), "Biomes")
    if reg:
        for name, v in reg.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                registry[int(v)] = name
    names: List[str] = []
    lut = np.full(256, -1, np.int16)  # biome byte (signed, +128) -> names index
    for raw, name in registry.items():
        if -128 <= raw <= 127:
            lut[raw + 128] = len(names)
            names.append(name)
    lut[:128] = -1  # negative bytes mean "unset"
    if version in (2, 3):
        for s in glist(level, "Sections") or []:
            if not isinstance(s, dict):
                continue
            y = gi(s, "yPos")
            if not 0 <= y <= 15:
                continue
            b = s.get("Blocks")
            if isinstance(b, np.ndarray) and b.dtype.kind == "i" and b.itemsize == 2 and b.size == 4096:
                blocks[y * 16:y * 16 + 16] = (b.astype(np.int32) & 16383).reshape(16, 16, 16)
            d = s.get("Data")
            if isinstance(d, np.ndarray) and d.dtype == np.int8 and d.size == 4096:
                data[y * 16:y * 16 + 16] = d.view(np.uint8).reshape(16, 16, 16)
            bm = s.get("BiomeMap")
            if isinstance(bm, np.ndarray) and bm.dtype == np.int8 and bm.size == 512:
                biomes[y * 2:y * 2 + 2] = lut[bm.astype(np.int16) + 128].reshape(2, 16, 16)
    else:
        # legacy (no version) and version 1: flat XZY arrays of 16 x 16 x 256
        b = level.get("Blocks")
        if isinstance(b, np.ndarray) and b.dtype.kind == "i" and b.itemsize == 2:
            flat = np.zeros(65536, np.int32)
            n = min(65536, b.size)
            flat[:n] = b[:n].astype(np.int32) & 16383
            blocks[:] = flat.reshape(16, 16, 256).transpose(2, 1, 0)
        d = level.get("Data")
        if isinstance(d, np.ndarray) and d.dtype == np.int8:
            flat = np.zeros(65536, np.uint8)
            n = min(65536, d.size)
            flat[:n] = d[:n].view(np.uint8)
            data[:] = flat.reshape(16, 16, 256).transpose(2, 1, 0)
        bm = level.get("BiomeMap") if version == 1 else None
        if isinstance(bm, np.ndarray) and bm.dtype == np.int8:
            flat = np.full(32 * 256, -1, np.int16)
            n = min(flat.size, bm.size)
            flat[:n] = lut[bm[:n].astype(np.int16) + 128]
            biomes[:] = flat.reshape(32, 16, 16).transpose(0, 2, 1)  # [half, x, z] -> [half, z, x]
    c = BtaChunk(gi(level, "xPos"), gi(level, "zPos"), blocks, data, biomes, names)
    c.version = version
    c.terrain_populated = gi(level, "TerrainPopulated") != 0
    c.ticks_on_unload = gl(level, "TicksOnUnload", -1)
    c.entities = [e for e in glist(level, "Entities") or [] if isinstance(e, dict)]
    c.tile_entities = [e for e in glist(level, "TileEntities") or [] if isinstance(e, dict)]
    return c


class BtaWorld:
    """Locates the parts of a BTA save."""

    def __init__(self, path: str):
        self.dir = path
        root = _level(path)
        data = gc(root, "Data")
        if data is None:
            raise ValueError("level.dat senza compound Data")
        self.level = data
        self.save_version = gi(data, "version", 0)
        self._regions: Dict[int, Dict[Tuple[int, int], str]] = {}
        self._open: Dict[str, Optional[JavaRegion]] = {}

    @property
    def name(self) -> str:
        return gs(self.level, "LevelName", "") or os.path.basename(os.path.normpath(self.dir))

    def region_dir(self, dim: int) -> Optional[str]:
        modern = os.path.join(self.dir, "dimensions", str(dim), "region")
        if os.path.isdir(modern):
            return modern
        legacy = {OVERWORLD: os.path.join(self.dir, "region"), NETHER: os.path.join(self.dir, "DIM-1", "region")}.get(
            dim, os.path.join(self.dir, f"DIM{dim}", "region"))
        return legacy if os.path.isdir(legacy) else None

    def regions(self, dim: int) -> Dict[Tuple[int, int], str]:
        if dim not in self._regions:
            out: Dict[Tuple[int, int], str] = {}
            rd = self.region_dir(dim)
            if rd:
                for n in os.listdir(rd):
                    m = _REGION.match(n)
                    p = os.path.join(rd, n)
                    if m and os.path.getsize(p) >= 8192:
                        out[(int(m.group(1)), int(m.group(2)))] = p
            self._regions[dim] = dict(sorted(out.items(), key=lambda kv: (kv[0][1], kv[0][0])))
        return self._regions[dim]

    def dimensions(self) -> List[int]:
        return [d for d in BTA_DIMENSIONS if self.regions(d)]

    def region(self, dim: int, rx: int, rz: int) -> Optional[JavaRegion]:
        p = self.regions(dim).get((rx, rz))
        if p is None:
            return None
        if p not in self._open:
            if len(self._open) > 16:
                self._open.clear()
            self._open[p] = JavaRegion(p)
        return self._open[p]

    def chunk_coords(self, dim: int) -> List[Tuple[int, int]]:
        out = []
        for (rx, rz), p in self.regions(dim).items():
            r = JavaRegion(p)
            out.extend((rx * 32 + lx, rz * 32 + lz) for lx, lz in r.chunks())
        return out

    def read_level(self, dim: int, cx: int, cz: int) -> Optional[dict]:
        """The chunk's "Level" compound; None when absent.  Raises when present but unreadable."""
        r = self.region(dim, cx >> 5, cz >> 5)
        if r is None or not r.offsets[(cx & 31) + (cz & 31) * 32]:
            return None
        raw = r.read(cx & 31, cz & 31)
        if raw is None:
            raise nbtio.BtaNbtError(tr("unreadable chunk data"))
        return gc(nbtio.loads(raw), "Level")

    def timestamp(self, dim: int, cx: int, cz: int) -> int:
        r = self.region(dim, cx >> 5, cz >> 5)
        if r is None or len(r.data) < 8192:
            return 0
        import struct

        return struct.unpack_from(">i", r.data, 4096 + 4 * ((cx & 31) + (cz & 31) * 32))[0]

    def world_type(self, dim: int = OVERWORLD) -> str:
        f = os.path.join(self.dir, "dimensions", str(dim), "dimension.dat")
        if os.path.isfile(f):
            try:
                return gs(gc(nbtio.load_gzip(f), "Data"), "WorldType", "")
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def players(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        pd = os.path.join(self.dir, "players")
        if os.path.isdir(pd):
            for n in sorted(os.listdir(pd)):
                if n.endswith(".dat"):
                    try:
                        out[n[:-4]] = nbtio.load_gzip(os.path.join(pd, n))
                    except Exception:  # noqa: BLE001
                        pass
        return out

    def host_player(self, players: Optional[Dict[str, dict]] = None) -> Tuple[Optional[str], Optional[dict]]:
        """(key, compound) of the single-player player: level.dat "Player", else LastPlayerUUID's file."""
        p = gc(self.level, "Player")
        last = gs(self.level, "LastPlayerUUID", "")
        if p is not None:
            return (last or None), p
        players = self.players() if players is None else players
        if last and last in players:
            return last, players[last]
        return None, None

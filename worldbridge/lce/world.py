"""Legacy Console Edition world reader / writer on top of the hub model."""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .. import blocks as blk
from .. import entities as _ent
from .. import ids, nbt
from ..model import NETHER, OVERWORLD, THE_END, NumericChunk, Progress, WorldInfo, WorldSource, dimension_of
from . import chunk as lch
from . import compat as _compat
from . import region as lreg
from .container import PLATFORMS, SaveContainer
from ..i18n import N_, tr

_REGION_RE = re.compile(r"^(DIM-1|DIM1/)?r\.(-?\d+)\.(-?\d+)\.mcr$")
# PS3 / Vita / PS4 player files: P_<12 hex>_<8 digits>_<online id>.dat (FileHeader::getValidPlayerDatFiles)
_SONY_PLAYER = re.compile(r"^[PN]_[0-9A-Fa-f]{12}_\d{8}.*\.dat$")
# the oldest Xbox 360 saves (save version 1, before TU1) keep the player at the top of the listing:
# players_<XUID>.dat instead of players/<XUID>.dat
_FLAT_PLAYER = re.compile(r"^players_(\d{1,20})\.dat$")
SONY = ("ps3", "vita", "ps4")
_DIM_PREFIX = {OVERWORLD: "", NETHER: "DIM-1", THE_END: "DIM1/"}
_SPLIT_DIM = {0: OVERWORLD, 1: NETHER, 2: THE_END}
_SPLIT_DIM_INV = {v: k for k, v in _SPLIT_DIM.items()}

# world size presets (chunks across) -> (label, nether scale)
WORLD_SIZES = {
    54: ("Classic 864×864", 3),
    64: ("Small 1024×1024", 3),
    192: ("Medium 3072×3072", 6),
    320: ("Large 5120×5120", 8),
}

# The End of the LCE games is a fixed square centred on chunk 0, 0 (the same on every platform).
# Up to TU43 it is 18 x 18 chunks: ChunkSource.h of the game's source has END_LEVEL_MAX_WIDTH = END_LEVEL_MIN_WIDTH
# = 18 ("fix the size of the end for all platforms, 54 / 3"), and every save from TU12 to TU43 has exactly
# 324 End chunks in x, z -9..8.  The saves from TU46 on (the End with its outer islands and cities) have End
# chunks at x -6..5, z -6..30: no centred square of 18 holds them (the game's chunk cache is a centred square,
# index = chunk + size / 2), and no constant for it is in the source we have.  64 x 64 (chunks -32..31, the four
# region files DIM1/r.{-1,0}.{-1,0}) is the smallest region-aligned square that holds them, and the window
# je2be's LCE reader scans for the End (kLengthEndRegions = 1).
END_SIZE_OLD = 18
END_SIZE_NEW = 64

# LCE profiles: which numeric blocks the target game knows and which formats it writes
@dataclass(frozen=True)
class LCEProfile:
    key: str
    label: str
    save_version: int
    chunk_version: int
    allowed: frozenset
    tiles: Optional[frozenset] = None  # allowed block entity ids (None = any)
    entities: Optional[frozenset] = None  # allowed entity ids (None = any)
    end_size: int = END_SIZE_OLD  # chunks across the End the game keeps (centred on 0, 0)


def _profiles() -> Dict[str, LCEProfile]:
    return {
        p.key: p
        for p in (
            LCEProfile("tu31", N_("TU31 – 1.8 blocks (neoLegacy on PC, Bountiful consoles)"), 9, 9, blk.java_upto("1.8")),
            LCEProfile("tu46", N_("TU46 – 1.9 blocks (Elytra Update)"), 9, 9, blk.java_upto("1.9"), end_size=END_SIZE_NEW),
            LCEProfile("tu54", N_("TU54+ – 1.12 blocks (World of Color)"), 9, 9, blk.java_upto("1.12"), end_size=END_SIZE_NEW),
        )
    }


PROFILES = _profiles()
# the versions each platform is written for: on PC only the current neoLegacy (TU31), updated along
# with it; the consoles have their own updates
PLATFORM_PROFILES = {"win64": ("tu31",)}
CONSOLE_PROFILES = ("tu54", "tu46", "tu31")


# the 7th generation consoles (and the Vita) only know the Classic world; the bigger ones came with
# the world size option of the 8th generation, Wii U and the PC port
OLD_GEN = ("xbox360", "ps3", "vita")


def platform_sizes(platform: str) -> Tuple[int, ...]:
    return (54,) if platform in OLD_GEN else tuple(WORLD_SIZES)


def map_area(dim: int, size: int, offset_x: int, offset_z: int, end_size: int = END_SIZE_OLD) -> Tuple[int, int, int, int]:
    """The source chunks ``[x0, x1) × [z0, z1)`` that land in an LCE map of ``size`` chunks whose chunk
    0 is the source chunk ``(offset_x, offset_z)`` (``LCEWriter.target_coords`` keeps exactly these);
    ``end_size``: the End of the target's profile (``LCEProfile.end_size``)."""
    scale = WORLD_SIZES.get(size, ("", 3))[1]
    if dim == NETHER:
        size, ox, oz = max(18, size // scale), offset_x // scale, offset_z // scale
    elif dim == THE_END:
        size, ox, oz = end_size, 0, 0
    else:
        ox, oz = offset_x, offset_z
    lo, hi = -(size // 2), size - size // 2
    return lo + ox, hi + ox, lo + oz, hi + oz


# Windows64 / Xbox load a player from players/<XUID>.dat, the XUID a decimal 64 bit number the game
# gives the user (on neoLegacy one per installation, not derived from the name)
XUID_PLATFORMS = ("win64", "xbox360", "xboxone")


def is_xuid(value: Optional[str]) -> bool:
    return bool(value) and re.fullmatch(r"\d{1,20}", value) is not None and int(value) < 1 << 64


def save_players(path: str) -> Dict[str, str]:
    """The players of an LCE save: name (their "UUID" tag, the nickname on neoLegacy) -> file id
    (the XUID).  The id of the user of a PC is taken from any world played there."""
    c = SaveContainer.load(path)
    out: Dict[str, str] = {}
    for key, blob in sorted(c.files.items()):
        flat = _FLAT_PLAYER.match(key)
        if flat:
            key = f"players/{flat.group(1)}.dat"
        if not (key.startswith("players/") and key.endswith(".dat")):
            continue
        fid = key[len("players/"):-4]
        try:
            name = nbt.get(nbt.load(blob, compressed=None).tag, "UUID")
        except Exception:  # noqa: BLE001
            name = None
        out[str(name) if isinstance(name, str) and name else fid] = fid
    return out


def platform_profiles(platform: str) -> Tuple[str, ...]:
    return PLATFORM_PROFILES.get(platform, CONSOLE_PROFILES)


def resolve_profile(platform: str, profile: Optional[str]) -> str:
    """The profile actually written: the platform's default when none is given, and the only one
    Windows64 has (neoLegacy TU31) whatever is asked."""
    choices = platform_profiles(platform)
    return profile if profile in choices else choices[0]


class LCEWorld(WorldSource):
    """Read a Legacy Console Edition save."""

    def __init__(self, path: str, platform_hint: Optional[str] = None, progress: Optional[Progress] = None):
        self.container = SaveContainer.load(path, platform_hint)
        self.progress = progress
        self._regions: Dict[int, Dict[Tuple[int, int], Tuple[bytes, int]]] = {OVERWORLD: {}, NETHER: {}, THE_END: {}}
        self._index: Dict[int, Dict[Tuple[int, int], Tuple[Tuple[int, int], int, int]]] = {}
        c = self.container
        # neoLegacy stamps its new worlds with a "region_format_16" file: their regions hold 16 x 16
        # chunks (r.X.Z with X = chunk x >> 4), still indexed as in the 32 x 32 files
        width = 16 if "region_format_16" in c.files else 32
        for name, data in c.files.items():
            m = _REGION_RE.match(name)
            if not m:
                continue
            dim = {None: OVERWORLD, "DIM-1": NETHER, "DIM1/": THE_END}[m.group(1)]
            self._regions[dim][(int(m.group(2)), int(m.group(3)))] = (data, width)
        for (sdim, rx, rz), data in c.split_regions.items():
            dim = _SPLIT_DIM.get(sdim, OVERWORLD)
            self._regions[dim][(rx, rz)] = (data, 16)
        self.info = self._read_info()
        self.max_height = 256

    # ------------------------------------------------------------ info
    def _read_info(self) -> WorldInfo:
        c = self.container
        info = WorldInfo()
        level = c.files.get("level.dat")
        data = nbt.CompoundTag()
        if level:
            try:
                root = nbt.load(level, compressed=None).tag
                data = nbt.get_tag(root, "Data") or root
            except Exception:  # noqa: BLE001
                data = nbt.CompoundTag()
        if c.display_name and not nbt.get(data, "LevelName"):
            data["LevelName"] = nbt.StringTag(c.display_name)
        info.level = data
        for name, blob in c.files.items():
            flat = _FLAT_PLAYER.match(name)
            if flat:
                name = f"players/{flat.group(1)}.dat"
            base = name.rsplit("/", 1)[-1]
            if name.endswith(".dat") and (name.startswith("players/") or _SONY_PLAYER.match(base)):
                try:
                    info.players[base[:-4]] = nbt.load(blob, compressed=None).tag
                    info.extra_files["raw_player:" + name] = blob
                except Exception:  # noqa: BLE001
                    pass
            elif name.startswith("data/") or name in ("requiredGameRules.dat",):
                info.extra_files[name] = blob
        info.thumbnail_png = c.thumbnail
        info.source_description = f"Legacy Console Edition – {c.platform.label} (save v{c.version}, orig v{c.original_version})"
        return info

    # ------------------------------------------------------------ chunks
    def dimensions(self) -> List[int]:
        return [d for d in (OVERWORLD, NETHER, THE_END) if self._regions[d]]

    def _build_index(self, dim: int):
        if dim in self._index:
            return self._index[dim]
        idx = {}
        for (rx, rz), (data, width) in self._regions[dim].items():
            for lx, lz, p, length, rle, dlen in lreg.region_entries(data, self.container.endian, width):
                idx[(rx * width + lx, rz * width + lz)] = ((rx, rz), p, length, rle, dlen)
        self._index[dim] = idx
        return idx

    def chunk_coords(self, dim: int):
        return sorted(self._build_index(dim).keys())

    def read_raw_chunk(self, dim: int, cx: int, cz: int) -> Optional[lch.LCEChunk]:
        entry = self._build_index(dim).get((cx, cz))
        if entry is None:
            return None
        (rx, rz), p, length, rle, dlen = entry           # straight to the chunk (the index knows where)
        data, _width = self._regions[dim][(rx, rz)]
        raw = lreg.decompress_payload(data[p:p + length], rle, self.container.platform.chunk, dlen)
        c = lch.decode_chunk(raw)
        c.cx, c.cz = cx, cz
        return c

    def read_chunk(self, dim: int, cx: int, cz: int) -> Optional[NumericChunk]:
        try:
            c = self.read_raw_chunk(dim, cx, cz)
        except Exception as ex:  # noqa: BLE001
            if self.progress:
                self.progress.warn(f"Chunk LCE {cx},{cz} (dim {dim}) illeggibile, saltato: {ex}")
            return None
        if c is None:
            return None
        return lce_to_numeric(c)


def lce_to_numeric(c: lch.LCEChunk) -> NumericChunk:
    n = NumericChunk(c.cx, c.cz, 256, blocks=c.blocks.astype(np.uint16), data=c.data.copy())
    n.sky_light = c.sky
    n.block_light = c.block_light
    n.biomes = c.biomes
    n.entities = list(c.entities)
    n.tile_entities = list(c.tile_entities)
    n.tile_ticks = list(c.tile_ticks)
    n.last_update = c.last_update
    n.inhabited_time = c.inhabited
    n.terrain_populated = c.terrain_populated != 0
    n.lce_terrain_flags = int(c.terrain_populated)
    n.lce_heightmap = c.heightmap
    n.waterlogged = c.waterlogged
    modern = n.blocks > 255
    if modern.any():
        ys, zs, xs = np.nonzero(modern)
        for y, z, x in zip(ys.tolist(), zs.tolist(), xs.tolist()):
            bid = int(n.blocks[y, z, x])
            d = int(n.data[y, z, x])
            state = ids.lce_modern_state(bid, d)
            if state:
                n.modern_blocks[(x, y, z)] = state
            fid, fd = ids.lce_modern_fallback(bid)
            n.blocks[y, z, x] = fid
            n.data[y, z, x] = fd
    return n


# ======================================================================= writer


@dataclass
class LCEWriteOptions:
    platform: str = "win64"
    profile: str = "tu31"
    world_size: int = 320  # chunks across (overworld)
    offset_x: int = 0  # source chunk that becomes chunk 0
    offset_z: int = 0
    chunk_format: Optional[int] = None  # override chunk version (7 = NBT)
    world_name: Optional[str] = None
    host_player_id: Optional[str] = None  # XUID / file name for the host player (PC port, Xbox)
    # LCE → LCE: the End chunks [x0, x1) × [z0, z1) of the source (it is a save the game itself wrote, so
    # all of them are kept, whatever the End of the target's profile)
    keep_end: Optional[Tuple[int, int, int, int]] = None


class LCEWriter:
    def __init__(self, out_dir: str, options: LCEWriteOptions, progress: Progress):
        self.out_dir = out_dir
        self.opt = options
        self.progress = progress
        self.platform = PLATFORMS[options.platform]
        self.profile = PROFILES[resolve_profile(options.platform, options.profile)]
        self.chunk_version = options.chunk_format or self.profile.chunk_version
        self.regions: Dict[Tuple[int, int, int], Dict[Tuple[int, int], Tuple[bytes, int]]] = {}
        self.replaced_blocks = 0
        self.skipped_outside = 0
        # items, enchantments and entities the target game has (neoLegacy: from its source)
        self.compat = _compat.compat_for(self.profile.key, self.platform.key, self.profile.allowed)
        self.dropped: Dict[str, int] = {}

    def bounds(self, dim: int) -> Tuple[int, int]:
        size = self.opt.world_size
        scale = WORLD_SIZES.get(size, ("", 3))[1]
        if dim == NETHER:
            size = max(18, size // scale)
        elif dim == THE_END:
            size = self.profile.end_size
        half = size // 2
        return -half, size - half  # [lo, hi)

    def area(self, dim: int) -> Tuple[int, int, int, int]:
        """The chunks ``[x0, x1) × [z0, z1)`` the map keeps, in the coordinates of the converted world."""
        lo, hi = self.bounds(dim)
        x0, x1, z0, z1 = lo, hi, lo, hi
        if dim == THE_END and self.opt.keep_end is not None:
            kx0, kx1, kz0, kz1 = self.opt.keep_end
            x0, x1, z0, z1 = min(x0, kx0), max(x1, kx1), min(z0, kz0), max(z1, kz1)
        return x0, x1, z0, z1

    def target_coords(self, dim: int, cx: int, cz: int) -> Optional[Tuple[int, int]]:
        ox, oz = self.opt.offset_x, self.opt.offset_z
        if dim == NETHER:
            scale = WORLD_SIZES.get(self.opt.world_size, ("", 3))[1]
            ox, oz = ox // scale, oz // scale
        elif dim == THE_END:
            ox = oz = 0
        tx, tz = cx - ox, cz - oz
        x0, x1, z0, z1 = self.area(dim)
        if x0 <= tx < x1 and z0 <= tz < z1:
            return tx, tz
        return None

    def add_chunk(self, dim: int, chunk: NumericChunk, shift: bool = True):
        self.store(self.encode(dim, chunk, shift))

    def store(self, rec) -> None:
        """Keeps a chunk made by ``encode`` (in this process, in the conversion's order)."""
        if rec is None:
            self.skipped_outside += 1
            return
        key, loc, entry, replaced = rec[:4]
        self.replaced_blocks += replaced
        for what, n in (rec[4] if len(rec) > 4 else {}).items():
            self.dropped[what] = self.dropped.get(what, 0) + n
        self.regions.setdefault(key, {})[loc] = entry

    def encode(self, dim: int, chunk: NumericChunk, shift: bool = True):
        """The chunk as it goes into its region (None: outside the world).  Changes nothing in the
        writer, so it can run in a worker process (parallel.py); ``store`` keeps the result."""
        t = self.target_coords(dim, chunk.cx, chunk.cz)
        if t is None:
            return None
        tx, tz = t
        dx, dz = (tx - chunk.cx) * 16, (tz - chunk.cz) * 16
        if chunk.height != 256:
            chunk.resize(256)
        blocks, data, n = blk.downgrade(chunk.blocks, chunk.data, self.profile.allowed)
        c = lch.LCEChunk()
        c.version = self.chunk_version
        c.cx, c.cz = tx, tz
        c.blocks = blocks.astype(np.uint16)
        c.data = data.astype(np.uint8)
        c.sky = chunk.sky_light if chunk.sky_light is not None else chunk.compute_sky_light()
        if dim != OVERWORLD and chunk.sky_light is None:
            c.sky = np.zeros((256, 16, 16), np.uint8) if dim == NETHER else c.sky
        c.block_light = chunk.block_light if chunk.block_light is not None else chunk.compute_block_light()
        c.biomes = _biomes_for(chunk.biomes, self.profile.key)
        c.last_update = chunk.last_update
        c.inhabited = chunk.inhabited_time
        # sTerrainPopulatedAllNeighbours (1022) | sTerrainPostPostProcessed (1024)
        if chunk.lce_terrain_flags is not None:
            c.terrain_populated = chunk.lce_terrain_flags
        else:
            c.terrain_populated = 2046 if chunk.terrain_populated else 0
        if chunk.lce_heightmap is not None and n == 0:
            c.heightmap = chunk.lce_heightmap
        # what the game has of the items, enchantments and entities (the report counts the rest)
        self.compat.dropped = {}
        ents = []
        for x in chunk.entities:
            e = shift_entity(x, dx, dz)
            if e is not None:
                ents.append(e)
            elif ids.entity_to_old(nbt.get(x, "id", ""))[0] is None:
                self.compat._drop(f"entity {nbt.get(x, 'id', '')}")           # no such mob in the LCE id scheme
        if self.profile.entities is not None:
            ents = [e for e in (_restrict_entity(x, self.profile.entities) for x in ents) if e is not None]
        c.entities = [x for x in (self.compat.entity(e) for e in ents) if x is not None]
        c.tile_entities = [self.compat.holder(t) for t in
                           sanitize_tiles(chunk.tile_entities, c.blocks, dx, dz, self.profile.tiles, lce=True)]
        c.tile_ticks = []
        for tk in chunk.tile_ticks:
            if not isinstance(nbt.get(tk, "i"), int):
                continue  # 1.8+ string ids are not understood by LCE
            if dx or dz:
                tk = nbt.copy(tk)
                tk["x"] = nbt.IntTag(int(tk["x"].py_data) + dx)
                tk["z"] = nbt.IntTag(int(tk["z"].py_data) + dz)
            c.tile_ticks.append(tk)
        payload = lch.encode_chunk(c, self.chunk_version)
        comp = lreg.compress_payload(payload, self.platform.chunk)
        if self.platform.split:
            rx, rz, lx, lz = tx >> 4, tz >> 4, tx & 15, tz & 15
        else:
            rx, rz, lx, lz = tx >> 5, tz >> 5, tx & 31, tz & 31
        return (dim, rx, rz), (lx, lz), (comp, len(payload)), n, dict(self.compat.dropped)

    def finish(self, info: WorldInfo) -> str:
        cont = SaveContainer(self.platform, self.profile.save_version, self.profile.save_version)
        level = build_lce_level(info, self.opt, self.target_coords)
        cont.files["level.dat"] = nbt.dump(nbt.CompoundTag({"Data": level}), "")
        spawn = (int(nbt.get(level, "SpawnX", 0)), int(nbt.get(level, "SpawnY", 64)), int(nbt.get(level, "SpawnZ", 0)))
        self.compat.dropped = {}
        for (dim, rx, rz), chunks in sorted(self.regions.items()):
            data = lreg.build_region(chunks, self.platform.endian)
            if self.platform.split:
                cont.split_regions[(_SPLIT_DIM_INV[dim], rx, rz)] = data
            else:
                cont.files[f"{_DIM_PREFIX[dim]}r.{rx}.{rz}.mcr"] = data
        sony = self.platform.key in SONY
        same_place = self.opt.offset_x == 0 and self.opt.offset_z == 0 and "XZSize" in info.level
        raw_players = {k.split(":", 1)[1]: v for k, v in info.extra_files.items() if k.startswith("raw_player:")}
        for i, (name, player) in enumerate(info.players.items()):
            raw = next((v for k, v in raw_players.items() if k.rsplit("/", 1)[-1][:-4] == name), None)
            nick = getattr(info.player_links.get(name), "nickname", None)
            if nick and not re.fullmatch(r"[0-9A-Za-z_\-]{1,40}", nick):
                nick = None
            if same_place and raw is not None and (sony == bool(_SONY_PLAYER.match(name + ".dat"))):
                orig = next(k for k in raw_players if k.rsplit("/", 1)[-1][:-4] == name)
                if nick and not sony:
                    orig = f"players/{nick}.dat"  # player id chosen in the "Giocatori" tab
                    if self.platform.key in XUID_PLATFORMS and not is_xuid(nick):
                        self.progress.warn(tr("“{name}” is not an XUID: the game will not load this player (it "
                                              "needs the number of its file in players/).", name=nick))
                cont.files[orig] = raw  # unchanged world position: keep the player file byte for byte
                continue
            p = legacy_player(player, self.opt, self.target_coords)
            # the fields and types the game writes; the game's own player files keep their name in "UUID"
            own = nbt.get(p, "UUID")
            p = _compat.lce_player(p, self.compat, spawn, name=nick or (own if isinstance(own, str) and own else None))
            is_sony_name = bool(_SONY_PLAYER.match(name + ".dat"))
            if sony:
                # the first "P_" file is loaded for the primary (local) user
                fname = name if is_sony_name else f"P_000000000000_{i:08d}_Player{i}"
                cont.files[f"{fname}.dat"] = nbt.dump(p, "")
            else:
                fname = name if re.fullmatch(r"[0-9A-Za-z_\-]{1,40}", name) and not is_sony_name else f"player{i}"
                chosen = None
                if i == 0 and self.opt.host_player_id:
                    fname = chosen = self.opt.host_player_id
                if nick:
                    fname = chosen = nick  # player id chosen in the "Giocatori" tab
                if chosen and self.platform.key in XUID_PLATFORMS and not is_xuid(chosen):
                    self.progress.warn(tr(
                        "“{name}” is not an XUID: the game loads the player from players/<number>.dat, so it will "
                        "start at the spawn with an empty inventory. Give the number (the name of your file in "
                        "players/ of a world already played, or use “From my world…” in the GUI).", name=chosen))
                cont.files[f"players/{fname}.dat"] = nbt.dump(p, "")
        for name, blob in info.extra_files.items():
            if name.startswith("data/map_") and not same_place:
                try:  # LCE knows the 36 map colours of Java 1.6
                    from ..maps import java_map_file, legacy_map_data

                    data = nbt.get_tag(nbt.load(blob, compressed=None).tag, "data")
                    blob = java_map_file(legacy_map_data(data, 36))
                except Exception:  # noqa: BLE001
                    pass
            if name.startswith("data/map_") or name == "data/idcounts.dat" or (same_place and name.startswith("data/")):
                cont.files[name] = blob
        folder = self.out_dir
        if self.platform.key == "win64":
            path = cont.save(folder, "saveData.ms")
            thumb = info.thumbnail_png or _default_thumbnail()
            os.makedirs(os.path.join(folder, "thumbnails"), exist_ok=True)
            with open(os.path.join(folder, "thumbnails", "thumbData.png"), "wb") as f:
                f.write(thumb)
        else:
            path = cont.save(folder)
            if info.thumbnail_png and self.platform.key in ("ps4", "xboxone", "switch", "ps3"):
                with open(os.path.join(folder, "THUMB" if self.platform.key != "ps3" else "ICON0.PNG"), "wb") as f:
                    f.write(info.thumbnail_png)
        if self.replaced_blocks:
            self.progress.warn(
                tr("{n} blocks that do not exist in {version} were replaced with equivalents.", n=self.replaced_blocks,
                   version=tr(self.profile.label))
            )
        if self.skipped_outside:
            self.progress.warn(
                tr("{n} chunks outside the LCE world's limits ({size}×{size} chunks) were left out.",
                   n=self.skipped_outside, size=self.opt.world_size)
            )
        for what, n in self.compat.dropped.items():                       # the players' items
            self.dropped[what] = self.dropped.get(what, 0) + n
        if self.dropped:
            items = sum(n for w, n in self.dropped.items() if w.startswith("item"))
            ench = sum(n for w, n in self.dropped.items() if w.startswith("enchantment"))
            ents = sorted({w.split(" ", 1)[1].split(":")[-1] for w in self.dropped if w.startswith("entity")})
            parts = ([tr("{n} items", n=items)] if items else []) + ([tr("{n} enchantments", n=ench)] if ench else []) + \
                ([tr("the entities {names}", names=", ".join(ents))] if ents else [])
            self.progress.warn(tr("{version} does not have {what} of the source world: removed (the game does not know "
                                  "them); new arrows, boats and potions become their classic versions.",
                                  version=self.profile.label.split(" –")[0], what=tr(" and ").join(parts)))
        return path


def shift_entity(e: nbt.CompoundTag, dx: float, dz: float) -> Optional[nbt.CompoundTag]:
    e = legacy_entity(e)
    if e is None:
        return None
    _ent.hanging_to_old(e)  # LCE (Java 1.6 code): paintings / item frames store the wall block
    if dx or dz:
        pos = nbt.get_tag(e, "Pos")
        if pos is not None and len(pos) == 3:
            e["Pos"] = nbt.pos_list(float(pos[0].py_data) + dx, pos[1], float(pos[2].py_data) + dz)
        for k in ("TileX", "TileZ"):
            if k in e:
                e[k] = nbt.IntTag(int(e[k].py_data) + (dx if k == "TileX" else dz))
    return e


_MINECART_TYPES = {"MinecartRideable": 0, "MinecartChest": 1, "MinecartFurnace": 2}


def _restrict_entity(e: nbt.CompoundTag, allowed: frozenset) -> Optional[nbt.CompoundTag]:
    eid = nbt.get(e, "id", "")
    if eid in allowed:
        return e
    if eid in _MINECART_TYPES and "Minecart" in allowed:
        e["id"] = nbt.StringTag("Minecart")
        e["Type"] = nbt.IntTag(_MINECART_TYPES[eid])
        return e
    return None


def legacy_entity(e: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
    """Make sure an entity uses the pre-1.11 id scheme (what LCE understands)."""
    eid = nbt.get(e, "id", "")
    old, extra = ids.entity_to_old(eid)
    if old is None:
        return None
    e = nbt.copy(e)
    e["id"] = nbt.StringTag(old)
    for k, v in extra.items():
        e[k] = nbt.ByteTag(v) if k in ("SkeletonType", "IsVillager", "Elder") else nbt.IntTag(v)
    for key in ("Inventory", "Items"):
        lst = nbt.get_tag(e, key)
        if lst is not None:
            e[key] = legacy_items(lst)
    for key in ("Equipment", "ArmorItems", "HandItems"):  # positional lists: keep empty slots
        lst = nbt.get_tag(e, key)
        if lst is not None and len(lst):
            fixed = nbt.ListTag([], 10)
            for it in lst:
                li = legacy_item(it) if len(it) else None
                fixed.append(li if li is not None else nbt.CompoundTag())
            e[key] = fixed
    if "Item" in e:
        it = legacy_item(e["Item"])
        if it is None:
            return None
        e["Item"] = it
    if "Passengers" in e:
        del e["Passengers"]
    return e


def legacy_item(it: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
    if not isinstance(it, nbt.CompoundTag) or "id" not in it:
        return None
    iid = it["id"]
    if isinstance(iid, nbt.StringTag):
        num = ids.item_id_from_name(iid.py_data)
        if num is None or "components" in it or "count" in it:
            from .. import items as _items

            canon = _items.from_java_modern(it)
            return _items.to_legacy(canon) if canon else None
        it = nbt.copy(it)
        it["id"] = nbt.ShortTag(num)
    return it


def legacy_items(lst, modern: bool = False) -> nbt.ListTag:
    """``modern``: the stacks of Java 1.13+ data (a player with DataVersion >= 1451), named as in
    1.13+: "melon" is the block there, not the slice of Java 1.12."""
    if len(lst) == 0:
        return lst
    out = nbt.ListTag([], 10)
    for it in lst:
        if len(it) == 0:
            continue
        li = legacy_item(it) if not modern else _modern_item(it)
        if li is not None:
            out.append(li)
    return out


def _modern_item(it: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
    from .. import items as _items

    canon = _items.from_java_modern(it) if isinstance(it, nbt.CompoundTag) else None
    return _items.to_legacy(canon) if canon else None


def sanitize_tiles(tiles: List[nbt.CompoundTag], blocks: np.ndarray, dx: int, dz: int,
                   allowed_ids: Optional[frozenset] = None, lce: bool = False) -> List[nbt.CompoundTag]:
    from .. import items as _items

    out = []
    for t in tiles:
        tid = ids.tile_to_old(nbt.get(t, "id", ""))
        if tid is None:
            continue
        if allowed_ids is not None and tid not in allowed_ids and tid not in ("ShulkerBox", "Dropper", "Hopper"):
            continue
        try:
            x, y, z = int(nbt.get(t, "x")), int(nbt.get(t, "y")), int(nbt.get(t, "z"))
        except (TypeError, ValueError):
            continue
        if not 0 <= y < blocks.shape[0]:
            continue
        b = int(blocks[y, z & 15, x & 15])
        want = blk.TILE_FOR_BLOCK.get(b)
        if want is None:
            continue
        if want != tid:
            if {want, tid} <= {"Chest", "ShulkerBox", "Trap", "Dropper", "Hopper"}:
                tid = want
            else:
                continue
        if allowed_ids is not None and tid not in allowed_ids:
            continue
        t = nbt.copy(t)
        t["id"] = nbt.StringTag(tid)
        t["x"] = nbt.IntTag(x + dx)
        t["z"] = nbt.IntTag(z + dz)
        if "Items" in t:
            t["Items"] = legacy_items(t["Items"])
        if tid == "FlowerPot" and isinstance(nbt.get_tag(t, "Item"), nbt.StringTag):
            num = ids.item_id_from_name(nbt.get(t, "Item"))  # LCE reads the plant as an int id
            if num is None:
                del t["Item"]
            else:
                t["Item"] = nbt.IntTag(num)
        if tid == "Sign":
            for i in range(1, 5):
                line = _items.plain_text(nbt.get(t, f"Text{i}", ""))
                t[f"Text{i}"] = nbt.StringTag(_compat.plain_sign_line(line)[:15] if lce else line)
        out.append(t)
    return out


def legacy_player(p: nbt.CompoundTag, opt: LCEWriteOptions, mapper) -> nbt.CompoundTag:
    p = nbt.copy(p)
    modern = int(nbt.get(p, "DataVersion", 0) or 0) >= 1451
    for key in ("Inventory", "EnderItems"):
        if key in p:
            p[key] = legacy_items(p[key], modern)
    dim = dimension_of(p)
    if isinstance(nbt.get_tag(p, "Dimension"), nbt.StringTag):
        p["Dimension"] = nbt.IntTag(dim)
    if int(nbt.get(p, "playerGameType", 0) or 0) not in (0, 1, 2):  # LCE has no Spectator
        p["playerGameType"] = nbt.IntTag(1)
    pos = nbt.get_tag(p, "Pos")
    if pos is not None and len(pos) == 3:
        cx, cz = int(pos[0].py_data) >> 4, int(pos[2].py_data) >> 4
        t = mapper(dim, cx, cz)
        if t is None:
            for k in ("Pos",):
                del p[k]
        else:
            dx, dz = (t[0] - cx) * 16, (t[1] - cz) * 16
            p["Pos"] = nbt.pos_list(float(pos[0].py_data) + dx, pos[1], float(pos[2].py_data) + dz)
    return p


def build_lce_level(info: WorldInfo, opt: LCEWriteOptions, mapper) -> nbt.CompoundTag:
    src = info.level
    if "XZSize" in src:  # LCE -> LCE: keep every field, adjust only what depends on the target
        lvl = nbt.copy(src)
        if opt.world_name:
            lvl["LevelName"] = nbt.StringTag(opt.world_name)
        lvl["XZSize"] = nbt.IntTag(opt.world_size)
        lvl["HellScale"] = nbt.IntTag(WORLD_SIZES.get(opt.world_size, ("", 3))[1])
        sx, sy, sz = info.spawn
        t = mapper(OVERWORLD, sx >> 4, sz >> 4)
        if t is None:
            sx, sz = 0, 0
        else:
            sx += (t[0] - (sx >> 4)) * 16
            sz += (t[1] - (sz >> 4)) * 16
        lvl["SpawnX"], lvl["SpawnZ"] = nbt.IntTag(sx), nbt.IntTag(sz)
        if opt.offset_x or opt.offset_z:
            lvl["hasStronghold"] = nbt.ByteTag(0)
            lvl["hasStrongholdEndPortal"] = nbt.ByteTag(0)
        return lvl
    lvl = nbt.CompoundTag()
    keep = {
        "RandomSeed": nbt.LongTag, "GameType": nbt.IntTag, "Time": nbt.LongTag, "LastPlayed": nbt.LongTag,
        "rainTime": nbt.IntTag, "raining": nbt.ByteTag, "thunderTime": nbt.IntTag, "thundering": nbt.ByteTag,
        "hardcore": nbt.ByteTag, "allowCommands": nbt.ByteTag, "MapFeatures": nbt.ByteTag,
        "spawnBonusChest": nbt.ByteTag, "SizeOnDisk": nbt.LongTag, "hasBeenInCreative": nbt.ByteTag,
        "generatorVersion": nbt.IntTag, "Difficulty": nbt.ByteTag, "DayTime": nbt.LongTag,
    }
    for k, cls in keep.items():
        v = nbt.get(src, k)
        if v is not None and not isinstance(v, (dict, list)):
            try:
                lvl[k] = cls(int(v))
            except (TypeError, ValueError):
                pass
    wgs = nbt.get_tag(src, "WorldGenSettings")
    if "RandomSeed" not in lvl:
        lvl["RandomSeed"] = nbt.LongTag(int(nbt.get(wgs, "seed", 0) or 0) if wgs is not None else 0)
    gen = str(nbt.get(src, "generatorName", "default") or "default").lower()
    lvl["generatorName"] = nbt.StringTag(gen if gen in ("default", "flat", "largebiomes") else "default")
    lvl.setdefault("generatorVersion", nbt.IntTag(1))
    lvl["LevelName"] = nbt.StringTag(opt.world_name or info.name)
    sx, sy, sz = info.spawn
    t = mapper(OVERWORLD, sx >> 4, sz >> 4)
    if t is None:
        sx, sz = 0, 0
        sy = max(sy, 64)
    else:
        sx += (t[0] - (sx >> 4)) * 16
        sz += (t[1] - (sz >> 4)) * 16
    sy = min(max(sy, 1), 250)
    lvl["SpawnX"], lvl["SpawnY"], lvl["SpawnZ"] = nbt.IntTag(sx), nbt.IntTag(sy), nbt.IntTag(sz)
    lvl["version"] = nbt.IntTag(19132)
    lvl["initialized"] = nbt.ByteTag(1)
    lvl["newSeaLevel"] = nbt.ByteTag(1)
    lvl.setdefault("MapFeatures", nbt.ByteTag(1))
    lvl.setdefault("GameType", nbt.IntTag(0))
    if int(lvl["GameType"].py_data) not in (0, 1, 2):  # LCE has no Spectator
        lvl["GameType"] = nbt.IntTag(1)
    lvl.setdefault("Time", nbt.LongTag(0))
    lvl["hasStronghold"] = nbt.ByteTag(0)
    lvl["StrongholdX"] = lvl["StrongholdY"] = lvl["StrongholdZ"] = nbt.IntTag(0)
    lvl["hasStrongholdEndPortal"] = nbt.ByteTag(0)
    lvl["StrongholdEndPortalX"] = lvl["StrongholdEndPortalZ"] = nbt.IntTag(0)
    lvl["generatorOptions"] = nbt.StringTag(str(nbt.get(src, "generatorOptions", "") or ""))
    for moat in ("ClassicMoat", "SmallMoat", "MediumMoat"):
        lvl[moat] = nbt.ByteTag(0)
    lvl["XZSize"] = nbt.IntTag(opt.world_size)
    lvl["HellScale"] = nbt.IntTag(WORLD_SIZES.get(opt.world_size, ("", 3))[1])
    if "GameRules" in src:
        lvl["GameRules"] = nbt.copy(src["GameRules"])
    return lvl


def _default_thumbnail() -> bytes:
    import zlib as _z

    w = h = 64
    raw = b"".join(b"\x00" + bytes((106, 170, 100)) * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", _z.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", _z.compress(raw)) + chunk(b"IEND", b""))


# biome ids every LCE target knows (Java 1.7 - 1.12 ids); the 1.9+ End sub-biomes become the End
_BIOME_LUT = np.arange(256, dtype=np.uint8)
_BIOME_LUT[40:128] = 1
_BIOME_LUT[40:44] = 9
_BIOME_LUT[255] = 255       # "not computed yet": the game recalculates it


def _biomes_for(biomes, profile: str):
    if biomes is None:
        return None
    return _BIOME_LUT[biomes.astype(np.uint8)]

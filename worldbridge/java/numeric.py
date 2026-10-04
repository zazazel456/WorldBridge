"""Java Edition worlds that use numeric block ids.

* Alpha / Infdev (``c.X.Z.dat`` per chunk, base36 folders)   Infdev 0327 - Beta 1.2
* McRegion (``region/r.X.Z.mcr``)                              Beta 1.3 - 1.1
* Anvil numeric (``region/r.X.Z.mca``, Sections)               1.2.1 - 1.12.2

The writer of the Anvil flavour is also the hub that the Amulet based
Java 1.13+/Bedrock conversions start from or end in.
"""

from __future__ import annotations

import gzip
import os
import re
import time
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .. import blocks as blk
from .. import ids, items, nbt
from ..lce.chunk import array_to_nibbles, java128_to_yzx, nibbles_to_array, yzx_to_java128
from ..model import NETHER, OVERWORLD, THE_END, NumericChunk, Progress, WorldInfo, WorldSource
from ..entities import hanging_to_modern
from ..maps import capped_map_file, java_map_colors
from . import oldcontent
from .oldcontent import OldContent
from .region import ChunkIndex, JavaRegion, RegionWriter
from ..i18n import tr

_DIM_DIRS = {OVERWORLD: "", NETHER: "DIM-1", THE_END: "DIM1"}
_REGION_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.(mca|mcr)$")
_ALPHA_RE = re.compile(r"^c\.(-?[0-9a-z]+)\.(-?[0-9a-z]+)\.dat$")


def _b36(n: int) -> str:
    if n == 0:
        return "0"
    neg = n < 0
    n = abs(n)
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
    return "-" + s if neg else s


def detect_java_numeric(path: str) -> Optional[str]:
    """Return 'anvil' / 'mcregion' / 'alpha' when ``path`` is a numeric Java world."""
    if not os.path.isfile(os.path.join(path, "level.dat")):
        return None
    reg = os.path.join(path, "region")
    if os.path.isdir(reg):
        files = os.listdir(reg)
        mca = [f for f in files if f.endswith(".mca")]
        mcr = [f for f in files if f.endswith(".mcr")]
        if mca:
            # numeric only if chunks carry no block palette (<1.13): sniff real chunks
            verdict = _sniff_anvil(reg, mca)
            if verdict is not None:
                return "anvil" if verdict else None
            try:
                root = nbt.load(open(os.path.join(path, "level.dat"), "rb").read()).tag
                data = nbt.get_tag(root, "Data") or root
                dv = nbt.get(data, "DataVersion")
                if dv is not None and int(dv) >= 1444:  # 1.13 snapshots
                    return None
            except Exception:  # noqa: BLE001
                pass
            return "anvil"
        if mcr:
            return "mcregion"
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        if os.path.isdir(full) and re.fullmatch(r"-?[0-9a-z]{1,2}", entry):
            return "alpha"
    return None


def _sniff_anvil(reg_dir: str, files: List[str]) -> Optional[bool]:
    """True = numeric chunk found, False = palette (1.13+) chunk found, None = no chunk."""
    for fn in sorted(files, key=lambda f: os.path.getsize(os.path.join(reg_dir, f)), reverse=True)[:3]:
        try:
            r = JavaRegion(os.path.join(reg_dir, fn))
        except OSError:
            continue
        for lx, lz in r.chunks():
            raw = r.read(lx, lz)
            if raw is None:
                continue
            try:
                root = nbt.load(raw, compressed=False).tag
            except Exception:  # noqa: BLE001
                continue
            dv = nbt.get(root, "DataVersion")
            if dv is not None and int(dv) >= 1444:
                return False
            lvl = nbt.get_tag(root, "Level") or root
            for sec in nbt.get_tag(lvl, "Sections") or []:
                if "Blocks" in sec:
                    return True
                if "Palette" in sec or "block_states" in sec:
                    return False
            if "sections" in root:
                return False
    return None


class JavaNumericWorld(WorldSource):
    def __init__(self, path: str, progress: Optional[Progress] = None):
        self.path = path
        self.progress = progress
        self.kind = detect_java_numeric(path) or "anvil"
        self.info = self._read_info()
        self.max_height = 256 if self.kind == "anvil" else 128
        self._coords: Dict[int, object] = {}         # dim -> ChunkIndex (a dict for Alpha's chunk files)
        self._region_cache: Dict[str, JavaRegion] = {}

    def _read_info(self) -> WorldInfo:
        info = WorldInfo()
        root = nbt.load(open(os.path.join(self.path, "level.dat"), "rb").read()).tag
        info.level = nbt.get_tag(root, "Data") or root
        p = nbt.get_tag(info.level, "Player")
        if p is not None:
            info.players["host"] = p
        for folder in ("players",):
            d = os.path.join(self.path, folder)
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    if fn.endswith(".dat"):
                        try:
                            info.players.setdefault(fn[:-4], nbt.load(open(os.path.join(d, fn), "rb").read()).tag)
                        except Exception:  # noqa: BLE001
                            pass
        data_dir = os.path.join(self.path, "data")
        if os.path.isdir(data_dir):
            for fn in os.listdir(data_dir):
                if fn.startswith("map_") or fn == "idcounts.dat":
                    info.extra_files["data/" + fn] = open(os.path.join(data_dir, fn), "rb").read()
        icon = os.path.join(self.path, "icon.png")
        if os.path.exists(icon):
            info.thumbnail_png = open(icon, "rb").read()
        from ..detect import numeric_label

        info.source_description = numeric_label(self.kind, info.level)
        return info

    def _dim_dir(self, dim: int) -> str:
        return os.path.join(self.path, _DIM_DIRS[dim]) if _DIM_DIRS[dim] else self.path

    def dimensions(self) -> List[int]:
        return [d for d in (OVERWORLD, NETHER, THE_END) if self._scan(d)]

    def _scan(self, dim: int):
        if dim in self._coords:
            return self._coords[dim]
        out = {}                                        # Alpha: one file per chunk
        base = self._dim_dir(dim)
        if self.kind == "alpha":
            if os.path.isdir(base):
                for root, _dirs, files in os.walk(base):
                    if root != base and os.path.relpath(root, base).count(os.sep) > 1:
                        continue
                    for fn in files:
                        m = _ALPHA_RE.match(fn)
                        if m:
                            cx, cz = int(m.group(1), 36), int(m.group(2), 36)
                            out[(cx, cz)] = (os.path.join(root, fn), 0, 0)
        else:
            out = ChunkIndex()
            reg = os.path.join(base, "region")
            ext = "mca" if self.kind == "anvil" else "mcr"
            if os.path.isdir(reg):
                for fn in os.listdir(reg):
                    m = _REGION_RE.match(fn)
                    if not m or m.group(3) != ext:
                        continue
                    try:
                        out.add_region(int(m.group(1)), int(m.group(2)), os.path.join(reg, fn))
                    except OSError:
                        continue
        self._coords[dim] = out
        return out

    def chunk_coords(self, dim: int):
        return sorted(self._scan(dim).keys())

    def read_chunk(self, dim: int, cx: int, cz: int) -> Optional[NumericChunk]:
        entry = self._scan(dim).get((cx, cz))
        if entry is None:
            return None
        path, lx, lz = entry
        try:
            if self.kind == "alpha":
                raw = gzip.decompress(open(path, "rb").read())
            else:
                r = self._region_cache.get(path)
                if r is None:
                    if len(self._region_cache) > 8:
                        self._region_cache.clear()
                    r = self._region_cache[path] = JavaRegion(path)
                raw = r.read(lx, lz)
            if raw is None:
                return None
            root = nbt.load(raw, compressed=False).tag
            return java_chunk_to_numeric(root, cx, cz)
        except Exception as ex:  # noqa: BLE001
            if self.progress:
                self.progress.warn(tr("Java chunk {cx},{cz} unreadable, skipped: {error}", cx=cx, cz=cz, error=ex))
            return None


def _ba(tag, key) -> Optional[np.ndarray]:
    t = nbt.get_tag(tag, key)
    if t is None:
        return None
    return np.asarray(t.np_array).astype(np.uint8) if hasattr(t, "np_array") else np.asarray(t.py_data).astype(np.uint8)


def java_chunk_to_numeric(root: nbt.CompoundTag, cx: int, cz: int) -> Optional[NumericChunk]:
    lvl = nbt.get_tag(root, "Level") or root
    if "Sections" in lvl:
        c = NumericChunk(cx, cz, 256)
        c.sky_light = np.full((256, 16, 16), 15, np.uint8)
        c.block_light = np.zeros((256, 16, 16), np.uint8)
        for sec in nbt.get_tag(lvl, "Sections"):
            y = int(nbt.get(sec, "Y", 0))
            if y < 0 or y > 15:
                continue
            ys = slice(y * 16, y * 16 + 16)
            b = _ba(sec, "Blocks")
            if b is None:
                if "Palette" in sec or "block_states" in sec:
                    return None  # 1.13+ chunk, not numeric
                continue
            ids_ = b.astype(np.uint16)
            add = _ba(sec, "Add")
            if add is not None:
                ids_ |= nibbles_to_array(add.tobytes(), 4096).astype(np.uint16) << 8
            c.blocks[ys] = ids_.reshape(16, 16, 16)
            d = _ba(sec, "Data")
            if d is not None:
                c.data[ys] = nibbles_to_array(d.tobytes(), 4096).reshape(16, 16, 16)
            s = _ba(sec, "SkyLight")
            if s is not None and s.size >= 2048:
                c.sky_light[ys] = nibbles_to_array(s.tobytes(), 4096).reshape(16, 16, 16)
            bl = _ba(sec, "BlockLight")
            if bl is not None and bl.size >= 2048:
                c.block_light[ys] = nibbles_to_array(bl.tobytes(), 4096).reshape(16, 16, 16)
        bio = _ba(lvl, "Biomes")
        if bio is not None and bio.size >= 256:
            c.biomes = bio[:256].reshape(16, 16).copy()
    elif "Blocks" in lvl:
        b = _ba(lvl, "Blocks")
        h = 128 if b.size <= 32768 else 256
        c = NumericChunk(cx, cz, 128)
        c.blocks = java128_to_yzx(b[:32768]).astype(np.uint16)
        d = _ba(lvl, "Data")
        if d is not None and d.size >= 16384:
            c.data = java128_to_yzx(nibbles_to_array(d.tobytes(), 32768)).copy()
        s = _ba(lvl, "SkyLight")
        c.sky_light = java128_to_yzx(nibbles_to_array(s.tobytes(), 32768)).copy() if s is not None and s.size >= 16384 else None
        bl = _ba(lvl, "BlockLight")
        c.block_light = java128_to_yzx(nibbles_to_array(bl.tobytes(), 32768)).copy() if bl is not None and bl.size >= 16384 else None
        del h
    else:
        return None
    c.entities = list(nbt.get_tag(lvl, "Entities") or [])
    c.tile_entities = list(nbt.get_tag(lvl, "TileEntities") or [])
    c.tile_ticks = list(nbt.get_tag(lvl, "TileTicks") or [])
    c.last_update = int(nbt.get(lvl, "LastUpdate", 0) or 0)
    c.inhabited_time = int(nbt.get(lvl, "InhabitedTime", 0) or 0)
    c.terrain_populated = bool(nbt.get(lvl, "TerrainPopulated", 1))
    return c


# ======================================================================= writer


@dataclass
class JavaWriteOptions:
    kind: str = "anvil"  # anvil | mcregion | alpha
    version_limit: Optional[str] = None  # e.g. "1.8": replace newer blocks
    world_name: Optional[str] = None
    y_offset: int = 0
    keep_modern: bool = True  # (hub only) keep modern_blocks side info
    # players that already are Java 1.13+ data with a DataVersion up to this one stay as they are
    # (the game upgrades them from there) instead of being downgraded; 0 = none.  It must not
    # be newer than the data version the game upgrades them from (level.dat: the level's)
    player_dv: int = 0

    def old_version(self) -> Optional[str]:
        """The Java version whose content (items, mobs, block entities) the output is limited to."""
        if self.kind == "alpha":
            return self.version_limit or "b1.2"
        if self.kind == "mcregion":
            return self.version_limit or "1.0"
        return self.version_limit

    def legacy_layout(self) -> bool:
        """player / level.dat rebuilt from a whitelist (pre-1.9 games cast every field they read)."""
        v = self.old_version()
        return v is not None and blk.version_rank(v) < blk.version_rank("1.9")


class JavaNumericWriter:
    def __init__(self, out_dir: str, options: JavaWriteOptions, progress: Progress):
        self.out = out_dir
        self.opt = options
        self.progress = progress
        self.regions: Dict[Tuple[int, int, int], RegionWriter] = {}
        self.allowed = None
        old = options.old_version()
        self.old = OldContent(old) if old else None
        if old:
            self.allowed = blk.java_upto(old)
        self.replaced = 0
        self.modern: Dict[int, Dict[Tuple[int, int, int], str]] = {}
        self.waterlogged: Dict[int, List[Tuple[int, int, int]]] = {}
        os.makedirs(out_dir, exist_ok=True)
        self._region_count = 0
        self._read_back: Dict[str, JavaRegion] = {}      # regions on disk read by stored_biomes

    def _flush_regions(self, keep: int = 64):
        if len(self.regions) <= keep:
            return
        for key in list(self.regions.keys())[: len(self.regions) - keep // 2]:
            self._write_region(key, self.regions.pop(key))

    def _region_path(self, key) -> str:
        dim, rx, rz = key
        base = os.path.join(self.out, _DIM_DIRS[dim]) if _DIM_DIRS[dim] else self.out
        ext = "mca" if self.opt.kind == "anvil" else "mcr"
        return os.path.join(base, "region", f"r.{rx}.{rz}.{ext}")

    def stored_biomes(self, dim: int, cx: int, cz: int) -> Optional[np.ndarray]:
        """The biomes [z, x] of a chunk this writer already has (None: not written), read back from its
        region, in memory or already on disk (model.BiomeFiller)."""
        key = (dim, cx >> 5, cz >> 5)
        rw = self.regions.get(key)
        comp = rw.chunks.get((cx & 31, cz & 31)) if rw is not None else None
        if comp is not None:
            raw = zlib.decompress(comp)
        else:
            path = self._region_path(key)
            reg = self._read_back.get(path)
            if reg is None:
                if not os.path.exists(path):
                    return None
                if len(self._read_back) > 8:
                    self._read_back.clear()
                reg = self._read_back[path] = JavaRegion(path)
            raw = reg.read(cx & 31, cz & 31)
            if raw is None:
                return None
        root = nbt.load(raw, compressed=False).tag
        bio = _ba(nbt.get_tag(root, "Level") or root, "Biomes")
        return bio[:256].reshape(16, 16).copy() if bio is not None and bio.size >= 256 else None

    def _write_region(self, key, rw: RegionWriter):
        path = self._region_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._read_back.pop(path, None)
        if os.path.exists(path):  # region evicted earlier: merge
            old = JavaRegion(path)
            for lx, lz in old.chunks():
                if (lx, lz) not in rw.chunks:
                    raw = old.read(lx, lz)
                    if raw is not None:
                        rw.put(lx, lz, raw)
        rw.write(path)

    def add_chunk(self, dim: int, c: NumericChunk, shift: bool = True):
        """shift=False: the chunk is already at the target's heights (e.g. generated terrain)."""
        self.store(self.encode(dim, c, shift))

    def encode(self, dim: int, c: NumericChunk, shift: bool = True):
        """The chunk as it goes into its region (None: not written).  Changes nothing in the writer
        (the Alpha format's own file aside), so it can run in a worker process (parallel.py);
        ``store`` keeps the result."""
        if dim == THE_END and self.old is not None and self.old.r < blk.version_rank("1.0"):
            return None  # the End arrived with 1.0
        if self.opt.y_offset and shift:
            _shift_chunk_y(c, self.opt.y_offset)
        height = 256 if self.opt.kind == "anvil" else 128
        if c.height != height:
            c.resize(height)
        modern = wl = None
        if c.modern_blocks and self.opt.keep_modern:
            base_x, base_z = c.cx * 16, c.cz * 16
            modern = {(base_x + x, y, base_z + z): st for (x, y, z), st in c.modern_blocks.items()}
        if c.waterlogged is not None and self.opt.keep_modern:
            ys, zs, xs = np.nonzero(c.waterlogged)
            wl = [(c.cx * 16 + x, y, c.cz * 16 + z) for y, z, x in zip(ys.tolist(), zs.tolist(), xs.tolist())]
        blocks, data = c.blocks, c.data
        n = 0
        if self.allowed is not None:
            blocks, data, n = blk.downgrade(blocks, data, self.allowed)
        else:
            over = blocks > 255
            if over.any():  # unknown to Java numeric ids (e.g. LCE aquatic without fallback)
                blocks = np.where(over, 1, blocks)
        old = self.old
        before = (old.dropped_items, old.dropped_entities, old.dropped_tiles) if old is not None else None
        comp = None
        if self.opt.kind == "alpha":
            self._write_alpha(dim, c, blocks, data)
        else:
            comp = zlib.compress(nbt.dump(self._chunk_nbt(c, blocks, data), ""), 6)
        dropped = None
        if old is not None:
            dropped = (old.dropped_items - before[0], old.dropped_entities - before[1], old.dropped_tiles - before[2])
            old.dropped_items, old.dropped_entities, old.dropped_tiles = before
        return dim, c.cx, c.cz, comp, n, modern, wl, dropped

    def store(self, rec) -> None:
        """Keeps a chunk made by ``encode`` (in this process, in the conversion's order)."""
        if rec is None:
            return
        dim, cx, cz, comp, n, modern, wl, dropped = rec
        if modern:
            self.modern.setdefault(dim, {}).update(modern)
        if wl is not None:
            self.waterlogged.setdefault(dim, []).extend(wl)
        self.replaced += n
        if dropped is not None:
            self.old.dropped_items += dropped[0]
            self.old.dropped_entities += dropped[1]
            self.old.dropped_tiles += dropped[2]
        if comp is None:
            return
        key = (dim, cx >> 5, cz >> 5)
        rw = self.regions.get(key)
        if rw is None:
            rw = self.regions[key] = RegionWriter()
            self._flush_regions()
        rw.put_compressed(cx & 31, cz & 31, comp)

    def _common_level(self, c: NumericChunk, blocks: np.ndarray) -> nbt.CompoundTag:
        lvl = nbt.CompoundTag()
        lvl["xPos"] = nbt.IntTag(c.cx)
        lvl["zPos"] = nbt.IntTag(c.cz)
        lvl["LastUpdate"] = nbt.LongTag(int(c.last_update or 0))
        lvl["TerrainPopulated"] = nbt.ByteTag(1 if c.terrain_populated else 0)
        if self.old is None:  # a 1.12.2 world: item ids by name (see items.named_item)
            lvl["Entities"] = nbt.compound_list(_legacy_entities(c.entities, named=True))
            lvl["TileEntities"] = nbt.compound_list(_legacy_tiles(c.tile_entities, named=True))
            if c.tile_ticks:
                lvl["TileTicks"] = nbt.compound_list(c.tile_ticks)
            return lvl
        from ..lce.world import sanitize_tiles

        old = self.old
        ents = (old.entity(e) for e in _legacy_entities(c.entities))
        lvl["Entities"] = nbt.compound_list(e for e in ents if e is not None)
        tiles = sanitize_tiles(c.tile_entities, blocks, 0, 0, allowed_ids=old.tile_ids)
        tiles = [t for t in (old.tile(t) for t in tiles) if t is not None]
        old.dropped_tiles += len(c.tile_entities) - len(tiles)
        lvl["TileEntities"] = nbt.compound_list(tiles)
        # scheduled ticks are dropped: they name blocks by id and are recreated by the game
        return lvl

    def _chunk_nbt(self, c: NumericChunk, blocks: np.ndarray, data: np.ndarray) -> nbt.CompoundTag:
        lvl = self._common_level(c, blocks)
        sky = c.sky_light if c.sky_light is not None else c.compute_sky_light()
        bl = c.block_light if c.block_light is not None else c.compute_block_light()
        hm = c.heightmap()
        if self.opt.kind == "anvil":
            lvl["LightPopulated"] = nbt.ByteTag(1)
            lvl["InhabitedTime"] = nbt.LongTag(c.inhabited_time)
            lvl["HeightMap"] = nbt.IntArrayTag(hm.reshape(-1).astype(np.int32))
            bio = c.biomes if c.biomes is not None else np.ones((16, 16), np.uint8)
            lvl["Biomes"] = nbt.ByteArrayTag(bio.astype(np.uint8).reshape(-1).view(np.int8))
            secs = nbt.ListTag([], 10)
            for sy in range(16):
                ys = slice(sy * 16, sy * 16 + 16)
                sb = blocks[ys]
                if not sb.any():
                    continue
                sec = nbt.CompoundTag()
                sec["Y"] = nbt.ByteTag(sy)
                flat = sb.reshape(-1)
                sec["Blocks"] = nbt.ByteArrayTag((flat & 0xFF).astype(np.uint8).view(np.int8))
                if (flat > 255).any():
                    sec["Add"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles((flat >> 8) & 15), np.int8))
                sec["Data"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles(data[ys].reshape(-1)), np.int8))
                sec["SkyLight"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles(sky[ys].reshape(-1)), np.int8))
                sec["BlockLight"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles(bl[ys].reshape(-1)), np.int8))
                secs.append(sec)
            lvl["Sections"] = secs
        else:
            lvl["Blocks"] = nbt.ByteArrayTag(yzx_to_java128(np.clip(blocks, 0, 255).astype(np.uint8)).view(np.int8))
            lvl["Data"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles(yzx_to_java128(data)), np.int8))
            lvl["SkyLight"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles(yzx_to_java128(sky)), np.int8))
            lvl["BlockLight"] = nbt.ByteArrayTag(np.frombuffer(array_to_nibbles(yzx_to_java128(bl)), np.int8))
            lvl["HeightMap"] = nbt.ByteArrayTag(np.minimum(hm, 127).astype(np.uint8).reshape(-1).view(np.int8))
        return nbt.CompoundTag({"Level": lvl})

    def _write_alpha(self, dim: int, c: NumericChunk, blocks, data):
        root = self._chunk_nbt(c, blocks, data)
        base = os.path.join(self.out, _DIM_DIRS[dim]) if _DIM_DIRS[dim] else self.out
        folder = os.path.join(base, _b36(c.cx % 64), _b36(c.cz % 64))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"c.{_b36(c.cx)}.{_b36(c.cz)}.dat"), "wb") as f:
            f.write(nbt.dump(root, "", compressed=True))

    def finish(self, info: WorldInfo) -> str:
        for key, rw in self.regions.items():
            self._write_region(key, rw)
        self.regions.clear()
        size = oldcontent.size_on_disk(self.out) if self.opt.legacy_layout() else 0
        data = build_java_level(info, self.opt, size_on_disk=size)
        with open(os.path.join(self.out, "level.dat"), "wb") as f:
            f.write(nbt.dump(nbt.CompoundTag({"Data": data}), "", compressed=True))
        n_players = write_java_players(self.out, info, self.opt)
        if n_players:
            self.progress.log(tr("Players: {n} playerdata files written.", n=n_players))
        if info.thumbnail_png:
            with open(os.path.join(self.out, "icon.png"), "wb") as f:
                f.write(info.thumbnail_png)
        data_dir = os.path.join(self.out, "data")
        max_base = java_map_colors(self.opt.old_version())  # colour ids the target registers
        for name, blob in info.extra_files.items():
            if name.startswith("data/map_") or name == "data/idcounts.dat":
                if name.startswith("data/map_"):
                    blob = capped_map_file(blob, max_base)
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(self.out, name), "wb") as f:
                    f.write(blob)
        if self.replaced:
            self.progress.warn(tr("{n} blocks that do not exist in the target version were replaced.", n=self.replaced))
        if self.old is not None:
            o = self.old
            if o.dropped_items or o.dropped_entities or o.dropped_tiles:
                self.progress.warn(tr("Content that does not exist in {version}: removed {items} items, {entities} "
                                      "entities and {tiles} block entities.", version=o.label, items=o.dropped_items,
                                      entities=o.dropped_entities, tiles=o.dropped_tiles))
        with open(os.path.join(self.out, "session.lock"), "wb") as f:
            f.write(int(time.time() * 1000).to_bytes(8, "big"))
        return self.out


def _shift_chunk_y(c: NumericChunk, dy: int):
    def sh(arr, fill=0):
        if arr is None:
            return None
        out = np.full_like(arr, fill)
        if dy > 0:
            out[dy:] = arr[: arr.shape[0] - dy]
        else:
            out[: arr.shape[0] + dy] = arr[-dy:]
        return out

    c.blocks = sh(c.blocks)
    c.data = sh(c.data)
    if dy > 0 and c.blocks.any():
        c.blocks[:dy] = 7  # bedrock under a raised world
    elif dy < 0:
        c.blocks[0] = np.where(c.blocks[: -dy + 1].any(axis=0), 7, c.blocks[0])  # the floor of a lowered world
    c.sky_light = c.block_light = None  # recomputed from the moved blocks
    c.waterlogged = sh(c.waterlogged, False)
    c.modern_blocks = {(x, y + dy, z): s for (x, y, z), s in c.modern_blocks.items() if 0 <= y + dy < c.height}
    for t in list(c.tile_entities) + list(c.tile_ticks):
        if "y" in t:
            t["y"] = nbt.IntTag(int(t["y"].py_data) + dy)
    for e in c.entities:
        pos = nbt.get_tag(e, "Pos")
        if pos is not None and len(pos) == 3:
            e["Pos"] = nbt.ListTag([pos[0], nbt.DoubleTag(float(pos[1].py_data) + dy), pos[2]], 6)
        if "TileY" in e:                                              # paintings, item frames
            e["TileY"] = nbt.IntTag(int(nbt.get(e, "TileY")) + dy)


def _legacy_entities(ents, named: bool = False):
    from ..lce.world import legacy_entity

    out = []
    for e in ents:
        le = legacy_entity(e)
        if le is not None:
            if named:
                _name_entity_items(le)
            out.append(java_entity_nbt(le))
    return out


def _name_entity_items(e: nbt.CompoundTag) -> None:
    for key in ("Inventory", "Items", "Equipment", "ArmorItems", "HandItems"):
        lst = nbt.get_tag(e, key)
        if isinstance(lst, nbt.ListTag) and len(lst):
            e[key] = items.named_items(lst)
    if "Item" in e:
        e["Item"] = items.named_item(e["Item"])
    sub = nbt.get_tag(e, "Riding")
    if isinstance(sub, nbt.CompoundTag):
        _name_entity_items(sub)


# Legacy Console Edition stores a few entity fields differently from Java.  Minecraft's
# DataFixer throws on them, and a chunk whose upgrade throws is discarded and regenerated.
_LCE_UUID_RE = re.compile(r"^(?:ent)?([0-9a-fA-F]{32})$")
# LCE eATTRIBUTE_ID order (same as Java's SharedMonsterAttributes registration order)
_LCE_ATTRIBUTE_NAMES = {
    0: "generic.maxHealth",
    1: "generic.followRange",
    2: "generic.knockbackResistance",
    3: "generic.movementSpeed",
    4: "generic.attackDamage",
    5: "horse.jumpStrength",
    6: "zombie.spawnReinforcements",
}


def _signed64(v: int) -> int:
    return v - (1 << 64) if v >= 1 << 63 else v


def java_entity_nbt(e: nbt.CompoundTag) -> nbt.CompoundTag:
    """Rewrite LCE specific entity fields into their Java 1.12 form (in place)."""
    uid = nbt.get_tag(e, "UUID")
    if isinstance(uid, nbt.StringTag):
        del e["UUID"]
        m = _LCE_UUID_RE.match(uid.py_data)
        if m and "UUIDMost" not in e:
            v = int(m.group(1), 16)
            e["UUIDMost"] = nbt.LongTag(_signed64(v >> 64))
            e["UUIDLeast"] = nbt.LongTag(_signed64(v & ((1 << 64) - 1)))
    # tameable mobs / horses: LCE writes "" for "no owner" (Java: absent).  A player name
    # is kept - Minecraft resolves owner names to UUIDs when the mob is loaded.
    for key in ("Owner", "OwnerName", "OwnerUUID"):
        owner = nbt.get_tag(e, key)
        if isinstance(owner, nbt.StringTag):
            m = _LCE_UUID_RE.match(owner.py_data)
            if not owner.py_data.strip():
                del e[key]
            elif m:
                del e[key]
                h = m.group(1).lower()
                e["OwnerUUID"] = nbt.StringTag(f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}")
    attrs = nbt.get_tag(e, "Attributes")
    if isinstance(attrs, nbt.ListTag) and len(attrs):
        fixed = nbt.ListTag([], 10)
        for a in attrs:
            if not isinstance(a, nbt.CompoundTag):
                continue
            if "Name" not in a:
                name = _LCE_ATTRIBUTE_NAMES.get(int(nbt.get(a, "ID", -1)))
                if name is None:
                    continue
                a = nbt.CompoundTag({"Name": nbt.StringTag(name), "Base": a.get("Base", nbt.DoubleTag(0.0))})
            fixed.append(a)
        e["Attributes"] = fixed
    hanging_to_modern(e)  # LCE / Java <= 1.7 paintings: wall block + Direction -> Java 1.8+ layout
    for key in ("Riding",):
        sub = nbt.get_tag(e, key)
        if isinstance(sub, nbt.CompoundTag):
            java_entity_nbt(sub)
    return e


def _legacy_tiles(tiles, named: bool = False):
    from ..lce.world import legacy_items

    out = []
    for t in tiles:
        tid = ids.tile_to_old(nbt.get(t, "id", ""))
        if tid is None:
            continue
        t = nbt.copy(t)
        t["id"] = nbt.StringTag(tid)
        if "Items" in t:
            t["Items"] = legacy_items(t["Items"])
            if named:
                t["Items"] = items.named_items(t["Items"])
        out.append(t)
    return out


def java_player_nbt(player: nbt.CompoundTag, opt: JavaWriteOptions) -> nbt.CompoundTag:
    """A source player in the form written to level.dat / playerdata."""
    p = nbt.copy(player)
    dv = int(nbt.get(p, "DataVersion", 0) or 0)
    if 1451 <= dv <= opt.player_dv:
        # already a Java 1.13+ player (Java or Bedrock source): keep it untouched, the game
        # upgrades it from its own DataVersion
        return p
    from ..lce.world import legacy_items

    # the player is written in the legacy layout (numeric item ids): a DataVersion carried
    # over from the source (LCE Aquatic stores 922) would make Minecraft skip the item-id
    # fixes and drop every item it cannot read
    p.pop("DataVersion", None)
    if "equipment" in p:  # Java 1.21.5+: armour and off hand back into the inventory's slots
        p["Inventory"] = items.player_stacks(p)
        del p["equipment"]
    for key in ("Inventory", "EnderItems"):
        if key in p:
            p[key] = legacy_items(p[key], dv >= 1451)
            if not opt.legacy_layout():
                # read by Java 1.9+: numeric ids the game's ItemIdFix does not know (cooked
                # mutton 424, banners, shields, elytra...) would become air
                p[key] = items.named_items(p[key])
    if isinstance(nbt.get_tag(p, "Dimension"), nbt.StringTag):
        p["Dimension"] = nbt.IntTag({"minecraft:the_nether": -1, "minecraft:the_end": 1}.get(nbt.get(p, "Dimension"), 0))
    if opt.y_offset and "Pos" in p and len(p["Pos"]) == 3:
        pos = p["Pos"]
        p["Pos"] = nbt.ListTag([pos[0], nbt.DoubleTag(float(pos[1].py_data) + opt.y_offset), pos[2]], 6)
    return java_entity_nbt(p)


def old_player_nbt(player: nbt.CompoundTag, opt: JavaWriteOptions) -> nbt.CompoundTag:
    """The player for a pre-1.9 game: only the fields that version reads, with its NBT types."""
    oc = OldContent(opt.old_version())
    return oc.player(java_player_nbt(player, opt))


def write_java_players(out_dir: str, info: WorldInfo, opt: JavaWriteOptions, folder: str = "playerdata") -> int:
    """playerdata/<uuid>.dat for the players linked to a nickname in the "Giocatori" tab
    (players/<nickname>.dat before Java 1.8, when player files were still named after the player)."""
    from ..selection import write_java_playerdata

    if opt.legacy_layout() and blk.version_rank(opt.old_version()) < blk.version_rank("1.8"):
        n = 0
        links = getattr(info, "player_links", None) or {}
        for key, p in info.players.items():
            ln = links.get(key)
            if ln is None or not getattr(ln, "nickname", None):
                continue
            folder = os.path.join(out_dir, "players")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f"{ln.nickname}.dat"), "wb") as f:
                f.write(nbt.dump(nbt.CompoundTag(old_player_nbt(p, opt)), "", compressed=True))
            n += 1
        return n
    if opt.legacy_layout():
        return write_java_playerdata(out_dir, info, lambda p: old_player_nbt(p, opt))
    return write_java_playerdata(out_dir, info, lambda p: java_player_nbt(p, opt), folder)


def generator_name(level) -> str:
    """The world type an old Java level.dat gets from the source's level (default, flat,
    largeBiomes, amplified, customized)."""
    gen = nbt.get(level, "generatorName", None)
    wgs = nbt.get_tag(level, "WorldGenSettings")
    if gen is None and wgs is not None:  # 1.16+: the preset is in WorldGenSettings
        ow = nbt.get_tag(nbt.get_tag(wgs, "dimensions") or nbt.CompoundTag(), "minecraft:overworld")
        g = nbt.get_tag(ow, "generator") if ow is not None else None
        preset = nbt.get(g, "settings") if g is not None else None
        kind = str(nbt.get(g, "type", "") or "") if g is not None else ""
        gen = ("flat" if kind.endswith("flat") else
               {"minecraft:amplified": "amplified", "minecraft:large_biomes": "largeBiomes"}.get(str(preset), "default"))
    gen = str(gen or "default")
    if gen.lower() == "largebiomes":
        return "largeBiomes"
    return gen.lower() if gen.lower() in ("default", "flat", "amplified", "customized") else "default"


def build_java_level(info: WorldInfo, opt: JavaWriteOptions, size_on_disk: int = 0) -> nbt.CompoundTag:
    src = info.level
    if opt.legacy_layout():
        player = None
        if info.players:
            key = next(iter(info.players))
            player = old_player_nbt(info.players[key], opt)
            ln = info.player_links.get(key)
            if ln is not None and getattr(ln, "uuid", None) and blk.version_rank(opt.old_version()) >= blk.version_rank("1.8"):
                from ..selection import set_player_uuid

                set_player_uuid(player, ln.uuid)
        return OldContent(opt.old_version()).level(src, opt.world_name or info.name, player, size_on_disk,
                                                   y_offset=opt.y_offset)
    out = nbt.CompoundTag()
    for key in ("RandomSeed", "generatorName", "generatorVersion", "generatorOptions", "GameType", "SpawnX",
                "SpawnY", "SpawnZ", "Time", "DayTime", "LastPlayed", "rainTime", "raining", "thunderTime",
                "thundering", "hardcore", "allowCommands", "MapFeatures", "initialized", "Difficulty",
                "DifficultyLocked", "GameRules", "clearWeatherTime", "SizeOnDisk"):
        t = nbt.get_tag(src, key)
        if t is not None:
            out[key] = nbt.copy(t) if isinstance(t, nbt.CompoundTag) else t
    wgs = nbt.get_tag(src, "WorldGenSettings")
    if "RandomSeed" not in out and wgs is not None and "seed" in wgs:
        out["RandomSeed"] = nbt.LongTag(int(nbt.get(wgs, "seed")))
    out["generatorName"] = nbt.StringTag(generator_name(src))
    out["LevelName"] = nbt.StringTag(opt.world_name or info.name)
    if "DayTime" not in out and "Time" in out:
        out["DayTime"] = nbt.LongTag(int(out["Time"].py_data) % 24000)
    out.setdefault("GameType", nbt.IntTag(0))
    if not all(k in out for k in ("SpawnX", "SpawnY", "SpawnZ")):  # Java 1.21.9+: spawn: {pos: [I; x, y, z]}
        for k, v in zip(("SpawnX", "SpawnY", "SpawnZ"), oldcontent.level_spawn(src)):
            out[k] = nbt.IntTag(v)
    out.setdefault("LastPlayed", nbt.LongTag(int(time.time() * 1000)))
    out["initialized"] = nbt.ByteTag(1)
    if opt.y_offset:
        out["SpawnY"] = nbt.IntTag(int(out["SpawnY"].py_data) + opt.y_offset)
    if opt.kind == "anvil":
        out["version"] = nbt.IntTag(19133)
    elif opt.kind == "mcregion":
        out["version"] = nbt.IntTag(19132)
    if info.players:
        key = next(iter(info.players))
        p = java_player_nbt(info.players[key], opt)
        ln = info.player_links.get(key)
        if ln is not None and getattr(ln, "uuid", None):
            from ..selection import set_player_uuid

            set_player_uuid(p, ln.uuid)  # singleplayer data file = playerdata/<uuid>.dat (written as well)
        out["Player"] = p
    return out

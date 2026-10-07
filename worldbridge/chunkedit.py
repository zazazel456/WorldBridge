"""Chunk edits made on a world itself, without converting it (map tab, "Modifica il mondo"):
chunks removed (world trim, "cancella i selezionati", "tieni solo i selezionati") and chunks
given a biome.

Java (every region format with biomes: Anvil 1.2+, also 1.18+ and 26.x), Legacy Console Edition
(every platform and chunk format) and Bedrock (through Amulet).  Before anything is written, a copy
of every file that changes goes into ``<world>.wb-backup-<date>/`` next to the world, so an edit can
always be undone by copying the files back.  The world must not be open in the game meanwhile.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from . import biomes as bio
from . import gameversion as gv
from . import nbt
from .model import NETHER, OVERWORLD, THE_END, ConversionError, Progress
from .i18n import tr

Chunk = Tuple[int, int]
SECTOR = 4096
_REGION = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mc[ar]$")


@dataclass
class EditResult:
    removed: int = 0
    painted: int = 0
    skipped: int = 0                  # chunks whose format has no place for that biome
    backup: str = ""
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.removed:
            parts.append(tr("{n} chunks deleted", n=self.removed))
        if self.painted:
            parts.append(tr("{n} chunks with the new biome", n=self.painted))
        if self.skipped:
            parts.append(tr("{n} chunks left as they were (their format does not have that biome)", n=self.skipped))
        text = ", ".join(parts) or tr("no chunk changed")
        if self.backup:
            text += tr(". Backup of the changed files: {path}", path=self.backup)
        return text


# ------------------------------------------------------------------ which game the world is
def world_game(path: str) -> Tuple[str, Optional[Tuple[int, ...]]]:
    """(family, version) of a world, to know its biomes: "java" / "lce" / "bedrock" / "pe_old"."""
    from . import detect as det

    try:
        d = det.detect(path)
    except ConversionError:
        return "", None
    if d is None:
        return "", None
    if d.kind == "lce":
        return "lce", None
    if d.kind == "pe_old":
        return "pe_old", None
    if d.kind == "java_numeric":
        return "java", (1, 12) if d.subkind == "anvil" else (1, 1)
    if d.kind == "java_modern":
        return "java", _java_version(d.path)
    if d.kind == "bedrock":
        try:
            from .amulet_bridge import load_format_version

            return "bedrock", gv.bedrock(load_format_version(d.path))
        except Exception:  # noqa: BLE001
            return "bedrock", None
    return "", None


# only when PyMCTranslate cannot say (it knows every release's DataVersion)
_DATA_VERSIONS = ((5020, (26, 3)), (4901, (26, 2)), (4783, (26, 1)), (4189, (1, 21, 4)), (3463, (1, 20)),
                  (3105, (1, 19)), (2860, (1, 18)), (2724, (1, 17)), (2566, (1, 16)), (2225, (1, 15)), (1952, (1, 14)), (1451, (1, 13)))


def _java_version(world: str) -> Tuple[int, ...]:
    """From the chunks' DataVersion (the level.dat may be older: worlds WorldBridge writes for the
    game to upgrade, or not yet opened in the new version)."""
    from .java.modern import _folder
    from .java.region import JavaRegion

    dv = 0
    folder = _folder(world, OVERWORLD, "region")
    for fn in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not _REGION.match(fn) or os.path.getsize(os.path.join(folder, fn)) < 2 * SECTOR:
            continue
        reg = JavaRegion(os.path.join(folder, fn))
        for lx, lz in reg.chunks():
            raw = reg.read(lx, lz)
            if raw:
                dv = max(dv, int(nbt.get(nbt.load(raw, compressed=False).tag, "DataVersion", 0) or 0))
                break
        if dv:
            break
    if not dv:
        try:
            root = nbt.load(open(os.path.join(world, "level.dat"), "rb").read()).tag
            dv = int(nbt.get(nbt.get_tag(root, "Data") or root, "DataVersion", 0) or 0)
        except Exception:  # noqa: BLE001
            dv = 0
    return gv.java_from_data_version(dv) or next((v for n, v in _DATA_VERSIONS if dv >= n), (1, 12))


# ------------------------------------------------------------------ backup
class _Backup:
    def __init__(self, world_dir: str):
        self.world = os.path.abspath(world_dir)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = f"{self.world.rstrip(os.sep)}.wb-backup-{stamp}"
        self.saved: Set[str] = set()

    def save(self, path: str) -> None:
        path = os.path.abspath(path)
        if path in self.saved or not os.path.exists(path):
            return
        rel = os.path.relpath(path, self.world)
        dest = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.isdir(path):
            shutil.copytree(path, dest)
        else:
            shutil.copy2(path, dest)
        self.saved.add(path)

    @property
    def used(self) -> str:
        return self.dir if self.saved else ""


# ------------------------------------------------------------------ entry point
def edit_world(path: str, remove: Optional[Dict[int, Set[Chunk]]] = None,
               paint: Optional[Dict[int, Dict[Chunk, int]]] = None,
               progress: Optional[Progress] = None) -> EditResult:
    """Removes the chunks of ``remove`` and gives the chunks of ``paint`` their biome (an id of
    worldbridge.biomes), in the world at ``path`` itself."""
    from . import detect as det

    progress = progress or Progress()
    remove = {d: set(v) for d, v in (remove or {}).items() if v}
    paint = {d: dict(v) for d, v in (paint or {}).items() if v}
    for d, cs in remove.items():                       # a removed chunk is not painted
        if d in paint:
            paint[d] = {c: b for c, b in paint[d].items() if c not in cs}
    d = det.detect(path)
    if d is None:
        raise ConversionError(tr("World format not recognised."))
    if d.kind in ("java_modern", "java_numeric"):
        if d.kind == "java_numeric" and d.subkind == "alpha":
            raise ConversionError(tr("Alpha worlds (one file per chunk) cannot be edited here: convert them first."))
        return _edit_java(d.path, remove, paint, progress)
    if d.kind == "lce":
        return _edit_lce(d.path, remove, paint, progress)
    if d.kind == "bedrock":
        return _edit_bedrock(d.path, remove, paint, progress)
    raise ConversionError(tr("Chunk editing not available for {world}.", world=d.description))


# ------------------------------------------------------------------ Java
def _rewrite_region(path: str, drop: Set[Chunk], edit: Dict[Chunk, Callable[[bytes], Optional[bytes]]],
                    backup: _Backup) -> Tuple[int, int, int]:
    """Rewrites a Java region file without the ``drop`` chunks and with ``edit`` applied to the
    NBT of others (the untouched chunks are copied byte for byte).  Returns (removed, edited, skipped)."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 2 * SECTOR:
        return 0, 0, 0
    offsets = struct.unpack_from(">1024I", data, 0)
    stamps = struct.unpack_from(">1024I", data, SECTOR)
    m = _REGION.match(os.path.basename(path))
    rx, rz = int(m.group(1)), int(m.group(2))
    folder = os.path.dirname(path)
    present = {(i % 32, i // 32) for i, off in enumerate(offsets) if off}
    if not (present & drop) and not (present & edit.keys()):
        return 0, 0, 0
    backup.save(path)
    new_off = [0] * 1024
    new_stamp = [0] * 1024
    body = bytearray()
    sector = 2
    removed = edited = skipped = 0
    now = int(time.time())
    for i, off in enumerate(offsets):
        if not off:
            continue
        lx, lz = i % 32, i // 32
        start = (off >> 8) * SECTOR
        if start + 5 > len(data):
            continue
        length, ctype = struct.unpack_from(">IB", data, start)
        mcc = os.path.join(folder, f"c.{rx * 32 + lx}.{rz * 32 + lz}.mcc")
        if (lx, lz) in drop:
            removed += 1
            if ctype & 0x80 and os.path.exists(mcc):
                backup.save(mcc)
                os.remove(mcc)
            continue
        blob = data[start:start + 4 + length] if not ctype & 0x80 else data[start:start + 5]
        stamp = stamps[i]
        fn = edit.get((lx, lz))
        if fn is not None:
            from .java.region import JavaRegion

            raw = JavaRegion(path).read(lx, lz)
            new = fn(raw) if raw is not None else None
            if new is None:
                skipped += 1
            else:
                comp = zlib.compress(new, 6)
                if ctype & 0x80 and os.path.exists(mcc):
                    backup.save(mcc)
                if len(comp) + 5 > 255 * SECTOR:          # too big for the region: external file
                    with open(mcc, "wb") as f:
                        f.write(comp)
                    blob = struct.pack(">IB", 1, 0x82)
                else:
                    if ctype & 0x80 and os.path.exists(mcc):
                        os.remove(mcc)
                    blob = struct.pack(">IB", len(comp) + 1, 2) + comp
                stamp = now
                edited += 1
        count = max(1, (len(blob) + SECTOR - 1) // SECTOR)
        body += blob + b"\x00" * (count * SECTOR - len(blob))
        new_off[i] = (sector << 8) | count
        new_stamp[i] = stamp
        sector += count
    if not any(new_off):
        os.remove(path)
        return removed, edited, skipped
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(struct.pack(">1024I", *new_off))
        f.write(struct.pack(">1024I", *new_stamp))
        f.write(body)
    os.replace(tmp, path)
    return removed, edited, skipped


def java_paint(raw: bytes, bid: int) -> Optional[bytes]:
    """A Java chunk (its NBT) with every biome of it set to ``bid``; None when its format cannot
    hold that biome (a 1.18+ one in an older chunk, or McRegion, which stores no biomes)."""
    named = nbt.load(raw, compressed=False)
    root = named.tag
    lvl = nbt.get_tag(root, "Level")
    lvl = lvl if isinstance(lvl, nbt.CompoundTag) else root
    secs = nbt.get_tag(root, "sections")
    if secs is None:
        secs = nbt.get_tag(lvl, "Sections")
    paletted = [s for s in (secs or []) if isinstance(nbt.get_tag(s, "biomes"), nbt.CompoundTag)]
    if paletted:                                              # 1.18+
        name = nbt.StringTag("minecraft:" + bio.modern_name(bid))
        for s in paletted:
            s["biomes"] = nbt.CompoundTag({"palette": nbt.ListTag([name], 8)})
    else:
        old = nbt.get_tag(lvl, "Biomes")
        if isinstance(old, nbt.IntArrayTag) and bid < 1000:  # 1.13 - 1.17
            lvl["Biomes"] = nbt.IntArrayTag(np.full(len(old), bid, np.int32))
        elif bid in bio.JAVA_19 and bid < 256 and (isinstance(old, nbt.ByteArrayTag) or
                                                   "DataVersion" not in root and "Sections" in lvl):
            lvl["Biomes"] = nbt.ByteArrayTag(np.full(256, bid, np.uint8).astype(np.int8))   # 1.2 - 1.12
        else:
            return None
    return nbt.dump(root, named.name)


def _edit_java(world: str, remove, paint, progress: Progress) -> EditResult:
    from .java.modern import _folder

    res = EditResult()
    backup = _Backup(world)
    jobs = []
    for dim in (OVERWORLD, NETHER, THE_END):
        drop = remove.get(dim, set())
        pdim = paint.get(dim, {})
        if not drop and not pdim:
            continue
        for sub in ("region", "entities", "poi"):
            folder = _folder(world, dim, sub)
            if not os.path.isdir(folder):
                continue
            for fn in sorted(os.listdir(folder)):
                m = _REGION.match(fn)
                if not m:
                    continue
                rx, rz = int(m.group(1)), int(m.group(2))
                local_drop = {(cx - rx * 32, cz - rz * 32) for cx, cz in drop if cx >> 5 == rx and cz >> 5 == rz}
                local_edit = {}
                if sub == "region":
                    for (cx, cz), b in pdim.items():
                        if cx >> 5 == rx and cz >> 5 == rz:
                            local_edit[(cx - rx * 32, cz - rz * 32)] = (lambda raw, b=b: java_paint(raw, b))
                if local_drop or local_edit:
                    jobs.append((os.path.join(folder, fn), local_drop, local_edit, sub))
    for i, (p, drop, edit, sub) in enumerate(jobs):
        progress.check()
        r, e, s = _rewrite_region(p, drop, edit, backup)
        if sub == "region":
            res.removed += r
            res.painted += e
            res.skipped += s
        progress.update((i + 1) / max(1, len(jobs)), f"Regione {i + 1}/{len(jobs)}")
    res.backup = backup.used
    return res


# ------------------------------------------------------------------ Legacy Console Edition
def lce_paint(payload: bytes, bid: int) -> bytes:
    """A decompressed LCE chunk with its 256 biome bytes set to ``bid`` (the rest untouched)."""
    from .lce import chunk as lch

    c = lch.decode_chunk(payload)
    if c.biome_at is not None:
        return payload[:c.biome_at] + bytes([bid]) * 256 + payload[c.biome_at + 256:]
    named = nbt.load(payload, compressed=False)                 # old NBT chunks
    lvl = nbt.get_tag(named.tag, "Level") or named.tag
    lvl["Biomes"] = nbt.ByteArrayTag(np.full(256, bid, np.uint8).astype(np.int8))
    return nbt.dump(named.tag, named.name)


def _edit_lce_region(data: bytes, endian: str, width: int, rx: int, rz: int, drop: Set[Chunk],
                     paint: Dict[Chunk, int], method: str, res: EditResult) -> Optional[bytes]:
    from .lce import region as lreg

    chunks = {}
    changed = False
    for lx, lz, payload, rle, dlen in lreg.iter_region_chunks(data, endian, width):
        c = (rx * width + lx, rz * width + lz)
        if c in drop:
            res.removed += 1
            changed = True
            continue
        bid = paint.get(c)
        if bid is not None:
            raw = lreg.decompress_payload(payload, rle, method, dlen)
            new = lce_paint(raw, bid)
            chunks[(lx, lz)] = (lreg.compress_payload(new, method), len(new), True)
            res.painted += 1
            changed = True
        else:
            chunks[(lx, lz)] = (payload, dlen, rle)
    if not changed:
        return None
    return lreg.build_region(chunks, endian)


def _edit_lce(path: str, remove, paint, progress: Progress) -> EditResult:
    from .lce.container import SaveContainer
    from .lce.world import _REGION_RE, _SPLIT_DIM, ENTITY_FILES, entity_file_entries, write_entity_file

    for bid in {b for v in paint.values() for b in v.values()}:
        if bid not in bio.LCE:
            raise ConversionError(tr("The biome {biome} does not exist in Legacy Console Edition.", biome=bio.BIOMES[bid][0]))
    c = SaveContainer.load(path)
    if open(c.source_path, "rb").read(4) in (b"CON ", b"LIVE", b"PIRS"):
        raise ConversionError(tr("Save inside an STFS package (Xbox 360): extract it before editing it."))
    res = EditResult()
    endian, method = c.endian, c.platform.chunk
    width = 16 if "region_format_16" in c.files else 32
    dims = {None: OVERWORLD, "DIM-1": NETHER, "DIM1/": THE_END}
    for name, data in list(c.files.items()):
        m = _REGION_RE.match(name)
        if not m:
            continue
        dim = dims[m.group(1)]
        new = _edit_lce_region(data, endian, width, int(m.group(2)), int(m.group(3)), remove.get(dim, set()),
                               paint.get(dim, {}), method, res)
        if new is not None:
            c.files[name] = new
    for key, data in list(c.split_regions.items()):
        sdim, rx, rz = key
        dim = _SPLIT_DIM.get(sdim, OVERWORLD)
        new = _edit_lce_region(data, endian, 16, rx, rz, remove.get(dim, set()), paint.get(dim, {}), method, res)
        if new is not None:
            c.split_regions[key] = new
    if res.removed:  # split saves: the entities of the removed chunks are in entities.dat
        for dim, fname in ENTITY_FILES.items():
            gone = remove.get(dim, set())
            if fname not in c.files or not gone:
                continue
            try:
                entries = entity_file_entries(c.files[fname])
            except Exception:  # noqa: BLE001
                continue
            c.files[fname] = write_entity_file({(cx, cz): raw for cx, cz, _t, raw in entries if (cx, cz) not in gone})
    if res.removed or res.painted:
        folder, name = os.path.split(os.path.abspath(c.source_path))
        backup = _Backup(folder)
        backup.save(c.source_path)
        for fn in os.listdir(folder):
            if fn.startswith("GAMEDATA_"):
                backup.save(os.path.join(folder, fn))
        c.save(folder, name)
        res.backup = backup.used
    return res


# ------------------------------------------------------------------ Bedrock
def _edit_bedrock(world: str, remove, paint, progress: Progress) -> EditResult:
    from . import amulet_bridge as ab

    res = EditResult()
    backup = _Backup(world)
    backup.save(os.path.join(world, "db"))
    level = ab.load_level(world)
    try:
        for dim, cs in remove.items():
            name = ab.AMULET_DIMS[dim]
            for cx, cz in cs:
                try:
                    level.delete_chunk(cx, cz, name)
                    res.removed += 1
                except Exception:  # noqa: BLE001
                    pass
        for dim, chunks in paint.items():
            name = ab.AMULET_DIMS[dim]
            for (cx, cz), b in chunks.items():
                try:
                    ab.paint_biome(level, level.get_chunk(cx, cz, name), b)
                    res.painted += 1
                except Exception:  # noqa: BLE001
                    res.skipped += 1
        level.save()
    finally:
        level.close()
    res.backup = backup.used
    return res


def keep_only(path: str, keep: Dict[int, Set[Chunk]], dims: Sequence[int], progress: Optional[Progress] = None) -> EditResult:
    """Removes every chunk of ``dims`` that is not in ``keep`` (world trim, "tieni solo i selezionati")."""
    from .mapview import open_map

    m = open_map(path, progress or Progress())
    try:
        present = {d: set(m.chunk_coords(d)) for d in dims}
    finally:
        m.close()
    remove = {d: present[d] - set(keep.get(d, set())) for d in dims}
    return edit_world(path, remove=remove, progress=progress)

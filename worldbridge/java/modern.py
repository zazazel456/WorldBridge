"""Java Edition 1.13+ worlds: raw access to block entities and entities
(Amulet translates the blocks, this module the rest)."""

from __future__ import annotations

import os
import re
import struct
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Tuple

from .. import entities as ent
from .. import nbt, tiles
from ..model import NETHER, OVERWORLD, THE_END, Progress, WorldInfo
from .region import JavaRegion, RegionWriter
from ..i18n import tr

_DIM_DIRS = {OVERWORLD: "", NETHER: "DIM-1", THE_END: "DIM1"}
_REGION_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")
ENTITY_SPLIT_DV = 2724  # 1.17: entities moved to entities/*.mca


_NEW_DIM_DIRS = {OVERWORLD: "overworld", NETHER: "the_nether", THE_END: "the_end"}


def _folder(world: str, dim: int, sub: str) -> str:
    """Folder of ``sub`` (region/entities) for a dimension, classic or 26.1+ layout."""
    new = os.path.join(world, "dimensions", "minecraft", _NEW_DIM_DIRS[dim], sub)
    base = os.path.join(world, _DIM_DIRS[dim]) if _DIM_DIRS[dim] else world
    old = os.path.join(base, sub)
    if os.path.isdir(new) and not os.path.isdir(old):
        return new
    return old


def _regions(folder: str):
    if not os.path.isdir(folder):
        return []
    out = []
    for fn in os.listdir(folder):
        m = _REGION_RE.match(fn)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), os.path.join(folder, fn)))
    return out


def _chunk_parts(root: nbt.CompoundTag):
    lvl = nbt.get_tag(root, "Level")
    if lvl is not None:
        return nbt.get_tag(lvl, "TileEntities") or [], nbt.get_tag(lvl, "Entities") or []
    return nbt.get_tag(root, "block_entities") or [], nbt.get_tag(root, "Entities") or []


# Java 1.13+ keeps the plant of a flower pot and the pitch of a note block in the block state;
# Java <= 1.12 (the hub) needs a FlowerPot / Music block entity for them.
SPANNING_DV = 2527  # before 20w17a (1.16) palette entries may span two longs


def _state_tile(name: str, props) -> Optional[dict]:
    name = name.split(":", 1)[-1]
    if name.startswith("potted_"):
        plant = tiles.pot_plant(name[7:])
        return {"kind": "flower_pot", "plant": plant} if plant else None
    if name == "note_block":
        try:
            return {"kind": "noteblock", "note": int(str(nbt.get(props, "note", 0)))}
        except ValueError:
            return None
    return None


def _sections(root: nbt.CompoundTag):
    """(section, palette key, data key, holder) of every section of a 1.13+ chunk."""
    lvl = nbt.get_tag(root, "Level")
    for sec in nbt.get_tag(lvl if lvl is not None else root, "Sections" if lvl is not None else "sections") or []:
        bs = nbt.get_tag(sec, "block_states")
        if bs is not None:
            yield sec, bs, "palette", "data"
        elif "Palette" in sec:
            yield sec, sec, "Palette", "BlockStates"


def _decode(data, n_palette: int, spanning: bool):
    import numpy as np

    if n_palette <= 1:
        return np.zeros(4096, np.int64)
    if data is None or not len(data):
        return None
    bits = max(4, (n_palette - 1).bit_length())
    longs = np.asarray(data, dtype=np.int64).view(np.uint64)
    mask = np.uint64((1 << bits) - 1)
    if spanning:
        if len(longs) * 64 < 4096 * bits:
            return None
        pos = np.arange(4096, dtype=np.uint64) * np.uint64(bits)
        word = (pos >> np.uint64(6)).astype(np.int64)
        off = pos & np.uint64(63)
        lo = longs[word] >> off
        nxt = np.minimum(word + 1, len(longs) - 1)
        spill = off + np.uint64(bits) > np.uint64(64)
        hi = np.where(spill, longs[nxt] << ((np.uint64(64) - off) & np.uint64(63)), np.uint64(0))
        return ((lo | hi) & mask).astype(np.int64)
    per = 64 // bits
    i = np.arange(4096)
    word = i // per
    if word[-1] >= len(longs):
        return None
    return ((longs[word] >> ((i % per) * bits).astype(np.uint64)) & mask).astype(np.int64)


def _encode(idx, n_palette: int, spanning: bool):
    import numpy as np

    bits = max(4, (n_palette - 1).bit_length())
    vals = idx.astype(np.uint64)
    if spanning:
        out = [0] * ((4096 * bits + 63) // 64)
        for i, v in enumerate(vals.tolist()):
            p = i * bits
            w, o = p >> 6, p & 63
            out[w] |= (v << o) & 0xFFFFFFFFFFFFFFFF
            if o + bits > 64:
                out[w + 1] |= v >> (64 - o)
        arr = np.array(out, np.uint64)
    else:
        per = 64 // bits
        n = (4096 + per - 1) // per
        arr = np.zeros(n, np.uint64)
        i = np.arange(4096)
        np.bitwise_or.at(arr, i // per, vals << ((i % per) * bits).astype(np.uint64))
    return nbt.LongArrayTag(arr.view(np.int64))


def state_tiles(root: nbt.CompoundTag, cx: int, cz: int) -> List[dict]:
    """Canonical flower pot / note block entities rebuilt from the block states of a 1.13+ chunk."""
    import numpy as np

    dv = int(nbt.get(root, "DataVersion", 0) or 0)
    out = []
    for sec, holder, pkey, dkey in _sections(root):
        palette = nbt.get_tag(holder, pkey) or []
        wanted = {}
        for i, st in enumerate(palette):
            name = nbt.state_name(st, "")
            if "potted_" in name or name.endswith("note_block"):
                t = _state_tile(name, nbt.state_props(st))
                if t is not None:
                    wanted[i] = t
        if not wanted:
            continue
        idx = _decode(nbt.get_tag(holder, dkey), len(palette), bool(dv) and dv < SPANNING_DV)
        if idx is None:
            continue
        sy = int(nbt.get(sec, "Y", 0))
        for pi, t in wanted.items():
            for n in np.nonzero(idx == pi)[0]:
                c = dict(t)
                c["pos"] = (cx * 16 + int(n & 15), sy * 16 + int(n >> 8), cz * 16 + int((n >> 4) & 15))
                out.append(c)
    return out


def apply_state_tiles(root: nbt.CompoundTag, canon: List[dict]) -> int:
    """The reverse of ``state_tiles``: put the plant of the canonical flower pots and the pitch of
    the note blocks into the block states of a 1.13+ chunk (Amulet leaves them empty / at 0).
    Returns the number of blocks changed."""
    dv = int(nbt.get(root, "DataVersion", 0) or 0)
    todo = {}
    for c in canon:
        if c.get("kind") == "flower_pot":
            flat = tiles.pot_flat(c.get("plant"))
            if flat:
                todo[tuple(c["pos"])] = ("flower_pot", "minecraft:potted_" + flat, None)
        elif c.get("kind") == "noteblock" and 0 < int(c.get("note", 0)) <= 24:
            todo[tuple(c["pos"])] = ("note_block", None, str(int(c["note"])))
    if not todo:
        return 0
    by_y = defaultdict(list)
    for (x, y, z), v in todo.items():
        by_y[y >> 4].append(((y & 15) << 8 | (z & 15) << 4 | (x & 15), v))
    changed = 0
    spanning = bool(dv) and dv < SPANNING_DV
    for sec, holder, pkey, dkey in _sections(root):
        wanted = by_y.get(int(nbt.get(sec, "Y", -99)))
        palette = nbt.get_tag(holder, pkey)
        if not wanted or palette is None:
            continue
        n0 = len(palette)
        idx = _decode(nbt.get_tag(holder, dkey), n0, spanning)
        if idx is None:
            continue
        keys = [nbt.dump(st, "") for st in palette]
        here = 0
        for n, (base, new_name, note) in wanted:
            cur = palette[int(idx[n])]
            if nbt.state_name(cur, "").split(":", 1)[-1] != base:
                continue  # not the expected block: leave it alone
            if new_name is not None:
                st = nbt.CompoundTag({"Name": nbt.StringTag(new_name)})
            else:
                st = nbt.copy(cur)
                props = nbt.get_tag(st, "Properties") or nbt.CompoundTag()
                props["note"] = nbt.StringTag(note)
                st["Properties"] = props
            k = nbt.dump(st, "")
            if k not in keys:
                palette.append(st)
                keys.append(k)
            idx[n] = keys.index(k)
            here += 1
        if here:
            changed += here
            holder[dkey] = _encode(idx, len(palette), spanning)
    return changed


def _iter_chunks(world: str, sub: str, dim: int):
    for rx, rz, path in _regions(_folder(world, dim, sub)):
        try:
            reg = JavaRegion(path)
        except OSError:
            continue
        for lx, lz in reg.chunks():
            raw = reg.read(lx, lz)
            if raw is None:
                continue
            try:
                root = nbt.load(raw, compressed=False).tag
            except Exception:  # noqa: BLE001
                continue
            yield rx * 32 + lx, rz * 32 + lz, root


def iter_modern_extras(world: str, progress: Optional[Progress] = None,
                       with_states: bool = False) -> Iterator[Tuple[int, int, int, list, list]]:
    """Yield (dim, cx, cz, block_entities, entities) of a Java 1.13+ world.  with_states: the
    block entity list also gets the canonical dicts of ``state_tiles`` (after the NBT ones)."""
    for dim in (OVERWORLD, NETHER, THE_END):
        per_chunk: Dict[Tuple[int, int], List[list]] = defaultdict(lambda: [[], []])
        for cx, cz, root in _iter_chunks(world, "region", dim):
            te, en = _chunk_parts(root)
            te = list(te)
            if with_states:
                te += state_tiles(root, cx, cz)
            if len(te) or len(en):
                per_chunk[(cx, cz)][0].extend(te)
                per_chunk[(cx, cz)][1].extend(en)
        for cx, cz, root in _iter_chunks(world, "entities", dim):
            en = nbt.get_tag(root, "Entities") or []
            if len(en):
                per_chunk[(cx, cz)][1].extend(en)
        for (cx, cz), (te, en) in per_chunk.items():
            yield dim, cx, cz, te, en


class JavaModernExtras:
    """Java 1.13+ block entities / entities, converted to the legacy hub format per chunk."""

    def __init__(self, path: str, progress: Progress):
        self.data: Dict[Tuple[int, int, int], Tuple[list, list]] = {}
        for dim, cx, cz, te, en in iter_modern_extras(path, progress, with_states=True):
            self.data[(dim, cx, cz)] = (te, en)

    def chunk_extras(self, dim: int, cx: int, cz: int):
        te, en = self.data.get((dim, cx, cz), ([], []))
        canon, seen = [], set()
        for t in te:
            c = t if isinstance(t, dict) else tiles.from_java_modern(t)
            if c is not None and 0 <= c["pos"][1] < 256 and tuple(c["pos"]) not in seen:
                seen.add(tuple(c["pos"]))
                canon.append(c)
        tl = tiles.write_list(canon, "legacy")
        el = []
        for c in ent.read_list(en, "java"):
            if 0 <= c["pos"][1] < 256:
                e = ent.to_legacy(c)
                if e is not None:
                    el.append(e)
        return el, tl


# ---------------------------------------------------------------- Bedrock -> Java writer


def _bedrock_chunks(src: str) -> Dict[Tuple[int, int, int], Tuple[list, list]]:
    from ..bedrock.extra import (BE_TAG, DIM_FROM_BEDROCK, ENTITY_TAG, _db, _get, frame_canon, is_frame_tile,
                                 read_nbt_list)

    db = _db(src)
    out: Dict[Tuple[int, int, int], Tuple[list, list]] = {}
    try:
        for key, value in db.iterate():
            k = bytes(key)
            if len(k) in (9, 13) and k[-1] in (BE_TAG, ENTITY_TAG):
                cx, cz = struct.unpack_from("<ii", k, 0)
                dim = DIM_FROM_BEDROCK.get(struct.unpack_from("<i", k, 8)[0], None) if len(k) == 13 else OVERWORLD
                if dim is None:
                    continue
                slot = out.setdefault((dim, cx, cz), ([], []))
                lst = read_nbt_list(bytes(value))
                if k[-1] == BE_TAG:  # item frames: block entities in Bedrock, entities in Java
                    for t in lst:
                        if is_frame_tile(t):
                            c = frame_canon(db, k[:-1], t)
                            if c is not None:
                                slot[1].append(c)
                        else:
                            slot[0].append(t)
                else:
                    slot[1].extend(lst)
            elif k.startswith(b"digp") and len(k) in (12, 16):
                cx, cz = struct.unpack_from("<ii", k, 4)
                dim = DIM_FROM_BEDROCK.get(struct.unpack_from("<i", k, 12)[0], None) if len(k) == 16 else OVERWORLD
                if dim is None:
                    continue
                digp = bytes(value)
                slot = out.setdefault((dim, cx, cz), ([], []))
                for i in range(0, len(digp) // 8 * 8, 8):
                    a = _get(db, b"actorprefix" + digp[i : i + 8])
                    if a:
                        slot[1].extend(read_nbt_list(a))
    finally:
        db.close()
    return out


def inject_from_bedrock(src: str, out_dir: str, info: WorldInfo, progress: Progress):
    canon = {}
    for key, (te, en) in _bedrock_chunks(src).items():
        tl = [c for c in (tiles.from_bedrock(t) for t in te) if c is not None]
        el = [e for e in en if isinstance(e, dict)] + ent.read_list([e for e in en if not isinstance(e, dict)], "bedrock")
        if tl or el:
            canon[key] = (tl, el)
    inject_canon(out_dir, canon, progress)


def inject_from_java(src: str, out_dir: str, info: WorldInfo, progress: Progress):
    canon = {}
    for dim, cx, cz, te, en in iter_modern_extras(src, progress):
        tl = [c for c in (tiles.from_java_modern(t) for t in te) if c is not None]
        el = ent.read_list(en, "java")
        if tl or el:
            canon[(dim, cx, cz)] = (tl, el)
    inject_canon(out_dir, canon, progress)


def inject_from_hub(hub_dir: str, out_dir: str, info: WorldInfo, progress: Progress):
    from .numeric import JavaNumericWorld

    hub = JavaNumericWorld(hub_dir)
    canon = {}
    for dim in hub.dimensions():
        for cx, cz in hub.chunk_coords(dim):
            c = hub.read_chunk(dim, cx, cz)
            if c is None:
                continue
            tl = [x for x in (tiles.from_legacy(t) for t in c.tile_entities) if x is not None]
            el = ent.read_list(c.entities, "legacy")
            if tl or el:
                canon[(dim, cx, cz)] = (tl, el)
    inject_canon(out_dir, canon, progress)


def _drop_bedrock_entities(root: nbt.CompoundTag) -> None:
    """Amulet copies Bedrock actors verbatim into the ``Entities`` of a Java 1.13-1.16 chunk: the
    game would load them as a second, broken copy of every mob.  The translated ones replace them."""
    lvl = nbt.get_tag(root, "Level")
    ents = nbt.get_tag(lvl if lvl is not None else root, "Entities")
    if ents is None:
        return
    keep = [e for e in ents if not ("identifier" in e or "definitions" in e)]
    if len(keep) != len(ents):
        (lvl if lvl is not None else root)["Entities"] = nbt.compound_list(keep)


def inject_canon(out_dir: str, canon, progress: Progress):
    by_region: Dict[Tuple[int, int, int], List[Tuple[int, int, list, list]]] = defaultdict(list)
    for (dim, cx, cz), (tl, el) in canon.items():
        by_region[(dim, cx >> 5, cz >> 5)].append((cx, cz, tl, el))
    n_t = n_e = 0
    for (dim, rx, rz), entries in by_region.items():
        path = os.path.join(_folder(out_dir, dim, "region"), f"r.{rx}.{rz}.mca")
        if not os.path.exists(path):
            continue
        reg = JavaRegion(path)
        rw = RegionWriter()
        todo = {(cx & 31, cz & 31): (tl, el) for cx, cz, tl, el in entries}
        ent_writer = None
        dv_seen = 3465
        for lx, lz in reg.chunks():
            raw = reg.read(lx, lz)
            if raw is None:
                continue
            bedrock_junk = b"\x0bdefinitions" in raw or b"\x08identifier" in raw
            if (lx, lz) not in todo and not bedrock_junk:
                rw.put(lx, lz, raw)
                continue
            root = nbt.load(raw, compressed=False).tag
            if bedrock_junk:
                _drop_bedrock_entities(root)
            if (lx, lz) not in todo:
                rw.put(lx, lz, nbt.dump(root, ""))
                continue
            dv = int(nbt.get(root, "DataVersion", 3465))
            dv_seen = dv
            tl, el = todo[(lx, lz)]
            apply_state_tiles(root, tl)
            new_tiles = tiles.write_list(tl, "java", data_version=dv)
            lvl = nbt.get_tag(root, "Level")
            holder, key = (lvl, "TileEntities") if lvl is not None else (root, "block_entities")
            existing = {(int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))): t
                        for t in (nbt.get_tag(holder, key) or [])}
            for t in new_tiles:
                existing[(int(t["x"].py_data), int(t["y"].py_data), int(t["z"].py_data))] = t
                n_t += 1
            holder[key] = nbt.compound_list(existing.values())
            if el:
                ents = [e for e in (ent.to_java_modern(c, dv if dv < ENTITY_SPLIT_DV else 2730) for c in el) if e is not None]
                n_e += len(ents)
                if dv < ENTITY_SPLIT_DV and lvl is not None:
                    lvl["Entities"] = nbt.compound_list(list(nbt.get_tag(lvl, "Entities") or []) + ents)
                else:
                    if ent_writer is None:
                        ent_writer = {}
                    cx, cz = rx * 32 + lx, rz * 32 + lz
                    ent_writer[(lx, lz)] = nbt.CompoundTag({
                        "DataVersion": nbt.IntTag(2730),
                        "Position": nbt.IntArrayTag(__import__("numpy").array([cx, cz], "int32")),
                        "Entities": nbt.compound_list(ents)})
            rw.put(lx, lz, nbt.dump(root, ""))
        rw.write(path)
        if ent_writer:
            folder = _folder(out_dir, dim, "entities")
            os.makedirs(folder, exist_ok=True)
            epath = os.path.join(folder, f"r.{rx}.{rz}.mca")
            ew = RegionWriter()
            if os.path.exists(epath):
                old = JavaRegion(epath)
                for lx, lz in old.chunks():
                    r = old.read(lx, lz)
                    if r is not None and (lx, lz) not in ent_writer:
                        ew.put(lx, lz, r)
            for (lx, lz), root in ent_writer.items():
                ew.put(lx, lz, nbt.dump(root, ""))
            ew.write(epath)
        del dv_seen
    progress.log(tr("Java: {tiles} block entities and {entities} entities written.", tiles=n_t, entities=n_e))


def tidy_entity_regions(world: str) -> int:
    """Make the 1.17+ ``entities/`` region files look like the game's own.

    Amulet writes an entity record for every chunk, empty ones included, and without the
    ``Position`` field that Minecraft reads *before* upgrading the record: 26.x then logs
    "Failed to load chunk" for each of them.  Empty records are dropped (a missing record
    means "no entities") and ``Position`` is added where it is missing.  Returns the number
    of records removed or fixed."""
    import numpy as np

    changed = 0
    for dim in (OVERWORLD, NETHER, THE_END):
        for rx, rz, path in _regions(_folder(world, dim, "entities")):
            reg = JavaRegion(path)
            rw = RegionWriter()
            kept = dirty = 0
            for lx, lz in reg.chunks():
                raw = reg.read(lx, lz)
                if raw is None:
                    continue
                root = nbt.load(raw, compressed=False).tag
                if not len(nbt.get_tag(root, "Entities") or []):
                    dirty += 1
                    continue
                if "Position" not in root:
                    root["Position"] = nbt.IntArrayTag(np.array([rx * 32 + lx, rz * 32 + lz], "int32"))
                    raw = nbt.dump(root, "")
                    dirty += 1
                rw.put(lx, lz, raw)
                kept += 1
            if not dirty:
                continue
            changed += dirty
            if kept:
                rw.write(path)
            else:
                os.remove(path)
    return changed


def chunk_data_version(world: str) -> Optional[int]:
    """DataVersion of the first readable chunk of the Overworld."""
    for rx, rz, path in sorted(_regions(_folder(world, OVERWORLD, "region")), key=lambda r: -os.path.getsize(r[2])):
        try:
            reg = JavaRegion(path)
        except OSError:
            continue
        for lx, lz in reg.chunks():
            raw = reg.read(lx, lz)
            if raw is None:
                continue
            try:
                root = nbt.load(raw, compressed=False).tag
            except Exception:  # noqa: BLE001
                continue
            dv = nbt.get(root, "DataVersion")
            return int(dv) if dv is not None else 0
    return None

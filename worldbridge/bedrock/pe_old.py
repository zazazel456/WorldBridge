"""Pocket Edition 0.1 - 0.8 worlds (``chunks.dat`` + ``level.dat`` + ``entities.dat``).

* level.dat     [i32 LE storage version 3][i32 LE length][LE NBT]
* chunks.dat    1024 x [u8 sectors][u24 LE sector offset] (index x + z*32), then per chunk
                (optional u32 LE length) blocks[32768] data[16384] sky[16384] light[16384] biomes[256]
                arrays in YZX order (x*2048 + z*128 + y), 16x16 chunks used (256x256 blocks)
* entities.dat  'ENT\\0' [i32 1][i32 length][LE NBT {Entities, TileEntities}]
"""

from __future__ import annotations

import os
import struct
from collections import Counter
from typing import List, Optional, Tuple

import numpy as np

from .. import blocks as blk
from .. import ids, nbt
from ..lce.chunk import array_to_nibbles, java128_to_yzx, nibbles_to_array, yzx_to_java128
from ..model import OVERWORLD, NumericChunk, Progress, WorldInfo, WorldSource, dimension_of
from ..i18n import tr

SECTOR = 4096
CHUNK_BYTES = 32768 + 16384 * 3 + 256
PE_TO_JAVA = {95: (166, 0), 157: (125, 0), 158: (126, 0), 245: (58, 0), 246: (49, 0), 247: (42, 0),
              248: (1, 0), 249: (1, 0), 255: (0, 0)}
JAVA_TO_PE = {125: 157, 126: 158}
PE_ENTITY = {10: "Chicken", 11: "Cow", 12: "Pig", 13: "Sheep", 32: "Zombie", 33: "Creeper", 34: "Skeleton",
             35: "Spider", 36: "PigZombie", 64: "Item", 65: "PrimedTnt", 66: "FallingSand", 80: "Arrow",
             81: "Snowball", 82: "ThrownEgg", 83: "Painting", 84: "MinecartRideable"}
PE_ENTITY_INV = {v: k for k, v in PE_ENTITY.items()}
PE_ALLOWED = frozenset(list(range(0, 23)) + [24, 26, 27, 30, 31, 32, 35] + list(range(37, 55)) + list(range(56, 69))
                       + [71, 73, 74, 78, 79, 80, 81, 82, 83, 85, 86, 87, 89, 91, 92, 96, 98, 101, 102, 103, 104, 105,
                          107, 108, 109, 112, 114, 125, 126, 128, 141, 142, 155, 156, 170, 171, 173])


def _plain_pages(lst: nbt.ListTag) -> nbt.ListTag:
    """Book pages as plain text (Java 1.8+ written books keep JSON text components)."""
    from ..items import plain_text

    for it in lst:
        pages = nbt.get_tag(nbt.get_tag(it, "tag") or nbt.CompoundTag(), "pages")
        if pages is not None and len(pages) and isinstance(pages[0], nbt.StringTag):
            it["tag"]["pages"] = nbt.ListTag([nbt.StringTag(plain_text(p.py_data)) for p in pages], 8)
    return lst


def _read_le_nbt(path: str, header: int) -> Optional[nbt.CompoundTag]:
    if not os.path.exists(path):
        return None
    raw = open(path, "rb").read()
    try:
        return nbt.load(raw[header:], little_endian=True, compressed=False).tag
    except Exception:  # noqa: BLE001
        return None


def read_v1_level(raw: bytes) -> Optional[nbt.CompoundTag]:
    """The level.dat of PE 0.1 (storage version 1): [i32 LE 1][i32 LE length], then a big endian
    (RakNet BitStream) body: seed, spawn x/y/z, time, size on disk, last played (i32 each) and the
    name as [u16 length][bytes].  None when ``raw`` is not one."""
    if len(raw) < 8 + 30 or struct.unpack_from("<i", raw, 0)[0] != 1:
        return None
    (length,) = struct.unpack_from("<i", raw, 4)
    body = raw[8:8 + length]
    if length < 30 or len(body) < length:
        return None
    seed, sx, sy, sz, time, _size, played = struct.unpack_from(">7i", body, 0)
    (n,) = struct.unpack_from(">H", body, 28)
    if 30 + n > len(body):
        return None
    return nbt.CompoundTag({
        "LevelName": nbt.StringTag(body[30:30 + n].decode("utf-8", "replace")), "RandomSeed": nbt.LongTag(seed),
        "SpawnX": nbt.IntTag(sx), "SpawnY": nbt.IntTag(sy), "SpawnZ": nbt.IntTag(sz),
        "Time": nbt.LongTag(max(time, 0)), "LastPlayed": nbt.LongTag(played & 0xFFFFFFFF),
        "GameType": nbt.IntTag(1)})  # 0.1 - 0.2 had the creative mode only (no health, a hotbar without counts)


def read_v1_player(raw: bytes) -> Optional[nbt.CompoundTag]:
    """The player.dat of PE 0.1 - 0.2: [i32 LE 1][i32 LE 80], then little endian: position, motion
    (3 floats each), pitch, yaw and fall distance (floats), fire and air (i16), on ground (u8), 3
    bytes of padding and the 9 hotbar block ids (i32, -1 = empty).  As a Java player compound."""
    if len(raw) < 88 or struct.unpack_from("<ii", raw, 0) != (1, 80):
        return None
    v = struct.unpack_from("<9f2hB3x9i", raw, 8)
    pos, motion, pitch, yaw, fall = v[0:3], v[3:6], v[6], v[7], v[8]
    fire, air, ground, hotbar = v[9], v[10], v[11], v[12:21]
    if not all(abs(c) < 1e6 for c in pos):
        return None
    inv = nbt.ListTag([], 10)
    for slot, iid in enumerate(hotbar):
        if 0 < iid < 512:
            iid, dmg = PE_TO_JAVA.get(iid, (iid, 0))
            if iid:
                inv.append(nbt.CompoundTag({"id": nbt.ShortTag(iid), "Count": nbt.ByteTag(1),
                                            "Damage": nbt.ShortTag(dmg), "Slot": nbt.ByteTag(slot)}))
    return nbt.CompoundTag({
        "Pos": nbt.ListTag([nbt.DoubleTag(c) for c in pos], 6),
        "Motion": nbt.ListTag([nbt.DoubleTag(c) for c in motion], 6),
        "Rotation": nbt.ListTag([nbt.FloatTag(yaw), nbt.FloatTag(pitch)], 5),
        "FallDistance": nbt.FloatTag(fall), "Fire": nbt.ShortTag(fire), "Air": nbt.ShortTag(air),
        "OnGround": nbt.ByteTag(ground), "Health": nbt.ShortTag(20), "Dimension": nbt.IntTag(0),
        "Inventory": inv})


def _read_v1(path: str, parse):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return parse(f.read())


class PEOldWorld(WorldSource):
    def __init__(self, path: str):
        self.path = path
        self.max_height = 128
        lvl = _read_v1(os.path.join(path, "level.dat"), read_v1_level)  # PE 0.1: a binary level.dat
        lvl = lvl or _read_le_nbt(os.path.join(path, "level.dat"), 8) or nbt.CompoundTag()
        if "Player" not in lvl:  # PE 0.1 - 0.2: a binary player.dat beside it
            player = _read_v1(os.path.join(path, "player.dat"), read_v1_player)
            if player is not None:
                lvl["Player"] = player
        self.info = WorldInfo()
        self.info.level = nbt.CompoundTag()
        for k in ("LevelName", "RandomSeed", "SpawnX", "SpawnY", "SpawnZ", "GameType", "Time", "LastPlayed"):
            if k in lvl:
                self.info.level[k] = lvl[k]
        if "Player" in lvl:
            p = nbt.copy(lvl["Player"])
            for key in ("Pos", "Motion"):  # PE stores floats, Java reads doubles
                lst = nbt.get_tag(p, key)
                if lst is not None and len(lst) == 3:
                    p[key] = nbt.ListTag([nbt.DoubleTag(float(v.py_data)) for v in lst], 6)
            self.info.players["host"] = p
        self.info.source_description = "Pocket Edition 0.1 – 0.8"
        ents = _read_le_nbt(os.path.join(path, "entities.dat"), 12) or nbt.CompoundTag()
        self._ents = [e for e in (self._entity(e) for e in (nbt.get_tag(ents, "Entities") or [])) if e is not None]
        self._tiles = list(nbt.get_tag(ents, "TileEntities") or [])
        self.raw = open(os.path.join(path, "chunks.dat"), "rb").read()
        self.index = {}
        for i in range(1024):
            count = self.raw[i * 4]
            off = int.from_bytes(self.raw[i * 4 + 1 : i * 4 + 4], "little")
            if count and off:
                self.index[(i % 32, i // 32)] = off * SECTOR

    @staticmethod
    def _entity(e):
        eid = nbt.get(e, "id")
        if isinstance(eid, int):
            name = PE_ENTITY.get(eid)
            if name is None:
                return None
            e = nbt.copy(e)
            e["id"] = nbt.StringTag(name)
            for key in ("Pos", "Motion"):
                lst = nbt.get_tag(e, key)
                if lst is not None:
                    e[key] = nbt.ListTag([nbt.DoubleTag(float(v.py_data)) for v in lst], 6)
        return e

    def dimensions(self) -> List[int]:
        return [OVERWORLD]

    def chunk_coords(self, dim: int) -> List[Tuple[int, int]]:
        return sorted(self.index)

    def read_chunk(self, dim: int, cx: int, cz: int) -> Optional[NumericChunk]:
        p = self.index.get((cx, cz))
        if p is None:
            return None
        head = struct.unpack_from("<I", self.raw, p)[0] if p + 4 <= len(self.raw) else 0
        if head in (CHUNK_BYTES, CHUNK_BYTES + 4):
            p += 4
        body = self.raw[p : p + CHUNK_BYTES]
        if len(body) < 32768 + 16384 * 3:
            return None
        c = NumericChunk(cx, cz, 128)
        b = np.frombuffer(body, np.uint8, 32768).astype(np.uint16)
        d = nibbles_to_array(body[32768:49152], 32768)
        for pe, (jid, jd) in PE_TO_JAVA.items():
            m = b == pe
            if m.any():
                b[m] = jid
                d[m] = jd
        c.blocks = java128_to_yzx(b).copy()
        c.data = java128_to_yzx(d).copy()
        c.sky_light = java128_to_yzx(nibbles_to_array(body[49152:65536], 32768)).copy()
        c.block_light = java128_to_yzx(nibbles_to_array(body[65536:81920], 32768)).copy()
        c.biomes = np.ones((16, 16), np.uint8)
        x0, z0 = cx * 16, cz * 16
        for t in self._tiles:
            if x0 <= int(nbt.get(t, "x", -99)) < x0 + 16 and z0 <= int(nbt.get(t, "z", -99)) < z0 + 16:
                c.tile_entities.append(t)
        for e in self._ents:
            pos = nbt.get_tag(e, "Pos")
            if pos is not None and x0 <= float(pos[0].py_data) < x0 + 16 and z0 <= float(pos[2].py_data) < z0 + 16:
                c.entities.append(e)
        return c


class PEOldWriter:
    """Writes a PE 0.8 world: 256x256 blocks (chunks 0..15), 128 high."""

    def __init__(self, out_dir: str, progress: Progress, world_name: Optional[str] = None,
                 origin: Tuple[int, int] = (0, 0)):
        self.origin = origin  # source chunk that becomes chunk (0, 0)
        self.out = out_dir
        self.progress = progress
        self.world_name = world_name
        self.chunks = {}
        self.tiles: List[nbt.CompoundTag] = []
        self.ents: List[nbt.CompoundTag] = []
        self.replaced = 0
        self.skipped = 0
        self.dropped_items = 0
        self.dropped_ents: Counter = Counter()     # what the game has no entity or block entity for
        self.dropped_tiles: Counter = Counter()
        os.makedirs(out_dir, exist_ok=True)

    def add_chunk(self, dim: int, c: NumericChunk, shift: bool = True):
        tx, tz = c.cx - self.origin[0], c.cz - self.origin[1]
        if dim != OVERWORLD or not (0 <= tx < 16 and 0 <= tz < 16):
            self.skipped += 1
            return
        from ..lce.world import shift_entity

        dx, dz = (tx - c.cx) * 16, (tz - c.cz) * 16
        c.entities = [e for e in (shift_entity(e, dx, dz) for e in c.entities) if e is not None]
        for t in c.tile_entities:
            if "x" in t:
                t["x"] = nbt.IntTag(int(t["x"].py_data) + dx)
                t["z"] = nbt.IntTag(int(t["z"].py_data) + dz)
        c.cx, c.cz = tx, tz
        if c.height != 128:
            c.resize(128)
        b, d, n = blk.downgrade(c.blocks, c.data, PE_ALLOWED)
        self.replaced += n
        b = b.astype(np.uint16)
        for j, pe in JAVA_TO_PE.items():
            b[b == j] = pe
        sky = c.sky_light if c.sky_light is not None else c.compute_sky_light()
        bl = c.block_light if c.block_light is not None else c.compute_block_light()
        body = (yzx_to_java128(b.astype(np.uint8)).tobytes() + array_to_nibbles(yzx_to_java128(d))
                + array_to_nibbles(yzx_to_java128(sky)) + array_to_nibbles(yzx_to_java128(bl)) + bytes(256))
        self.chunks[(c.cx, c.cz)] = body
        from ..items import plain_text
        from ..lce.compat import plain_sign_line
        from ..lce.world import legacy_items

        for t in c.tile_entities:
            raw_id = str(nbt.get(t, "id", ""))
            tid = ids.tile_to_old(raw_id) or raw_id.split(":", 1)[-1]        # "chest" (1.11+) or "Chest"
            if tid not in ("Chest", "Furnace", "Sign"):
                self.dropped_tiles[tid or "?"] += 1
                continue
            t = nbt.copy(t)
            t["id"] = nbt.StringTag(tid)
            if "Items" in t:
                n = len(t["Items"])
                t["Items"] = _plain_pages(legacy_items(t["Items"]))
                self.dropped_items += n - len(t["Items"])
            if tid == "Sign":  # PE keeps plain lines (at most 15 characters), not Java's JSON text
                for i in range(1, 5):
                    line = plain_sign_line(plain_text(nbt.get(t, f"Text{i}", "")))
                    t[f"Text{i}"] = nbt.StringTag(line[:15])
            self.tiles.append(t)
        for e in c.entities:
            raw_id = str(nbt.get(e, "id", ""))
            old, _extra = ids.entity_to_old(raw_id)                          # "Chicken" or "minecraft:chicken"
            num = PE_ENTITY_INV.get(old)
            if num is None:
                self.dropped_ents[old or raw_id.split(":", 1)[-1] or "?"] += 1
                continue
            e = nbt.copy(e)
            e["id"] = nbt.IntTag(num)
            # PE 0.x reads Health as a short (Java 1.6+ writes a float, with HealF beside the short before 1.9)
            hp = nbt.get(e, "HealF", nbt.get(e, "Health"))
            if hp is not None:
                try:
                    e["Health"] = nbt.ShortTag(max(0, min(32767, int(round(float(hp))))))
                except (TypeError, ValueError):
                    del e["Health"]
            if "HealF" in e:
                del e["HealF"]
            if isinstance(nbt.get_tag(e, "Item"), nbt.CompoundTag):
                e["Item"] = _plain_pages(nbt.ListTag([e["Item"]], 10))[0]
            pos = nbt.get_tag(e, "Pos")
            if pos is not None:
                e["Pos"] = nbt.ListTag([nbt.FloatTag(float(v.py_data)) for v in pos], 5)
            for key in ("Motion",):
                m = nbt.get_tag(e, key)
                if m is not None:
                    e[key] = nbt.ListTag([nbt.FloatTag(float(v.py_data)) for v in m], 5)
            self.ents.append(e)

    def _player(self, info: WorldInfo) -> Optional[nbt.CompoundTag]:
        """The main player: position, rotation and health.  The inventory is not written (the slot
        layout of the 0.x client is undocumented; a wrong one could break the save)."""
        if not info.players:
            return None
        p = next(iter(info.players.values()))
        pos = nbt.get_tag(p, "Pos")
        if pos is None or len(pos) != 3 or dimension_of(p) != 0:
            return None
        x = float(pos[0].py_data) - self.origin[0] * 16
        y = min(float(pos[1].py_data), 127.0)
        z = float(pos[2].py_data) - self.origin[1] * 16
        if not (0 <= x < 256 and 0 <= z < 256):
            return None
        rot = nbt.get_tag(p, "Rotation")
        yaw, pitch = (float(rot[0].py_data), float(rot[1].py_data)) if rot is not None and len(rot) == 2 else (0.0, 0.0)
        hp = nbt.get(p, "HealF", nbt.get(p, "Health", 20))
        self.progress.warn(tr("Pocket Edition 0.8: the player keeps position and health, but not the inventory."))
        return nbt.CompoundTag({
            "Pos": nbt.ListTag([nbt.FloatTag(x), nbt.FloatTag(y), nbt.FloatTag(z)], 5),
            "Motion": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(0), nbt.FloatTag(0)], 5),
            "Rotation": nbt.ListTag([nbt.FloatTag(yaw), nbt.FloatTag(pitch)], 5),
            "Health": nbt.ShortTag(max(1, min(20, int(round(float(hp or 20)))))), "Dimension": nbt.IntTag(0),
            "OnGround": nbt.ByteTag(1), "Air": nbt.ShortTag(300), "Fire": nbt.ShortTag(-1),
            "FallDistance": nbt.FloatTag(0)})

    def finish(self, info: WorldInfo) -> str:
        header = bytearray(SECTOR)
        body = bytearray()
        sector = 1
        per = (CHUNK_BYTES + 4 + SECTOR - 1) // SECTOR  # 21
        for cz in range(32):
            for cx in range(32):
                data = self.chunks.get((cx, cz))
                if data is None and cx < 16 and cz < 16:
                    data = bytes(CHUNK_BYTES)
                if data is None:
                    continue
                i = cx + cz * 32
                header[i * 4] = per
                header[i * 4 + 1 : i * 4 + 4] = sector.to_bytes(3, "little")
                blob = struct.pack("<I", CHUNK_BYTES + 4) + data  # the length counts its own 4 bytes, as in every real save
                body += blob + bytes(per * SECTOR - len(blob))
                sector += per
        with open(os.path.join(self.out, "chunks.dat"), "wb") as f:
            f.write(bytes(header) + bytes(body))
        src = info.level
        lvl = nbt.CompoundTag({
            "LevelName": nbt.StringTag(self.world_name or info.name), "Platform": nbt.IntTag(2),
            "StorageVersion": nbt.IntTag(3), "GameType": nbt.IntTag(min(1, int(nbt.get(src, "GameType", 0) or 0))),
            "RandomSeed": nbt.LongTag(int(nbt.get(src, "RandomSeed", 0) or 0)),
            "Time": nbt.LongTag(int(nbt.get(src, "Time", 0) or 0)), "LastPlayed": nbt.LongTag(0),
            "SizeOnDisk": nbt.LongTag(0)})
        sx, sy, sz = info.spawn
        sx -= self.origin[0] * 16
        sz -= self.origin[1] * 16
        if not (0 <= sx < 256 and 0 <= sz < 256):
            sx, sz = 128, 128
        lvl["SpawnX"], lvl["SpawnY"], lvl["SpawnZ"] = nbt.IntTag(sx), nbt.IntTag(min(sy, 127)), nbt.IntTag(sz)
        player = self._player(info)
        if player is not None:
            lvl["Player"] = player
        payload = nbt.dump(lvl, "", little_endian=True)
        with open(os.path.join(self.out, "level.dat"), "wb") as f:
            f.write(struct.pack("<ii", 3, len(payload)) + payload)
        ent = nbt.dump(nbt.CompoundTag({"Entities": nbt.compound_list(self.ents),
                                        "TileEntities": nbt.compound_list(self.tiles)}), "", little_endian=True)
        with open(os.path.join(self.out, "entities.dat"), "wb") as f:
            f.write(b"ENT\x00" + struct.pack("<ii", 1, len(ent)) + ent)
        if self.replaced:
            self.progress.warn(tr("{n} blocks missing in Pocket Edition 0.8 were replaced.", n=self.replaced))
        n_ents, n_tiles = sum(self.dropped_ents.values()), sum(self.dropped_tiles.values())
        if n_ents or n_tiles or self.dropped_items:
            self.progress.warn(tr("Content that does not exist in {version}: removed {items} items, {entities} "
                                  "entities and {tiles} block entities.", version="Pocket Edition 0.8",
                                  items=self.dropped_items, entities=n_ents, tiles=n_tiles))
            names = ", ".join(f"{k} ×{v}" for k, v in (self.dropped_ents + self.dropped_tiles).most_common(8))
            if names:
                self.progress.log(tr("Left out of Pocket Edition 0.8: {names}", names=names))
        if self.skipped:
            self.progress.warn(tr("{n} chunks outside the 256×256 area of Pocket Edition 0.8 were left out (Overworld "
                                  "only, chunks 0..15).", n=self.skipped))
        return self.out

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
from typing import List, Optional, Tuple

import numpy as np

from .. import blocks as blk
from .. import nbt
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


def _read_le_nbt(path: str, header: int) -> Optional[nbt.CompoundTag]:
    if not os.path.exists(path):
        return None
    raw = open(path, "rb").read()
    try:
        return nbt.load(raw[header:], little_endian=True, compressed=False).tag
    except Exception:  # noqa: BLE001
        return None


class PEOldWorld(WorldSource):
    def __init__(self, path: str):
        self.path = path
        self.max_height = 128
        lvl = _read_le_nbt(os.path.join(path, "level.dat"), 8) or nbt.CompoundTag()
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
        from ..lce.world import legacy_items

        for t in c.tile_entities:
            tid = str(nbt.get(t, "id", "")).split(":", 1)[-1]
            tid = {"chest": "Chest", "furnace": "Furnace", "sign": "Sign"}.get(tid, tid)
            if tid in ("Chest", "Furnace", "Sign"):
                t = nbt.copy(t)
                t["id"] = nbt.StringTag(tid)
                if "Items" in t:
                    t["Items"] = legacy_items(t["Items"])
                self.tiles.append(t)
        for e in c.entities:
            eid = nbt.get(e, "id", "")
            num = PE_ENTITY_INV.get(eid)
            if num is None:
                continue
            e = nbt.copy(e)
            e["id"] = nbt.IntTag(num)
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
                blob = struct.pack("<I", CHUNK_BYTES) + data
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
        if self.skipped:
            self.progress.warn(tr("{n} chunks outside the 256×256 area of Pocket Edition 0.8 were left out (Overworld "
                                  "only, chunks 0..15).", n=self.skipped))
        return self.out

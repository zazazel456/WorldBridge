"""WorldBridge test matrix: every source format x every target, big worlds and broken input.

    python tools/matrix.py quick     # a few representative routes (~5 min)
    python tools/matrix.py full      # every source x every target (1-2 hours)
    python tools/matrix.py scale     # big worlds: time, memory, output size
    python tools/matrix.py robust    # corrupted / truncated / odd input, cancel, archives
    python tools/matrix.py all
    options: --out DIR (default ./matrix-out) --jobs N --real FILE_OR_DIR ... (your own saves as extra sources)

How it works
------------
1. A "golden" world is built in the converter's hub format (Java 1.12 numeric) with the content that
   converters usually break: double chests, enchanted / named items, written books, potions, dyed
   armour, signs with accents, beds, banners, flower pots, skulls, shulker boxes, spawners, jukebox,
   redstone, doors, stairs, tamed wolves, saddled horses, villagers, item frames, paintings, armour
   stands, chest minecarts, dropped items, a player with armour and ender chest, three dimensions,
   negative and very far coordinates.
2. It is written in every source format WorldBridge can produce (Java Anvil / McRegion / Alpha / 1.20
   / 26.x, Bedrock, every LCE console, Pocket Edition 0.x) plus Better than Adventure.
3. Every source is converted to every target; each output is re-detected, opened on the map and
   converted back to Java 1.12 to "probe" it: chunk counts, blocks, the chest items, the sign text,
   block entities, entities and the player.  Old-Java outputs are also read with a strict Alpha/Beta
   NBT reader; with WB_DFU_HARNESS set, Java outputs go through Minecraft 26.3's DataFixer.
4. Results go to <out>/report.md and <out>/results.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from worldbridge import nbt  # noqa: E402
from worldbridge.model import NETHER, OVERWORLD, THE_END, NumericChunk, Progress, WorldInfo, WorldSource  # noqa: E402

S, B, I, L, F, D, STR = (nbt.ShortTag, nbt.ByteTag, nbt.IntTag, nbt.LongTag, nbt.FloatTag, nbt.DoubleTag, nbt.StringTag)
MUSEUM = (0, 0)       # chunk with the block entities / entities
SIGN_TEXT = "WorldBridge àèé €"


# ============================================================ golden world
def _item(iid, count=1, damage=0, slot=None, tag=None):
    it = nbt.CompoundTag({"id": S(iid), "Count": B(count), "Damage": S(damage)})
    if slot is not None:
        it["Slot"] = B(slot)
    if tag is not None:
        it["tag"] = tag
    return it


def _lst(items, t=10):
    return nbt.ListTag(list(items), t)


def _pos(x, y, z):
    return _lst([D(x), D(y), D(z)], 6)


def _ent(eid, x, y, z, **extra):
    e = nbt.CompoundTag({"id": STR(eid), "Pos": _pos(x, y, z), "Motion": _pos(0, 0, 0),
                         "Rotation": _lst([F(0), F(0)], 5), "OnGround": B(1), "Air": S(300), "Fire": S(-1),
                         "UUIDMost": L(random.getrandbits(63)), "UUIDLeast": L(random.getrandbits(63))})
    for k, v in extra.items():
        e[k] = v
    return e


def _te(tid, x, y, z, **extra):
    t = nbt.CompoundTag({"id": STR(tid), "x": I(x), "y": I(y), "z": I(z)})
    for k, v in extra.items():
        t[k] = v
    return t


def chest_items():
    ench = nbt.CompoundTag({"ench": _lst([nbt.CompoundTag({"id": S(16), "lvl": S(5)})]),
                            "display": nbt.CompoundTag({"Name": STR("Excalibur")})})
    book = nbt.CompoundTag({"title": STR("Diario"), "author": STR("Steve"), "resolved": B(1),
                            "pages": _lst([STR('{"text":"Pagina uno"}'), STR('{"text":"Pagina due"}')], 8)})
    leather = nbt.CompoundTag({"display": nbt.CompoundTag({"color": I(0xFF0000)})})
    return [_item(264, 5, slot=0), _item(276, 1, slot=1, tag=ench), _item(387, 1, slot=2, tag=book),
            _item(373, 1, 8193, slot=3), _item(299, 1, slot=4, tag=leather), _item(4, 64, slot=5),
            _item(35, 12, 14, slot=6), _item(322, 3, 1, slot=7)]


class GoldenWorld(WorldSource):
    """Deterministic world with everything worth checking (hub = Java 1.12 numeric)."""

    def __init__(self, radius: int = 4, far: bool = True, dims=(OVERWORLD, NETHER, THE_END), seed: int = 1):
        self.radius = radius
        self.far = far
        self.dims = list(dims)
        self.seed = seed
        info = WorldInfo()
        info.level = nbt.CompoundTag({
            "LevelName": STR("Golden è"), "RandomSeed": L(424242), "SpawnX": I(8), "SpawnY": I(66), "SpawnZ": I(8),
            "GameType": I(0), "Time": L(6000), "DayTime": L(6000), "generatorName": STR("default"),
            "raining": B(0), "thundering": B(0), "Difficulty": B(2), "allowCommands": B(1),
        })
        info.players["host"] = nbt.CompoundTag({
            "Pos": _pos(8.5, 66.0, 8.5), "Rotation": _lst([F(90), F(0)], 5), "Dimension": I(0), "Health": F(18.0),
            "foodLevel": I(17), "XpLevel": I(12), "XpP": F(0.5), "XpTotal": I(250), "playerGameType": I(0),
            "Inventory": _lst([_item(276, 1, slot=0, tag=nbt.CompoundTag({"ench": _lst([nbt.CompoundTag({"id": S(16), "lvl": S(3)})])})),
                               _item(50, 64, slot=1), _item(364, 20, slot=2), _item(310, 1, slot=103),
                               _item(311, 1, slot=102), _item(312, 1, slot=101), _item(313, 1, slot=100)]),
            "EnderItems": _lst([_item(264, 32, slot=0)]),
            "SpawnX": I(8), "SpawnY": I(66), "SpawnZ": I(8),
        })
        # map #0 (in the item frame): a recognisable pattern of four colours
        cols = np.zeros(128 * 128, np.int8)
        cols[: 64 * 128] = 1 * 4 + 2  # grass
        cols[64 * 128:] = 12 * 4 + 2  # water
        info.extra_files["data/map_0.dat"] = nbt.dump(nbt.CompoundTag({"data": nbt.CompoundTag({
            "scale": B(0), "dimension": B(0), "width": S(128), "height": S(128), "xCenter": I(64), "zCenter": I(64),
            "colors": nbt.ByteArrayTag(cols)})}), "", compressed=True)
        self.info = info

    def dimensions(self):
        return list(self.dims)

    def chunk_coords(self, dim):
        r = self.radius if dim == OVERWORLD else max(1, self.radius // 2)
        out = [(x, z) for x in range(-r, r) for z in range(-r, r)]
        if self.far and dim == OVERWORLD:
            out += [(1000, 1000), (-1000, 500)]
        return out

    def read_chunk(self, dim, cx, cz):
        c = NumericChunk(cx, cz, 256)
        rng = np.random.default_rng(abs(hash((self.seed, dim, cx, cz))) % (2 ** 32))
        c.biomes = np.full((16, 16), {NETHER: 8, THE_END: 9}.get(dim, 4 if cx < 0 else 1), np.uint8)
        c.inhabited_time = 0 if abs(cx) + abs(cz) > 4 else 20 * 60 * 10
        if dim == NETHER:
            c.blocks[0] = 7
            c.blocks[1:40] = 87
            c.blocks[40:44] = 88
            c.blocks[120:128] = 7
            c.blocks[50, 5:8, 5:8] = 89
            return c
        if dim == THE_END:
            c.blocks[40:60] = 121
            c.blocks[60, 3, 3] = 49
            return c
        c.blocks[0] = 7
        c.blocks[1:60] = 1
        ore = rng.random((50, 16, 16)) < 0.02
        c.blocks[5:55][ore] = rng.choice([14, 15, 16, 56, 21, 73], size=int(ore.sum()))
        c.blocks[60:64] = 3
        c.blocks[64] = 2
        if (cx + cz) % 3 == 0:  # small pond and sand
            c.blocks[62:65, 2:6, 2:6] = 9
            c.blocks[61, 2:6, 2:6] = 12
        if (cx, cz) != MUSEUM and (cx * 7 + cz) % 4 == 0:  # a tree
            c.blocks[65:70, 10, 10] = 17
            c.blocks[68:72, 8:13, 8:13] = 18
            c.blocks[65:70, 10, 10] = 17
            c.data[68:72, 8:13, 8:13] = 4
        if (cx, cz) == MUSEUM:
            self._museum(c)
        if (cx, cz) == (-1, 0):  # wall behind the item frames (x = -1), or the game drops them
            c.blocks[65:69, 11:14, 15] = 1
        if (cx, cz) == (0, 1):  # wall behind the painting (z = 16)
            c.blocks[66:69, 0, 4:7] = 1
        if (cx, cz) == (1, 0):  # entities spread on another chunk
            c.entities.append(_ent("Cow", 24.5, 65.0, 8.5, Health=F(10)))
            c.entities.append(_ent("Sheep", 26.5, 65.0, 8.5, Color=B(11), Health=F(8)))
        return c

    def _museum(self, c: NumericChunk):
        def put(x, y, z, bid, data=0):
            c.blocks[y, z, x] = bid
            c.data[y, z, x] = data

        y = 65
        # double chest + items
        put(1, y, 1, 54, 3)
        put(2, y, 1, 54, 3)
        c.tile_entities.append(_te("Chest", 1, y, 1, Items=_lst(chest_items()), CustomName=STR("Tesoro")))
        c.tile_entities.append(_te("Chest", 2, y, 1, Items=_lst([_item(266, 10, slot=0)])))
        # standing sign with accents
        put(4, y, 1, 63, 8)
        c.tile_entities.append(_te("Sign", 4, y, 1, Text1=STR('{"text":"' + SIGN_TEXT + '"}'), Text2=STR('{"text":"Riga 2"}'),
                                   Text3=STR('{"text":""}'), Text4=STR('{"text":"fine"}')))
        # furnace with smelting items, dispenser, hopper, dropper
        put(6, y, 1, 61, 3)
        c.tile_entities.append(_te("Furnace", 6, y, 1, Items=_lst([_item(15, 8, slot=0), _item(263, 4, slot=1)]),
                                   BurnTime=S(0), CookTime=S(0), CookTimeTotal=S(200)))
        put(8, y, 1, 23, 3)
        c.tile_entities.append(_te("Trap", 8, y, 1, Items=_lst([_item(262, 16, slot=0)])))
        put(10, y, 1, 154, 0)
        c.tile_entities.append(_te("Hopper", 10, y, 1, Items=_lst([_item(265, 3, slot=0)]), TransferCooldown=I(0)))
        put(12, y, 1, 158, 3)
        c.tile_entities.append(_te("Dropper", 12, y, 1, Items=_lst([_item(288, 5, slot=0)])))
        # jukebox with record, spawner, note block
        put(1, y, 4, 84, 1)
        c.tile_entities.append(_te("RecordPlayer", 1, y, 4, Record=I(2256), RecordItem=_item(2256)))
        put(3, y, 4, 52)
        c.tile_entities.append(_te("MobSpawner", 3, y, 4, EntityId=STR("Zombie"), Delay=S(20)))
        put(5, y, 4, 25)
        c.tile_entities.append(_te("Music", 5, y, 4, note=B(12)))
        # bed (red), banner (with pattern), flower pot, skull, shulker box, ender chest, enchanting table
        put(7, y, 4, 26, 0)       # foot, facing south
        put(7, y, 5, 26, 8)       # head
        c.tile_entities.append(_te("Bed", 7, y, 4, color=I(14)))
        c.tile_entities.append(_te("Bed", 7, y, 5, color=I(14)))
        put(9, y, 4, 176, 0)
        c.tile_entities.append(_te("Banner", 9, y, 4, Base=I(1), Patterns=_lst([nbt.CompoundTag({"Pattern": STR("cr"), "Color": I(15)})])))
        put(11, y, 4, 140)
        c.tile_entities.append(_te("FlowerPot", 11, y, 4, Item=STR("minecraft:red_flower"), Data=I(0)))
        put(13, y, 4, 144, 1)
        c.tile_entities.append(_te("Skull", 13, y, 4, SkullType=B(4), Rot=B(0)))
        put(1, y, 7, 229, 1)      # red shulker box
        c.tile_entities.append(_te("ShulkerBox", 1, y, 7, Items=_lst([_item(264, 1, slot=0), _item(57, 2, slot=1)])))
        put(3, y, 7, 130, 2)
        c.tile_entities.append(_te("EnderChest", 3, y, 7))
        put(5, y, 7, 116)
        c.tile_entities.append(_te("EnchantTable", 5, y, 7))
        # redstone line: lever -> wire -> repeater -> lamp, piston, torch
        put(1, y, 10, 69, 5)
        put(2, y, 10, 55, 0)
        put(3, y, 10, 93, 1)
        put(4, y, 10, 123)
        put(6, y, 10, 33, 1)
        put(8, y, 10, 76, 5)
        # door (bottom + top), stairs, slabs, fence, glass pane, trapdoor, ladder, rail, torch on wall
        put(10, y, 10, 64, 1)
        put(10, y + 1, 10, 64, 8)
        put(12, y, 10, 53, 2)
        put(13, y, 10, 44, 0)
        put(14, y, 10, 43, 0)
        put(1, y, 13, 85)
        put(2, y, 13, 85)
        put(3, y, 13, 102)
        put(4, y, 13, 102)
        put(6, y, 13, 96, 4)
        put(8, y, 13, 66, 1)
        put(9, y, 13, 66, 1)
        put(11, y + 1, 13, 50, 1)
        # blocks from later versions (downgrades for old targets)
        for i, bid in enumerate((155, 168, 251, 235, 218, 198, 201, 165, 213, 216)):
            put(i, y - 1, 15, bid, 0)
        # entities: tamed wolf, saddled horse, villager, pig with saddle, chicken, zombie with armour,
        # item frame with item, painting, armour stand, chest minecart, boat, dropped item
        owner = {"OwnerUUID": STR("0f0e0d0c-0b0a-4908-8706-050403020100")}
        c.entities += [
            _ent("Wolf", 3.5, 66.0, 3.5, Sitting=B(1), CollarColor=B(14), Health=F(20), **{k: v for k, v in owner.items()}),
            _ent("EntityHorse", 6.5, 66.0, 6.5, Type=I(0), Variant=I(3), Tame=B(1), SaddleItem=_item(329),
                 ArmorItem=_item(418), Health=F(25), **owner),
            _ent("Villager", 9.5, 66.0, 6.5, Profession=I(1), Career=I(1), Health=F(20)),
            _ent("Pig", 12.5, 66.0, 6.5, Saddle=B(1), Health=F(10)),
            _ent("Chicken", 14.5, 66.0, 6.5, Health=F(4)),
            _ent("Zombie", 14.5, 66.0, 12.5, Health=F(20), CustomName=STR("Guardiano"), PersistenceRequired=B(1),
                 ArmorItems=_lst([_item(301), _item(300), _item(299), _item(298)]),
                 HandItems=_lst([_item(267), nbt.CompoundTag()])),
            _ent("ItemFrame", 0.03125, 66.5, 12.5, TileX=I(0), TileY=I(66), TileZ=I(12), Facing=B(3), Item=_item(345),
                 ItemRotation=B(0)),
            _ent("ItemFrame", 0.03125, 67.5, 12.5, TileX=I(0), TileY=I(67), TileZ=I(12), Facing=B(3),
                 Item=_item(358, 1, 0), ItemRotation=B(1)),
            _ent("Painting", 5.5, 67.0, 15.96875, TileX=I(5), TileY=I(67), TileZ=I(15), Facing=B(2), Motive=STR("Kebab")),
            _ent("ArmorStand", 8.5, 65.0, 12.5, ArmorItems=_lst([_item(317), _item(316), _item(315), _item(314)]),
                 ShowArms=B(1)),
            _ent("MinecartChest", 10.5, 65.5, 13.5, Items=_lst([_item(264, 7, slot=0)])),
            _ent("Boat", 4.5, 65.0, 12.5, Type=STR("oak")),
            _ent("Item", 12.5, 65.2, 12.5, Item=_item(388, 3), Health=S(5), Age=S(0), PickupDelay=S(0)),
        ]


def write_golden_numeric(path: str, kind: str = "anvil", limit: Optional[str] = None, **golden) -> str:
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions

    src = GoldenWorld(**golden)
    w = JavaNumericWriter(path, JavaWriteOptions(kind=kind, version_limit=limit), Progress())
    for dim in src.dimensions():
        for cx, cz in src.chunk_coords(dim):
            w.add_chunk(dim, src.read_chunk(dim, cx, cz))
    w.finish(src.info)
    return path


def write_golden_bta(path: str, radius: int = 3) -> str:
    sys.path.insert(0, ROOT)
    from tests.bta_helpers import BtaChunkBuilder, Byte, Float, Long, Short, item, write_gzip, write_region

    player = "0f0e0d0c-0b0a-4908-8706-050403020100"
    write_gzip(os.path.join(path, "level.dat"), {"Data": {
        "LevelName": "Golden BTA", "RandomSeed": Long(424242), "SpawnX": 8, "SpawnY": 129, "SpawnZ": 8,
        "Time": Long(6000), "version": 19135, "LastPlayerUUID": player}})
    write_gzip(os.path.join(path, "dimensions", "0", "dimension.dat"), {"Data": {"WorldType": "minecraft:overworld.extended"}})
    write_gzip(os.path.join(path, "players", player + ".dat"), {
        "Pos": [8.5, 129.0, 8.5], "Rotation": [Float(0), Float(0)], "Health": Short(20), "Dimension": 0,
        "Inventory": [item(16395, slot=0), item(16434, slot=103)]})
    chunks = {}
    for cx in range(-radius, radius):
        for cz in range(-radius, radius):
            c = BtaChunkBuilder(cx, cz)
            c.blocks[0] = 260
            c.blocks[1:128] = 1
            c.blocks[128] = 200
            chunks[(cx, cz)] = c
    c = chunks[(0, 0)]
    c.set(2, 129, 2, 682, 2)
    c.tiles.append({"id": "Chest", "x": 2, "y": 129, "z": 2, "Items": [item(16392, 5, slot=0)]})
    c.set(4, 129, 2, 710, 0)
    c.tiles.append({"id": "Sign", "x": 4, "y": 129, "z": 2, "Text1": "§4WorldBridge", "Text2": "", "Text3": "", "Text4": ""})
    c.entities.append({"id": "Pig", "Pos": [8.5, 129.0, 8.5], "Health": Short(10), "Saddle": Byte(1)})
    by_region: Dict[Tuple[int, int], list] = {}
    for (cx, cz), ch in chunks.items():
        by_region.setdefault((cx >> 5, cz >> 5), []).append(ch)
    for (rx, rz), lst in by_region.items():
        write_region(os.path.join(path, "dimensions", "0", "region", f"r.{rx}.{rz}.mcr"), lst)
    return path


# ============================================================ sources and targets
def _convert(src, out, **target):
    from worldbridge.convert import TargetSpec, convert

    return convert(src, out, TargetSpec(**target), Progress())


SOURCES = {
    # name: (builder(dir, base_golden_anvil) -> path, description)
    "java_anvil_1.12": "golden world, Java 1.12 Anvil (numeric)",
    "java_mcregion": "Java Beta 1.3-1.1 McRegion",
    "java_alpha": "Java Alpha / Beta 1.2 (World1)",
    "java_1.20.1": "Java 1.20.1 (Amulet)",
    "java_26.3": "Java 26.3 (Amulet)",
    "bedrock_latest": "Bedrock 26.50",
    "bedrock_1.16": "Bedrock 1.16.220",
    "lce_win64_tu31": "LCE PC neoLegacy (saveData.ms, TU31)",
    "lce_xbox360": "LCE Xbox 360 (savegame.dat)",
    "lce_ps3": "LCE PS3 (GAMEDATA)",
    "lce_vita": "LCE PS Vita",
    "lce_wiiu": "LCE Wii U",
    "lce_ps4": "LCE PS4 (split save)",
    "lce_xboxone": "LCE Xbox One",
    "lce_switch": "LCE Switch",
    "pe_old": "Pocket Edition 0.8 chunks.dat",
    "bta": "Better than Adventure 8.0.1",
}

TARGETS = {
    # name: TargetSpec kwargs
    "java_auto": dict(family="java"),
    "java_1.20.1": dict(family="java", java_mode="amulet", version=(1, 20, 1)),
    "java_1.16.5": dict(family="java", java_mode="amulet", version=(1, 16, 5)),
    "java_1.12": dict(family="java", java_mode="numeric", java_version_limit="1.12"),
    "java_1.8": dict(family="java", java_mode="numeric", java_version_limit="1.8"),
    "java_1.0_mcregion": dict(family="java", java_mode="mcregion", java_version_limit="1.0"),
    "java_b1.7_mcregion": dict(family="java", java_mode="mcregion", java_version_limit="b1.7"),
    "java_b1.2_alpha": dict(family="java", java_mode="alpha", java_version_limit="b1.2"),
    "bedrock_latest": dict(family="bedrock"),
    "bedrock_1.18.30": dict(family="bedrock", version=(1, 18, 30)),
    # LCE maps are filled whole around the converted world (up to 100,000 chunks): here the content is
    # compared, the filling has its own case in "robust" and tests/test_border.py
    "lce_win64_tu31": dict(family="lce", lce_platform="win64", lce_profile="tu31", ring=False),
    "lce_xbox360": dict(family="lce", lce_platform="xbox360", lce_profile="tu54", ring=False),
    "lce_ps3": dict(family="lce", lce_platform="ps3", lce_profile="tu54", ring=False),
    "lce_vita": dict(family="lce", lce_platform="vita", lce_profile="tu54", ring=False),
    "lce_wiiu": dict(family="lce", lce_platform="wiiu", lce_profile="tu54", ring=False),
    "lce_ps4": dict(family="lce", lce_platform="ps4", lce_profile="tu54", ring=False),
    "lce_switch": dict(family="lce", lce_platform="switch", lce_profile="tu54", ring=False),
    "pe_old": dict(family="pe_old"),
}

QUICK = [("java_anvil_1.12", t) for t in ("java_auto", "java_1.20.1", "bedrock_latest", "lce_win64_tu31", "java_b1.2_alpha", "pe_old")] + \
        [("lce_win64_tu31", "java_auto"), ("lce_ps3", "bedrock_latest"), ("bedrock_latest", "java_auto"),
         ("bedrock_latest", "lce_win64_tu31"), ("java_26.3", "lce_xbox360"), ("java_alpha", "java_auto"),
         ("pe_old", "java_auto"), ("bta", "java_auto")]


def build_source(name: str, base: str, work: str) -> str:
    """Returns the path of source ``name`` (built once, from the golden Anvil world)."""
    out = os.path.join(work, "sources", name)
    marker = out + ".ok"
    if os.path.exists(marker):
        return open(marker).read().strip()
    if name == "java_anvil_1.12":
        return base
    shutil.rmtree(out, ignore_errors=True)
    if name == "bta":
        path = write_golden_bta(out)
    elif name == "java_mcregion":
        path = write_golden_numeric(out, "mcregion", "1.1")
    elif name == "java_alpha":
        path = write_golden_numeric(os.path.join(out, "World1"), "alpha", "b1.2")
    else:
        spec = {"java_1.20.1": dict(family="java", java_mode="amulet", version=(1, 20, 1)),
                "java_26.3": dict(family="java", java_mode="amulet"),
                "bedrock_latest": dict(family="bedrock"),
                "bedrock_1.16": dict(family="bedrock", version=(1, 16, 220)),
                "pe_old": dict(family="pe_old")}.get(name)
        if spec is None and name.startswith("lce_"):
            plat = name.split("_")[1]
            spec = dict(family="lce", lce_platform=plat, lce_profile="tu31" if plat == "win64" else "tu54", ring=False)
        _convert(base, out, **spec)
        path = out
        if name.startswith("lce_"):
            files = [os.path.join(r, f) for r, _d, fs in os.walk(out) for f in fs]
            main = [f for f in files if os.path.basename(f) in ("saveData.ms", "savegame.dat", "GAMEDATA")]
            path = main[0] if main else out
    with open(marker, "w") as f:
        f.write(path)
    return path


# ============================================================ probing an output
def _hub_view(path: str, tmp: str):
    """Opens ``path`` as a hub (Java 1.12 numeric) world, converting it if needed."""
    from worldbridge import detect as det
    from worldbridge.java.numeric import JavaNumericWorld

    d = det.detect(path)
    if d is not None and d.kind == "java_numeric" and d.subkind == "anvil":
        return JavaNumericWorld(d.path)
    back = os.path.join(tmp, "probe")
    shutil.rmtree(back, ignore_errors=True)
    _convert(path, back, family="java", java_mode="numeric", java_version_limit="1.12")
    return JavaNumericWorld(back)


def _item_id(t) -> int:
    """Numeric id of a hub item: Java 1.8 - 1.12 data carries registry names (minecraft:diamond)."""
    from worldbridge import items as witems

    v = nbt.get(t, "id", 0)
    if isinstance(v, str):
        name = v.split(":")[-1]
        return next((i for i, n in witems._registry_names().items() if n == name), -1)
    return int(v or 0)


def probe(path: str, tmp: str) -> Dict[str, object]:
    """What survived: counts and presence checks (True / False / number)."""
    r: Dict[str, object] = {}
    w = _hub_view(path, tmp)
    for dim in (OVERWORLD, NETHER, THE_END):
        r[f"chunks_{dim}"] = len(w.chunk_coords(dim)) if dim in w.dimensions() else 0
    c, museum = _find_museum(w)
    if c is None:
        r["museum"] = False
        return r
    r["museum"] = True
    tes = {nbt.get(t, "id"): t for t in c.tile_entities}
    dy = next(int(nbt.get(t, "y")) - 65 for t in c.tile_entities if nbt.get(t, "id") == "Chest"
              and (int(nbt.get(t, "x")) & 15, int(nbt.get(t, "z")) & 15) == (1, 1))
    r["y_shift"] = dy
    tes_by_pos = {(int(nbt.get(t, "x")) & 15, int(nbt.get(t, "y")) - dy, int(nbt.get(t, "z")) & 15): t for t in c.tile_entities}
    r["stone_blocks"] = int((c.blocks[1:55] == 1).sum())
    chest = tes_by_pos.get((1, 65, 1))
    items = {_item_id(i): i for i in (nbt.get_tag(chest, "Items") or [])} if chest is not None else {}
    r["chest"] = chest is not None
    r["chest_diamonds"] = int(nbt.get(items[264], "Count")) if 264 in items else 0
    sword = items.get(276)
    r["enchant"] = bool(sword is not None and "ench" in str(nbt.get_tag(sword, "tag")))
    r["item_name"] = bool(sword is not None and "Excalibur" in str(nbt.get_tag(sword, "tag")))
    r["written_book"] = bool(387 in items and "Pagina" in str(nbt.get_tag(items[387], "tag")))
    r["potion"] = 373 in items
    r["double_chest"] = (2, 65, 1) in tes_by_pos
    sign = tes_by_pos.get((4, 65, 1))
    r["sign_text"] = bool(sign is not None and "WorldBridge" in str(nbt.get(sign, "Text1", "")))
    r["sign_accents"] = bool(sign is not None and "àèé" in str(nbt.get(sign, "Text1", "")))
    for tid in ("Furnace", "Trap", "Hopper", "Dropper", "RecordPlayer", "MobSpawner", "Bed", "Banner", "FlowerPot",
                "Skull", "ShulkerBox", "EnderChest", "EnchantTable", "Music"):
        r[f"te_{tid}"] = tid in tes
    pot = tes_by_pos.get((11, 65, 4))
    r["pot_plant"] = bool(pot is not None and str(nbt.get(pot, "Item", "")).split(":")[-1] in ("red_flower", "38")
                          and int(nbt.get(pot, "Data", -1)) == 0)
    music = tes_by_pos.get((5, 65, 4))
    r["note_pitch"] = bool(music is not None and int(nbt.get(music, "note", 0)) == 12)
    r["blocks_redstone"] = bool(c.blocks[65 + dy, 10, 2] == 55)
    r["blocks_door"] = bool(c.blocks[65 + dy, 10, 10] == 64 and c.blocks[66 + dy, 10, 10] == 64)
    ents: Dict[str, int] = {}
    for dd, cc in ((0, museum), (0, (museum[0] + 1, museum[1]))):
        try:
            ch = w.read_chunk(dd, *cc)
        except Exception:  # noqa: BLE001
            ch = None
        for e in (ch.entities if ch else []):
            k = str(nbt.get(e, "id", "?"))
            ents[k] = ents.get(k, 0) + 1
    for eid in ("Wolf", "EntityHorse", "Villager", "Pig", "Chicken", "Zombie", "ItemFrame", "Painting", "ArmorStand",
                "MinecartChest", "Boat", "Item", "Cow", "Sheep"):
        r[f"ent_{eid}"] = ents.get(eid, 0) > 0
    frames = [e for e in c.entities if nbt.get(e, "id") == "ItemFrame"]
    r["frame_map"] = any(_item_id(nbt.get_tag(f, "Item") or nbt.CompoundTag()) == 358 for f in frames)
    r["map_data"] = False
    for mp in (os.path.join(w.path, "data", "map_0.dat"),):
        try:
            cols = nbt.get_tag(nbt.get_tag(nbt.load(open(mp, "rb").read()).tag, "data"), "colors")
            r["map_data"] = bool(cols is not None and int(np.asarray(cols)[0]) == 6 and int(np.asarray(cols)[-1]) == 50)
        except Exception:  # noqa: BLE001
            pass
    wolf = [e for e in c.entities if nbt.get(e, "id") == "Wolf"]
    r["wolf_owner"] = bool(wolf and (nbt.get(wolf[0], "OwnerUUID") or "OwnerUUIDMost" in wolf[0] or "Owner" in wolf[0]))
    r["wolf_sitting"] = bool(wolf and int(nbt.get(wolf[0], "Sitting", 0) or 0))
    p = next(iter(w.info.players.values()), None) if w.info.players else None
    inv = {_item_id(i): i for i in (nbt.get_tag(p, "Inventory") or [])} if p is not None else {}
    r["player"] = p is not None
    r["player_sword"] = 276 in inv
    r["player_armor"] = any(int(nbt.get(i, "Slot", 0)) >= 100 for i in inv.values())
    r["player_enderchest"] = bool(p is not None and len(nbt.get_tag(p, "EnderItems") or []) > 0)
    return r


def _find_museum(w):
    """The chunk with the golden chest: (0, 0), unless the target moved the world (finite worlds)."""
    coords = w.chunk_coords(OVERWORLD) if OVERWORLD in w.dimensions() else []
    order = sorted(coords, key=lambda c: (c != MUSEUM, abs(c[0]) + abs(c[1])))
    for cx, cz in order[:400]:
        try:
            ch = w.read_chunk(OVERWORLD, cx, cz)
        except Exception:  # noqa: BLE001
            continue
        if ch is None:
            continue
        for t in ch.tile_entities:
            if nbt.get(t, "id") == "Chest" and (int(nbt.get(t, "x")) & 15, int(nbt.get(t, "z")) & 15) == (1, 1) \
                    and int(nbt.get(t, "y")) in (64, 65, 66):  # the old sea (Alpha/Beta, PE) moves worlds by one
                return ch, (cx, cz)
    return None, MUSEUM


# documented limits: not counted as failures
KNOWN_LIMITS = {"pe_old": {"player_sword"}}

CORE = ("museum", "chest", "chest_diamonds", "sign_text", "player", "player_sword")


def check_output(target: str, out: str, tmp: str) -> Dict[str, object]:
    """Target-specific structural checks."""
    from worldbridge import detect as det
    from worldbridge.mapview import open_map

    res: Dict[str, object] = {}
    d = det.detect(out)
    res["detected"] = d.kind if d else None
    try:
        m = open_map(out)
        dims = m.dimensions()
        res["map_dims"] = dims
        coords = m.chunk_coords(OVERWORLD) if OVERWORLD in dims else []
        res["map_tile"] = bool(coords) and m.tile(OVERWORLD, *coords[len(coords) // 2]) is not None
        m.close()
    except Exception as ex:  # noqa: BLE001
        res["map_error"] = str(ex)[:200]
    if target in ("java_b1.2_alpha", "java_b1.7_mcregion", "java_1.0_mcregion"):
        res["strict_old_nbt"] = _strict_old(out)
    harness = os.environ.get("WB_DFU_HARNESS")
    if harness and target.startswith("java_") and target not in ("java_b1.2_alpha", "java_b1.7_mcregion", "java_1.0_mcregion"):
        try:
            p = subprocess.run([harness, out], capture_output=True, text=True, timeout=3600)
            last = [ln for ln in p.stdout.splitlines() if ln.startswith("OK ")]
            res["dfu"] = last[-1] if last else ("ERROR " + p.stdout[-300:] + p.stderr[-300:])
        except Exception as ex:  # noqa: BLE001
            res["dfu"] = f"ERROR {ex}"
    return res


def _strict_old(world: str) -> str:
    from tests.strict_old_nbt import Unreadable, load
    from worldbridge.java.region import JavaRegion

    try:
        load(open(os.path.join(world, "level.dat"), "rb").read())
        n = 0
        for root, _d, files in os.walk(world):
            for f in files:
                p = os.path.join(root, f)
                if f.startswith("c.") and f.endswith(".dat"):
                    load(open(p, "rb").read())
                    n += 1
                elif f.endswith(".mcr"):
                    reg = JavaRegion(p)
                    for lx, lz in reg.chunks():
                        load(reg.read(lx, lz), gz=False)
                        n += 1
        return f"OK {n}"
    except Unreadable as ex:
        return f"UNREADABLE {ex}"


# ============================================================ one conversion (worker process)
def run_case(source: str, src_path: str, target: str, work: str) -> Dict[str, object]:
    random.seed(1)
    case = f"{source}__{target}"
    out = os.path.join(work, "out", case)
    tmp = os.path.join(work, "tmp", case)
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    res: Dict[str, object] = {"source": source, "target": target}
    if source == "bta" and not target.startswith("java_auto"):
        res["status"] = "n/a"
        res["note"] = "BTA converte solo verso Java 26.3"
        return res
    t0 = time.time()
    try:
        r = _convert(src_path, out, **TARGETS[target])
        res["seconds"] = round(time.time() - t0, 1)
        res["chunks"] = r.chunks
        res["warnings"] = r.warnings
    except Exception as ex:  # noqa: BLE001
        res["status"] = "CONVERT_FAIL"
        res["error"] = f"{type(ex).__name__}: {ex}"
        res["trace"] = traceback.format_exc()[-2000:]
        return res
    res["size_mb"] = round(_size(out) / 2 ** 20, 2)
    res.update(check_output(target, out, tmp))
    if source == "bta":
        res["status"] = "OK" if res.get("detected") else "FAIL"
        return res
    try:
        res["probe"] = probe(out, tmp)
    except Exception as ex:  # noqa: BLE001
        res["status"] = "PROBE_FAIL"
        res["error"] = f"{type(ex).__name__}: {ex}"
        res["trace"] = traceback.format_exc()[-2000:]
        return res
    known = KNOWN_LIMITS.get(target, set()) | KNOWN_LIMITS.get(source, set())
    bad = [k for k in CORE if not res["probe"].get(k) and k not in known]
    if str(res.get("strict_old_nbt", "OK")).startswith("UNREADABLE") or (res.get("dfu") and "FAIL 0" not in str(res["dfu"])):
        bad.append("validation")
    res["status"] = "OK" if not bad else "FAIL"
    res["failed_core"] = bad
    shutil.rmtree(tmp, ignore_errors=True)
    return res


def _size(path: str) -> int:
    return sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(path) for f in fs) if os.path.isdir(path) \
        else os.path.getsize(path)


# ============================================================ scale
def run_scale(work: str) -> List[Dict[str, object]]:
    import resource

    rows = []
    cases = [("anvil_4096", dict(radius=32, far=False)), ("anvil_16384", dict(radius=64, far=False))]
    for name, golden in cases:
        base = os.path.join(work, "scale", name)
        if not os.path.exists(os.path.join(base, "level.dat")):
            t0 = time.time()
            write_golden_numeric(base, **golden)
            rows.append({"case": f"build {name}", "seconds": round(time.time() - t0, 1), "size_mb": round(_size(base) / 2 ** 20, 1)})
        for target in ("java_auto", "lce_win64_tu31", "bedrock_latest"):
            if name == "anvil_16384" and target == "bedrock_latest" and os.environ.get("WB_SCALE_SKIP_SLOW"):
                continue
            out = os.path.join(work, "scale", f"{name}__{target}")
            shutil.rmtree(out, ignore_errors=True)
            t0 = time.time()
            status = "OK"
            try:
                r = _convert(base, out, **TARGETS[target])
                chunks = r.chunks
            except Exception as ex:  # noqa: BLE001
                status, chunks = f"FAIL {ex}", 0
            rss = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
            rows.append({"case": f"{name} → {target}", "status": status, "chunks": chunks,
                         "seconds": round(time.time() - t0, 1), "chunks_per_s": round(chunks / max(0.1, time.time() - t0), 1),
                         "peak_rss_mb": round(rss / 1024, 0), "size_mb": round(_size(out) / 2 ** 20, 1) if os.path.exists(out) else 0})
            print(rows[-1], flush=True)
        # map + trim on the big world
        from worldbridge import trim
        from worldbridge.mapview import open_map

        t0 = time.time()
        m = open_map(base)
        coords = m.chunk_coords(OVERWORLD)
        for cx, cz in coords[:2000]:
            m.tile(OVERWORLD, cx, cz)
        m.close()
        rows.append({"case": f"{name} map 2000 tiles", "seconds": round(time.time() - t0, 1)})
        t0 = time.time()
        sc = trim.scan(base)
        keep = trim.plan(sc)
        rows.append({"case": f"{name} trim scan", "seconds": round(time.time() - t0, 1), "summary": trim.summary(sc, keep)})
        print(rows[-2:], flush=True)
    # big BTA world
    bta = os.path.join(work, "scale", "bta_4096")
    if not os.path.exists(os.path.join(bta, "level.dat")):
        write_golden_bta(bta, radius=32)
    out = bta + "__java"
    shutil.rmtree(out, ignore_errors=True)
    t0 = time.time()
    r = _convert(bta, out, family="java")
    rows.append({"case": "bta_4096 → java 26.3", "chunks": r.chunks, "seconds": round(time.time() - t0, 1),
                 "chunks_per_s": round(r.chunks / max(0.1, time.time() - t0), 1)})
    print(rows[-1], flush=True)
    return rows


# ============================================================ robustness
def run_robust(work: str, base: str) -> List[Dict[str, object]]:
    from worldbridge.model import ConversionCancelled, ConversionError

    rows = []
    rdir = os.path.join(work, "robust")
    shutil.rmtree(rdir, ignore_errors=True)
    os.makedirs(rdir)

    def case(name, fn):
        t0 = time.time()
        try:
            note = fn()
            rows.append({"case": name, "status": "OK", "note": note, "seconds": round(time.time() - t0, 1)})
        except Exception as ex:  # noqa: BLE001
            rows.append({"case": name, "status": "FAIL", "note": f"{type(ex).__name__}: {ex}",
                         "trace": traceback.format_exc()[-1500:]})
        print(rows[-1]["case"], rows[-1]["status"], rows[-1].get("note", ""), flush=True)

    def corrupt_copy(name, mutate):
        w = os.path.join(rdir, name)
        shutil.copytree(base, w)
        mutate(w)
        return w

    def garbage_chunk(w):
        p = os.path.join(w, "region", "r.0.0.mca")
        data = bytearray(open(p, "rb").read())
        off = (int.from_bytes(data[0:4], "big") >> 8) * 4096
        data[off + 5:off + 200] = os.urandom(195)
        open(p, "wb").write(data)

    def expect_ok(w, **target):
        out = w + "__out_" + target.get("family", "")
        r = _convert(w, out, **target)
        return f"{r.chunks} chunk, avvisi: {len(r.warnings)} {' | '.join(r.warnings)[:160]}"

    case("chunk con dati casuali → java", lambda: expect_ok(corrupt_copy("garbage", garbage_chunk), family="java"))
    case("chunk con dati casuali → bedrock", lambda: expect_ok(corrupt_copy("garbage_b", garbage_chunk), family="bedrock"))

    def truncate(w):
        p = os.path.join(w, "region", "r.-1.-1.mca")
        data = open(p, "rb").read()
        open(p, "wb").write(data[:len(data) // 2])

    case("file regione troncato a metà → java", lambda: expect_ok(corrupt_copy("trunc", truncate), family="java"))

    def tiny_region(w):
        open(os.path.join(w, "region", "r.5.5.mca"), "wb").write(b"\x00" * 100)

    case("file regione di 100 byte → lce", lambda: expect_ok(corrupt_copy("tiny", tiny_region), family="lce", ring=False))

    def no_level(w):
        os.remove(os.path.join(w, "level.dat"))

    def expect_error(w, **target):
        try:
            _convert(w, w + "__out", **target)
        except ConversionError as ex:
            return f"errore chiaro: {ex}"
        return "convertito comunque"

    case("mondo senza level.dat", lambda: expect_error(corrupt_copy("nolevel", no_level), family="java"))

    def unicode_path():
        w = os.path.join(rdir, "Mondo di prova è € 日本")
        shutil.copytree(base, w)
        return expect_ok(w, family="bedrock")

    case("percorso con spazi e unicode", unicode_path)

    def zip_input():
        z = os.path.join(rdir, "mondo.zip")
        with zipfile.ZipFile(z, "w") as zf:
            for r, _d, fs in os.walk(base):
                for f in fs:
                    zf.write(os.path.join(r, f), os.path.join("Mondo", os.path.relpath(os.path.join(r, f), base)))
        r = _convert(z, os.path.join(rdir, "zip_out"), family="lce", ring=False)
        return f"{r.chunks} chunk"

    case("archivio .zip come sorgente", zip_input)

    def level_dat_input():
        r = _convert(os.path.join(base, "level.dat"), os.path.join(rdir, "leveldat_out"), family="java",
                     java_mode="numeric", java_version_limit="1.8")
        return f"{r.chunks} chunk"

    case("level.dat scelto al posto della cartella", level_dat_input)

    def non_empty_output():
        out = os.path.join(rdir, "nonempty")
        os.makedirs(out)
        open(os.path.join(out, "x.txt"), "w").write("x")
        try:
            _convert(base, out, family="java")
        except ConversionError as ex:
            return f"rifiutato: {ex}"
        raise AssertionError("ha scritto in una cartella non vuota")

    case("cartella di destinazione non vuota", non_empty_output)

    def cancel():
        from worldbridge.convert import TargetSpec, convert

        big = os.path.join(rdir, "cancel_src")
        write_golden_numeric(big, radius=24, far=False)
        p = Progress()
        import threading

        threading.Timer(2.0, p.cancel).start()
        out = os.path.join(rdir, "cancel_out")
        try:
            convert(big, out, TargetSpec(family="bedrock"), p)
        except ConversionCancelled:
            leftovers = [n for n in os.listdir(rdir) if n.startswith(".worldbridge_")]
            return f"annullato; cartelle temporanee rimaste: {len(leftovers)}"
        return "terminato prima dell'annullamento"

    case("annullamento a metà", cancel)

    def selection_combo():
        from worldbridge.selection import PlayerLink, Selection
        from worldbridge.trim import TrimOptions

        sel = Selection(chunks={OVERWORLD: {(0, 0), (1, 0), (-1, -1)}}, spawn=(20, 70, 5),
                        players=[PlayerLink(key="host", host=True, nickname="Steve", online=False)])
        r = _convert(base, os.path.join(rdir, "sel_out"), family="java", selection=sel, trim=TrimOptions())
        return f"{r.chunks} chunk"

    case("selezione + spawn + giocatore + trim", selection_combo)

    def same_format_lce():
        lce = os.path.join(work, "sources", "lce_win64_tu31")
        files = [os.path.join(r, f) for r, _d, fs in os.walk(lce) for f in fs if f == "saveData.ms"]
        if not files:
            return "sorgente LCE non costruita"
        r = _convert(files[0], os.path.join(rdir, "lce_same"), family="lce", lce_platform="win64", lce_profile="tu31", ring=False)
        return f"{r.chunks} chunk"

    case("LCE → stesso LCE (senza perdite)", same_format_lce)

    def far_coords_lce():
        r = _convert(base, os.path.join(rdir, "far_lce"), family="lce", lce_platform="xbox360", lce_profile="tu54", ring=False)
        return f"{r.chunks} chunk; avvisi: {'; '.join(r.warnings)[:200]}"

    case("coordinate lontane → LCE (mondo finito)", far_coords_lce)

    def lce_filled():
        r = _convert(base, os.path.join(rdir, "lce_fill"), family="lce", lce_platform="xbox360", lce_profile="tu54")
        from worldbridge import detect as det
        from worldbridge.lce.world import LCEWorld

        n = len(LCEWorld(det.detect(os.path.join(rdir, "lce_fill")).path).chunk_coords(0))
        if n != 54 * 54:
            raise AssertionError(f"{n} chunk invece di {54 * 54}")
        return f"{r.chunks} chunk convertiti, mappa intera {n} chunk"

    case("LCE: mappa riempita tutta (nessun bordo scoperto)", lce_filled)
    return rows


# ============================================================ report
def write_report(work: str, results: List[dict], extra: Dict[str, List[dict]]) -> str:
    with open(os.path.join(work, "results.json"), "w") as f:
        json.dump({"matrix": results, **extra}, f, indent=1, default=str)
    lines = ["# WorldBridge – risultati della matrice di test", ""]
    if results:
        ok = sum(1 for r in results if r.get("status") == "OK")
        lines.append(f"Conversioni: **{ok} OK** su {len(results)} (n/a: {sum(1 for r in results if r.get('status') == 'n/a')})\n")
        lines.append("| sorgente | destinazione | esito | s | chunk | MB | persi rispetto al campione |")
        lines.append("|---|---|---|---:|---:|---:|---|")
        base = next((r["probe"] for r in results if r.get("source") == "java_anvil_1.12" and r.get("target") == "java_1.12"
                     and r.get("probe")), None)
        for r in sorted(results, key=lambda r: (r["source"], r["target"])):
            lost = ""
            if r.get("probe") and base:
                lost = ", ".join(k for k, v in base.items() if v and not r["probe"].get(k) and not k.startswith("chunks_"))
            status = r.get("status", "?")
            if r.get("failed_core"):
                status += " (" + ",".join(r["failed_core"]) + ")"
            if r.get("error"):
                status += f" – {r['error'][:120]}"
            lines.append(f"| {r['source']} | {r['target']} | {status} | {r.get('seconds', '')} | {r.get('chunks', '')} | "
                         f"{r.get('size_mb', '')} | {lost} |")
    for name, rows in extra.items():
        lines += ["", f"## {name}", ""]
        for row in rows:
            lines.append("- " + " · ".join(f"{k}: {v}" for k, v in row.items() if k != "trace"))
    path = os.path.join(work, "report.md")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["quick", "full", "scale", "robust", "all"])
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "matrix-out"))
    ap.add_argument("--jobs", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    ap.add_argument("--real", action="append", default=[], help="extra real saves used as sources")
    ap.add_argument("--only", default=None, help="substring filter on source__target")
    a = ap.parse_args(argv)
    work = os.path.abspath(a.out)
    os.makedirs(work, exist_ok=True)
    base = os.path.join(work, "sources", "java_anvil_1.12")
    if not os.path.exists(os.path.join(base, "level.dat")):
        write_golden_numeric(base)
    extra: Dict[str, List[dict]] = {}
    results: List[dict] = []
    if a.mode in ("quick", "full", "all"):
        pairs = QUICK if a.mode == "quick" else [(s, t) for s in SOURCES for t in TARGETS]
        for r in a.real:
            pairs += [(f"real:{r}", t) for t in ("java_auto", "bedrock_latest", "lce_win64_tu31", "java_1.12")]
        if a.only:
            pairs = [p for p in pairs if a.only in f"{p[0]}__{p[1]}"]
        srcs = {}
        for s, _t in pairs:
            if s not in srcs:
                t0 = time.time()
                srcs[s] = s[5:] if s.startswith("real:") else build_source(s, base, work)
                print(f"sorgente {s}: {srcs[s]} ({time.time() - t0:.0f}s)", flush=True)
        import multiprocessing as mp

        with ProcessPoolExecutor(max_workers=a.jobs, mp_context=mp.get_context("spawn")) as ex:
            futs = {ex.submit(run_case, s.replace("/", "_").replace("real:", "real_"), srcs[s], t, work): (s, t) for s, t in pairs}
            for i, f in enumerate(as_completed(futs), 1):
                s, t = futs[f]
                try:
                    r = f.result()
                except Exception as e:  # noqa: BLE001
                    r = {"source": s, "target": t, "status": "CRASH", "error": str(e)}
                results.append(r)
                print(f"[{i}/{len(futs)}] {s} → {t}: {r.get('status')} {r.get('error', '')[:150]} "
                      f"{r.get('failed_core', '')} {r.get('seconds', '')}s", flush=True)
                write_report(work, results, extra)
    if a.mode in ("robust", "all"):
        build_source("lce_win64_tu31", base, work)
        extra["Robustezza"] = run_robust(work, base)
    if a.mode in ("scale", "all"):
        extra["Mondi grandi"] = run_scale(work)
    path = write_report(work, results, extra)
    print("report:", path)


if __name__ == "__main__":
    main()

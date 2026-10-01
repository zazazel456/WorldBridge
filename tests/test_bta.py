"""Better than Adventure -> Java 26.3."""
import os

import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.bta import nbtio, text
from worldbridge.bta.convert import BtaOptions, convert_world, self_test
from worldbridge.bta.palette import Palette
from worldbridge.bta.world import looks_like_bta
from worldbridge.convert import TargetSpec, convert
from worldbridge.detect import detect
from worldbridge.java.region import JavaRegion
from worldbridge.mapview import _unpack
from worldbridge.model import ConversionError, NETHER, OVERWORLD
from worldbridge.selection import PlayerLink, Selection, offline_uuid

from .bta_helpers import BtaChunkBuilder, Byte, Float, Long, Short, item, write_gzip, write_region

PLAYER = "0f0e0d0c-0b0a-4908-8706-050403020100"


def make_bta_world(root) -> str:
    w = str(root / "bta")
    write_gzip(os.path.join(w, "level.dat"), {"Data": {
        "LevelName": "Casa BTA", "RandomSeed": Long(1234), "SpawnX": 8, "SpawnY": 129, "SpawnZ": 8, "Time": Long(6000),
        "TotalTime": Long(90000), "version": 19135, "LastPlayerUUID": PLAYER, "Difficulty": Byte(1)}})
    write_gzip(os.path.join(w, "dimensions", "0", "dimension.dat"), {"Data": {"WorldType": "minecraft:overworld.extended"}})
    write_gzip(os.path.join(w, "players", PLAYER + ".dat"), {
        "Pos": [8.5, 129.0, 8.5], "Rotation": [Float(90), Float(0)], "Health": Short(15), "Dimension": 0,
        "Gamemode": "minecraft:gamemode/creative", "Inventory": [
            item(16395, damage=100, slot=0), item(16434, slot=103), item(16437, slot=100)]})
    chunks = []
    for cx, cz in ((0, 0), (1, 0), (0, 1), (1, 1)):
        c = BtaChunkBuilder(cx, cz)
        c.blocks[0] = 260           # bedrock
        c.blocks[1:128] = 1         # stone
        c.blocks[128] = 200         # grass
        c.biome[:] = 0 if cx == 0 else 1
        chunks.append(c)
    c = chunks[0]
    c.set(1, 129, 1, 720)                       # snow layer on grass
    c.set(5, 129, 5, 161, 3)                    # cobble stairs facing north...
    c.set(5, 129, 4, 161, 0)                    # ...with an east facing stair behind it: outer corner
    c.set(8, 129, 8, 80)                        # two oak fences
    c.set(9, 129, 8, 80)
    c.set(12, 129, 12, 280)                     # log + leaves
    c.set(12, 130, 12, 290)
    c.set(14, 140, 14, 290)                     # floating leaves: kept (persistent)
    c.set(2, 129, 10, 682, 2)                   # chest facing south
    c.tiles.append({"id": "Chest", "x": 2, "y": 129, "z": 10, "Items": [
        item(16392, 5, slot=0), item(16508, slot=1), item(30000, slot=2)]})
    c.set(2, 129, 12, 680)                      # legacy (direction-less) double chest
    c.set(3, 129, 12, 680)
    c.tiles.append({"id": "Chest", "x": 2, "y": 129, "z": 12, "Items": [item(16393, 3, slot=0)]})
    c.tiles.append({"id": "Chest", "x": 3, "y": 129, "z": 12, "Items": [item(16394, 4, slot=0)]})
    c.set(6, 130, 1, 711, 2)                    # wall sign
    c.tiles.append({"id": "Sign", "x": 6, "y": 130, "z": 1, "Text1": "§4Ciao", "Text2": "mondo", "Text3": "", "Text4": ""})
    c.entities.append({"id": "Painting", "Pos": [10.5, 130.5, 3.03], "Dir": 0, "TileX": 10, "TileY": 130, "TileZ": 3,
                       "Motive": "Kebab"})
    c.entities.append({"id": "Pig", "Pos": [8.5, 129.0, 8.5], "Rotation": [Float(0), Float(0)], "Health": Short(10),
                       "Saddle": Byte(1)})
    c.entities.append({"id": "Arrow", "Pos": [1.0, 140.0, 1.0]})
    write_region(os.path.join(w, "dimensions", "0", "region", "r.0.0.mcr"), chunks)
    n = BtaChunkBuilder(0, 0)
    n.blocks[0:40] = 803                        # netherrack
    write_region(os.path.join(w, "dimensions", "1", "region", "r.0.0.mcr"), [n])
    return w


class Out:
    """Reads blocks / block entities / entities back from the converted 1.18.2 world."""

    def __init__(self, world: str, sub: str = "region"):
        self.world = world
        self.region = JavaRegion(os.path.join(world, sub, "r.0.0.mca"))

    def chunk(self, cx: int, cz: int):
        raw = self.region.read(cx, cz)
        return None if raw is None else nbt.load(raw).tag

    def block(self, x: int, y: int, z: int) -> str:
        root = self.chunk(x >> 4, z >> 4)
        for s in root["sections"]:
            if int(s["Y"].py_data) == y >> 4:
                bs = s["block_states"]
                pal = bs["palette"]
                idx = 0
                if "data" in bs:
                    bits = max(4, (len(pal) - 1).bit_length())
                    idx = int(_unpack(np.asarray(bs["data"]), bits, 4096, False)[((y & 15) << 8) | ((z & 15) << 4) | (x & 15)])
                p = pal[idx]
                props = ",".join(f"{k}={v.py_data}" for k, v in sorted(p["Properties"].items())) if "Properties" in p else ""
                return str(p["Name"].py_data) + (f"[{props}]" if props else "")
        return "minecraft:air"

    def block_entity(self, x: int, y: int, z: int):
        for t in self.chunk(x >> 4, z >> 4)["block_entities"]:
            if (int(t["x"].py_data), int(t["y"].py_data), int(t["z"].py_data)) == (x, y, z):
                return t
        return None


def props(state: str) -> dict:
    return dict(kv.split("=") for kv in state.split("[", 1)[1].rstrip("]").split(",")) if "[" in state else {}


def test_detection_and_dialect(tmp_path):
    w = make_bta_world(tmp_path)
    assert looks_like_bta(w)
    assert detect(w).kind == "bta" and detect(os.path.join(w, "level.dat")).kind == "bta"
    from .bta_helpers import dump

    doc = nbtio.loads(dump({"b": np.arange(5, dtype=np.int16) - 2, "l": [], "n": Short(-3)}))
    assert doc["b"].tolist() == [-2, -1, 0, 1, 2] and doc["l"] == [] and doc["n"] == -3
    assert nbtio.gi({"x": 3.9}, "x") == 3 and nbtio.gs({"x": 1}, "x", "d") == "d"


def test_every_bta_block_and_item_maps_to_a_valid_26_3_state():
    assert self_test(Palette()) == []


def test_formatted_text():
    assert text.formatted_to_json("plain") == '{"text":"plain"}'
    assert text.formatted_to_json("§4Ciao §lmondo") == (
        '{"text":"","extra":[{"text":"Ciao ","color":"#DECF2A"},{"text":"mondo","color":"#DECF2A","bold":true}]}')
    assert text.strip_formatting("§<#ff0000>rosso§r!") == "rosso!"


def test_bta_to_java_26_3(tmp_path):
    src = make_bta_world(tmp_path)
    out = str(tmp_path / "java")
    res = convert(src, out, TargetSpec(family="java"))
    assert res.chunks == 5
    o = Out(out)
    root = o.chunk(0, 0)
    assert int(root["DataVersion"].py_data) == 2975 and int(root["yPos"].py_data) == -4
    # "extended" world: moved down 65 blocks, BTA's floor becomes the 1.18 bedrock floor
    assert o.block(0, -64, 0) == "minecraft:bedrock"
    assert o.block(0, 62, 0) == "minecraft:stone" and o.block(0, 63, 0).startswith("minecraft:grass_block")
    assert o.block(1, 63, 1) == "minecraft:grass_block[snowy=true]" and o.block(0, 63, 0) == "minecraft:grass_block[snowy=false]"
    assert o.block(1, 64, 1) == "minecraft:snow[layers=1]"
    assert "shape=outer_right" in o.block(5, 64, 5) and "shape=straight" in o.block(5, 64, 4)
    assert "east=true" in o.block(8, 64, 8) and "west=true" in o.block(9, 64, 8)
    assert "distance=1" in o.block(12, 65, 12) and "persistent=false" in o.block(12, 65, 12)
    assert "persistent=true" in o.block(14, 75, 14)
    # containers: the quiver becomes a bundle, its surplus arrows fill free slots; unknown items are skipped
    chest = o.block_entity(2, 64, 10)
    items = {int(i["Slot"].py_data): (str(i["id"].py_data), int(i["Count"].py_data)) for i in chest["Items"]}
    assert items == {0: ("minecraft:diamond", 5), 1: ("minecraft:bundle", 1), 2: ("minecraft:arrow", 64),
                     3: ("minecraft:arrow", 64)}
    assert "facing=south" in o.block(2, 64, 10)
    a, b = props(o.block(2, 64, 12)), props(o.block(3, 64, 12))
    assert {a["type"], b["type"]} == {"left", "right"} and a["facing"] == b["facing"]
    sign = o.block_entity(6, 65, 1)
    assert "Ciao" in str(sign["Text1"].py_data) and "#DECF2A" in str(sign["Text1"].py_data)
    ents = {str(e["id"].py_data): e for e in root["entities"]}
    assert "minecraft:arrow" not in ents  # projectiles are not converted
    pig = ents["minecraft:pig"]
    assert float(pig["Pos"][1].py_data) == 64.0 and int(pig["Saddle"].py_data) == 1 and float(pig["Health"].py_data) == 10
    painting = ents["minecraft:painting"]
    assert [int(painting[k].py_data) for k in ("TileX", "TileY", "TileZ", "Facing")] == [10, 65, 2, 2]
    # biomes, nether, level.dat, player
    bio = root["sections"][8]["biomes"]["palette"]
    assert [str(b.py_data) for b in bio] == ["minecraft:forest"]
    assert Out(out, os.path.join("DIM-1", "region")).block(0, 10, 0) == "minecraft:netherrack"
    lvl = nbt.load(open(os.path.join(out, "level.dat"), "rb").read()).tag["Data"]
    assert int(lvl["SpawnY"].py_data) == 129 - 65 and str(lvl["LevelName"].py_data) == "Casa BTA"
    assert int(lvl["WorldGenSettings"]["seed"].py_data) == 1234 and int(lvl["GameType"].py_data) == 1
    p = lvl["Player"]
    inv = {int(i["Slot"].py_data): str(i["id"].py_data) for i in p["Inventory"]}
    assert inv == {0: "minecraft:iron_sword", 103: "minecraft:iron_helmet", 100: "minecraft:iron_boots"}
    assert float(p["Pos"][1].py_data) == 129.0 - 65
    assert os.path.isfile(os.path.join(out, "playerdata", PLAYER + ".dat"))


def test_selection_spawn_and_player_link(tmp_path):
    src = make_bta_world(tmp_path)
    out = str(tmp_path / "sel")
    sel = Selection(chunks={OVERWORLD: {(0, 0)}}, spawn=(3, 140, 3),
                    players=[PlayerLink(key=PLAYER, host=True, nickname="Steve", online=False)])
    convert(src, out, TargetSpec(family="java", selection=sel))
    assert sorted(JavaRegion(os.path.join(out, "region", "r.0.0.mca")).chunks()) == [(0, 0)]
    assert not os.path.exists(os.path.join(out, "DIM-1"))  # nether not selected
    lvl = nbt.load(open(os.path.join(out, "level.dat"), "rb").read()).tag["Data"]
    assert [int(lvl[k].py_data) for k in ("SpawnX", "SpawnY", "SpawnZ")] == [3, 140 - 65, 3]
    assert os.listdir(os.path.join(out, "playerdata")) == [offline_uuid("Steve") + ".dat"]


def test_only_java_targets_and_single_worker(tmp_path):
    src = make_bta_world(tmp_path)
    with pytest.raises(ConversionError):
        convert(src, str(tmp_path / "b"), TargetSpec(family="bedrock"))
    with pytest.raises(ConversionError):
        convert(src, str(tmp_path / "old"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    n, report = convert_world(src, str(tmp_path / "one"), BtaOptions(workers=1, y_offset=0))
    assert n == 5 and report["overworld.y_shift"] == 0 and report["entities.dropped.projectile.arrow"] == 1
    assert Out(str(tmp_path / "one")).block(0, 128, 0).startswith("minecraft:grass_block")


def test_map_preview(tmp_path):
    from worldbridge.mapview import open_map

    m = open_map(make_bta_world(tmp_path))
    try:
        assert sorted(m.dimensions()) == [NETHER, OVERWORLD]
        assert len(m.chunk_coords(OVERWORLD)) == 4 and m.spawn == (8, 129, 8)
        t = m.tile(OVERWORLD, 0, 0)
        assert t.name_at(0, 0) == "minecraft:grass_block" and t.height[0, 0] == 128
        assert [p.key for p in m.players] == [PLAYER]
    finally:
        m.close()

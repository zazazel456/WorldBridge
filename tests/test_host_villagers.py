"""The host player of a Java world (kept by Minecraft 26.1's own upgrade), the owners of the tamed animals, the villagers
(profession, experience, trades, bed / job site), the decorated pots of 26.x, block entities without a block and the
chunks Bedrock does not save.  All found with Casca, a real Bedrock 1.26.52 world, and a real 26.3 server."""
from __future__ import annotations

import json
import os
import uuid


from worldbridge import entities as ent
from worldbridge import holes, nbt, pets, selection, tiles
from worldbridge import amulet_bridge as ab
from worldbridge.bedrock.extra import _db, bedrock_player_to_java, read_village_pois
from worldbridge.java import modern
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import OVERWORLD, Progress, WorldInfo

UNIQUE_ID = -4294967295


def _stack(name, count=1, slot=None):
    t = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name if name else ""), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(0),
                         "WasPickedUp": nbt.ByteTag(0)})
    if slot is not None:
        t["Slot"] = nbt.ByteTag(slot)
    return t


def _attr(name, cur):
    return nbt.CompoundTag({"Name": nbt.StringTag(name), "Current": nbt.FloatTag(cur), "Base": nbt.FloatTag(cur),
                            "Max": nbt.FloatTag(1024.0), "Min": nbt.FloatTag(0.0)})


def _bedrock_player(unique_id=UNIQUE_ID):
    return nbt.CompoundTag({
        "UniqueID": nbt.LongTag(unique_id), "DimensionId": nbt.IntTag(0), "PlayerGameMode": nbt.IntTag(5),
        "Pos": nbt.ListTag([nbt.FloatTag(-330.5), nbt.FloatTag(66.62), nbt.FloatTag(10.5)], 5),
        "Rotation": nbt.ListTag([nbt.FloatTag(10.0), nbt.FloatTag(5.0)], 5),
        "Inventory": nbt.ListTag([_stack("iron_sword", 1, 0), _stack("bread", 7, 1)], 10),
        "Armor": nbt.ListTag([_stack("iron_helmet"), _stack("", 0), _stack("", 0), _stack("", 0)], 10),
        "Offhand": nbt.ListTag([_stack("shield")], 10),
        "EnderChestInventory": nbt.ListTag([_stack("diamond", 3, 0)], 10),
        "Attributes": nbt.ListTag([_attr("minecraft:health", 17.0), _attr("minecraft:player.hunger", 15.0),
                                   _attr("minecraft:player.saturation", 2.5), _attr("minecraft:player.exhaustion", 1.25),
                                   _attr("minecraft:player.level", 18.0), _attr("minecraft:player.experience", 0.5)], 10),
        "ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.ByteTag(24), "Amplifier": nbt.ByteTag(1),
                                                       "Duration": nbt.IntTag(600), "ShowParticles": nbt.ByteTag(1)}),
                                      nbt.CompoundTag({"Id": nbt.ByteTag(25), "Amplifier": nbt.ByteTag(0),
                                                       "Duration": nbt.IntTag(10)})], 10),
        "SelectedInventorySlot": nbt.IntTag(6),
        "SpawnBlockPositionX": nbt.IntTag(-341), "SpawnBlockPositionY": nbt.IntTag(72), "SpawnBlockPositionZ": nbt.IntTag(54),
        "SpawnDimension": nbt.IntTag(0)})


# ------------------------------------------------------------------ the host player
def test_the_bedrock_host_keeps_xp_hunger_effects_and_spawn_point():
    p = bedrock_player_to_java(_bedrock_player())
    assert int(p["XpLevel"].py_data) == 18 and abs(float(p["XpP"].py_data) - 0.5) < 1e-6
    assert int(p["XpTotal"].py_data) == 441 + 26                     # level 18 is 441 points, half of the 52 to the next
    assert int(p["foodLevel"].py_data) == 15 and float(p["foodSaturationLevel"].py_data) == 2.5
    assert float(p["foodExhaustionLevel"].py_data) == 1.25 and abs(float(p["Health"].py_data) - 17.0) < 1e-6
    assert int(p["SelectedItemSlot"].py_data) == 6
    # Bedrock's levitation (24) is Java's 25; the fatal poison (25) does not exist in Java
    eff = [(int(e["Id"].py_data), int(e["Amplifier"].py_data), int(e["Duration"].py_data)) for e in p["ActiveEffects"]]
    assert eff == [(25, 1, 600)]
    assert [int(p[k].py_data) for k in ("SpawnX", "SpawnY", "SpawnZ")] == [-341, 72, 54]
    assert nbt.get(p, "SpawnDimension") == "minecraft:overworld"
    slots = sorted(int(i["Slot"].py_data) for i in p["Inventory"])
    assert slots == [-106, 0, 1, 103] and len(p["EnderItems"]) == 1       # off hand, armour, ender chest


def test_a_player_without_a_spawn_point_gets_none():
    raw = _bedrock_player()
    for k in ("SpawnBlockPositionX", "SpawnBlockPositionY", "SpawnBlockPositionZ"):
        raw[k] = nbt.IntTag(-2147483648)
    p = bedrock_player_to_java(raw)
    assert "SpawnX" not in p


def _info(player, link=None):
    info = WorldInfo(level=nbt.CompoundTag({"LevelName": nbt.StringTag("Casca"), "RandomSeed": nbt.LongTag(1),
                                            "SpawnX": nbt.IntTag(0), "SpawnY": nbt.IntTag(70), "SpawnZ": nbt.IntTag(0)}))
    info.players["host"] = player
    if link is not None:
        info.player_links["host"] = link
    return info


def _read(path):
    return nbt.load(open(path, "rb").read()).tag


def test_the_host_is_in_level_dat_and_in_playerdata(tmp_path):
    """A real single player world before Java 26.1 has both; with a UUID in level.dat and no file the 26.1 upgrade drops the
    player (found with the real 26.3 server: inventory, XP and position were gone)."""
    out = str(tmp_path)
    info = _info(bedrock_player_to_java(_bedrock_player()))
    ab.write_java_level_dat(out, info, (26, 3), Progress())
    data = nbt.get_tag(_read(os.path.join(out, "level.dat")), "Data")
    player = nbt.get_tag(data, "Player")
    u = selection.player_uuid_of(player)
    assert u == str(uuid.UUID(int=ent.bedrock_uuid(UNIQUE_ID)))
    f = os.path.join(out, "playerdata", u + ".dat")
    assert os.path.exists(f)
    same = _read(f)
    assert len(same["Inventory"]) == len(player["Inventory"]) == 4 and int(same["XpLevel"].py_data) == 18
    assert selection.player_uuid_of(same) == u


def test_a_linked_host_gets_one_file_named_after_the_account(tmp_path):
    out = str(tmp_path)
    acct = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
    link = selection.PlayerLink(key="host", host=True, nickname="Notch", online=False, uuid=acct)
    info = _info(bedrock_player_to_java(_bedrock_player()), link)
    ab.write_java_level_dat(out, info, (26, 3), Progress())
    assert os.listdir(os.path.join(out, "playerdata")) == [acct + ".dat"]
    player = nbt.get_tag(nbt.get_tag(_read(os.path.join(out, "level.dat")), "Data"), "Player")
    assert selection.player_uuid_of(player) == acct


def test_a_player_without_uuid_writes_no_file(tmp_path):
    """No UUID in level.dat: the game's upgrade names the file after the nil UUID itself and the owner loads it."""
    assert selection.write_host_playerdata(str(tmp_path), nbt.CompoundTag({"Player": nbt.CompoundTag({"XpLevel": nbt.IntTag(1)})})) is None
    assert not os.path.exists(tmp_path / "playerdata")


def test_other_players_are_warned_about_with_their_inventories(tmp_path):
    from worldbridge.convert import TargetSpec, _warn_single_player
    from worldbridge.selection import Selection

    info = _info(bedrock_player_to_java(_bedrock_player()))
    info.players["player_server_x"] = bedrock_player_to_java(_bedrock_player(5))
    prog = Progress()
    _warn_single_player(info, TargetSpec(family="java"), Selection(), prog)
    assert any("1 players were not written, so their inventories" in w for w in prog.warnings), prog.warnings


# ------------------------------------------------------------------ the owners of the tamed animals
def _pet(owner, name="wolf"):
    return {"name": name, "pos": (0.5, 70.0, 0.5), "motion": (0.0, 0.0, 0.0), "rot": (0.0, 0.0), "extra": {},
            "tamed": True, "owner": owner}


def test_bedrock_pets_follow_the_hosts_uuid():
    placeholder = ent.bedrock_uuid(UNIQUE_ID)
    c = ent.from_bedrock(nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:wolf"), "IsTamed": nbt.ByteTag(1),
                                          "OwnerNew": nbt.LongTag(UNIQUE_ID)}))
    assert c["owner"] == placeholder
    p = bedrock_player_to_java(_bedrock_player())
    assert uuid.UUID(selection.player_uuid_of(p)).int == c["owner"]


def test_account_mode_gives_the_pets_the_accounts_uuid():
    acct = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
    link = selection.PlayerLink(key="host", host=True, nickname="Notch", online=False, uuid=acct)
    info = _info(bedrock_player_to_java(_bedrock_player()), link)
    prog = Progress()
    plan = pets.plan_for("auto", info, 5023, prog)
    assert plan.mode == "account"
    pet = _pet(ent.bedrock_uuid(UNIQUE_ID))
    stranger = _pet(12345)
    plan.apply([pet, stranger])
    assert pet["owner"] == uuid.UUID(acct).int and stranger["owner"] == 12345 and not pet.get("pet_tag")
    w = ent.to_java_modern(pet, 2730)
    assert ent.uuid_string(sum((int(v) & 0xFFFFFFFF) << s for v, s in zip(w["Owner"], (96, 64, 32, 0)))) == acct


def test_first_player_mode_tags_the_pets_and_writes_a_data_pack(tmp_path):
    info = _info(bedrock_player_to_java(_bedrock_player()))
    prog = Progress()
    plan = pets.plan_for("auto", info, 5023, prog)          # no link: the first player
    assert plan.mode == "first-player" and not prog.warnings
    pet = _pet(ent.bedrock_uuid(UNIQUE_ID))
    other = _pet(777)
    plan.apply([pet, other])
    assert pet["pet_tag"] and plan.tagged == 1 and not other.get("pet_tag")
    assert list(ent.to_java_modern(pet, 2730)["Tags"]) == ["worldbridge_host_pet"]
    assert "Tags" not in ent.to_java_modern(other, 2730)
    root = pets.write_datapack(str(tmp_path), 5023)
    meta = json.load(open(os.path.join(root, "pack.mcmeta")))["pack"]
    assert meta["min_format"] <= 121 <= meta["max_format"] and "pack_format" not in meta
    fn = os.path.join(root, "data", "worldbridge", "function")
    assert "run function worldbridge:bind" in open(os.path.join(fn, "tick.mcfunction")).read()
    assert "data modify entity @s Owner set from entity @p UUID" in open(os.path.join(fn, "bind.mcfunction")).read()
    assert json.load(open(os.path.join(root, "data", "minecraft", "tags", "function", "tick.json"))) == {
        "values": ["worldbridge:tick"]}


def test_the_data_pack_follows_the_target_version(tmp_path):
    a = pets.write_datapack(str(tmp_path / "a"), 3700)       # 1.20.3: functions, format 26
    assert json.load(open(os.path.join(a, "pack.mcmeta")))["pack"]["pack_format"] == 26
    assert os.path.isdir(os.path.join(a, "data", "worldbridge", "functions"))
    b = pets.write_datapack(str(tmp_path / "b"), 2586)       # 1.16.4
    assert json.load(open(os.path.join(b, "pack.mcmeta")))["pack"]["pack_format"] == 6
    c = pets.write_datapack(str(tmp_path / "c"), 3953)       # 1.21: function
    assert json.load(open(os.path.join(c, "pack.mcmeta")))["pack"]["pack_format"] == 48
    assert os.path.isdir(os.path.join(c, "data", "worldbridge", "function"))


def test_a_target_older_than_1_16_cannot_bind_the_pets_and_says_so():
    info = _info(bedrock_player_to_java(_bedrock_player()))
    prog = Progress()
    plan = pets.plan_for("auto", info, 2230, prog)
    assert plan.mode == "none" and any("will not recognise the player" in w for w in prog.warnings)


def test_account_mode_without_a_link_falls_back_with_a_warning():
    info = _info(bedrock_player_to_java(_bedrock_player()))
    prog = Progress()
    plan = pets.plan_for("account", info, 5023, prog)
    assert plan.mode == "first-player" and any("needs the host linked" in w for w in prog.warnings)


def test_other_sources_keep_their_accounts_unless_asked():
    info = _info(bedrock_player_to_java(_bedrock_player()))
    assert pets.plan_for("auto", info, 5023, Progress(), first_by_default=False).mode == "none"
    assert pets.plan_for("first-player", info, 5023, Progress(), first_by_default=False).mode == "first-player"


# ------------------------------------------------------------------ villagers
def _recipe(buy, buy_n, sell, sell_n, tier, uses=0, max_uses=16, exp=2):
    return nbt.CompoundTag({
        "buyA": _stack(buy, buy_n), "buyCountA": nbt.IntTag(buy_n), "buyCountB": nbt.IntTag(0), "sell": _stack(sell, sell_n),
        "demand": nbt.IntTag(3), "maxUses": nbt.IntTag(max_uses), "uses": nbt.IntTag(uses), "tier": nbt.IntTag(tier),
        "priceMultiplierA": nbt.FloatTag(0.05), "priceMultiplierB": nbt.FloatTag(0.0), "rewardExp": nbt.ByteTag(1),
        "traderExp": nbt.IntTag(exp)})


def _bedrock_villager(profession="farmer", tier=0, xp=0, uid=-4294966906):
    return nbt.CompoundTag({
        "identifier": nbt.StringTag("minecraft:villager_v2"), "UniqueID": nbt.LongTag(uid),
        "Pos": nbt.ListTag([nbt.FloatTag(-308.5), nbt.FloatTag(70.0), nbt.FloatTag(80.5)], 5),
        "PreferredProfession": nbt.StringTag(profession), "TradeTier": nbt.IntTag(tier), "TradeExperience": nbt.IntTag(xp),
        "MarkVariant": nbt.IntTag(0),
        "Offers": nbt.CompoundTag({"Recipes": nbt.ListTag([_recipe("carrot", 22, "emerald", 1, 0),
                                                           _recipe("emerald", 1, "bread", 6, 0, uses=2, max_uses=16)], 10)})})


def test_villager_keeps_profession_level_experience_and_trades():
    c = ent.from_bedrock(_bedrock_villager("cleric", tier=2, xp=40))
    e = ent.to_java_modern(c, 2730)
    vd = e["VillagerData"]
    assert vd["profession"] == "minecraft:cleric" and int(vd["level"].py_data) == 3
    assert int(e["Xp"].py_data) == 40
    recipes = e["Offers"]["Recipes"]
    assert len(recipes) == 2
    r = recipes[0]
    assert nbt.get(r["buy"], "id") == "minecraft:carrot" and int(r["buy"]["Count"].py_data) == 22
    assert nbt.get(r["sell"], "id") == "minecraft:emerald" and int(r["sell"]["Count"].py_data) == 1
    assert int(r["maxUses"].py_data) == 16 and int(r["xp"].py_data) == 2 and int(r["demand"].py_data) == 3
    assert abs(float(r["priceMultiplier"].py_data) - 0.05) < 1e-6 and int(r["specialPrice"].py_data) == 0
    assert int(recipes[1]["uses"].py_data) == 2 and "buyB" not in recipes[1]


def test_experience_is_never_made_up():
    e = ent.to_java_modern(ent.from_bedrock(_bedrock_villager("farmer", tier=0, xp=0)), 2730)
    assert "Xp" not in e                                   # the game writes 0 itself; nothing invented to dodge its reset
    assert int(e["VillagerData"]["level"].py_data) == 1


def test_unskilled_villagers_have_no_profession():
    e = ent.to_java_modern(ent.from_bedrock(_bedrock_villager("unskilled")), 2730)
    assert "VillagerData" not in e or e["VillagerData"]["profession"] == "minecraft:none"


def test_villager_brain_has_the_bed_bell_and_job_site():
    c = ent.from_bedrock(_bedrock_villager())
    c["poi"] = {"home": (-360, 78, 90), "meeting_point": (-364, 76, 78), "job_site": (-343, 77, 85)}
    mem = ent.to_java_modern(c, 2730)["Brain"]["memories"]
    js = mem["minecraft:job_site"]["value"]
    assert list(js["pos"]) == [-343, 77, 85] and js["dimension"] == "minecraft:overworld"
    assert set(mem.keys()) == {"minecraft:home", "minecraft:meeting_point", "minecraft:job_site"}
    assert "Brain" not in ent.to_java_modern(ent.from_bedrock(_bedrock_villager()), 2730)


def test_zombie_villager_keeps_its_profession():
    z = _bedrock_villager("librarian")
    z["identifier"] = nbt.StringTag("minecraft:zombie_villager_v2")
    e = ent.to_java_modern(ent.from_bedrock(z), 2730)
    assert e["id"] == "minecraft:zombie_villager" and e["VillagerData"]["profession"] == "minecraft:librarian"


def _village_world(tmp_path):
    path = str(tmp_path / "be")
    os.makedirs(os.path.join(path, "db"))
    db = _db(path, create=True)

    def inst(kind, x, y, z, name):
        return nbt.CompoundTag({"Type": nbt.IntTag(kind), "X": nbt.IntTag(x), "Y": nbt.IntTag(y), "Z": nbt.IntTag(z),
                                "Name": nbt.StringTag(name), "Skip": nbt.ByteTag(0)})

    skip = nbt.CompoundTag({"Skip": nbt.ByteTag(1)})
    poi = nbt.CompoundTag({"POI": nbt.ListTag([
        nbt.CompoundTag({"VillagerID": nbt.LongTag(-100), "instances": nbt.ListTag(
            [inst(0, 1, 70, 2, "villager"), inst(1, 5, 70, 6, "villager"), inst(2, 9, 70, 10, "cleric")], 10)}),
        nbt.CompoundTag({"VillagerID": nbt.LongTag(-101), "instances": nbt.ListTag(
            [skip, inst(1, 5, 70, 6, "villager"), skip], 10)})], 10)})
    db.put(b"VILLAGE_Overworld_aaaa_POI", nbt.dump(poi, "", little_endian=True, compressed=False))
    db.put(b"VILLAGE_Nether_bbbb_POI", nbt.dump(poi, "", little_endian=True, compressed=False))
    db.close()
    return path


def test_village_records_give_each_villager_its_places(tmp_path):
    pois = read_village_pois(_village_world(tmp_path))
    assert pois[-100] == {"home": (1, 70, 2), "meeting_point": (5, 70, 6), "job_site": (9, 70, 10)}
    assert pois[-101] == {"meeting_point": (5, 70, 6)}


# ------------------------------------------------------------------ decorated pots
def test_decorated_pots_are_a_map_from_data_version_4997():
    c = {"kind": "decorated_pot", "pos": (1, 70, 2), "sherds": ["brick", "angler_pottery_sherd", "brick", "arms_up_pottery_sherd"]}
    new = tiles.to_java_modern(c, 5020)
    sh = new["sherds"]
    assert isinstance(sh, nbt.CompoundTag)
    assert [nbt.get(sh[k], "id") for k in ("back", "left", "right", "front")] == [
        "minecraft:brick", "minecraft:angler_pottery_sherd", "minecraft:brick", "minecraft:arms_up_pottery_sherd"]
    assert int(sh["left"]["count"].py_data) == 1
    for dv in (3465, 4996):
        old = tiles.to_java_modern(c, dv)
        assert isinstance(old["sherds"], nbt.ListTag) and len(old["sherds"]) == 4, dv
    # and back
    assert tiles.from_java_modern(new)["sherds"] == c["sherds"]
    assert tiles.from_java_modern(tiles.to_java_modern(c, 3465))["sherds"] == c["sherds"]


# ------------------------------------------------------------------ block entities without a block
def _chunk_with(tmp_path, blocks):
    """A 1.18+ chunk (0, 0) whose section 4 (y 64..79) holds the given {(x, y, z): block name}."""
    names = ["minecraft:air"] + sorted({b for b in blocks.values()})
    import numpy as np

    idx = np.zeros(4096, np.int64)
    for (x, y, z), b in blocks.items():
        idx[(y & 15) << 8 | (z & 15) << 4 | (x & 15)] = names.index(b)
    bits = max(4, (len(names) - 1).bit_length())
    per = 64 // bits
    longs = np.zeros((4096 + per - 1) // per, np.uint64)
    for i, v in enumerate(idx):
        longs[i // per] |= np.uint64(int(v)) << np.uint64((i % per) * bits)
    sec = nbt.CompoundTag({"Y": nbt.ByteTag(4), "block_states": nbt.CompoundTag({
        "palette": nbt.compound_list([nbt.CompoundTag({"Name": nbt.StringTag(n)}) for n in names]),
        "data": nbt.LongArrayTag(longs.view(np.int64))})})
    return nbt.CompoundTag({"DataVersion": nbt.IntTag(5020), "sections": nbt.compound_list([sec])})


def _te(i, x, y, z):
    return nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + i), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z)})


def test_block_entities_without_their_block_are_left_out(tmp_path):
    root = _chunk_with(tmp_path, {(1, 70, 1): "minecraft:spawner", (2, 70, 2): "minecraft:cobweb", (3, 70, 3): "minecraft:chest",
                                  (4, 70, 4): "minecraft:trapped_chest", (6, 70, 6): "minecraft:red_banner"})
    tl = [_te("mob_spawner", 1, 70, 1), _te("mob_spawner", 2, 70, 2),      # on a cobweb
          _te("chest", 3, 70, 3), _te("trapped_chest", 4, 70, 4), _te("chest", 5, 70, 5),   # on air
          _te("banner", 6, 70, 6), _te("sign", 7, 70, 7)]                # a banner on its block stays; a sign on air goes
    kept, dropped = modern.drop_orphans(root, tl)
    assert dropped == 3
    ids = sorted((nbt.get(t, "id"), int(t["x"].py_data)) for t in kept)
    assert ("minecraft:mob_spawner", 1) in ids and ("minecraft:mob_spawner", 2) not in ids
    assert ("minecraft:chest", 5) not in ids and ("minecraft:banner", 6) in ids and ("minecraft:sign", 7) not in ids
    assert ("minecraft:chest", 3) in ids and ("minecraft:trapped_chest", 4) in ids


def test_inject_canon_counts_the_orphans_in_one_warning(tmp_path):
    region = tmp_path / "w" / "region"
    region.mkdir(parents=True)
    root = _chunk_with(tmp_path, {(2, 70, 2): "minecraft:cobweb", (3, 70, 3): "minecraft:chest"})
    root["xPos"], root["zPos"] = nbt.IntTag(0), nbt.IntTag(0)
    root["block_entities"] = nbt.ListTag([], 10)
    rw = RegionWriter(external=True)
    rw.put(0, 0, nbt.dump(root, ""))
    rw.write(str(region / "r.0.0.mca"))
    canon = {(OVERWORLD, 0, 0): ([{"kind": "mob_spawner", "pos": (2, 70, 2)}, {"kind": "chest", "pos": (3, 70, 3), "items": []},
                                  {"kind": "chest", "pos": (9, 70, 9), "items": []}], [])}
    prog = Progress()
    modern.inject_canon(str(tmp_path / "w"), canon, prog, 5023)
    got = nbt.load(JavaRegion(str(region / "r.0.0.mca")).read(0, 0), compressed=False).tag
    assert [(nbt.get(t, "id"), int(t["x"].py_data)) for t in got["block_entities"]] == [("minecraft:chest", 3)]
    assert [w for w in prog.warnings if "had no block" in w] == ["2 block entities of the source had no block: left out"]


# ------------------------------------------------------------------ chunks Bedrock does not save
def test_holes_inside_the_explored_area_are_counted():
    full = {(x, z) for x in range(0, 13) for z in range(0, 13)}
    assert holes.count_holes(full) == 0
    assert holes.count_holes(full - {(6, 6)}) == 1
    assert holes.count_holes(full - {(6, 6), (6, 7), (7, 6)}) == 3
    assert holes.count_holes(full - {(0, 6)}) == 0              # the edge of the area is not a hole
    far = full | {(x + 5000, z - 3000) for x, z in full - {(6, 6)}}
    assert holes.count_holes(far) == 1


def test_missing_chunks_are_logged_for_a_bedrock_world(tmp_path):
    path = str(tmp_path / "be")
    os.makedirs(os.path.join(path, "db"))
    db = _db(path, create=True)
    import struct

    for x in range(0, 9):
        for z in range(0, 9):
            if (x, z) != (4, 4):
                db.put(struct.pack("<ii", x, z) + bytes([0x2C]), b"\x28")
    db.close()
    lines = []
    prog = Progress(on_log=lines.append)
    assert holes.log_missing_chunks(path, prog) == 1
    assert any(m.startswith("1 chunks inside the explored area are not saved") for m in lines), lines
    assert not prog.warnings                                       # a log line, not a warning

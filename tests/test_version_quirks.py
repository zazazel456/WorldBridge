"""What changes from one version (and edition) to the other in a world's settings and players."""
import os

from worldbridge import amulet_bridge as ab
from worldbridge import gamerules, items, nbt
from worldbridge.bedrock.extra import bedrock_player_to_legacy, legacy_player_to_bedrock
from worldbridge.extra import classic_java_level
from worldbridge.java.numeric import JavaWriteOptions, java_player_nbt
from worldbridge.model import WorldInfo


def test_game_rules_of_1_21_11_read_back():
    typed = nbt.CompoundTag({"minecraft:keep_inventory": nbt.ByteTag(1), "minecraft:raids": nbt.ByteTag(0),
                             "minecraft:respawn_radius": nbt.IntTag(4), "minecraft:advance_time": nbt.ByteTag(0),
                             "minecraft:fire_spread_radius_around_player": nbt.IntTag(0)})
    old = gamerules.classic_java_rules(typed)
    assert {k: v.py_data for k, v in old.items()} == {"keepInventory": "true", "disableRaids": "true",
                                                      "spawnRadius": "4", "doDaylightCycle": "false",
                                                      "doFireTick": "false"}


def test_game_rules_between_editions():
    be = gamerules.bedrock_rules(nbt.CompoundTag({"keepInventory": nbt.StringTag("true"),
                                                  "spawnRadius": nbt.StringTag("3"),
                                                  "randomTickSpeed": nbt.StringTag("3")}))
    assert {k: v.py_data for k, v in be.items()} == {"keepinventory": 1, "spawnradius": 3}   # not the tick speed
    back = gamerules.java_rules_from_bedrock(nbt.CompoundTag({k: v for k, v in be.items()}))
    assert back["keepInventory"].py_data == "true" and back["spawnRadius"].py_data == "3"


def test_peaceful_stays_peaceful(tmp_path):
    info = WorldInfo()
    info.level = nbt.CompoundTag({"LevelName": nbt.StringTag("p"), "Difficulty": nbt.ByteTag(0),
                                  "GameRules": nbt.CompoundTag({"keepInventory": nbt.StringTag("true")})})
    ab.write_bedrock_level_dat(str(tmp_path), info, (1, 21, 50))
    root = ab.read_bedrock_level_dat(str(tmp_path))
    assert int(root["Difficulty"].py_data) == 0 and int(root["keepinventory"].py_data) == 1
    java = ab.bedrock_info_to_java(root)
    assert int(java["Difficulty"].py_data) == 0 and java["GameRules"]["keepInventory"].py_data == "true"


def test_spectator_world_and_player_stay_spectators_between_editions(tmp_path):
    def world(version, mode):
        info = WorldInfo()
        info.level = nbt.CompoundTag({"LevelName": nbt.StringTag("s"), "GameType": nbt.IntTag(mode)})
        d = tmp_path / ("w%d_%d_%d" % (version[1], version[2], mode))
        d.mkdir()
        ab.write_bedrock_level_dat(str(d), info, version)
        return int(ab.read_bedrock_level_dat(str(d))["GameType"].py_data)

    assert world((1, 21, 50), 3) == 6 and world((1, 26, 50), 3) == 6          # Bedrock has Spectator from 1.21.40
    assert world((1, 21, 20), 3) == 1 and world((1, 16, 220), 3) == 1         # before: the nearest, Creative
    assert [world((1, 21, 50), m) for m in (0, 1, 2)] == [0, 1, 2]
    # Bedrock 6 is Spectator, 3 is the "default" mode: Survival
    for bedrock, java in ((6, 3), (3, 0), (2, 2), (1, 1), (0, 0)):
        root = nbt.CompoundTag({"LevelName": nbt.StringTag("b"), "GameType": nbt.IntTag(bedrock)})
        assert int(ab.bedrock_info_to_java(root)["GameType"].py_data) == java
    # a spectator player in a spectator world follows it; in another world he keeps his mode
    player = nbt.CompoundTag({"playerGameType": nbt.IntTag(3)})
    for version, expected in (((1, 21, 50), 5), ((1, 21, 20), 5)):
        assert int(legacy_player_to_bedrock(player, version, 1, 3)["PlayerGameMode"].py_data) == expected
    assert int(legacy_player_to_bedrock(player, (1, 21, 50), 1, 0)["PlayerGameMode"].py_data) == 6
    assert int(legacy_player_to_bedrock(player, (1, 21, 20), 1, 0)["PlayerGameMode"].py_data) == 1
    assert int(legacy_player_to_bedrock(player, (1, 21, 20), 1, 1)["PlayerGameMode"].py_data) == 5   # both Creative there
    back = bedrock_player_to_legacy(legacy_player_to_bedrock(player, (1, 21, 50), 1, 0))
    assert int(back["playerGameType"].py_data) == 3


def test_java_26_level_read_with_the_classic_keys(tmp_path):
    data = tmp_path / "data" / "minecraft"
    data.mkdir(parents=True)

    def side(name, tag):
        (data / (name + ".dat")).write_bytes(nbt.dump(nbt.CompoundTag({"data": tag}), "", compressed=True))

    side("weather", nbt.CompoundTag({"raining": nbt.ByteTag(1), "thundering": nbt.ByteTag(0)}))
    side("game_rules", nbt.CompoundTag({"minecraft:keep_inventory": nbt.ByteTag(1)}))
    side("world_gen_settings", nbt.CompoundTag({"seed": nbt.LongTag(77)}))
    info = WorldInfo()
    info.level = nbt.CompoundTag({"DataVersion": nbt.IntTag(4786), "LevelName": nbt.StringTag("n"),
                                  "difficulty_settings": nbt.CompoundTag({"difficulty": nbt.StringTag("hard"),
                                                                          "hardcore": nbt.ByteTag(1)})})
    classic_java_level(info, str(tmp_path))
    lv = info.level
    assert int(lv["Difficulty"].py_data) == 3 and int(lv["hardcore"].py_data) == 1 and int(lv["raining"].py_data) == 1
    assert lv["GameRules"]["keepInventory"].py_data == "true" and int(lv["WorldGenSettings"]["seed"].py_data) == 77
    out = tmp_path / "out"
    out.mkdir()
    ab.write_java_level_dat(str(out), info, ab.latest("java"))   # the source's own level.dat, as it was
    kept = nbt.load(open(os.path.join(out, "level.dat"), "rb").read()).tag["Data"]
    assert not any(k in kept for k in ("Difficulty", "hardcore", "raining", "GameRules", "WorldGenSettings"))


def _java_1215_player(gamemode=3):
    boots = nbt.CompoundTag({"id": nbt.StringTag("minecraft:iron_boots"), "count": nbt.IntTag(1)})
    shield = nbt.CompoundTag({"id": nbt.StringTag("minecraft:shield"), "count": nbt.IntTag(1)})
    return nbt.CompoundTag({"DataVersion": nbt.IntTag(4325), "playerGameType": nbt.IntTag(gamemode),
                            "Inventory": nbt.ListTag([], 10),
                            "equipment": nbt.CompoundTag({"feet": boots, "offhand": shield})})


def test_java_1_21_5_equipment_reaches_bedrock_and_old_java():
    be = legacy_player_to_bedrock(_java_1215_player(), (1, 21, 50), 1)
    assert str(be["Armor"][3]["Name"].py_data) == "minecraft:iron_boots"
    assert str(be["Offhand"][0]["Name"].py_data) == "minecraft:shield"
    old = java_player_nbt(_java_1215_player(), JavaWriteOptions(kind="anvil"))
    assert sorted(int(t["Slot"].py_data) for t in old["Inventory"]) == [-106, 100] and "equipment" not in old
    assert len(items.player_stacks(_java_1215_player())) == 2


def test_spectator_and_the_worlds_mode_between_editions():
    assert int(legacy_player_to_bedrock(_java_1215_player(3), (1, 21, 50), 1)["PlayerGameMode"].py_data) == 6
    assert int(legacy_player_to_bedrock(_java_1215_player(3), (1, 21, 30), 1)["PlayerGameMode"].py_data) == 1
    spectator = bedrock_player_to_legacy(nbt.CompoundTag({"PlayerGameMode": nbt.IntTag(6)}))
    assert int(spectator["playerGameType"].py_data) == 3
    world_mode = bedrock_player_to_legacy(nbt.CompoundTag({"PlayerGameMode": nbt.IntTag(5)}))
    assert "playerGameType" not in world_mode           # Java too then follows the world's mode


def test_java_26_single_player_stays_in_players_data(tmp_path):
    from worldbridge.extra import _copy_java_side_files
    from worldbridge.selection import uuid_int_array

    uid = "0f0e0d0c-0b0a-4908-8706-050403020100"
    src = tmp_path / "src"
    (src / "players" / "data").mkdir(parents=True)
    other = nbt.CompoundTag({"DataVersion": nbt.IntTag(4786), "Health": nbt.FloatTag(3.0)})
    (src / "players" / "data" / "11111111-2222-4333-8444-555555555555.dat").write_bytes(
        nbt.dump(other, "", compressed=True))
    host = nbt.CompoundTag({"DataVersion": nbt.IntTag(4786), "Health": nbt.FloatTag(9.0)})
    info = WorldInfo()
    info.level = nbt.CompoundTag({"DataVersion": nbt.IntTag(4786), "LevelName": nbt.StringTag("n"),
                                  "singleplayer_uuid": uuid_int_array(uid)})
    info.players = {"host": host}
    out = tmp_path / "out"
    out.mkdir()
    ab.write_java_level_dat(str(out), info, ab.latest("java"))
    _copy_java_side_files(str(src), str(out))
    data = nbt.load((out / "level.dat").read_bytes()).tag["Data"]
    assert "Player" not in data                                    # 26.1+ reads the player from players/data
    files = sorted(os.listdir(out / "players" / "data"))
    assert files == ["0f0e0d0c-0b0a-4908-8706-050403020100.dat", "11111111-2222-4333-8444-555555555555.dat"]
    p = nbt.load((out / "players" / "data" / files[0]).read_bytes()).tag
    assert float(p["Health"].py_data) == 9.0
    assert not (out / "playerdata").exists()

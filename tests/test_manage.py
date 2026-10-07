"""World management: the documents of every kind of world, read, edited and saved back."""
import os
import struct

from worldbridge import nbt
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.manage import open_world
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _field(w, label):
    return next(f for f in w.quick_fields() if f.label == label)


def test_java_settings_are_edited_and_saved_with_a_backup(tmp_path):
    src = SyntheticWorld(radius=1)
    out = str(tmp_path / "java")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    wr.add_chunk(0, src.read_chunk(0, 0, 0))
    wr.finish(src.info)
    w = open_world(out)
    assert w.kind == "java" and w.get(_field(w, "Name")) == "Test World"
    w.set(_field(w, "Game mode"), 2)
    w.set(_field(w, "Spawn Y"), 99)
    w.set(_field(w, "Seed"), -42)
    w.save()
    assert os.path.isfile(os.path.join(out, "level.dat.wb-backup"))
    again = open_world(out)
    assert again.get(_field(again, "Game mode")) == 2
    assert again.get(_field(again, "Spawn Y")) == 99 and again.get(_field(again, "Seed")) == -42


def test_second_save_keeps_the_original_backup(tmp_path):
    src = SyntheticWorld(radius=1)
    out = str(tmp_path / "java")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    wr.add_chunk(0, src.read_chunk(0, 0, 0))
    wr.finish(src.info)
    w = open_world(out)
    w.set(_field(w, "Name"), "First edit")
    w.save()
    w.set(_field(w, "Name"), "Second edit")
    w.save()
    with open(os.path.join(out, "level.dat.wb-backup"), "rb") as f:
        root = nbt.load(f.read()).tag
    assert str(nbt.get(root["Data"], "LevelName")) == "Test World"
    assert open_world(out).get(_field(open_world(out), "Name")) == "Second edit"


def test_old_pocket_edition_level_dat(tmp_path):
    root = nbt.CompoundTag({"LevelName": nbt.StringTag("PE"), "RandomSeed": nbt.LongTag(7), "GameType": nbt.IntTag(0),
                            "SpawnX": nbt.IntTag(1), "SpawnY": nbt.IntTag(64), "SpawnZ": nbt.IntTag(1)})
    body = nbt.dump(root, "", little_endian=True)
    world = tmp_path / "pe"
    world.mkdir()
    (world / "level.dat").write_bytes(struct.pack("<ii", 3, len(body)) + body)
    (world / "chunks.dat").write_bytes(b"\0" * 4096)
    w = open_world(str(world))
    assert w.kind == "pe_old" and w.get(_field(w, "Seed")) == 7
    w.set(_field(w, "Game mode"), 1)
    w.save()
    raw = (world / "level.dat").read_bytes()
    assert struct.unpack_from("<i", raw)[0] == 3                                    # the header is kept
    assert int(nbt.get(nbt.load(raw[8:], little_endian=True).tag, "GameType")) == 1


def test_lce_level_dat_inside_the_save(tmp_path):
    src = SyntheticWorld(radius=1)
    out = tmp_path / "lce"
    wr = LCEWriter(str(out), LCEWriteOptions(platform="win64", world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    w = open_world(str(out))
    assert w.kind == "lce" and not w.read_only
    w.set(_field(w, "Name"), "Rinominato")
    w.save()
    assert LCEWorld(str(out)).info.name == "Rinominato"
    assert len(LCEWorld(str(out)).chunk_coords(0)) == len(src.chunk_coords(0))    # the chunks are untouched


# ------------------------------------------------------------------ players and inventories

def _bedrock_world(tmp_path, player):
    import amulet_nbt as an

    from worldbridge.bedrock.extra import _db

    world = tmp_path / "be"
    (world / "db").mkdir(parents=True)
    body = nbt.dump(nbt.CompoundTag({"LevelName": nbt.StringTag("be"), "GameType": nbt.IntTag(0),
                                     "keepinventory": nbt.ByteTag(1), "spawnradius": nbt.IntTag(5)}),
                    "", little_endian=True)
    (world / "level.dat").write_bytes(struct.pack("<ii", 10, len(body)) + body)
    db = _db(str(world), create=True)
    db.put(b"~local_player", an.NamedTag(player, "").save_to(compressed=False, little_endian=True,
                                                             string_encoder=an.utf8_escape_encoder))
    db.close()
    return str(world)


def _native_bedrock_player():
    """A player as Bedrock saves it: every slot, the empty ones too, and raw bytes in a string."""
    import amulet_nbt as an

    def item(name="", count=0, slot=None, block=False):
        t = an.CompoundTag({"Name": an.StringTag(name), "Count": an.ByteTag(count), "Damage": an.ShortTag(0),
                            "WasPickedUp": an.ByteTag(0)})
        if slot is not None:
            t["Slot"] = an.ByteTag(slot)
        if block:
            t["Block"] = an.CompoundTag({"name": an.StringTag(name), "states": an.CompoundTag(),
                                         "version": an.IntTag(18168865)})
        return t

    inv = [item(slot=i) for i in range(36)]
    inv[20] = item("minecraft:cooked_mutton", 12, 20)
    inv[30] = item("minecraft:oak_planks", 64, 30, block=True)
    return an.CompoundTag({
        "identifier": an.StringTag("minecraft:player"),
        "internalComponents": an.CompoundTag({"EntityStorageKeyComponent": an.CompoundTag(
            {"StorageKey": an.StringTag("F␛x96␛x82   ")})}),
        "Inventory": an.ListTag(inv),
        "Armor": an.ListTag([item("minecraft:netherite_helmet", 1), item(), item(), item()]),
        "Offhand": an.ListTag([item("minecraft:shield", 1)]),
        "EnderChestInventory": an.ListTag([item("minecraft:elytra", 1, 0)] + [item(slot=i) for i in range(1, 27)])})


def test_native_bedrock_inventory_is_read_by_section(tmp_path):
    from worldbridge.manage import inventory, item_count, item_name

    w = open_world(_bedrock_world(tmp_path, _native_bedrock_player()))
    doc = next(d for d in w.docs if d.kind == "player")
    full = [(s.section, s.slot, item_name(s.tag), item_count(s.tag)) for s in inventory(doc) if not s.empty]
    assert full == [("Inventory", "20", "minecraft:cooked_mutton", 12), ("Inventory", "30", "minecraft:oak_planks", 64),
                    ("Armour", "head", "minecraft:netherite_helmet", 1), ("Off hand", "0", "minecraft:shield", 1),
                    ("Ender chest", "0", "minecraft:elytra", 1)]
    assert sum(s.empty for s in inventory(doc)) == 34 + 3 + 26


def test_bedrock_player_edit_keeps_raw_bytes_and_drops_the_old_block(tmp_path):
    from worldbridge.bedrock.extra import _db
    from worldbridge.manage import inventory, set_item_name

    path = _bedrock_world(tmp_path, _native_bedrock_player())
    w = open_world(path)
    doc = next(d for d in w.docs if d.kind == "player")
    planks = next(s for s in inventory(doc) if s.slot == "30" and s.section == "Inventory")
    set_item_name(planks.tag, "stone")
    doc.dirty = True
    w.save()
    db = _db(path)
    raw = db.get(b"~local_player")
    db.close()
    assert b"F\x96\x82   " in raw                      # the storage key, byte for byte
    p = nbt.load(raw, little_endian=True).tag
    t = p["Inventory"][30]
    assert nbt.get(t, "Name") == "minecraft:stone" and "Block" not in t


def test_bedrock_quick_settings_follow_the_edition(tmp_path):
    w = open_world(_bedrock_world(tmp_path, _native_bedrock_player()))
    assert set(_field(w, "Game mode").choices) == {0, 1, 2}             # Bedrock's 3 is not Spectator
    assert _field(w, "Rule: keepinventory").kind == "bool" and _field(w, "Rule: spawnradius").kind == "int"


def test_java_single_player_and_equipment(tmp_path):
    from worldbridge.manage import inventory, item_name

    world = tmp_path / "j"
    world.mkdir()
    sword = nbt.CompoundTag({"id": nbt.StringTag("minecraft:diamond_sword"), "count": nbt.IntTag(1), "Slot": nbt.ByteTag(0)})
    boots = nbt.CompoundTag({"id": nbt.StringTag("minecraft:iron_boots"), "count": nbt.IntTag(1)})
    player = nbt.CompoundTag({"DataVersion": nbt.IntTag(4325), "Health": nbt.FloatTag(20.0),
                              "Inventory": nbt.ListTag([sword], 10),
                              "equipment": nbt.CompoundTag({"feet": boots})})            # 1.21.5+
    rules = nbt.CompoundTag({"minecraft:keep_inventory": nbt.ByteTag(1), "minecraft:respawn_radius": nbt.IntTag(3)})
    data = nbt.CompoundTag({"DataVersion": nbt.IntTag(4671), "LevelName": nbt.StringTag("j"),
                            "RandomSeed": nbt.LongTag(1), "game_rules": rules, "Player": player})
    (world / "level.dat").write_bytes(nbt.dump(nbt.CompoundTag({"Data": data}), "", compressed=True))
    w = open_world(str(world))
    doc = next(d for d in w.docs if d.kind == "player")
    assert doc.parent is w.doc("level.dat")
    assert [(s.section, s.slot, item_name(s.tag)) for s in inventory(doc)] == [
        ("Hotbar", "0", "minecraft:diamond_sword"), ("Armour", "feet", "minecraft:iron_boots")]
    assert _field(w, "Rule: keep_inventory").kind == "bool" and _field(w, "Rule: respawn_radius").kind == "int"
    w.set(next(f for f in w.player_fields(doc) if f.path == ("Health",)), 7.0)
    w.save()
    again = open_world(str(world))
    p = nbt.get_tag(again.doc("level.dat").root["Data"], "Player")
    assert float(p["Health"].py_data) == 7.0


def test_beta_world_has_no_later_settings(tmp_path):
    world = tmp_path / "beta"
    (world / "region").mkdir(parents=True)
    (world / "region" / "r.0.0.mcr").write_bytes(b"\0" * 8192)
    data = nbt.CompoundTag({"version": nbt.IntTag(19132), "LevelName": nbt.StringTag("b"), "RandomSeed": nbt.LongTag(1),
                            "GameType": nbt.IntTag(0), "Time": nbt.LongTag(5)})
    (world / "level.dat").write_bytes(nbt.dump(nbt.CompoundTag({"Data": data}), "", compressed=True))
    w = open_world(str(world))
    labels = [f.label for f in w.quick_fields()]
    assert "Difficulty" not in labels and "Commands (cheats)" not in labels   # options.txt / Java 1.3
    assert set(_field(w, "Game mode").choices) == {0, 1}
    assert _field(w, "Time of day (ticks)").path[-1] == "Time"             # DayTime came with 1.3

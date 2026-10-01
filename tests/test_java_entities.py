"""LCE entities must reach Java in a form Minecraft's DataFixer accepts.

Minecraft discards (and regenerates) any chunk whose upgrade throws, so a single LCE
specific field - e.g. the string UUID "ent<hex>" - used to wipe every chunk with a mob,
item, minecart or item frame in it."""

from worldbridge import nbt
from worldbridge.java.numeric import _legacy_entities, java_entity_nbt


def _lce_cow():
    return nbt.CompoundTag({
        "id": nbt.StringTag("Cow"),
        "UUID": nbt.StringTag("entc1af2291955048cda072b5b04a89cf3e"),
        "Attributes": nbt.ListTag([
            nbt.CompoundTag({"ID": nbt.IntTag(0), "Base": nbt.DoubleTag(10.0)}),
            nbt.CompoundTag({"ID": nbt.IntTag(3), "Base": nbt.DoubleTag(0.2),
                             "Modifiers": nbt.ListTag([nbt.CompoundTag({"UUID": nbt.IntTag(1)})], 10)}),
            nbt.CompoundTag({"ID": nbt.IntTag(99), "Base": nbt.DoubleTag(1.0)}),
        ], 10),
        "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(64.0), nbt.DoubleTag(2.5)], 6),
    })


def test_lce_uuid_becomes_most_least():
    e = java_entity_nbt(_lce_cow())
    assert "UUID" not in e
    v = 0xc1af2291955048cda072b5b04a89cf3e
    most = (v >> 64) - (1 << 64) if (v >> 64) >= 1 << 63 else v >> 64
    least = v & ((1 << 64) - 1)
    least = least - (1 << 64) if least >= 1 << 63 else least
    assert int(e["UUIDMost"].py_data) == most
    assert int(e["UUIDLeast"].py_data) == least


def test_lce_attributes_get_java_names():
    e = java_entity_nbt(_lce_cow())
    attrs = e["Attributes"]
    assert [str(a["Name"].py_data) for a in attrs] == ["generic.maxHealth", "generic.movementSpeed"]
    assert all("ID" not in a and "Modifiers" not in a for a in attrs)


def test_non_hex_uuid_is_dropped_and_java_data_untouched():
    p = java_entity_nbt(nbt.CompoundTag({"UUID": nbt.StringTag("Player")}))
    assert "UUID" not in p and "UUIDMost" not in p
    java = nbt.CompoundTag({"UUIDMost": nbt.LongTag(5), "UUIDLeast": nbt.LongTag(7),
                            "Attributes": nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag("generic.maxHealth"),
                                                                        "Base": nbt.DoubleTag(4.0)})], 10)})
    out = java_entity_nbt(nbt.copy(java))
    assert int(out["UUIDMost"].py_data) == 5 and int(out["UUIDLeast"].py_data) == 7
    assert str(out["Attributes"][0]["Name"].py_data) == "generic.maxHealth"


def test_java_writer_never_emits_string_uuids():
    for e in _legacy_entities([_lce_cow()]):
        assert not isinstance(nbt.get_tag(e, "UUID"), nbt.StringTag)


def test_empty_lce_owner_is_removed_and_uuid_owner_converted():
    wolf = java_entity_nbt(nbt.CompoundTag({"id": nbt.StringTag("Wolf"), "Owner": nbt.StringTag("")}))
    assert "Owner" not in wolf and "OwnerUUID" not in wolf
    horse = java_entity_nbt(nbt.CompoundTag({"OwnerName": nbt.StringTag("")}))
    assert "OwnerName" not in horse
    cat = java_entity_nbt(nbt.CompoundTag({"Owner": nbt.StringTag("ent283f41104f65464cac855cdc3aa2f85f")}))
    assert "Owner" not in cat
    assert str(cat["OwnerUUID"].py_data) == "283f4110-4f65-464c-ac85-5cdc3aa2f85f"
    named = java_entity_nbt(nbt.CompoundTag({"Owner": nbt.StringTag("Steve")}))
    assert str(named["Owner"].py_data) == "Steve"


def test_bedrock_numeric_era_item_names_with_damage_zero():
    from worldbridge import items

    for name, dmg, flat in (("log", 0, "oak_log"), ("sapling", 0, "oak_sapling"), ("wool", 0, "white_wool"),
                            ("wool", 14, "red_wool"), ("oak_log", 0, "oak_log"), ("stick", 0, "stick")):
        c = items.from_bedrock(nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name),
                                                "Damage": nbt.ShortTag(dmg), "Count": nbt.ByteTag(1)}))
        assert c["name"] == flat


def test_java_level_player_drops_source_data_version():
    from worldbridge.java.numeric import JavaWriteOptions, build_java_level
    from worldbridge.model import WorldInfo

    info = WorldInfo(level=nbt.CompoundTag({"LevelName": nbt.StringTag("w")}))
    info.players["host"] = nbt.CompoundTag({"DataVersion": nbt.IntTag(922), "Inventory": nbt.ListTag([
        nbt.CompoundTag({"id": nbt.ShortTag(17), "Damage": nbt.ShortTag(0), "Count": nbt.ByteTag(3), "Slot": nbt.ByteTag(6)})], 10)})
    p = build_java_level(info, JavaWriteOptions(kind="anvil"))["Player"]
    assert "DataVersion" not in p  # numeric ids: Minecraft must run its item-id fixes

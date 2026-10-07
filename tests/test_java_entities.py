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


def _java_mob(name, **fields):
    e = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + name),
                         "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(64), nbt.DoubleTag(2.5)], 6),
                         "Motion": nbt.ListTag([nbt.DoubleTag(0)] * 3, 6), "Rotation": nbt.ListTag([nbt.FloatTag(0)] * 2, 5)})
    for k, v in fields.items():
        e[k] = v
    return e


def _to_bedrock(name, version=(1, 21, 60), **fields):
    from worldbridge import entities

    c = entities.from_java_modern(_java_mob(name, **fields))
    return entities.to_bedrock(c, -5, None, version)


def _defs(b):
    return {str(d.py_data) for d in b["definitions"]}


def test_bedrock_actors_carry_variants_saddles_and_professions():
    S, I, B = nbt.StringTag, nbt.IntTag, nbt.ByteTag
    horse = _to_bedrock("horse", Variant=I(3 | 2 << 8), SaddleItem=nbt.CompoundTag({
        "id": S("minecraft:saddle"), "Count": B(1)}), ArmorItem=nbt.CompoundTag({
            "id": S("minecraft:iron_horse_armor"), "Count": B(1)}))
    assert horse["Variant"].py_data == 3 and horse["MarkVariant"].py_data == 2 and horse["Saddled"].py_data == 1
    assert {"+minecraft:base_brown", "+minecraft:markings_white_fields"} <= _defs(horse)
    chest = {int(t["Slot"].py_data): t["Name"].py_data for t in horse["ChestItems"]}
    assert chest == {0: "minecraft:saddle", 1: "minecraft:iron_horse_armor"}
    pig = _to_bedrock("pig", Saddle=B(1))
    assert pig["Saddled"].py_data == 1 and "+minecraft:pig_saddled" in _defs(pig)
    assert "+minecraft:pig_unsaddled" in _defs(_to_bedrock("pig")) and _to_bedrock("pig")["Saddled"].py_data == 0
    assert _to_bedrock("llama", Variant=I(2))["Variant"].py_data == 2
    assert _to_bedrock("parrot", Variant=I(4))["Variant"].py_data == 4
    assert _to_bedrock("cat", CatType=I(8))["Variant"].py_data == 0          # Java white = Bedrock 0
    assert _to_bedrock("cat", variant=S("minecraft:tabby"))["Variant"].py_data == 8
    assert _to_bedrock("rabbit", RabbitType=I(99))["Variant"].py_data == 99
    assert _to_bedrock("axolotl", Variant=I(3))["Variant"].py_data == 1      # Java cyan = Bedrock 1
    assert _to_bedrock("fox", Type=S("snow"))["Variant"].py_data == 1
    moo = _to_bedrock("mooshroom", Type=S("brown"))
    assert moo["Variant"].py_data == 1 and "+minecraft:mooshroom_brown" in _defs(moo)
    vil = _to_bedrock("villager", VillagerData=nbt.CompoundTag({"profession": S("minecraft:librarian"), "level": I(3),
                                                                "type": S("minecraft:plains")}))
    assert vil["PreferredProfession"].py_data == "librarian" and "+librarian" in _defs(vil) and vil["TradeTier"].py_data == 2
    legacy = _to_bedrock("villager", Profession=I(1))                      # Java 1.12 numbers
    assert legacy["PreferredProfession"].py_data == "librarian"


def test_bedrock_variants_read_back_as_java():
    from worldbridge import entities

    S, I, B = nbt.StringTag, nbt.IntTag, nbt.ByteTag
    for name, fields in (("horse", dict(Variant=I(3 | 2 << 8), SaddleItem=nbt.CompoundTag({"id": S("minecraft:saddle"),
                                                                                           "Count": B(1)}))),
                         ("pig", dict(Saddle=B(1))), ("llama", dict(Variant=I(3))), ("cat", dict(CatType=I(4))),
                         ("rabbit", dict(RabbitType=I(5))), ("axolotl", dict(Variant=I(2))), ("fox", dict(Type=S("snow"))),
                         ("mooshroom", dict(Type=S("brown"))), ("parrot", dict(Variant=I(2)))):
        b = _to_bedrock(name, **fields)
        c = entities.from_bedrock(b)
        out = entities.to_java_modern(c, 2724)
        for k, v in fields.items():
            if k != "SaddleItem":
                assert out[k].py_data == v.py_data, (name, k)
        if name == "horse":
            assert out["SaddleItem"]["id"].py_data == "minecraft:saddle"
    vil = _to_bedrock("villager", VillagerData=nbt.CompoundTag({"profession": S("minecraft:cleric"), "level": I(2),
                                                                "type": S("minecraft:plains")}))
    out = entities.to_java_modern(entities.from_bedrock(vil), 2724)
    assert out["VillagerData"]["profession"].py_data == "minecraft:cleric" and out["VillagerData"]["level"].py_data == 2
    assert entities.to_legacy(entities.from_bedrock(vil))["Profession"].py_data == 2
    # a cat of Java 1.19+ has a name, not CatType
    cat = entities.to_java_modern(entities.from_bedrock(_to_bedrock("cat", CatType=I(8))), 3700)
    assert cat["variant"].py_data == "minecraft:white" and "CatType" not in cat
    # a worn helmet is not horse armour, and horse armour is not worn
    horse = _to_bedrock("horse", ArmorItem=nbt.CompoundTag({"id": S("minecraft:iron_horse_armor"), "Count": B(1)}))
    c = entities.from_bedrock(horse)
    assert c["equip"]["body"]["name"] == "iron_horse_armor" and not any(c["equip"]["armor"])


def test_pocket_edition_entities_are_read_by_their_number():
    from worldbridge import entities

    def pe(num, **kw):
        e = nbt.CompoundTag({"id": nbt.IntTag(num), "Pos": nbt.ListTag([nbt.FloatTag(1.5), nbt.FloatTag(64), nbt.FloatTag(2.5)], 5),
                             "Motion": nbt.ListTag([nbt.FloatTag(0)] * 3, 5), "Rotation": nbt.ListTag([nbt.FloatTag(10), nbt.FloatTag(0)], 5)})
        for k, v in kw.items():
            e[k] = v
        return entities.from_bedrock(e)

    assert [pe(n)["name"] for n in (10, 11, 12, 13, 14, 16, 32, 33, 34, 35, 36, 38, 65)] == [
        "chicken", "cow", "pig", "sheep", "wolf", "mooshroom", "zombie", "creeper", "skeleton", "spider",
        "zombified_piglin", "enderman", "tnt"]
    assert pe(13, Color=nbt.ByteTag(5), Sheared=nbt.ByteTag(1))["extra"]["Color"].py_data == 5
    assert pe(0x0B0D)["name"] == "sheep"                        # the category in the high byte
    assert pe(12, Age=nbt.IntTag(-100))["extra"]["Age"].py_data == -24000
    assert pe(99) is None and pe(63) is None
    item = pe(64, Item=nbt.CompoundTag({"id": nbt.ShortTag(297), "Damage": nbt.ShortTag(0), "Count": nbt.ByteTag(2)}))
    assert item["name"] == "item" and item["item"]["name"] == "bread" and item["item"]["count"] == 2
    assert entities.to_legacy(pe(13))["id"].py_data == "Sheep"
    assert pe(69)["name"] == "experience_orb" and pe(83)["name"] == "painting"


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

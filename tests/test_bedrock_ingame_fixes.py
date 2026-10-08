"""What real Bedrock Dedicated Servers (1.14 - 26.52) logged when they opened converted worlds: attributes the game does
not know, a jukebox state, the map record's parent, component groups the vanilla packs do not have."""
import numpy as np

from worldbridge import entities, maps, nbt, newcontent
from worldbridge.bedrock import extra as bx

from .test_java_entities import _defs, _to_bedrock


def _attr(name):
    return nbt.CompoundTag({"Name": nbt.StringTag(name), "Base": nbt.FloatTag(0.02), "Current": nbt.FloatTag(0.02),
                            "Max": nbt.FloatTag(1.0), "Min": nbt.FloatTag(0.0)})


def _actor(*names):
    return nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:chicken"),
                            "Attributes": nbt.ListTag([_attr(n) for n in names], 10)})


def _names(e):
    return [str(nbt.get(a, "Name")) for a in e["Attributes"]]


def test_attribute_lava_movement_exists_from_1_16():
    assert not newcontent.bedrock_attribute_exists("minecraft:lava_movement", (1, 14, 60))
    assert not newcontent.bedrock_attribute_exists("minecraft:lava_movement", (1, 15, 0))
    assert newcontent.bedrock_attribute_exists("minecraft:lava_movement", (1, 16, 0))
    assert newcontent.bedrock_attribute_exists("minecraft:lava_movement", (1, 21, 0))
    assert newcontent.bedrock_attribute_exists("minecraft:movement", (1, 12, 0))


def test_raw_actor_for_older_bedrock_loses_the_attributes_the_game_lacks():
    names = ("minecraft:health", "minecraft:lava_movement", "minecraft:movement")
    old, new = _actor(*names), _actor(*names)
    newcontent.downgrade_actor(old, (1, 14, 60))
    newcontent.downgrade_actor(new, (1, 16, 220))
    assert _names(old) == ["minecraft:health", "minecraft:movement"]
    assert _names(new) == list(names)
    # a list with nothing to remove is the same object, a mob without attributes is fine
    plain = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:pig")})
    assert newcontent.downgrade_actor(plain, (1, 14, 60)) is None and "Attributes" not in plain


def test_bedrock_player_for_older_bedrock_has_no_lava_movement():
    java = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(64), nbt.DoubleTag(0)], 6),
                            "Health": nbt.FloatTag(20.0)})
    for ver, expect in (((1, 14, 60), False), ((1, 16, 220), True), ((1, 21, 0), True)):
        p = bx.legacy_player_to_bedrock(java, ver, -1)
        assert ("minecraft:lava_movement" in _names(p)) is expect, ver
    # a player record that stays Bedrock is rewritten for the target
    root = nbt.CompoundTag({"Attributes": nbt.ListTag([_attr("minecraft:lava_movement"), _attr("minecraft:luck")], 10)})
    bx._retarget_player(root, (1, 14, 60))
    assert _names(root) == ["minecraft:luck"]


def test_numeric_jukebox_with_a_record_has_no_block_data_state():
    """PyMCTranslate knows only jukebox data 0; data 1 (a record inside) stayed ``jukebox[block_data=1]``, a state
    that Bedrock 1.14 - 1.18 reject ("block 'minecraft:jukebox' updated to a state 'block_data' that it does not
    contain")."""
    import amulet_nbt as an
    from amulet.api.block import Block

    from worldbridge import amulet_bridge as ab

    tm = ab.translation_manager()
    ab._install_legacy_fallback()
    j12 = tm.get_version("java", (1, 12, 2))
    for data in (0, 1):
        uni = j12.block.to_universal(Block("minecraft", "jukebox", {"block_data": an.IntTag(data)}))[0]
        for plat, ver in (("bedrock", (1, 14, 60)), ("bedrock", (1, 16, 220)), ("bedrock", (1, 18, 30)),
                          ("bedrock", (1, 21, 0))):
            out = tm.get_version(plat, ver).block.from_universal(uni)[0]
            assert out.base_name == "jukebox" and "block_data" not in out.properties, (data, ver, out)
    # Java 1.13+: the record flag survives
    uni = j12.block.to_universal(Block("minecraft", "jukebox", {"block_data": an.IntTag(1)}))[0]
    j20 = tm.get_version("java", (1, 20, 4)).block.from_universal(uni)[0]
    assert str(j20.properties["has_record"].py_data) == "true"


def test_bedrock_map_record_has_no_parent_map_id():
    """-1 is what Bedrock 1.17 - 26 logs as "Map item N has invalid parentMapId" at every load; a map without a parent
    has no parentMapId at all (checked against BDS 1.16.220 - 26.52)."""
    data = nbt.CompoundTag({"colors": nbt.ByteArrayTag(np.zeros(16384, np.int8)), "scale": nbt.ByteTag(1),
                            "xCenter": nbt.IntTag(64), "zCenter": nbt.IntTag(-64)})
    key, rec = maps.bedrock_record(3, data)
    assert key.startswith(b"map_") and "parentMapId" not in rec
    assert rec["mapId"].py_data == int(key[4:]) and rec["scale"].py_data == 1 and rec["xCenter"].py_data == 64


# the component groups of the vanilla behaviour packs (BDS 1.6 - 1.26, every vanilla* pack) for the age of a mob
_VANILLA_GROUPS = {
    "mooshroom": {"minecraft:cow_adult", "minecraft:cow_baby", "minecraft:mooshroom_red", "minecraft:mooshroom_brown"},
    "rabbit": {"adult", "baby", "coat_brown", "coat_white", "coat_black", "coat_splotched", "coat_desert", "coat_salt"},
    "bee": {"bee_adult", "bee_baby"}, "goat": {"goat_adult", "goat_baby"},
    "turtle": {"minecraft:adult", "minecraft:baby"}, "polar_bear": {"minecraft:adult", "minecraft:baby"},
    "pig": {"minecraft:pig_adult", "minecraft:pig_baby", "minecraft:pig_saddled", "minecraft:pig_unsaddled"},
    "cow": {"minecraft:cow_adult", "minecraft:cow_baby"}, "sheep": {"minecraft:sheep_adult", "minecraft:sheep_baby"},
    "chicken": {"minecraft:chicken_adult", "minecraft:chicken_baby"},
    "wolf": {"minecraft:wolf_adult", "minecraft:wolf_baby"}, "fox": {"minecraft:fox_adult", "minecraft:fox_baby"},
    "panda": {"minecraft:panda_adult", "minecraft:panda_baby"}, "cat": {"minecraft:cat_adult", "minecraft:cat_baby"},
}


def _groups(b):
    return {d[1:] for d in _defs(b)} - {"minecraft:" + str(b["identifier"].py_data).split(":")[-1]}


def test_age_groups_are_groups_the_vanilla_packs_have():
    I, B = nbt.IntTag, nbt.ByteTag
    for mob, groups in _VANILLA_GROUPS.items():
        adult = _to_bedrock(mob, version=(1, 21, 60))
        baby = _to_bedrock(mob, version=(1, 21, 60), Age=I(-24000))
        assert adult is not None and baby is not None, mob
        for b in (adult, baby):
            assert _groups(b) <= groups, (mob, _groups(b) - groups)
    assert _groups(_to_bedrock("mooshroom")) == {"minecraft:cow_adult"}
    assert _groups(_to_bedrock("mooshroom", Age=I(-24000))) == {"minecraft:cow_baby"}
    assert _groups(_to_bedrock("rabbit")) == {"adult"}
    assert _groups(_to_bedrock("rabbit", Age=I(-24000))) == {"baby"}
    assert _groups(_to_bedrock("turtle", version=(1, 21, 60))) == {"minecraft:adult"}
    assert _groups(_to_bedrock("polar_bear", Age=I(-24000))) == {"minecraft:baby"}
    assert _groups(_to_bedrock("bee", version=(1, 21, 60))) == {"bee_adult"}
    assert _groups(_to_bedrock("goat", version=(1, 21, 60), Age=I(-24000))) == {"goat_baby"}
    assert _groups(_to_bedrock("pig")) == {"minecraft:pig_adult", "minecraft:pig_unsaddled"}
    assert _groups(_to_bedrock("cow", Age=I(-24000))) == {"minecraft:cow_baby"}
    # a baby is flagged
    assert _to_bedrock("rabbit", Age=I(-24000))["IsBaby"].py_data == 1


def test_rabbit_coat_is_a_real_group_and_mooshroom_type_too():
    I, S = nbt.IntTag, nbt.StringTag
    for t, coat in ((0, "brown"), (1, "white"), (2, "black"), (3, "splotched"), (4, "desert"), (5, "salt")):
        b = _to_bedrock("rabbit", RabbitType=I(t))
        assert "+coat_" + coat in _defs(b) and b["Variant"].py_data == t
    assert not any(d.startswith("+coat_") for d in _defs(_to_bedrock("rabbit", RabbitType=I(99))))   # the killer bunny
    assert "+minecraft:mooshroom_brown" in _defs(_to_bedrock("mooshroom", Type=S("brown")))
    assert not any("rabbit_" in d or "mooshroom_adult" in d or "mooshroom_baby" in d
                   for mob in ("rabbit", "mooshroom") for d in _defs(_to_bedrock(mob)))
    assert entities.BEDROCK_AGE_GROUPS["bee"] == ("bee_adult", "bee_baby")

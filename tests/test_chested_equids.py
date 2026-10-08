"""Donkeys, mules and llamas keep their chests (and the llama its carpet) between Java, LCE and Bedrock, and the Bedrock
entity table keeps a villager (renamed) and drops the mobs an old Bedrock does not have."""
from worldbridge import entities, newcontent, nbt
from worldbridge.bedrock.extra import BedrockInjector, _db
from worldbridge.model import Progress

S, I, B = nbt.StringTag, nbt.IntTag, nbt.ByteTag


def _stack(name, count, slot=None):
    t = nbt.CompoundTag({"id": S("minecraft:" + name), "Count": B(count)})
    if slot is not None:
        t["Slot"] = B(slot)
    return t


def _mob(name, dv=None, **fields):
    e = nbt.CompoundTag({"id": S("minecraft:" + name),
                         "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(64), nbt.DoubleTag(2.5)], 6),
                         "Motion": nbt.ListTag([nbt.DoubleTag(0)] * 3, 6), "Rotation": nbt.ListTag([nbt.FloatTag(0)] * 2, 5)})
    if dv is not None:
        e[entities.DV_STAMP] = I(dv)
    for k, v in fields.items():
        e[k] = v
    return e


def _donkey_1204():
    return _mob("donkey", 3700, ChestedHorse=B(1), SaddleItem=_stack("saddle", 1),
                Items=nbt.ListTag([_stack("bread", 5, 2), _stack("apple", 3, 9), _stack("cookie", 1, 16)], 10))


def _chest_names(tag_list, key="Name", off=0):
    return {int(t["Slot"].py_data) - off: str(t[key].py_data).split(":")[-1] for t in tag_list
            if str(nbt.get(t, key, ""))}


def _defs(b):
    return {str(d.py_data) for d in b["definitions"]}


def _bedrock(c, version=(1, 21, 60)):
    return entities.to_bedrock(c, -5, None, version)


def test_java_1204_donkey_to_bedrock_and_back_to_both_java_layouts():
    c = entities.from_java_modern(_donkey_1204())
    assert c["chested"] and [(it["name"], it["slot"]) for it in c["chest"]] == [("bread", 0), ("apple", 7), ("cookie", 14)]
    b = _bedrock(c)
    assert b["Chested"].py_data == 1 and {"+minecraft:donkey_chested", "-minecraft:donkey_unchested"} <= _defs(b)
    assert _chest_names(b["ChestItems"]) == {0: "saddle", 1: "bread", 8: "apple", 15: "cookie"}
    assert "Items" not in b
    back = entities.from_bedrock(b)
    assert back["chested"] and back["equip"]["saddle"]["name"] == "saddle" and back["equip"]["body"] is None
    new = entities.to_java_modern(back, 4000)                         # 1.21: chest from slot 0
    assert new["ChestedHorse"].py_data == 1 and _chest_names(new["Items"], "id") == {0: "bread", 7: "apple", 14: "cookie"}
    old = entities.to_java_modern(back, 3700)                         # 1.20.4: chest from slot 2
    assert _chest_names(old["Items"], "id") == {2: "bread", 9: "apple", 16: "cookie"}
    assert old["SaddleItem"]["id"].py_data == "minecraft:saddle"
    # a modern Java donkey (no stamp: told by its keys) reads the same
    again = entities.from_java_modern(new)
    assert [(it["name"], it["slot"]) for it in again["chest"]] == [("bread", 0), ("apple", 7), ("cookie", 14)]
    stamped = entities.from_java_modern(_mob("mule", 4000, ChestedHorse=B(1),
                                             Items=nbt.ListTag([_stack("bread", 1, 0)], 10)))
    assert [(it["name"], it["slot"]) for it in stamped["chest"]] == [("bread", 0)]


def test_bedrock_unchested_donkey_has_only_its_saddle():
    c = entities.from_java_modern(_mob("donkey", 3700, SaddleItem=_stack("saddle", 1)))
    assert not c.get("chested")
    b = _bedrock(c)
    assert b["Chested"].py_data == 0 and "+minecraft:donkey_chested" not in _defs(b)
    assert _chest_names(b["ChestItems"]) == {0: "saddle"}


def test_llama_carpet_goes_to_slot_zero_and_back_to_decor_item():
    llama = _mob("llama", 3700, Variant=I(1), ChestedHorse=B(1), Strength=I(3),
                 DecorItem=_stack("red_carpet", 1),
                 Items=nbt.ListTag([_stack("hay_block", 2, 2), _stack("wheat", 9, 3)], 10))
    c = entities.from_java_modern(llama)
    assert c["equip"]["body"]["name"] == "red_carpet" and c["equip"]["saddle"] is None
    b = _bedrock(c)
    assert _chest_names(b["ChestItems"]) == {0: "red_carpet", 1: "hay_block", 2: "wheat"}
    assert b["Chested"].py_data == 1 and "+minecraft:llama_chested" in _defs(b) and "+minecraft:llama_white" in _defs(b)
    back = entities.from_bedrock(b)
    assert back["equip"]["body"]["name"] == "red_carpet" and back["equip"]["saddle"] is None
    old = entities.to_java_modern(back, 3700)
    assert old["DecorItem"]["id"].py_data == "minecraft:red_carpet" and "SaddleItem" not in old
    assert _chest_names(old["Items"], "id") == {2: "hay_block", 3: "wheat"}
    new = entities.to_java_modern(back, 3900)
    assert new["body_armor_item"]["id"].py_data == "minecraft:red_carpet" and "DecorItem" not in new
    assert _chest_names(new["Items"], "id") == {0: "hay_block", 1: "wheat"}
    eq = entities.to_java_modern(back, 4400)
    assert eq["equipment"]["body"]["id"].py_data == "minecraft:red_carpet"
    # an unchested llama with a carpet; the horse keeps saddle in 0 and armour in 1
    plain = _bedrock(entities.from_java_modern(_mob("llama", 3700, DecorItem=_stack("white_carpet", 1))))
    assert plain["Chested"].py_data == 0 and _chest_names(plain["ChestItems"]) == {0: "white_carpet"}
    horse = _bedrock(entities.from_java_modern(_mob("horse", 3700, SaddleItem=_stack("saddle", 1),
                                                    ArmorItem=_stack("iron_horse_armor", 1))))
    assert "Chested" not in horse and _chest_names(horse["ChestItems"]) == {0: "saddle", 1: "iron_horse_armor"}


def test_trader_llama_chest_uses_the_llama_definitions():
    c = entities.from_java_modern(_mob("trader_llama", 3700, ChestedHorse=B(1),
                                       Items=nbt.ListTag([_stack("bread", 1, 2)], 10)))
    b = _bedrock(c, (1, 21, 60))
    assert str(b["identifier"].py_data) == "minecraft:trader_llama" and "+minecraft:llama_chested" in _defs(b)
    assert _chest_names(b["ChestItems"]) == {1: "bread"}


def test_lce_entity_horse_donkey_chest_to_bedrock_and_back_to_lce():
    lce = nbt.CompoundTag({
        "id": S("EntityHorse"), "Type": I(1), "ChestedHorse": B(1),
        "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(64), nbt.DoubleTag(2.5)], 6),
        "Items": nbt.ListTag([nbt.CompoundTag({"id": S("minecraft:bread"), "Count": B(4), "Damage": nbt.ShortTag(0),
                                               "Slot": B(2)}),
                              nbt.CompoundTag({"id": I(260), "Count": B(2), "Damage": nbt.ShortTag(0), "Slot": B(16)})], 10)})
    c = entities.from_legacy(lce)
    assert c["name"] == "donkey" and c["chested"] and [it["slot"] for it in c["chest"]] == [0, 14]
    b = _bedrock(c)
    assert b["Chested"].py_data == 1 and set(_chest_names(b["ChestItems"])) == {1, 15}
    # Bedrock -> LCE / legacy Java: ChestedHorse and slots 2 .. 16
    out = entities.to_legacy(entities.from_bedrock(b))
    assert str(out["id"].py_data) == "EntityHorse" and out["ChestedHorse"].py_data == 1
    assert sorted(int(t["Slot"].py_data) for t in out["Items"]) == [2, 16]


def test_bedrock_donkey_with_chest_reaches_lce():
    b = _bedrock(entities.from_java_modern(_donkey_1204()))
    out = entities.to_legacy(entities.from_bedrock(b))
    assert out["ChestedHorse"].py_data == 1 and sorted(int(t["Slot"].py_data) for t in out["Items"]) == [2, 9, 16]
    assert out["SaddleItem"]["id"].py_data == 329                    # the LCE numeric id of the saddle


def test_a_chest_minecart_still_keeps_its_items():
    cart = _mob("chest_minecart", Items=nbt.ListTag([_stack("bread", 3, 4)], 10))
    c = entities.from_java_modern(cart)
    assert [it["slot"] for it in c["items"]] == [4] and "chest" not in c
    assert _chest_names(entities.to_java_modern(c, 3700)["Items"], "id") == {4: "bread"}
    assert "Items" in _bedrock(c)


# ------------------------------------------------------------------ the Bedrock entity table
def test_bedrock_entity_table():
    exists = newcontent.bedrock_entity_exists
    assert not exists("fox", (1, 12, 0)) and exists("fox", (1, 13, 0))
    assert not exists("parrot", (1, 1, 0)) and exists("parrot", (1, 2, 0))
    assert not exists("minecraft:dolphin", (1, 2, 0)) and exists("dolphin", (1, 4, 0))
    assert not exists("bee", (1, 13, 0)) and exists("bee", (1, 14, 0))
    assert not exists("sulfur_cube", (26, 10, 0)) and exists("sulfur_cube", (26, 20, 0))
    assert not exists("nautilus", (1, 21, 120)) and exists("nautilus", (1, 21, 130))
    assert exists("pig", (1, 1, 0)) and exists("villager_v2", (1, 1, 0))


def _actor(ident, defs=()):
    return nbt.CompoundTag({"identifier": S("minecraft:" + ident),
                            "definitions": nbt.ListTag([S(d) for d in defs], 8)})


def test_raw_actors_are_renamed_not_dropped_for_an_older_bedrock():
    v = _actor("villager_v2", ["+minecraft:villager_v2", "+minecraft:villager_v2_adult"])
    assert newcontent.downgrade_actor(v, (1, 10, 0)) == "renamed"
    assert str(v["identifier"].py_data) == "minecraft:villager"
    assert [str(d.py_data) for d in v["definitions"]] == ["+minecraft:villager", "+minecraft:villager_adult"]
    z = _actor("zombie_villager_v2")
    assert newcontent.downgrade_actor(z, (1, 10, 0)) == "renamed" and str(z["identifier"].py_data) == "minecraft:zombie_villager"
    keep = _actor("villager_v2")
    assert newcontent.downgrade_actor(keep, (1, 11, 0)) is None and str(keep["identifier"].py_data) == "minecraft:villager_v2"
    t = _actor("trader_llama", ["+minecraft:trader_llama"])
    assert newcontent.downgrade_actor(t, (1, 16, 220)) == "renamed"
    assert str(t["identifier"].py_data) == "minecraft:llama" and "+minecraft:llama_wandering_trader" in _defs(t)
    t2 = _actor("trader_llama")
    assert newcontent.downgrade_actor(t2, (1, 19, 10)) is None
    assert newcontent.downgrade_actor(_actor("fox"), (1, 12, 0)) == "removed"
    assert newcontent.downgrade_actor(_actor("fox"), (1, 13, 0)) is None
    assert newcontent.downgrade_actor(_actor("pig"), (1, 1, 0)) is None


def test_java_to_bedrock_picks_the_identifier_by_target_version():
    def make(name):
        return entities.from_java_modern(_mob(name, 3700))

    assert str(_bedrock(make("villager"), (1, 10, 0))["identifier"].py_data) == "minecraft:villager"
    assert str(_bedrock(make("villager"), (1, 11, 0))["identifier"].py_data) == "minecraft:villager_v2"
    assert str(_bedrock(make("zombie_villager"), (1, 2, 0))["identifier"].py_data) == "minecraft:zombie_villager"
    assert str(_bedrock(make("zombie_villager"), (1, 21, 0))["identifier"].py_data) == "minecraft:zombie_villager_v2"
    t = _bedrock(make("trader_llama"), (1, 16, 220))
    assert str(t["identifier"].py_data) == "minecraft:llama" and "+minecraft:llama_wandering_trader" in _defs(t)
    assert _bedrock(make("fox"), (1, 12, 0)) is None and _bedrock(make("fox"), (1, 13, 0)) is not None
    assert _bedrock(make("parrot"), (1, 1, 0)) is None and _bedrock(make("pig"), (1, 1, 0)) is not None


def test_injector_counts_dropped_and_renamed_mobs(tmp_path):
    prog = Progress()
    _db(str(tmp_path), True).close()
    inj = BedrockInjector(str(tmp_path), (1, 1, 0), prog)
    try:
        cs = [entities.from_java_modern(_mob(n, 3700)) for n in ("villager", "fox", "pig", "parrot", "zombie_villager")]
        inj.put_chunk(0, 0, 0, [], cs)
        assert inj.n_ents == 3
    finally:
        inj.close()
    t = newcontent.tally_of(prog)
    assert t.entities == 2 and t.renamed == 2

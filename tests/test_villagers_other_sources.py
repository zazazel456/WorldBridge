"""Trades, experience and the bed / job site of villagers coming from Java 1.13+ and from old Java / LCE worlds."""
import numpy as np

from worldbridge import entities as ent
from worldbridge import nbt


def _java_villager():
    return nbt.CompoundTag({
        "id": nbt.StringTag("minecraft:villager"),
        "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(70.0), nbt.DoubleTag(1.5)], 6),
        "VillagerData": nbt.CompoundTag({"profession": nbt.StringTag("minecraft:armorer"), "level": nbt.IntTag(2),
                                         "type": nbt.StringTag("minecraft:plains")}),
        "Xp": nbt.IntTag(15),
        "Offers": nbt.CompoundTag({"Recipes": nbt.ListTag([nbt.CompoundTag({
            "buy": nbt.CompoundTag({"id": nbt.StringTag("minecraft:coal"), "Count": nbt.ByteTag(15)}),
            "sell": nbt.CompoundTag({"id": nbt.StringTag("minecraft:emerald"), "Count": nbt.ByteTag(1)}),
            "uses": nbt.IntTag(1), "maxUses": nbt.IntTag(16), "rewardExp": nbt.ByteTag(1), "xp": nbt.IntTag(2),
            "priceMultiplier": nbt.FloatTag(0.05), "specialPrice": nbt.IntTag(-1), "demand": nbt.IntTag(4)})], 10)}),
        "Brain": nbt.CompoundTag({"memories": nbt.CompoundTag({"minecraft:job_site": nbt.CompoundTag({"value": nbt.CompoundTag({
            "dimension": nbt.StringTag("minecraft:overworld"), "pos": nbt.IntArrayTag(np.array([5, 70, 6], np.int32))})})})})})


def test_a_java_villager_keeps_its_trades_experience_and_job_site():
    c = ent.from_java_modern(_java_villager())
    e = ent.to_java_modern(c, 2730)
    assert int(e["Xp"].py_data) == 15 and int(e["VillagerData"]["level"].py_data) == 2
    r = e["Offers"]["Recipes"][0]
    assert nbt.get(r["buy"], "id") == "minecraft:coal" and int(r["buy"]["Count"].py_data) == 15
    assert int(r["uses"].py_data) == 1 and int(r["specialPrice"].py_data) == -1 and int(r["demand"].py_data) == 4
    assert [int(x) for x in e["Brain"]["memories"]["minecraft:job_site"]["value"]["pos"]] == [5, 70, 6]


def test_an_old_java_villager_keeps_its_trades():
    old = nbt.CompoundTag({
        "id": nbt.StringTag("Villager"), "Profession": nbt.IntTag(3), "Career": nbt.IntTag(1), "CareerLevel": nbt.IntTag(3),
        "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(70.0), nbt.DoubleTag(1.5)], 6),
        "Offers": nbt.CompoundTag({"Recipes": nbt.ListTag([nbt.CompoundTag({
            "buy": nbt.CompoundTag({"id": nbt.ShortTag(263), "Count": nbt.ByteTag(10), "Damage": nbt.ShortTag(0)}),
            "sell": nbt.CompoundTag({"id": nbt.ShortTag(388), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)}),
            "uses": nbt.IntTag(0), "maxUses": nbt.IntTag(7), "rewardExp": nbt.ByteTag(1)})], 10)})})
    e = ent.to_java_modern(ent.from_legacy(old), 2730)
    assert e["VillagerData"]["profession"] == "minecraft:armorer" and int(e["VillagerData"]["level"].py_data) == 3
    r = e["Offers"]["Recipes"][0]
    assert nbt.get(r["buy"], "id") == "minecraft:coal" and nbt.get(r["sell"], "id") == "minecraft:emerald"
    assert int(r["maxUses"].py_data) == 7

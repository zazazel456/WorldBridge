"""LCE targets get only the items, enchantments and entities the game has (neoLegacy: checked
against its source), and player files with the fields and types the game writes."""
from worldbridge import nbt
from worldbridge.lce.compat import compat_for, lce_player, plain_sign_line
from worldbridge.lce.world import PROFILES, LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.lce.container import SaveContainer
from worldbridge.model import Progress

from .helpers import SyntheticWorld, make_chunk


def _item(iid, count=1, dmg=0, ench=None):
    it = nbt.CompoundTag({"id": nbt.ShortTag(iid), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(dmg)})
    if ench:
        it["tag"] = nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(e), "lvl": nbt.ShortTag(1)})
                                                         for e in ench], 10)})
    return it


def _neo():
    return compat_for("tu31", "win64", PROFILES["tu31"].allowed)


def test_neolegacy_items():
    c = _neo()
    assert int(nbt.get(c.item(_item(425, dmg=4)), "id")) == 176          # banner: neoLegacy's id
    assert nbt.get(c.item(_item(425, dmg=4)), "Damage") == 4
    assert int(nbt.get(c.item(_item(439)), "id")) == 262                 # spectral arrow -> arrow
    assert int(nbt.get(c.item(_item(446)), "id")) == 333                 # birch boat -> boat
    splash = c.item(_item(438, dmg=5))
    assert int(nbt.get(splash, "id")) == 373 and nbt.get(splash, "Damage") == 5 | 0x4000
    for gone in (442, 443, 452, 426, 450):                               # shield, elytra, nugget, crystal, shell
        assert c.item(_item(gone)) is None
    assert int(nbt.get(c.item(_item(435)), "id")) == 435                 # beetroot seeds: backported
    assert int(nbt.get(c.item(_item(2261)), "id")) == 2261               # records
    # enchantments: sweeping edge (22) and curses gone, fishing ones at neoLegacy's ids, mending kept
    it = c.item(_item(276, ench=[70, 22, 16, 61, 62, 71]))
    assert [int(nbt.get(e, "id")) for e in it["tag"]["ench"]] == [70, 16, 65, 64]
    # blocks as items follow the target's blocks (concrete 251 does not exist in 1.8)
    assert c.item(_item(1)) is not None
    assert int(nbt.get(c.item(_item(251, dmg=3)), "id")) in PROFILES["tu31"].allowed
    assert c.dropped["item 442"] == 1 and c.dropped["enchantment 22"] == 1


def test_console_profiles_keep_their_items():
    tu31 = compat_for("tu31", "ps4", PROFILES["tu31"].allowed)
    assert nbt.get(tu31.item(_item(425)), "id") == "minecraft:banner"    # consoles: Java's id, by name
    assert tu31.item(_item(442)) is None
    tu54 = compat_for("tu54", "ps4", PROFILES["tu54"].allowed)
    assert nbt.get(tu54.item(_item(442)), "id") == "minecraft:shield"
    it = tu54.item(_item(276, ench=[22, 61]))
    assert [int(nbt.get(e, "id")) for e in it["tag"]["ench"]] == [22, 61]


def test_entities_and_holders():
    c = _neo()
    assert c.entity(nbt.CompoundTag({"id": nbt.StringTag("Parrot")})) is None
    assert c.entity(nbt.CompoundTag({"id": nbt.StringTag("Item"), "Item": _item(443)})) is None
    frame = c.entity(nbt.CompoundTag({"id": nbt.StringTag("ItemFrame"), "Item": _item(442)}))
    assert frame is not None and "Item" not in frame
    vill = nbt.CompoundTag({"id": nbt.StringTag("Villager"), "Offers": nbt.CompoundTag({"Recipes": nbt.ListTag([
        nbt.CompoundTag({"buy": _item(388), "sell": _item(443)}),
        nbt.CompoundTag({"buy": _item(388), "sell": _item(425)})], 10)})})
    recipes = c.entity(vill)["Offers"]["Recipes"]
    assert len(recipes) == 1 and int(nbt.get(recipes[0]["sell"], "id")) == 176
    chest = c.holder(nbt.CompoundTag({"id": nbt.StringTag("Chest"),
                                      "Items": nbt.ListTag([_item(442), _item(264, 5)], 10)}))
    assert [int(nbt.get(i, "id")) for i in chest["Items"]] == [264]


def test_player_file_like_the_game():
    """A Java 1.20.5+ / Paper player: only the game's fields, its types, armour from "equipment"."""
    p = nbt.CompoundTag({
        "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(70.0), nbt.DoubleTag(2.5)], 6),
        "Health": nbt.FloatTag(14.0), "UUID": nbt.IntArrayTag([1, 2, 3, 4]), "Dimension": nbt.IntTag(0),
        "Inventory": nbt.ListTag([_item(276, ench=[70, 22])], 10),
        "equipment": nbt.CompoundTag({"head": nbt.CompoundTag({"id": nbt.StringTag("minecraft:diamond_helmet"),
                                                               "count": nbt.IntTag(1)})}),
        "Brain": nbt.CompoundTag(), "Paper.Origin": nbt.ListTag([], 6), "recipeBook": nbt.CompoundTag(),
        "SelectedItemSlot": nbt.IntTag(40), "XpLevel": nbt.IntTag(3),
    })
    p["Inventory"][0]["Slot"] = nbt.ByteTag(0)
    out = lce_player(p, _neo(), (10, 64, 20), name="Steve")
    game = {"AbsorptionAmount", "Air", "AttackTime", "DeathTime", "Dimension", "EnderItems", "FallDistance", "Fire",
            "HealF", "Health", "HurtTime", "Inventory", "Invulnerable", "Motion", "OnGround", "PortalCooldown", "Pos",
            "Rotation", "Score", "SelectedItemSlot", "SleepTimer", "Sleeping", "UUID", "XpLevel", "XpP", "XpTotal",
            "abilities", "enchSeed", "foodExhaustionLevel", "foodLevel", "foodSaturationLevel", "foodTickTimer"}
    assert set(out.keys()) == game                          # the keys of a players/<XUID>.dat written by neoLegacy
    assert isinstance(out["Health"], nbt.ShortTag) and nbt.get(out, "HealF") == 14.0
    assert nbt.get(out, "UUID") == "Steve" and nbt.get(out, "SelectedItemSlot") == 8
    slots = {int(nbt.get(i, "Slot")): int(nbt.get(i, "id")) for i in out["Inventory"]}
    assert slots == {0: 276, 103: 310}
    assert [int(nbt.get(e, "id")) for e in out["Inventory"][0]["tag"]["ench"]] == [70]
    # no position (its chunk was not converted): the world's spawn, never a player without Pos
    del p["Pos"]
    pos = [float(v.py_data) for v in lce_player(p, _neo(), (10, 64, 20))["Pos"]]
    assert pos == [10.5, 64.0, 20.5]


def test_sign_codes():
    assert plain_sign_line("§rdegli§l x") == "degli x"


def test_written_save_has_only_what_the_game_knows(tmp_path):
    src = SyntheticWorld(radius=1, dims=(0,))
    w = LCEWriter(str(tmp_path / "out"), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        c = make_chunk(cx, cz, 0)
        c.tile_entities[0]["Items"].append(_item(442))
        c.tile_entities[0]["Items"].append(_item(425, dmg=1))
        c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("Parrot"), "Pos": c.entities[0]["Pos"],
                                           "Motion": c.entities[0]["Motion"], "Rotation": c.entities[0]["Rotation"]}))
        w.add_chunk(0, c)
    player = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.DoubleTag(8.0), nbt.DoubleTag(64.0), nbt.DoubleTag(8.0)], 6),
                              "Health": nbt.FloatTag(20.0), "Inventory": nbt.ListTag([], 10)})
    src.info.players = {"16141134514358595374": player}
    path = w.finish(src.info)
    out = LCEWorld(path)
    c = out.read_raw_chunk(0, 0, 0)
    chest = [t for t in c.tile_entities if nbt.get(t, "id") == "Chest"][0]
    assert sorted(int(nbt.get(i, "id")) for i in chest["Items"]) == [176, 264]
    assert "Parrot" not in {nbt.get(e, "id") for e in c.entities}
    cont = SaveContainer.load(path)
    lvl = nbt.load(cont.files["level.dat"], compressed=None).tag["Data"]
    assert "RandomSeed" in lvl
    pl = nbt.load(cont.files["players/16141134514358595374.dat"], compressed=None).tag
    assert isinstance(pl["Health"], nbt.ShortTag) and "HealF" in pl

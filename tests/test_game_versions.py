"""Versions as each game stores them: Bedrock 26.x writes 1.26.x in its files and 1.21.60.33 in
its blocks; Java worlds carry only a DataVersion.  Every reader and writer must agree with that."""
import struct

from worldbridge import amulet_bridge as ab
from worldbridge import biomes as bio
from worldbridge import gameversion as gv
from worldbridge import items, nbt
from worldbridge.chunkedit import edit_world, world_game
from worldbridge.convert import TargetSpec, convert

from .test_chunkedit import _java

NEW = {"dappled_forest", "sulfur_caves"}


def _names(family, version):
    return {bio.modern_name(b) for b in bio.available(family, version)}


def test_bedrock_numbers():
    assert gv.bedrock((1, 26, 52, 3, 0)) == (26, 52, 3, 0)
    assert gv.bedrock((1, 21, 50)) == (1, 21, 50) and gv.bedrock((26, 50, 0)) == (26, 50, 0)
    assert gv.bedrock_stored((26, 50, 0)) == (1, 26, 50, 0, 0)
    assert gv.bedrock_stored((1, 21, 110)) == (1, 21, 110, 0, 0)
    assert gv.bedrock_label((1, 26, 52, 3, 0)) == "26.52.3" and gv.bedrock_label((1, 21, 50, 0, 0)) == "1.21.50"
    # the biomes of a 26.52 world, read as the game stores its version
    assert NEW <= _names("bedrock", (1, 26, 52, 3, 0))
    assert not NEW & _names("bedrock", (1, 21, 110))


def test_java_release_from_data_version():
    assert gv.java_from_data_version(ab.java_data_version((26, 3, 0))) == (26, 3, 0)
    assert gv.java_from_data_version(ab.java_data_version((26, 2, 0))) == (26, 2, 0)
    assert gv.java_from_data_version(ab.java_data_version((1, 21, 4))) == (1, 21, 4)


def test_bedrock_block_items_carry_the_block_state_version():
    for v in ((26, 50, 0), (1, 21, 110), (1, 20, 80)):
        it = items.to_bedrock({"name": "dirt", "count": 1}, v)
        expected = ab.translation_manager().get_version("bedrock", v).data_version
        assert int(nbt.get(it["Block"], "version")) == expected
    it = items.to_bedrock({"name": "dirt", "count": 1}, (26, 50, 0))
    assert int(nbt.get(it["Block"], "version")) == 0x01153C21     # 1.21.60.33, as 26.52 itself writes


def test_java_26_3_world_offers_and_takes_its_biomes(tmp_path):
    hub, _src = _java(tmp_path, "hub")
    world = str(tmp_path / "java")
    convert(hub, world, TargetSpec(family="java", java_mode="amulet", version=(26, 3, 0), ring=False, blend=False))
    fam, ver = world_game(world)
    assert fam == "java" and ver >= (26, 3)
    assert NEW <= _names(fam, ver)
    assert edit_world(world, paint={0: {(0, 0): bio.parse("dappled_forest")}}).painted == 1


def test_bedrock_26_world_is_stored_and_read_as_the_game_does(tmp_path):
    hub, _src = _java(tmp_path, "hub")
    world = tmp_path / "bedrock"
    convert(hub, str(world), TargetSpec(family="bedrock", version=(26, 50, 0), ring=False, blend=False))
    raw = (world / "level.dat").read_bytes()
    root = nbt.load(raw[8:struct.unpack_from("<i", raw, 4)[0] + 8], compressed=False, little_endian=True).tag
    for key in ("lastOpenedWithVersion", "MinimumCompatibleClientVersion"):
        assert [int(x.py_data) for x in nbt.get_tag(root, key)] == [1, 26, 50, 0, 0]
    fam, ver = world_game(str(world))
    assert fam == "bedrock" and ver[:2] == (26, 50)
    assert NEW <= _names(fam, ver)
    assert edit_world(str(world), paint={0: {(1, 1): bio.parse("dappled_forest")}}).painted == 1

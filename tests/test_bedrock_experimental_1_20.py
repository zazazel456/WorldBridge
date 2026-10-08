"""Hanging signs and the other 1.20 content are only an experiment in Bedrock 1.19.50 - 1.19.80 (found by opening the
converted worlds in BDS 1.12 ... 1.19.83): the block and the block entity must both be left out of such a target, and
both kept from 1.20.0."""
from __future__ import annotations

import amulet_nbt
import pytest
from amulet.api.block import Block

from worldbridge import amulet_bridge as ab
from worldbridge import nbt, newcontent, tiles
from worldbridge.bedrock import extra
from worldbridge.bedrock.extra import BedrockInjector, _db
from worldbridge.model import Progress


def _hanging():
    return {"kind": "hanging_sign", "pos": (1, 70, 2), "front": ["a", "", "", ""], "back": ["", "", "", ""]}


def test_hanging_sign_block_entity_exists_from_bedrock_1_20_0():
    for v in ((1, 12, 0), (1, 18, 30), (1, 19, 50), (1, 19, 80), (1, 19, 99)):
        assert not tiles.exists_in_bedrock("hanging_sign", v), v
    for v in ((1, 20, 0), (1, 20, 80), (1, 21, 130), (26, 50, 0)):
        assert tiles.exists_in_bedrock("hanging_sign", v), v
    t = tiles.to_bedrock(_hanging(), (1, 20, 80))
    assert t is not None and t["id"].py_data == "HangingSign"
    tally = newcontent.Tally()
    assert tiles.write_list([_hanging()], "bedrock", tally, version=(1, 19, 80)) == []
    assert tally.tile_ids == {"hanging_sign": 1}


def test_other_1_20_block_entities_start_with_the_release():
    for kind in ("chiseled_bookshelf", "brushable_block", "calibrated_sculk_sensor"):
        assert not tiles.exists_in_bedrock(kind, (1, 19, 80)) and tiles.exists_in_bedrock(kind, (1, 20, 0)), kind
    assert tiles.exists_in_bedrock("sculk_sensor", (1, 19, 0))            # the 1.19 content is not experimental
    assert tiles.exists_in_bedrock("decorated_pot", (1, 19, 80))          # not in BDS 1.19.83's experiment pack


def _inject(path, version):
    _db(str(path), True).close()
    inj = BedrockInjector(str(path), version, Progress())
    # the copy of Java's block entity that Amulet wrote
    stale = nbt.CompoundTag({"id": nbt.StringTag("HangingSign"), "x": nbt.IntTag(1), "y": nbt.IntTag(70), "z": nbt.IntTag(2)})
    key = extra.chunk_prefix(0, 0, 0) + bytes([extra.BE_TAG])
    inj.db.put(key, extra.write_nbt_list([stale]))
    return inj, key


@pytest.mark.parametrize("version,kept", [((1, 19, 80), 0), ((1, 18, 30), 0), ((1, 20, 0), 1), ((1, 21, 130), 1)])
def test_injector_keeps_the_hanging_sign_entity_only_where_the_game_has_it(tmp_path, version, kept):
    inj, key = _inject(tmp_path, version)
    try:
        inj.put_chunk(0, 0, 0, [_hanging()], [])
        got = extra.read_nbt_list(inj.db.get(key) or b"")
        assert [t["id"].py_data for t in got] == ["HangingSign"] * kept
    finally:
        inj.close()
    lost = newcontent.tally_of(inj.progress).tile_ids
    assert (lost == {"hanging_sign": 1}) == (kept == 0)


def test_translator_replaces_the_experimental_blocks_before_bedrock_1_20():
    ab._install_legacy_fallback()
    tm = ab.translation_manager()
    new = tm.get_version("bedrock", (1, 20, 80))
    src = Block("minecraft", "spruce_hanging_sign", {"facing_direction": amulet_nbt.TAG_Int(2), "hanging": amulet_nbt.TAG_Byte(0),
                                                    "ground_sign_direction": amulet_nbt.TAG_Int(0), "attached_bit": amulet_nbt.TAG_Byte(0)})
    uni = new.block.to_universal(src)[0]
    assert "hanging_sign" in uni.base_name
    for ver, is_air in (((1, 19, 80), True), ((1, 19, 50), True), ((1, 20, 0), False), ((1, 20, 80), False)):
        out = tm.get_version("bedrock", ver).block.from_universal(uni)[0]
        assert (out.base_name == "air") == is_air, (ver, out)
        assert ("hanging_sign" in out.base_name) == (not is_air), (ver, out)
    assert ab.bedrock_1_20_stand_in("oak_wall_hanging_sign") == (True, None)
    assert ab.bedrock_1_20_stand_in("chiseled_bookshelf") == (True, "bookshelf")
    assert ab.bedrock_1_20_stand_in("oak_sign") == (False, None)

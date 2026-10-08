"""Signs of Java <= 1.19 / Console worlds go through Amulet as universal signs that PyMCTranslate cannot translate to a
newer game as they are: the block stayed ``universal_minecraft:wall_sign``, which no game knows, and the sign was lost
(found with BDS 1.18+ and the Xbox 360 TU75 world: 6 signs -> 0)."""
from __future__ import annotations

import amulet_nbt
import pytest
from amulet.api.block import Block
from amulet.api.block_entity import BlockEntity

from worldbridge import amulet_bridge as ab
from worldbridge import items


def _java12_sign(name, lines):
    be = BlockEntity("java", "Sign", 1, 5, 1, amulet_nbt.NamedTag(amulet_nbt.CompoundTag(
        {f"Text{i}": amulet_nbt.StringTag(t) for i, t in enumerate(lines, 1)})))
    return Block("minecraft", name, {"block_data": amulet_nbt.IntTag(3)}), be


@pytest.mark.parametrize("bver", [(1, 17, 40), (1, 19, 80), (1, 21, 100)])
@pytest.mark.parametrize("name", ["wall_sign", "standing_sign"])
@pytest.mark.parametrize("lines", [("blaze", "", "", ""),
                                   ('{"text":"blaze"}', '{"text":""}', '{"text":""}', '{"text":""}')])
def test_signs_of_old_worlds_become_bedrock_signs(bver, name, lines):
    ab._install_legacy_fallback()
    tm = ab.translation_manager()
    block, be = _java12_sign(name, lines)
    ub, ube, _ = tm.get_version("java", (1, 12, 2)).block.to_universal(block, be)
    out = tm.get_version("bedrock", bver).block.from_universal(ub, ube)
    assert out[0].namespace == "minecraft" and out[0].base_name == name, out[0]
    assert out[1] is not None


def test_universal_sign_fix_leaves_other_signs_alone():
    ab._install_legacy_fallback()

    def sign(front):
        return BlockEntity("universal_minecraft", "sign", 0, 0, 0, amulet_nbt.NamedTag(amulet_nbt.CompoundTag(
            {"utags": amulet_nbt.CompoundTag({"front_text": amulet_nbt.CompoundTag(front)})})))

    assert ab.fix_universal_sign(sign({"messages": amulet_nbt.ListTag([amulet_nbt.StringTag('"a"')])})) is None
    ok = sign({"java_json": amulet_nbt.ListTag([amulet_nbt.StringTag(x) for x in ('"a"', '"b"', '"c"', '"d"')])})
    assert ab.fix_universal_sign(ok) is None
    bad = sign({"java_json": amulet_nbt.ListTag([amulet_nbt.StringTag(x) for x in ("", "plain", "", "", "")])})
    fixed = ab.fix_universal_sign(bad)
    lines = [str(x) for x in fixed.nbt.compound["utags"]["front_text"]["java_json"]]
    assert len(lines) == 4 and lines[0] == '{"text": "plain"}'


def test_sign_line_json():
    assert items.sign_line_json("blaze") == '{"text": "blaze"}' and items.sign_line_json('{"text":"x"}') == '{"text":"x"}'
    assert items.sign_line_json('"x"') == '"x"' and items.sign_line_json("{broken") == '{"text": "{broken"}'
    assert items.sign_line_json(None) == '{"text": ""}'

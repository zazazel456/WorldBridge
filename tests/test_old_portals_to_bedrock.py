"""A nether portal of the numeric games with data 0 or 3 (the games read it as the x axis) used to stay
``portal[block_data=0]``: a state no newer game has (BDS content log: "block 'minecraft:portal' updated to a state
'block_data' that it does not contain")."""
from __future__ import annotations

import amulet_nbt
import pytest
from amulet.api.block import Block

from worldbridge import amulet_bridge as ab


@pytest.mark.parametrize("data,axis", [(0, "x"), (1, "x"), (2, "z"), (3, "x")])
@pytest.mark.parametrize("platform,ver,prop,name", [("bedrock", (1, 17, 40), "portal_axis", "portal"),
                                                    ("bedrock", (1, 21, 100), "portal_axis", "portal"),
                                                    ("java", (1, 20, 4), "axis", "nether_portal")])
def test_numeric_nether_portal_always_gets_an_axis(data, axis, platform, ver, prop, name):
    ab._install_legacy_fallback()
    tm = ab.translation_manager()
    uni = tm.get_version("java", (1, 12, 2)).block.to_universal(
        Block("minecraft", "portal", {"block_data": amulet_nbt.IntTag(data)}))[0]
    out = tm.get_version(platform, ver).block.from_universal(uni)[0]
    assert out.base_name == name and "block_data" not in out.properties, out
    assert str(out.properties[prop].py_data) == axis

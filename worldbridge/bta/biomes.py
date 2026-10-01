"""BTA biomes -> Java Edition 26.3 biome names (validated against the vanilla biome registry)."""

from __future__ import annotations

import functools
import os
from typing import Optional

from . import stats
from .world import DRIFT, NETHER

_MAP = {}
for _names, _v in (
        (("overworld.rainforest", "overworld.legacy.rainforest"), "jungle"),
        (("overworld.swampland", "overworld.legacy.swampland"), "swamp"),
        (("overworld.swampland.muddy",), "mangrove_swamp"),
        (("overworld.seasonal_forest", "overworld.legacy.seasonal_forest"), "flower_forest"),
        (("overworld.forest", "overworld.legacy.forest"), "forest"),
        (("overworld.grasslands",), "sunflower_plains"),
        (("overworld.outback", "overworld.outback.grassy", "overworld.legacy.savanna"), "savanna"),
        (("overworld.caatinga", "overworld.caatinga.plains"), "savanna_plateau"),
        (("overworld.shrubland", "overworld.legacy.shrubland"), "plains"),
        (("overworld.taiga", "overworld.legacy.taiga"), "snowy_taiga"),
        (("overworld.boreal_forest",), "taiga"),
        (("overworld.desert", "overworld.legacy.desert"), "desert"),
        (("overworld.plains", "overworld.legacy.plains", "overworld.retro"), "plains"),
        (("overworld.glacier",), "ice_spikes"),
        (("overworld.tundra", "overworld.legacy.tundra"), "snowy_plains"),
        (("overworld.meadow",), "meadow"),
        (("overworld.birch_forest",), "birch_forest"),
        (("overworld.hell",), "badlands"),
        (("nether.volcanic_islands", "nether.crag"), "basalt_deltas"),
        (("nether.crystal_plains", "nether.crystal_forest"), "crimson_forest"),
        (("nether.old_world.desert",), "soul_sand_valley"),
        (("nether.sulfur_pools", "nether.old_world", "nether.shelf", "nether.legacy.hell", "nether.nether"), "nether_wastes"),
        (("drift.drift",), "end_highlands")):
    for _n in _names:
        _MAP[_n] = "minecraft:" + _v


def fallback(dimension: int) -> str:
    if dimension == NETHER:
        return "minecraft:nether_wastes"
    if dimension == DRIFT:
        return "minecraft:end_highlands"
    return "minecraft:plains"


def map_biome(bta: Optional[str], dimension: int) -> str:
    if bta is None:
        return fallback(dimension)
    b = bta[10:] if bta.startswith("minecraft:") else bta
    v = _MAP.get(b)
    if v is None:
        stats.inc(f"biome.unknown.{b}")
        return fallback(dimension)
    return v


@functools.lru_cache(maxsize=None)
def vanilla_biomes() -> frozenset:
    with open(os.path.join(os.path.dirname(__file__), "data", "biomes-26.3.txt"), encoding="utf-8") as f:
        return frozenset(line.strip() for line in f if line.strip())

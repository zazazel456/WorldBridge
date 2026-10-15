"""Data of the Bedrock overworld generator before 1.18 (bedrockgen.py, bedrockbiomes.py, bedrocksurface.py).

Everything here is game data observed in Bedrock Dedicated Server 1.16.220: the biome definitions of its
``definitions/biomes`` folder (tags, temperature, hills / mutation / climate lists, surface materials) and the
depth / scale floats of its biome objects.  Block names are Bedrock's without the ``minecraft:`` prefix, a block
state is appended in brackets (``sand[sand_type=red]``).
"""

from __future__ import annotations

from typing import Dict, NamedTuple, Tuple

# id -> name of every overworld biome the old generator can produce (Bedrock registry ids)
BIOME_IDS: Dict[int, str] = {
    0: "ocean", 1: "plains", 2: "desert", 3: "extreme_hills", 4: "forest", 5: "taiga", 6: "swampland", 7: "river",
    8: "hell", 9: "the_end", 10: "legacy_frozen_ocean", 11: "frozen_river", 12: "ice_plains", 13: "ice_mountains",
    14: "mushroom_island", 15: "mushroom_island_shore", 16: "beach", 17: "desert_hills", 18: "forest_hills",
    19: "taiga_hills", 20: "extreme_hills_edge", 21: "jungle", 22: "jungle_hills", 23: "jungle_edge",
    24: "deep_ocean", 25: "stone_beach", 26: "cold_beach", 27: "birch_forest", 28: "birch_forest_hills",
    29: "roofed_forest", 30: "cold_taiga", 31: "cold_taiga_hills", 32: "mega_taiga", 33: "mega_taiga_hills",
    34: "extreme_hills_plus_trees", 35: "savanna", 36: "savanna_plateau", 37: "mesa", 38: "mesa_plateau_stone",
    39: "mesa_plateau", 40: "warm_ocean", 41: "deep_warm_ocean", 42: "lukewarm_ocean", 43: "deep_lukewarm_ocean",
    44: "cold_ocean", 45: "deep_cold_ocean", 46: "frozen_ocean", 47: "deep_frozen_ocean", 48: "bamboo_jungle",
    49: "bamboo_jungle_hills", 129: "sunflower_plains", 130: "desert_mutated", 131: "extreme_hills_mutated",
    132: "flower_forest", 133: "taiga_mutated", 134: "swampland_mutated", 140: "ice_plains_spikes",
    149: "jungle_mutated", 151: "jungle_edge_mutated", 155: "birch_forest_mutated",
    156: "birch_forest_hills_mutated", 157: "roofed_forest_mutated", 158: "cold_taiga_mutated",
    160: "redwood_taiga_mutated", 161: "redwood_taiga_hills_mutated", 162: "extreme_hills_plus_trees_mutated",
    163: "savanna_mutated", 164: "savanna_plateau_mutated", 165: "mesa_bryce", 166: "mesa_plateau_stone_mutated",
    167: "mesa_plateau_mutated",
}

# name -> id, tags, climate temperature, minimum snow accumulation, biome type (the "same kind" test of the
# hills rule), hills / mutation lists [[name, weight]] and the temperature classes it is generated for [[class, weight]]
# (0 medium, 1 warm, 2 lukewarm, 3 cold, 4 frozen)
BIOMES: Dict[str, dict] = {
    "ocean": dict(
        id=0, temp=0.5, snow=0.0, type=10,
        tags=("monster", "ocean", "overworld"),
        hills=[["deep_ocean", 1]], mutate=[],
        climates=[[0, 1]]),
    "plains": dict(
        id=1, temp=0.8, snow=0.0, type=11,
        tags=("animal", "bee_habitat", "monster", "overworld", "plains"),
        hills=[["forest_hills", 1], ["forest", 2]], mutate=[["sunflower_plains", 1]],
        climates=[[0, 3], [1, 1], [3, 1]]),
    "desert": dict(
        id=2, temp=2.0, snow=0.0, type=1,
        tags=("desert", "monster", "overworld"),
        hills=[["desert_hills", 1]], mutate=[["desert_mutated", 1]],
        climates=[[1, 3]]),
    "extreme_hills": dict(
        id=3, temp=0.2, snow=0.0, type=2,
        tags=("animal", "extreme_hills", "monster", "overworld"),
        hills=[["extreme_hills_plus_trees", 1]], mutate=[["extreme_hills_mutated", 1]],
        climates=[[0, 1], [3, 1]]),
    "forest": dict(
        id=4, temp=0.7, snow=0.0, type=4,
        tags=("animal", "bee_habitat", "forest", "monster", "overworld"),
        hills=[["forest_hills", 1]], mutate=[["flower_forest", 1]],
        climates=[[0, 1], [3, 1]]),
    "taiga": dict(
        id=5, temp=0.25, snow=0.0, type=16,
        tags=("animal", "forest", "monster", "overworld", "taiga"),
        hills=[["taiga_hills", 1]], mutate=[["taiga_mutated", 1]],
        climates=[[3, 1]]),
    "swampland": dict(
        id=6, temp=0.8, snow=0.0, type=15,
        tags=("animal", "monster", "overworld", "swamp"),
        hills=[], mutate=[["swampland_mutated", 1]],
        climates=[[0, 1]]),
    "river": dict(
        id=7, temp=0.5, snow=0.0, type=12,
        tags=("overworld", "river"),
        hills=[], mutate=[],
        climates=[]),
    "hell": dict(
        id=8, temp=2.0, snow=0.0, type=5,
        tags=("nether", "nether_wastes", "spawn_endermen", "spawn_few_piglins", "spawn_ghast", "spawn_magma_cubes",
            "spawn_zombified_piglin"),
        hills=[], mutate=[],
        climates=[]),
    "the_end": dict(
        id=9, temp=0.5, snow=0.0, type=17,
        tags=("the_end",),
        hills=[], mutate=[],
        climates=[]),
    "legacy_frozen_ocean": dict(
        id=10, temp=0.0, snow=0.125, type=10,
        tags=("frozen", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "frozen_river": dict(
        id=11, temp=0.0, snow=0.125, type=12,
        tags=("frozen", "overworld", "river"),
        hills=[], mutate=[],
        climates=[]),
    "ice_plains": dict(
        id=12, temp=0.0, snow=0.25, type=6,
        tags=("frozen", "ice", "ice_plains", "overworld"),
        hills=[["ice_mountains", 1]], mutate=[["ice_plains_spikes", 1]],
        climates=[[4, 3]]),
    "ice_mountains": dict(
        id=13, temp=0.0, snow=0.375, type=6,
        tags=("frozen", "ice", "mountain", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "mushroom_island": dict(
        id=14, temp=0.9, snow=0.0, type=9,
        tags=("mooshroom_island", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "mushroom_island_shore": dict(
        id=15, temp=0.9, snow=0.0, type=9,
        tags=("mooshroom_island", "overworld", "shore"),
        hills=[], mutate=[],
        climates=[]),
    "beach": dict(
        id=16, temp=0.8, snow=0.0, type=0,
        tags=("beach", "monster", "overworld", "warm"),
        hills=[], mutate=[],
        climates=[]),
    "desert_hills": dict(
        id=17, temp=2.0, snow=0.0, type=1,
        tags=("desert", "hills", "monster", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "forest_hills": dict(
        id=18, temp=0.7, snow=0.0, type=4,
        tags=("animal", "bee_habitat", "forest", "hills", "monster", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "taiga_hills": dict(
        id=19, temp=0.25, snow=0.0, type=16,
        tags=("animal", "forest", "hills", "monster", "overworld", "taiga"),
        hills=[], mutate=[],
        climates=[]),
    "extreme_hills_edge": dict(
        id=20, temp=0.2, snow=0.0, type=2,
        tags=("animal", "edge", "extreme_hills", "monster", "mountain", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "jungle": dict(
        id=21, temp=0.95, snow=0.0, type=7,
        tags=("animal", "jungle", "monster", "overworld", "rare"),
        hills=[["jungle_hills", 1]], mutate=[["jungle_mutated", 1]],
        climates=[[0, 1]]),
    "jungle_hills": dict(
        id=22, temp=0.95, snow=0.0, type=7,
        tags=("animal", "hills", "jungle", "monster", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "jungle_edge": dict(
        id=23, temp=0.95, snow=0.0, type=7,
        tags=("animal", "edge", "jungle", "monster", "overworld"),
        hills=[], mutate=[["jungle_edge_mutated", 1]],
        climates=[]),
    "deep_ocean": dict(
        id=24, temp=0.5, snow=0.0, type=10,
        tags=("deep", "monster", "ocean", "overworld"),
        hills=[["plains", 1], ["forest", 1]], mutate=[],
        climates=[[0, 1]]),
    "stone_beach": dict(
        id=25, temp=0.2, snow=0.0, type=14,
        tags=("beach", "monster", "overworld", "stone"),
        hills=[], mutate=[],
        climates=[]),
    "cold_beach": dict(
        id=26, temp=0.05, snow=0.125, type=0,
        tags=("beach", "cold", "monster", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "birch_forest": dict(
        id=27, temp=0.6, snow=0.0, type=4,
        tags=("animal", "bee_habitat", "birch", "forest", "monster", "overworld"),
        hills=[["birch_forest_hills", 1]], mutate=[["birch_forest_mutated", 1]],
        climates=[[0, 1]]),
    "birch_forest_hills": dict(
        id=28, temp=0.6, snow=0.0, type=4,
        tags=("animal", "bee_habitat", "birch", "forest", "hills", "monster", "overworld"),
        hills=[], mutate=[["birch_forest_hills_mutated", 1]],
        climates=[]),
    "roofed_forest": dict(
        id=29, temp=0.7, snow=0.0, type=4,
        tags=("animal", "forest", "monster", "no_legacy_worldgen", "overworld", "roofed"),
        hills=[["plains", 1]], mutate=[["roofed_forest_mutated", 1]],
        climates=[[0, 1]]),
    "cold_taiga": dict(
        id=30, temp=-0.5, snow=0.125, type=16,
        tags=("animal", "cold", "forest", "monster", "overworld", "taiga"),
        hills=[["cold_taiga_hills", 1]], mutate=[["cold_taiga_mutated", 1]],
        climates=[[4, 1]]),
    "cold_taiga_hills": dict(
        id=31, temp=-0.5, snow=0.125, type=16,
        tags=("animal", "cold", "forest", "hills", "monster", "overworld", "taiga"),
        hills=[], mutate=[],
        climates=[]),
    "mega_taiga": dict(
        id=32, temp=0.3, snow=0.0, type=16,
        tags=("animal", "forest", "mega", "monster", "overworld", "rare", "taiga"),
        hills=[["mega_taiga_hills", 1]], mutate=[["redwood_taiga_mutated", 1]],
        climates=[[3, 1]]),
    "mega_taiga_hills": dict(
        id=33, temp=0.3, snow=0.0, type=16,
        tags=("animal", "forest", "hills", "mega", "monster", "overworld", "taiga"),
        hills=[], mutate=[["redwood_taiga_hills_mutated", 1]],
        climates=[]),
    "extreme_hills_plus_trees": dict(
        id=34, temp=0.2, snow=0.0, type=2,
        tags=("animal", "extreme_hills", "forest", "monster", "mountain", "overworld"),
        hills=[], mutate=[["extreme_hills_plus_trees_mutated", 1]],
        climates=[]),
    "savanna": dict(
        id=35, temp=1.2, snow=0.0, type=13,
        tags=("animal", "monster", "overworld", "savanna"),
        hills=[["savanna_plateau", 1]], mutate=[["savanna_mutated", 1]],
        climates=[[1, 2]]),
    "savanna_plateau": dict(
        id=36, temp=1.0, snow=0.0, type=13,
        tags=("animal", "monster", "overworld", "plateau", "savanna"),
        hills=[], mutate=[["savanna_plateau_mutated", 1]],
        climates=[]),
    "mesa": dict(
        id=37, temp=2.0, snow=0.0, type=8,
        tags=("mesa", "monster", "overworld"),
        hills=[], mutate=[["mesa_bryce", 1]],
        climates=[]),
    "mesa_plateau_stone": dict(
        id=38, temp=2.0, snow=0.0, type=8,
        tags=("mesa", "monster", "overworld", "plateau", "rare", "stone"),
        hills=[["mesa", 1]], mutate=[["mesa_plateau_stone_mutated", 1]],
        climates=[[1, 2]]),
    "mesa_plateau": dict(
        id=39, temp=2.0, snow=0.0, type=8,
        tags=("mesa", "monster", "overworld", "plateau", "rare"),
        hills=[["mesa", 1]], mutate=[["mesa_plateau_mutated", 1]],
        climates=[[1, 1]]),
    "warm_ocean": dict(
        id=40, temp=0.5, snow=0.0, type=10,
        tags=("monster", "ocean", "overworld", "warm"),
        hills=[], mutate=[],
        climates=[[1, 1]]),
    "deep_warm_ocean": dict(
        id=41, temp=0.5, snow=0.0, type=10,
        tags=("deep", "monster", "ocean", "overworld", "warm"),
        hills=[], mutate=[],
        climates=[]),
    "lukewarm_ocean": dict(
        id=42, temp=0.5, snow=0.0, type=10,
        tags=("lukewarm", "monster", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[[2, 1]]),
    "deep_lukewarm_ocean": dict(
        id=43, temp=0.5, snow=0.0, type=10,
        tags=("deep", "lukewarm", "monster", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[[2, 1]]),
    "cold_ocean": dict(
        id=44, temp=0.5, snow=0.0, type=10,
        tags=("cold", "monster", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[[3, 1]]),
    "deep_cold_ocean": dict(
        id=45, temp=0.5, snow=0.0, type=10,
        tags=("cold", "deep", "monster", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[[3, 1]]),
    "frozen_ocean": dict(
        id=46, temp=0.0, snow=0.125, type=10,
        tags=("frozen", "monster", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[[4, 1]]),
    "deep_frozen_ocean": dict(
        id=47, temp=0.0, snow=0.125, type=10,
        tags=("deep", "frozen", "monster", "ocean", "overworld"),
        hills=[], mutate=[],
        climates=[[4, 1]]),
    "bamboo_jungle": dict(
        id=48, temp=0.95, snow=0.0, type=7,
        tags=("animal", "bamboo", "jungle", "monster", "overworld"),
        hills=[["bamboo_jungle_hills", 1]], mutate=[],
        climates=[]),
    "bamboo_jungle_hills": dict(
        id=49, temp=0.95, snow=0.0, type=7,
        tags=("animal", "bamboo", "hills", "jungle", "monster", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "sunflower_plains": dict(
        id=129, temp=0.8, snow=0.0, type=11,
        tags=("animal", "bee_habitat", "monster", "mutated", "overworld", "plains"),
        hills=[], mutate=[],
        climates=[]),
    "desert_mutated": dict(
        id=130, temp=2.0, snow=0.0, type=1,
        tags=("desert", "monster", "mutated", "overworld_generation"),
        hills=[], mutate=[],
        climates=[]),
    "extreme_hills_mutated": dict(
        id=131, temp=0.2, snow=0.0, type=2,
        tags=("animal", "extreme_hills", "monster", "mutated", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "flower_forest": dict(
        id=132, temp=0.7, snow=0.0, type=4,
        tags=("bee_habitat", "flower_forest", "monster", "mutated", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "taiga_mutated": dict(
        id=133, temp=0.25, snow=0.0, type=16,
        tags=("animal", "forest", "monster", "mutated", "overworld_generation", "taiga"),
        hills=[], mutate=[],
        climates=[]),
    "swampland_mutated": dict(
        id=134, temp=0.8, snow=0.0, type=15,
        tags=("animal", "monster", "mutated", "overworld_generation", "swamp"),
        hills=[], mutate=[],
        climates=[]),
    "ice_plains_spikes": dict(
        id=140, temp=0.0, snow=0.5, type=6,
        tags=("frozen", "ice_plains", "monster", "mutated", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "jungle_mutated": dict(
        id=149, temp=0.95, snow=0.0, type=7,
        tags=("animal", "jungle", "monster", "mutated", "overworld_generation"),
        hills=[], mutate=[],
        climates=[]),
    "jungle_edge_mutated": dict(
        id=151, temp=0.95, snow=0.0, type=7,
        tags=("animal", "edge", "jungle", "monster", "mutated", "overworld_generation"),
        hills=[], mutate=[],
        climates=[]),
    "birch_forest_mutated": dict(
        id=155, temp=0.7, snow=0.0, type=4,
        tags=("animal", "bee_habitat", "birch", "forest", "monster", "mutated", "overworld_generation"),
        hills=[], mutate=[],
        climates=[]),
    "birch_forest_hills_mutated": dict(
        id=156, temp=0.7, snow=0.0, type=4,
        tags=("animal", "birch", "forest", "hills", "monster", "mutated", "overworld_generation"),
        hills=[], mutate=[],
        climates=[]),
    "roofed_forest_mutated": dict(
        id=157, temp=0.7, snow=0.0, type=4,
        tags=("animal", "forest", "monster", "mutated", "overworld_generation", "roofed"),
        hills=[], mutate=[],
        climates=[]),
    "cold_taiga_mutated": dict(
        id=158, temp=-0.5, snow=0.0, type=16,
        tags=("animal", "cold", "forest", "monster", "mutated", "overworld_generation", "taiga"),
        hills=[], mutate=[],
        climates=[]),
    "redwood_taiga_mutated": dict(
        id=160, temp=0.25, snow=0.0, type=16,
        tags=("animal", "forest", "mega", "monster", "mutated", "overworld", "taiga"),
        hills=[], mutate=[],
        climates=[]),
    "redwood_taiga_hills_mutated": dict(
        id=161, temp=0.3, snow=0.0, type=16,
        tags=("animal", "forest", "hills", "mega", "monster", "mutated", "overworld_generation", "taiga"),
        hills=[], mutate=[],
        climates=[]),
    "extreme_hills_plus_trees_mutated": dict(
        id=162, temp=0.2, snow=0.0, type=2,
        tags=("animal", "extreme_hills", "forest", "monster", "mutated", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "savanna_mutated": dict(
        id=163, temp=1.1, snow=0.0, type=13,
        tags=("animal", "monster", "mutated", "overworld", "savanna"),
        hills=[], mutate=[],
        climates=[]),
    "savanna_plateau_mutated": dict(
        id=164, temp=1.0, snow=0.0, type=13,
        tags=("animal", "monster", "mutated", "overworld", "plateau", "savanna"),
        hills=[], mutate=[],
        climates=[]),
    "mesa_bryce": dict(
        id=165, temp=2.0, snow=0.0, type=8,
        tags=("animal", "mesa", "monster", "mutated", "overworld"),
        hills=[], mutate=[],
        climates=[]),
    "mesa_plateau_stone_mutated": dict(
        id=166, temp=2.0, snow=0.0, type=8,
        tags=("mesa", "monster", "mutated", "overworld", "plateau"),
        hills=[], mutate=[],
        climates=[]),
    "mesa_plateau_mutated": dict(
        id=167, temp=2.0, snow=0.0, type=8,
        tags=("mesa", "monster", "mutated", "overworld", "plateau", "stone"),
        hills=[], mutate=[],
        climates=[]),
}

# (depth, scale) of the height profiles that biomes share (``minecraft:overworld_height`` ``noise_type``)
HEIGHT_PROFILES: Dict[str, Tuple[float, float]] = {
    "default": (0.1, 0.2),
    "default_mutated": (0.2, 0.4),
    "lowlands": (0.125, 0.05),
    "river": (-0.5, 0.0),
    "ocean": (-1.0, 0.1),
    "deep_ocean": (-1.8, 0.1),
    "swamp": (-0.2, 0.1),
    "beach": (0.0, 0.025),
    "stone_beach": (0.1, 0.8),
    "mountains": (0.45, 0.3),
    "highlands": (1.5, 0.025),
    "extreme": (1.0, 0.5),
    "taiga": (0.2, 0.2),
    "mushroom": (0.2, 0.3),
    "less_extreme": (0.8, 0.3),
}
# id -> profile name, or its own (depth, scale), as the biome definitions say.  The biome objects of BDS gave
# the floats of 38 ids, all equal to their profile; "mushroom" (mushroom_island) and "less_extreme"
# (extreme_hills_edge, which the biome graph never produces) are not among them and carry the values
# Java gives those biomes.
BIOME_HEIGHT: Dict[int, object] = {
    0: "ocean", 1: "lowlands", 2: "lowlands", 3: "extreme", 4: "default", 5: "default", 6: "swamp", 7: "river",
    10: "ocean", 11: "river", 12: "lowlands", 13: "mountains", 14: "mushroom", 15: "beach", 16: "beach",
    17: "mountains", 18: "mountains", 19: "mountains", 20: "less_extreme", 21: "default", 22: "mountains",
    23: "default", 24: "deep_ocean", 25: "stone_beach", 26: "beach", 27: "default", 28: "mountains", 29: "default",
    30: "taiga", 31: "mountains", 32: "taiga", 33: "mountains", 34: "extreme", 35: "lowlands", 36: "highlands",
    37: "default", 38: "highlands", 39: "highlands", 40: "ocean", 41: "deep_ocean", 42: "ocean", 43: "deep_ocean",
    44: "ocean", 45: "deep_ocean", 46: "ocean", 47: "deep_ocean", 48: "default", 49: "mountains", 129: "lowlands",
    130: (0.225, 0.25), 131: "extreme", 132: (0.1, 0.4), 133: "default_mutated", 134: (-0.1, 0.3),
    140: (0.425, 0.45), 149: "default_mutated", 151: "default_mutated", 155: "default_mutated", 156: (0.55, 0.5),
    157: "default_mutated", 158: (0.3, 0.4), 160: "taiga", 161: (0.55, 0.5), 162: "extreme", 163: (0.3625, 1.225),
    164: (1.05, 1.2125), 165: "default", 166: "mountains", 167: "mountains",
}


class Adjustment(NamedTuple):
    """``minecraft:surface_material_adjustments`` entry: where the noise at the column is in [lo, hi) the listed
    material slots (top, mid, floor, base, sea) are replaced."""
    scale: float
    lo: float
    hi: float
    slots: Dict[str, str]


class SurfaceDef(NamedTuple):
    kind: str                       # default, swamp, frozen, mesa
    temp: float
    top: str = "grass"
    mid: str = "dirt"
    floor: str = "gravel"           # sea floor material (deeper than ``floor_depth`` under the sea)
    base: str = "stone"             # foundation material
    sea: str = "water"
    floor_depth: int = 7
    adjust: Tuple[Adjustment, ...] = ()
    bryce: bool = False             # mesa: pillars (mesa_bryce)
    forest: bool = False            # mesa: grass and coarse dirt on the high ground (mesa_plateau_stone)


# id -> surface of the biome (biomes without an entry, legacy_frozen_ocean, are left as the terrain made them)
SURFACES: Dict[int, SurfaceDef] = {
    0: SurfaceDef("default", 0.5),  # ocean
    1: SurfaceDef("default", 0.8),  # plains
    2: SurfaceDef("default", 2.0, top="sand", mid="sand"),  # desert
    3: SurfaceDef("default", 0.2,  # extreme_hills
        adjust=(
            Adjustment(0.0625, 0.121, 1.0, {"mid": "stone", "top": "stone"}),
        )),
    4: SurfaceDef("default", 0.7),  # forest
    5: SurfaceDef("default", 0.25),  # taiga
    6: SurfaceDef("swamp", 0.8),  # swampland
    7: SurfaceDef("default", 0.5),  # river
    11: SurfaceDef("default", 0.0),  # frozen_river
    12: SurfaceDef("default", 0.0),  # ice_plains
    13: SurfaceDef("default", 0.0),  # ice_mountains
    14: SurfaceDef("default", 0.9, top="mycelium"),  # mushroom_island
    15: SurfaceDef("default", 0.9, top="mycelium"),  # mushroom_island_shore
    16: SurfaceDef("default", 0.8, top="sand", mid="sand"),  # beach
    17: SurfaceDef("default", 2.0, top="sand", mid="sand"),  # desert_hills
    18: SurfaceDef("default", 0.7),  # forest_hills
    19: SurfaceDef("default", 0.25),  # taiga_hills
    20: SurfaceDef("default", 0.2),  # extreme_hills_edge
    21: SurfaceDef("default", 0.95),  # jungle
    22: SurfaceDef("default", 0.95),  # jungle_hills
    23: SurfaceDef("default", 0.95),  # jungle_edge
    24: SurfaceDef("default", 0.5),  # deep_ocean
    25: SurfaceDef("default", 0.2, top="stone", mid="stone"),  # stone_beach
    26: SurfaceDef("default", 0.05, top="sand", mid="sand"),  # cold_beach
    27: SurfaceDef("default", 0.6),  # birch_forest
    28: SurfaceDef("default", 0.6),  # birch_forest_hills
    29: SurfaceDef("default", 0.7),  # roofed_forest
    30: SurfaceDef("default", -0.5),  # cold_taiga
    31: SurfaceDef("default", -0.5),  # cold_taiga_hills
    32: SurfaceDef("default", 0.3,  # mega_taiga
        adjust=(
            Adjustment(0.0625, 0.212, 1.0, {"top": "dirt[dirt_type=coarse]"}),
            Adjustment(0.0625, -0.115, 0.212, {"top": "podzol"}),
        )),
    33: SurfaceDef("default", 0.3,  # mega_taiga_hills
        adjust=(
            Adjustment(0.0625, 0.212, 1.0, {"top": "dirt[dirt_type=coarse]"}),
            Adjustment(0.0625, -0.115, 0.212, {"top": "podzol"}),
        )),
    34: SurfaceDef("default", 0.2),  # extreme_hills_plus_trees
    35: SurfaceDef("default", 1.2),  # savanna
    36: SurfaceDef("default", 1.0),  # savanna_plateau
    37: SurfaceDef("mesa", 2.0, top="sand[sand_type=red]", mid="hardened_clay"),  # mesa
    38: SurfaceDef("mesa", 2.0, top="sand[sand_type=red]", mid="hardened_clay", forest=True),  # mesa_plateau_stone
    39: SurfaceDef("mesa", 2.0, top="sand[sand_type=red]", mid="hardened_clay"),  # mesa_plateau
    40: SurfaceDef("default", 0.5, floor="sand", floor_depth=3),  # warm_ocean
    41: SurfaceDef("default", 0.5, floor="sand", floor_depth=3),  # deep_warm_ocean
    42: SurfaceDef("default", 0.5, floor="sand", floor_depth=3),  # lukewarm_ocean
    43: SurfaceDef("default", 0.5, floor="sand"),  # deep_lukewarm_ocean
    44: SurfaceDef("default", 0.5),  # cold_ocean
    45: SurfaceDef("default", 0.5),  # deep_cold_ocean
    46: SurfaceDef("frozen", 0.0),  # frozen_ocean
    47: SurfaceDef("frozen", 0.0),  # deep_frozen_ocean
    48: SurfaceDef("default", 0.95),  # bamboo_jungle
    49: SurfaceDef("default", 0.95),  # bamboo_jungle_hills
    129: SurfaceDef("default", 0.8),  # sunflower_plains
    130: SurfaceDef("default", 2.0, top="sand", mid="sand"),  # desert_mutated
    131: SurfaceDef("default", 0.2,  # extreme_hills_mutated
        adjust=(
            Adjustment(0.0625, -1.0, -0.012, {"mid": "gravel", "top": "gravel"}),
            Adjustment(0.0625, 0.024, 1.0, {"mid": "gravel", "top": "gravel"}),
        )),
    132: SurfaceDef("default", 0.7),  # flower_forest
    133: SurfaceDef("default", 0.25),  # taiga_mutated
    134: SurfaceDef("swamp", 0.8),  # swampland_mutated
    140: SurfaceDef("default", 0.0, top="snow"),  # ice_plains_spikes
    149: SurfaceDef("default", 0.95),  # jungle_mutated
    151: SurfaceDef("default", 0.95),  # jungle_edge_mutated
    155: SurfaceDef("default", 0.7),  # birch_forest_mutated
    156: SurfaceDef("default", 0.7),  # birch_forest_hills_mutated
    157: SurfaceDef("default", 0.7),  # roofed_forest_mutated
    158: SurfaceDef("default", -0.5),  # cold_taiga_mutated
    160: SurfaceDef("default", 0.25,  # redwood_taiga_mutated
        adjust=(
            Adjustment(0.0625, 0.212, 1.0, {"top": "dirt[dirt_type=coarse]"}),
            Adjustment(0.0625, -0.115, 0.212, {"top": "podzol"}),
        )),
    161: SurfaceDef("default", 0.3,  # redwood_taiga_hills_mutated
        adjust=(
            Adjustment(0.0625, 0.212, 1.0, {"top": "dirt[dirt_type=coarse]"}),
            Adjustment(0.0625, -0.115, 0.212, {"top": "podzol"}),
        )),
    162: SurfaceDef("default", 0.2,  # extreme_hills_plus_trees_mutated
        adjust=(
            Adjustment(0.0625, -1.0, -0.012, {"mid": "gravel", "top": "gravel"}),
            Adjustment(0.0625, 0.024, 1.0, {"mid": "gravel", "top": "gravel"}),
        )),
    163: SurfaceDef("default", 1.1,  # savanna_mutated
        adjust=(
            Adjustment(0.0625, 0.212, 1.0, {"mid": "stone", "top": "stone"}),
            Adjustment(0.0625, -0.061, 0.212, {"top": "dirt[dirt_type=coarse]"}),
        )),
    164: SurfaceDef("default", 1.0,  # savanna_plateau_mutated
        adjust=(
            Adjustment(0.0625, 0.212, 1.0, {"mid": "stone", "top": "stone"}),
            Adjustment(0.0625, -0.061, 0.212, {"top": "dirt[dirt_type=coarse]"}),
        )),
    165: SurfaceDef("mesa", 2.0, top="sand[sand_type=red]", mid="hardened_clay", bryce=True),  # mesa_bryce
    166: SurfaceDef("mesa", 2.0, top="sand[sand_type=red]", mid="hardened_clay"),  # mesa_plateau_stone_mutated
    167: SurfaceDef("mesa", 2.0, top="sand[sand_type=red]", mid="hardened_clay"),  # mesa_plateau_mutated
}

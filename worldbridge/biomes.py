"""The biomes WorldBridge lets the user paint on a selection of chunks (map tab: "Bioma dei chunk
selezionati"), and which of them each game has.

A biome is kept as its numeric id: the ids of Java 1.12 (0 - 39 and the "mutated" 129 - 167), the ones
Java 1.13 - 1.17 added (40 - 50, 127, 168 - 175) and, for the biomes that only exist from 1.18 on and
never had a number, ids from 1000.  The list offered, and the names shown, follow the game of the
world being edited or of the conversion's target: LCE and Java up to 1.12 with their English names
("Swampland", "Extreme Hills"...), Java 1.13 - 1.17 with the 1.13 ids, 1.18+ with the current ones.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .i18n import language, tr

# id -> (Java 1.13 name, Italian label)
BIOMES: Dict[int, Tuple[str, str]] = {
    0: ("ocean", "Oceano"), 1: ("plains", "Pianura"), 2: ("desert", "Deserto"), 3: ("mountains", "Montagne"),
    4: ("forest", "Foresta"), 5: ("taiga", "Taiga"), 6: ("swamp", "Palude"), 7: ("river", "Fiume"),
    8: ("nether", "Nether"), 9: ("the_end", "End"), 10: ("frozen_ocean", "Oceano ghiacciato"),
    11: ("frozen_river", "Fiume ghiacciato"), 12: ("snowy_tundra", "Tundra innevata"),
    13: ("snowy_mountains", "Montagne innevate"), 14: ("mushroom_fields", "Campi di funghi"),
    15: ("mushroom_field_shore", "Riva dei funghi"), 16: ("beach", "Spiaggia"), 17: ("desert_hills", "Colline desertiche"),
    18: ("wooded_hills", "Colline boscose"), 19: ("taiga_hills", "Colline di taiga"),
    20: ("mountain_edge", "Margine montano"), 21: ("jungle", "Giungla"), 22: ("jungle_hills", "Colline della giungla"),
    23: ("jungle_edge", "Margine della giungla"), 24: ("deep_ocean", "Oceano profondo"),
    25: ("stone_shore", "Costa rocciosa"), 26: ("snowy_beach", "Spiaggia innevata"),
    27: ("birch_forest", "Foresta di betulle"), 28: ("birch_forest_hills", "Colline di betulle"),
    29: ("dark_forest", "Foresta oscura"), 30: ("snowy_taiga", "Taiga innevata"),
    31: ("snowy_taiga_hills", "Colline di taiga innevata"), 32: ("giant_tree_taiga", "Taiga di alberi giganti"),
    33: ("giant_tree_taiga_hills", "Colline di taiga gigante"), 34: ("wooded_mountains", "Montagne boscose"),
    35: ("savanna", "Savana"), 36: ("savanna_plateau", "Altopiano della savana"), 37: ("badlands", "Badlands (mesa)"),
    38: ("wooded_badlands_plateau", "Altopiano boscoso delle badlands"),
    39: ("badlands_plateau", "Altopiano delle badlands"),
    129: ("sunflower_plains", "Pianura di girasoli"), 130: ("desert_lakes", "Laghi del deserto"),
    131: ("gravelly_mountains", "Montagne ghiaiose"), 132: ("flower_forest", "Foresta fiorita"),
    133: ("taiga_mountains", "Montagne di taiga"), 134: ("swamp_hills", "Colline paludose"),
    140: ("ice_spikes", "Punte di ghiaccio"), 149: ("modified_jungle", "Giungla modificata"),
    151: ("modified_jungle_edge", "Margine di giungla modificato"), 155: ("tall_birch_forest", "Foresta di betulle alte"),
    156: ("tall_birch_hills", "Colline di betulle alte"), 157: ("dark_forest_hills", "Colline della foresta oscura"),
    158: ("snowy_taiga_mountains", "Montagne di taiga innevata"), 160: ("giant_spruce_taiga", "Taiga di abeti giganti"),
    161: ("giant_spruce_taiga_hills", "Colline di abeti giganti"),
    162: ("modified_gravelly_mountains", "Montagne ghiaiose modificate"),
    163: ("shattered_savanna", "Savana frastagliata"), 164: ("shattered_savanna_plateau", "Altopiano di savana frastagliata"),
    165: ("eroded_badlands", "Badlands erose"), 166: ("modified_wooded_badlands_plateau", "Altopiano boscoso modificato"),
    167: ("modified_badlands_plateau", "Altopiano delle badlands modificato"),
    # Java 1.13 - 1.17
    40: ("small_end_islands", "Piccole isole dell'End"), 41: ("end_midlands", "Terre centrali dell'End"),
    42: ("end_highlands", "Altopiani dell'End"), 43: ("end_barrens", "Lande dell'End"),
    44: ("warm_ocean", "Oceano caldo"), 45: ("lukewarm_ocean", "Oceano tiepido"), 46: ("cold_ocean", "Oceano freddo"),
    47: ("deep_warm_ocean", "Oceano caldo profondo"), 48: ("deep_lukewarm_ocean", "Oceano tiepido profondo"),
    49: ("deep_cold_ocean", "Oceano freddo profondo"), 50: ("deep_frozen_ocean", "Oceano ghiacciato profondo"),
    127: ("the_void", "Vuoto"), 168: ("bamboo_jungle", "Giungla di bambù"),
    169: ("bamboo_jungle_hills", "Colline della giungla di bambù"), 170: ("soul_sand_valley", "Valle delle anime"),
    171: ("crimson_forest", "Foresta cremisi"), 172: ("warped_forest", "Foresta distorta"),
    173: ("basalt_deltas", "Delta di basalto"), 174: ("dripstone_caves", "Grotte di speleotemi"),
    175: ("lush_caves", "Grotte lussureggianti"),
    # 1.18+ only (no number in any game): WorldBridge's own ids
    1000: ("meadow", "Prato"), 1001: ("grove", "Boschetto"), 1002: ("snowy_slopes", "Pendii innevati"),
    1003: ("jagged_peaks", "Picchi frastagliati"), 1004: ("frozen_peaks", "Picchi ghiacciati"),
    1005: ("stony_peaks", "Picchi rocciosi"), 1006: ("deep_dark", "Oscurità profonda"),
    1007: ("mangrove_swamp", "Palude di mangrovie"), 1008: ("cherry_grove", "Boschetto di ciliegi"),
    1009: ("pale_garden", "Giardino pallido"), 1010: ("sulfur_caves", "Grotte di zolfo"),
    1011: ("dappled_forest", "Foresta screziata"),
}
BY_NAME = {name: i for i, (name, _label) in BIOMES.items()}

# the English names of Java 1.2 - 1.12 and of the Legacy Console Edition (as neoLegacy's Biome.cpp)
LEGACY_NAMES: Dict[int, str] = {
    0: "Ocean", 1: "Plains", 2: "Desert", 3: "Extreme Hills", 4: "Forest", 5: "Taiga", 6: "Swampland",
    7: "River", 8: "Hell", 9: "The End", 10: "Frozen Ocean", 11: "Frozen River", 12: "Ice Plains",
    13: "Ice Mountains", 14: "Mushroom Island", 15: "Mushroom Island Shore", 16: "Beach", 17: "Desert Hills",
    18: "Forest Hills", 19: "Taiga Hills", 20: "Extreme Hills Edge", 21: "Jungle", 22: "Jungle Hills",
    23: "Jungle Edge", 24: "Deep Ocean", 25: "Stone Beach", 26: "Cold Beach", 27: "Birch Forest",
    28: "Birch Forest Hills", 29: "Roofed Forest", 30: "Cold Taiga", 31: "Cold Taiga Hills", 32: "Mega Taiga",
    33: "Mega Taiga Hills", 34: "Extreme Hills+", 35: "Savanna", 36: "Savanna Plateau", 37: "Mesa",
    38: "Mesa Plateau F", 39: "Mesa Plateau", 129: "Sunflower Plains", 130: "Desert M", 131: "Extreme Hills M",
    132: "Flower Forest", 133: "Taiga M", 134: "Swampland M", 140: "Ice Plains Spikes", 149: "Jungle M",
    151: "Jungle Edge M", 155: "Birch Forest M", 156: "Birch Forest Hills M", 157: "Roofed Forest M",
    158: "Cold Taiga M", 160: "Mega Spruce Taiga", 161: "Mega Spruce Taiga Hills", 162: "Extreme Hills+ M",
    163: "Savanna M", 164: "Savanna Plateau M", 165: "Mesa (Bryce)", 166: "Mesa Plateau F M", 167: "Mesa Plateau M",
}
LCE_NAMES = {**LEGACY_NAMES, 8: "Hell", 9: "Sky", 129: "Sunflowers Plains", 140: "Ice Spikes"}

# names since 1.18 (renamed in 1.16 / 1.18); the 1.13 biomes that 1.18 removed are not in the 1.18+ lists
MODERN_NAMES: Dict[int, str] = {
    3: "windswept_hills", 8: "nether_wastes", 12: "snowy_plains", 23: "sparse_jungle", 25: "stony_shore",
    32: "old_growth_pine_taiga", 34: "windswept_forest", 38: "wooded_badlands", 131: "windswept_gravelly_hills",
    155: "old_growth_birch_forest", 160: "old_growth_spruce_taiga", 163: "windswept_savanna",
}
_MUTATED = (129, 130, 131, 132, 133, 134, 140, 149, 151, 155, 156, 157, 158, 160, 161, 162, 163, 164, 165, 166, 167)
JAVA_12 = tuple(range(0, 23))                                         # Java 1.2 - 1.6
JAVA_17 = tuple(range(0, 40)) + _MUTATED                              # Java 1.7 - 1.12
JAVA_113 = JAVA_17 + tuple(range(40, 51)) + (127,)
JAVA_114 = JAVA_113 + (168, 169)
JAVA_116 = JAVA_114 + (170, 171, 172, 173)
JAVA_118 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 21, 23, 24, 25, 26, 27, 29, 30, 32, 34, 35, 36, 37, 38,
            40, 41, 42, 43, 44, 45, 46, 48, 49, 50, 127, 129, 131, 132, 140, 155, 160, 163, 165, 168, 170, 171, 172,
            173, 174, 175, 1000, 1001, 1002, 1003, 1004, 1005)
# the Legacy Console Edition (neoLegacy TU31): no Extreme Hills M / Extreme Hills+ M
LCE = tuple(b for b in JAVA_17 if b not in (131, 162))


def _java_list(version: Sequence[int]) -> Tuple[int, ...]:
    v = tuple(version)
    if v < (1, 2):
        return ()                                     # McRegion and older: the biomes are not stored
    if v < (1, 7):
        return JAVA_12
    if v < (1, 13):
        return JAVA_17
    if v < (1, 14):
        return JAVA_113
    if v < (1, 16):
        return JAVA_114
    if v < (1, 18):
        return JAVA_116
    return JAVA_118 + tuple(b for b, (java, _bedrock) in SINCE.items() if v >= java)


# the biomes added after 1.18: the first Java and Bedrock versions with them (the two editions
# number their versions differently: Bedrock 26.20 is not later than Java 26.3)
SINCE: Dict[int, Tuple[Tuple[int, ...], Tuple[int, ...]]] = {
    1006: ((1, 19), (1, 19)), 1007: ((1, 19), (1, 19)),            # deep_dark, mangrove_swamp
    1008: ((1, 20), (1, 20)),                                      # cherry_grove
    1009: ((1, 21, 4), (1, 21, 50)),                              # pale_garden
    1010: ((26, 2), (26, 20)),                                     # sulfur_caves
    1011: ((26, 3), (26, 50)),                                     # dappled_forest
}


def _bedrock_list(version: Sequence[int]) -> Tuple[int, ...]:
    v = tuple(version)
    if v >= (1, 18):
        return tuple(b for b in JAVA_118 if b not in (40, 41, 42, 43, 127)) + tuple(
            b for b, (_java, bedrock) in SINCE.items() if v >= bedrock)
    out = JAVA_17
    if v >= (1, 4):                                    # Update Aquatic
        out += tuple(range(44, 51))
    if v >= (1, 9):                                    # Village & Pillage: bamboo jungle
        out += (168, 169)
    if v >= (1, 16):
        out += (170, 171, 172, 173)
    return out


def available(family: str, version: Optional[Sequence[int]] = None) -> Tuple[int, ...]:
    """The biomes a game has: ``family`` "lce", "java", "bedrock" or "pe_old", ``version`` its version
    (None: the latest)."""
    if family == "lce":
        return LCE
    if family == "java":
        return _java_list(version or (99,))
    if family == "bedrock":
        return _bedrock_list(version or (99,))
    return ()                                          # Pocket Edition 0.x: no biomes in chunks.dat


def game_name(bid: int, family: str, version: Optional[Sequence[int]] = None) -> str:
    """The name the game gives the biome."""
    v = tuple(version or (99,))
    if family == "lce":
        return LCE_NAMES.get(bid, BIOMES[bid][0])
    if family == "java" and v < (1, 13):
        return LEGACY_NAMES.get(bid, BIOMES[bid][0])
    if family == "java" and v < (1, 16) and bid == 8:
        return "nether"
    if v >= (1, 18) or bid == 8:
        return MODERN_NAMES.get(bid, BIOMES[bid][0])
    return BIOMES[bid][0]


def label(bid: int, family: str, version: Optional[Sequence[int]] = None) -> str:
    """The game's name, followed in Italian by the biome's Italian name."""
    name = game_name(bid, family, version)
    return f"{name} · {BIOMES[bid][1]}" if language() == "it" else name


def modern_name(bid: int) -> str:
    """The Java 1.18+ name (also Bedrock's names are translated from it)."""
    return MODERN_NAMES.get(bid, BIOMES[bid][0])


def parse(value: str) -> int:
    """A biome given by number or by name (Java 1.13 or 1.18+ names, or the old English ones)."""
    v = value.strip().removeprefix("minecraft:")
    if v.isdigit() and int(v) in BIOMES:
        return int(v)
    low = v.lower()
    if low in BY_NAME:
        return BY_NAME[low]
    for table in (MODERN_NAMES, LEGACY_NAMES, LCE_NAMES):
        for bid, name in table.items():
            if name.lower() == low:
                return bid
    raise ValueError(tr("unknown biome: {name}", name=value))

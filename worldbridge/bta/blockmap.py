"""BTA 8.0.1 blocks (numeric id + 8-bit metadata) -> Java Edition 26.3 block states.

Every one of the 455 BTA blocks is listed explicitly, in id order.  Metadata layouts come from the
decompiled BTA block logic classes (bit masks, placement code and bounding boxes, cross-checked
against the shapes of the vanilla blocks).  Neighbour-dependent properties (stair shapes, fence and
pane connections, redstone wire sides, leaf distance, snowy grass, note block instruments) are
filled in afterwards by :mod:`.postprocess`.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from .palette import COLORS, Palette
from .states import AIR, BlockState, state
from .nbtio import gi


class MapCtx:
    """Per-block context: the BTA tile entity at that position (if any) and the dimension."""

    __slots__ = ("palette", "tile_entity", "dimension", "x", "y", "z")

    def __init__(self, palette: Palette):
        self.palette = palette
        self.tile_entity: Optional[dict] = None
        self.dimension = 0
        self.x = self.y = self.z = 0


Mapper = Callable[[int, MapCtx], BlockState]
TABLE: Dict[int, Mapper] = {}
BTA_NAMES: Dict[int, str] = {}

# horizontal facing from BTA's "legacy index" (N=0, E=1, S=2, W=3): gates, chests, ...
LEGACY_H = ("north", "east", "south", "west")
# BTA Direction ids (same order as vanilla): down, up, north, south, west, east
DIR = ("down", "up", "north", "south", "west", "east")


def map_block(bid: int, meta: int, ctx: MapCtx) -> Optional[BlockState]:
    m = TABLE.get(bid)
    return None if m is None else m(meta & 0xFF, ctx)


def known(bid: int) -> bool:
    return bid in TABLE


def bta_name(bid: int) -> Optional[str]:
    return BTA_NAMES.get(bid)


def reg(bid: int, name: str, m: Mapper) -> None:
    if bid in TABLE:
        raise ValueError(f"Duplicate mapping for BTA block {bid}")
    TABLE[bid] = m
    BTA_NAMES[bid] = name


# ------------------------------------------------------------------ helpers
def simple(name: str, **props) -> Mapper:
    s = state(name, **props)
    return lambda meta, c: s


def axis_of(meta: int) -> str:
    return {1: "z", 2: "x"}.get(meta & 3, "y")


def axis(name: str) -> Mapper:  # BTA AxisAligned: 0 = Y, 1 = Z, 2 = X
    return lambda meta, c: state(name, axis=axis_of(meta))


def slab_type(meta: int) -> str:
    return {1: "double", 2: "top"}.get(meta & 3, "bottom")


def slab(name: str) -> Mapper:
    return lambda meta, c: state(name, type=slab_type(meta))


def stairs_state(name: str, meta: int) -> BlockState:
    """Bits 0-1 = side of the full-height back (0 east, 1 west, 2 south, 3 north), bit 3 = upside down."""
    facing = ("east", "west", "south", "north")[meta & 3]
    return state(name, facing=facing, half="top" if meta & 8 else "bottom")


def stairs(name: str) -> Mapper:
    return lambda meta, c: stairs_state(name, meta)


def cw(d: str) -> str:
    return {"north": "east", "east": "south", "south": "west"}.get(d, "north")


def ccw(d: str) -> str:
    return {"north": "west", "west": "south", "south": "east"}.get(d, "north")


def opposite(d: str) -> str:
    return {"north": "south", "south": "north", "east": "west", "west": "east", "up": "down"}.get(d, "up")


def door(name: str, meta: int, top: bool) -> BlockState:
    """Reproduces BTA's getRotation / isOpen."""
    m = meta & 15
    right_hinge = (m & 8) != 0
    opened_bit = (m & 4) != 0
    is_open = opened_bit != right_hinge
    rotation = (m & 3) if opened_bit else ((m - 1) & 3)
    # edge of the block occupied by the panel (0 north, 1 east, 2 south, 3 west); vanilla puts the
    # panel on the edge opposite to its "door direction"
    door_dir = ("south", "west", "north", "east")[rotation]
    if not is_open:
        facing = door_dir
    elif right_hinge:
        facing = cw(door_dir)
    else:
        facing = ccw(door_dir)
    return state(name, facing=facing, half="upper" if top else "lower", hinge="right" if right_hinge else "left",
                 open="true" if is_open else "false", powered="false")


def trapdoor(name: str, meta: int) -> BlockState:
    """Bits 0-1 edge when open (0 south, 1 north, 2 east, 3 west), bit 2 open, bit 3 upper half."""
    facing = ("north", "south", "west", "east")[meta & 3]
    return state(name, facing=facing, half="top" if meta & 8 else "bottom", open="true" if meta & 4 else "false",
                 powered="false")


def gate(name: str, meta: int) -> BlockState:
    """Bits 0-1 legacy facing, bit 2 open, bit 3 powered."""
    return state(name, facing=LEGACY_H[meta & 3], open="true" if meta & 4 else "false", powered="false")


def button(name: str, d: int) -> BlockState:
    """1 on west wall, 2 east wall, 3 north wall, 4 south wall, 5 ceiling, 6 floor."""
    if d == 1:
        return state(name, face="wall", facing="east")
    if d == 2:
        return state(name, face="wall", facing="west")
    if d == 3:
        return state(name, face="wall", facing="south")
    if d == 4:
        return state(name, face="wall", facing="north")
    if d == 5:
        return state(name, face="ceiling", facing="north")
    return state(name, face="floor", facing="north")


def plate(plate_name: str, button_name: str, meta: int) -> BlockState:
    """BTA plates can be on any side; vanilla only on floors: wall/ceiling plates become buttons."""
    side = (meta & 14) >> 1
    if side == 0:
        return state(plate_name)
    return button(button_name, {1: 5, 2: 3, 3: 4, 4: 1}.get(side, 2))


def torch(standing: str, wall: str, meta: int, **extra) -> BlockState:
    facing = {1: "east", 2: "west", 3: "south", 4: "north"}.get(meta & 7)
    if facing is None:
        return state(standing, **extra)
    return state(wall, facing=facing, **extra)


def wall_facing(meta: int) -> str:
    """Wall signs / ladders: 2 north, 3 south, 4 west, 5 east."""
    return {3: "south", 4: "west", 5: "east"}.get(meta & 15, "north")


def leaves_state(name: str, meta: int) -> BlockState:
    # bit 0 = permanent (player placed); the distance is computed by the post processor
    return state(name, persistent="true" if meta & 1 else "false", distance="7")


def leaves(name: str) -> Mapper:
    return lambda meta, c: leaves_state(name, meta)


def sapling(name: str) -> Mapper:
    return lambda meta, c: state(name, stage="1" if meta & 8 else "0")


def fluid(name: str) -> Mapper:
    return lambda meta, c: state(name, level=str(meta & 15))


def wood(c: MapCtx, color: int) -> str:
    return c.palette.wood(color)


def color(meta: int) -> str:
    return COLORS[meta & 15]


def diode_facing(meta: int) -> str:
    """BTA repeaters store the placer's look direction (N=0,E=1,S=2,W=3); vanilla points back."""
    return ("south", "west", "north", "east")[meta & 3]


_RAIL_SHAPES = ("north_south", "east_west", "ascending_east", "ascending_west", "ascending_north", "ascending_south",
                "south_east", "south_west", "north_west", "north_east")


def rail(name: str, meta: int, straight_only: bool) -> BlockState:
    d = meta & 7 if straight_only else meta & 15
    if d >= len(_RAIL_SHAPES) or (straight_only and d > 5):
        d = 0
    s = state(name, shape=_RAIL_SHAPES[d])
    if s.has("powered"):
        s = s.with_("powered", "true" if straight_only and name.endswith("powered_rail") and meta & 8 else "false")
    return s


def pressure_plate(plate_name: str, button_name: str) -> Mapper:
    return lambda meta, c: plate(plate_name, button_name, meta)


def button_m(name: str) -> Mapper:
    return lambda meta, c: button(name, meta & 7)


def horizontal_dir(meta: int) -> str:
    """Rotatable blocks: Direction id in bits 0-2; vertical directions fall back to north."""
    d = meta & 7
    return DIR[d] if 2 <= d <= 5 else "north"


def lever(meta: int) -> BlockState:
    rot = meta & 15
    p = "true" if meta & 16 else "false"
    face, facing = {1: ("wall", "east"), 2: ("wall", "west"), 3: ("wall", "south"), 4: ("wall", "north"),
                    5: ("floor", "north"), 6: ("floor", "east"), 7: ("ceiling", "north")}.get(rot, ("ceiling", "east"))
    return state("lever", face=face, facing=facing, powered=p)


def repeater(meta: int, powered: bool) -> BlockState:
    return state("repeater", facing=diode_facing(meta), delay=str(((meta & 12) >> 2) + 1),
                 powered="true" if powered else "false", locked="false")


def piston_base(name: str, meta: int) -> BlockState:
    """New format (bit 7 set) keeps "extended" in bit 6; the legacy format in bit 3."""
    d = meta & 7
    if d > 5:
        d = 0
    extended = (meta & 0x40) != 0 if meta & 0x80 else (meta & 8) != 0
    return state(name, facing=DIR[d], extended="true" if extended else "false")


def piston_head(meta: int, sticky: bool) -> BlockState:
    d = meta & 7
    if d > 5:
        d = 0
    return state("piston_head", facing=DIR[d], type="sticky" if sticky else "normal", short="false")


def spikes(meta: int) -> BlockState:
    """Direction id in bits 1-3: vertical spikes become pointed dripstone, sideways ones iron bars."""
    d = (meta & 14) >> 1
    if d == 1:
        return state("pointed_dripstone", vertical_direction="up", thickness="tip")
    if d == 0:
        return state("pointed_dripstone", vertical_direction="down", thickness="tip")
    return state("iron_bars")


def bed_facing(meta: int) -> str:
    """Foot-to-head direction index: 0 south, 1 west, 2 north, 3 east."""
    return ("south", "west", "north", "east")[meta & 3]


def chest(meta: int) -> BlockState:
    """Bits 0-1 facing (N,E,S,W), bits 2-3 type.  BTA's LEFT half is vanilla's RIGHT half."""
    t = {1: "right", 2: "left"}.get((meta >> 2) & 3, "single")
    return state("chest", facing=LEGACY_H[meta & 3], type=t)


def matcher_facing(meta: int) -> str:
    return {1: "south", 2: "east"}.get(meta & 3, "up")


def colored_light(meta: int) -> BlockState:
    """Inverted lamps glow while unpowered; a lit one becomes a light block of similar colour."""
    m = meta & 15
    if m in (4, 1):
        return state("ochre_froglight", axis="y")
    if m in (5, 13):
        return state("verdant_froglight", axis="y")
    if m in (2, 6, 10):
        return state("pearlescent_froglight", axis="y")
    if m in (14, 12):
        return state("shroomlight")
    if m in (3, 9, 11):
        return state("sea_lantern")
    return state("glowstone")


_POTTED = {310: "potted_oak_sapling", 311: "potted_oak_sapling", 316: "potted_oak_sapling",
           312: "potted_spruce_sapling", 313: "potted_birch_sapling", 314: "potted_cherry_sapling",
           315: "potted_pale_oak_sapling", 317: "potted_jungle_sapling", 319: "potted_jungle_sapling",
           318: "potted_acacia_sapling", 320: "potted_fern", 321: "potted_fern", 322: "potted_dead_bush",
           323: "potted_dead_bush", 330: "potted_dandelion", 331: "potted_poppy", 332: "potted_pink_tulip",
           333: "potted_allium", 334: "potted_blue_orchid", 335: "potted_orange_tulip", 340: "potted_brown_mushroom",
           341: "potted_red_mushroom", 750: "potted_cactus", 1031: "potted_crimson_roots"}


def flower_jar(te: Optional[dict]) -> BlockState:
    """Flower jars keep their plant as a vanilla potted plant."""
    if te is None:
        return state("flower_pot")
    return state(_POTTED.get(gi(te, "PlantedId", 0), "flower_pot"))


def _boneshale(meta: int, c: MapCtx) -> BlockState:
    return state("bone_block", axis={2: "z", 3: "z", 4: "x", 5: "x"}.get(meta & 7, "y"))


# ------------------------------------------------------------------ table
def _table() -> None:
    reg(0, "air", simple("air"))
    reg(1, "stone", simple("stone"))
    reg(2, "basalt", simple("deepslate", axis="y"))
    reg(3, "limestone", simple("sandstone"))
    reg(4, "granite", simple("granite"))
    reg(5, "marble", simple("calcite"))
    reg(6, "slate", simple("tuff"))
    reg(7, "permafrost", simple("diorite"))

    reg(10, "cobble_stone", simple("cobblestone"))
    reg(11, "cobble_stone_mossy", simple("mossy_cobblestone"))
    reg(12, "cobble_basalt", simple("cobbled_deepslate"))
    reg(13, "cobble_limestone", simple("sandstone"))
    reg(14, "cobble_granite", simple("granite"))
    reg(15, "cobble_permafrost", simple("diorite"))
    reg(16, "cobble_basalt_mossy", simple("cobbled_deepslate"))
    reg(17, "cobble_limestone_mossy", simple("sandstone"))
    reg(18, "cobble_granite_mossy", simple("granite"))

    reg(20, "pillar_marble", axis("quartz_pillar"))
    reg(21, "capstone_marble", simple("chiseled_quartz_block"))
    reg(30, "sandstone", simple("sandstone"))

    reg(40, "stone_carved", simple("chiseled_stone_bricks"))
    reg(41, "granite_carved", simple("polished_granite"))
    reg(42, "limestone_carved", simple("chiseled_sandstone"))
    reg(43, "basalt_carved", simple("chiseled_deepslate"))
    reg(44, "permafrost_carved", simple("polished_diorite"))
    reg(45, "netherrack_carved", simple("chiseled_cinnabar"))
    reg(46, "gloomstone_carved", simple("chiseled_polished_blackstone"))

    reg(50, "planks_oak", lambda meta, c: state(Palette.planks(c.palette.oak_wood)))
    reg(51, "planks_oak_painted", lambda meta, c: state(Palette.planks(wood(c, meta))))
    reg(60, "torch_coal", lambda meta, c: torch("torch", "wall_torch", meta))
    reg(70, "ladder_oak", lambda meta, c: state("ladder", facing=wall_facing(meta)))
    reg(80, "fence_planks_oak", lambda meta, c: state(c.palette.oak_wood + "_fence"))
    reg(81, "fence_planks_oak_painted", lambda meta, c: state(wood(c, meta) + "_fence"))
    reg(90, "fence_gate_planks_oak", lambda meta, c: gate(c.palette.oak_wood + "_fence_gate", meta))
    reg(91, "fence_gate_planks_oak_painted", lambda meta, c: gate(wood(c, meta >> 4) + "_fence_gate", meta))
    reg(100, "bookshelf_planks_oak", simple("bookshelf"))
    reg(110, "wool", lambda meta, c: state(color(meta) + "_wool"))
    reg(111, "rope", simple("cave_vines_plant", berries="false"))

    reg(120, "brick_clay", simple("bricks"))
    reg(121, "brick_stone_polished", simple("stone_bricks"))
    reg(122, "brick_stone_polished_mossy", simple("mossy_stone_bricks"))
    reg(123, "brick_sandstone", simple("cut_sandstone"))
    reg(124, "brick_gold", simple("sulfur_bricks"))
    reg(125, "brick_lapis", simple("lapis_block"))
    reg(126, "brick_basalt", simple("deepslate_bricks"))
    reg(127, "brick_limestone", simple("cut_sandstone"))
    reg(128, "brick_granite", simple("mud_bricks"))
    reg(129, "brick_marble", simple("quartz_bricks"))
    reg(130, "brick_slate", simple("tuff_bricks"))
    reg(131, "brick_stone", simple("stone_bricks"))
    reg(132, "brick_permafrost", simple("polished_diorite"))
    reg(133, "brick_iron", simple("iron_block"))
    reg(134, "brick_steel", simple("deepslate_tiles"))
    reg(135, "brick_olivine", simple("lime_concrete"))
    reg(136, "brick_quartz", simple("pink_concrete"))
    reg(137, "brick_diamond", simple("prismarine_bricks"))

    reg(140, "slab_planks_oak", lambda meta, c: state(c.palette.oak_wood + "_slab", type=slab_type(meta)))
    reg(141, "slab_cobble_stone", slab("cobblestone_slab"))
    reg(142, "slab_sandstone", slab("sandstone_slab"))
    reg(143, "slab_brick_stone_polished", slab("stone_brick_slab"))
    reg(144, "slab_stone_carved", slab("smooth_stone_slab"))
    reg(145, "slab_brick_marble", slab("quartz_slab"))
    reg(146, "slab_brick_clay", slab("brick_slab"))
    reg(147, "slab_capstone_marble", slab("smooth_quartz_slab"))
    reg(148, "slab_cobble_basalt", slab("cobbled_deepslate_slab"))
    reg(149, "slab_cobble_limestone", slab("sandstone_slab"))
    reg(150, "slab_cobble_granite", slab("granite_slab"))
    reg(151, "slab_brick_basalt", slab("deepslate_brick_slab"))
    reg(152, "slab_brick_limestone", slab("cut_sandstone_slab"))
    reg(153, "slab_brick_granite", slab("mud_brick_slab"))
    reg(154, "slab_planks_oak_painted", lambda meta, c: state(wood(c, meta >> 4) + "_slab", type=slab_type(meta)))
    reg(155, "slab_brick_slate", slab("tuff_brick_slab"))
    reg(156, "slab_brick_stone", slab("stone_brick_slab"))
    reg(157, "slab_granite_carved", slab("polished_granite_slab"))
    reg(158, "slab_limestone_carved", slab("smooth_sandstone_slab"))
    reg(159, "slab_basalt_carved", slab("polished_deepslate_slab"))

    reg(160, "stairs_planks_oak", lambda meta, c: stairs_state(c.palette.oak_wood + "_stairs", meta))
    reg(161, "stairs_cobble_stone", stairs("cobblestone_stairs"))
    reg(162, "stairs_brick_stone_polished", stairs("stone_brick_stairs"))
    reg(163, "stairs_brick_marble", stairs("quartz_stairs"))
    reg(164, "stairs_cobble_basalt", stairs("cobbled_deepslate_stairs"))
    reg(165, "stairs_cobble_limestone", stairs("sandstone_stairs"))
    reg(166, "stairs_cobble_granite", stairs("granite_stairs"))
    reg(167, "stairs_brick_basalt", stairs("deepslate_brick_stairs"))
    reg(168, "stairs_brick_limestone", stairs("smooth_sandstone_stairs"))
    reg(169, "stairs_brick_granite", stairs("mud_brick_stairs"))
    reg(170, "stairs_brick_clay", stairs("brick_stairs"))
    reg(171, "stairs_planks_oak_painted", lambda meta, c: stairs_state(wood(c, meta >> 4) + "_stairs", meta))
    reg(172, "stairs_brick_slate", stairs("tuff_brick_stairs"))
    reg(173, "stairs_brick_stone", stairs("stone_brick_stairs"))
    reg(174, "stairs_sandstone", stairs("sandstone_stairs"))
    reg(175, "stairs_brick_sandstone", stairs("smooth_sandstone_stairs"))
    reg(176, "stairs_cobble_permafrost", stairs("diorite_stairs"))
    reg(177, "stairs_brick_permafrost", stairs("polished_diorite_stairs"))

    reg(180, "obsidian", simple("obsidian"))
    reg(190, "glass", simple("glass"))
    reg(191, "glass_tinted", simple("tinted_glass"))
    reg(192, "glass_steel", simple("glass"))
    reg(200, "grass", simple("grass_block"))
    reg(201, "grass_retro", simple("grass_block"))
    reg(202, "grass_scorched", simple("grass_block"))
    reg(210, "path_dirt", simple("dirt_path"))
    reg(220, "dirt", simple("dirt"))
    reg(221, "dirt_scorched", simple("coarse_dirt"))
    reg(222, "dirt_scorched_rich", simple("rooted_dirt"))
    reg(225, "mud", simple("mud"))
    reg(226, "mud_baked", simple("packed_mud"))
    reg(230, "sponge_dry", simple("sponge"))
    reg(231, "sponge_wet", simple("wet_sponge"))
    reg(232, "pumice_dry", simple("dripstone_block"))
    reg(233, "pumice_wet", simple("magma_block"))
    reg(240, "moss_stone", simple("moss_block"))
    reg(241, "moss_basalt", simple("moss_block"))
    reg(242, "moss_limestone", simple("moss_block"))
    reg(243, "moss_granite", simple("moss_block"))
    reg(250, "sand", simple("sand"))
    reg(251, "gravel", simple("gravel"))
    reg(260, "bedrock", simple("bedrock"))
    reg(261, "boneshale", _boneshale)
    reg(270, "fluid_water_flowing", fluid("water"))
    reg(271, "fluid_water_still", fluid("water"))
    reg(272, "fluid_lava_flowing", fluid("lava"))
    reg(273, "fluid_lava_still", fluid("lava"))

    reg(280, "log_oak", axis("oak_log"))
    reg(281, "log_pine", axis("spruce_log"))
    reg(282, "log_birch", axis("birch_log"))
    reg(283, "log_cherry", axis("cherry_log"))
    reg(284, "log_eucalyptus", axis("stripped_cherry_log"))
    reg(285, "log_oak_mossy", axis("oak_log"))
    reg(286, "log_thorn", axis("acacia_log"))
    reg(287, "log_palm", axis("jungle_log"))

    reg(290, "leaves_oak", leaves("oak_leaves"))
    reg(291, "leaves_oak_retro", leaves("oak_leaves"))
    reg(292, "leaves_pine", leaves("spruce_leaves"))
    reg(293, "leaves_birch", leaves("birch_leaves"))
    reg(294, "leaves_cherry", leaves("cherry_leaves"))
    reg(295, "leaves_eucalyptus", leaves("pale_oak_leaves"))
    reg(296, "leaves_shrub", leaves("oak_leaves"))
    reg(297, "leaves_cherry_flowering", leaves("cherry_leaves"))
    reg(298, "leaves_cacao", leaves("jungle_leaves"))
    reg(299, "leaves_thorn", leaves("acacia_leaves"))
    reg(300, "leaves_palm", leaves("jungle_leaves"))

    reg(310, "sapling_oak", sapling("oak_sapling"))
    reg(311, "sapling_oak_retro", sapling("oak_sapling"))
    reg(312, "sapling_pine", sapling("spruce_sapling"))
    reg(313, "sapling_birch", sapling("birch_sapling"))
    reg(314, "sapling_cherry", sapling("cherry_sapling"))
    reg(315, "sapling_eucalyptus", sapling("pale_oak_sapling"))
    reg(316, "sapling_shrub", sapling("oak_sapling"))
    reg(317, "sapling_cacao", sapling("jungle_sapling"))
    reg(318, "sapling_thorn", sapling("acacia_sapling"))
    reg(319, "sapling_palm", sapling("jungle_sapling"))

    reg(320, "tallgrass", simple("short_grass"))
    reg(321, "tallgrass_fern", simple("fern"))
    reg(322, "deadbush", simple("dead_bush"))
    reg(323, "spinifex", simple("short_dry_grass"))
    reg(324, "algae", simple("lily_pad"))
    reg(330, "flower_yellow", simple("dandelion"))
    reg(331, "flower_red", simple("poppy"))
    reg(332, "flower_pink", simple("pink_tulip"))
    reg(333, "flower_purple", simple("allium"))
    reg(334, "flower_light_blue", simple("blue_orchid"))
    reg(335, "flower_orange", simple("orange_tulip"))
    reg(340, "mushroom_brown", simple("brown_mushroom"))
    reg(341, "mushroom_red", simple("red_mushroom"))

    for base, ore, deep in ((350, "coal_ore", "deepslate_coal_ore"), (360, "iron_ore", "deepslate_iron_ore"),
                            (370, "gold_ore", "deepslate_gold_ore"), (380, "lapis_ore", "deepslate_lapis_ore"),
                            (410, "diamond_ore", "deepslate_diamond_ore")):
        kind = ore.split("_")[0]
        for i, host in enumerate(("stone", "basalt", "limestone", "granite", "permafrost")):
            reg(base + i, f"ore_{kind}_{host}", simple(deep if host == "basalt" else ore))
    for base, lit, tag in ((390, "false", "ore_redstone"), (400, "true", "ore_redstone_glowing")):
        for i, host in enumerate(("stone", "basalt", "limestone", "granite", "permafrost")):
            reg(base + i, f"{tag}_{host}", simple("deepslate_redstone_ore" if host == "basalt" else "redstone_ore", lit=lit))
    reg(420, "ore_nethercoal_netherrack", simple("coal_ore"))
    reg(421, "ore_nethercoal_basalt", simple("deepslate_coal_ore"))
    reg(422, "ore_nethercoal_gloomstone", simple("deepslate_coal_ore"))

    reg(430, "block_coal", simple("coal_block"))
    reg(431, "block_iron", simple("iron_block"))
    reg(432, "block_gold", simple("gold_block"))
    reg(433, "block_lapis", simple("lapis_block"))
    reg(434, "block_redstone", simple("redstone_block"))
    reg(435, "block_diamond", simple("diamond_block"))
    reg(436, "block_nethercoal", simple("nether_wart_block"))
    reg(437, "block_steel", simple("polished_blackstone"))
    reg(438, "block_quartz", simple("quartz_block"))
    reg(439, "block_olivine", simple("emerald_block"))
    reg(440, "block_charcoal", simple("coal_block"))

    reg(450, "wire_redstone", lambda meta, c: state("redstone_wire", power=str(meta & 15)))
    reg(460, "torch_redstone_idle", lambda meta, c: torch("redstone_torch", "redstone_wall_torch", meta, lit="false"))
    reg(461, "torch_redstone_active", lambda meta, c: torch("redstone_torch", "redstone_wall_torch", meta, lit="true"))
    reg(470, "button_stone", button_m("stone_button"))
    reg(471, "button_planks", lambda meta, c: button(c.palette.oak_wood + "_button", meta & 7))
    reg(472, "button_planks_painted", lambda meta, c: button(wood(c, meta >> 4) + "_button", meta & 7))
    reg(480, "lever_cobble_stone", lambda meta, c: lever(meta))
    reg(490, "pressure_plate_stone", pressure_plate("stone_pressure_plate", "stone_button"))
    reg(491, "pressure_plate_planks_oak",
        lambda meta, c: plate(c.palette.oak_wood + "_pressure_plate", c.palette.oak_wood + "_button", meta))
    reg(492, "pressure_plate_cobble_stone", pressure_plate("stone_pressure_plate", "stone_button"))
    reg(493, "pressure_plate_planks_oak_painted",
        lambda meta, c: plate(wood(c, meta >> 4) + "_pressure_plate", wood(c, meta >> 4) + "_button", meta))
    reg(500, "motion_sensor_idle", lambda meta, c: state("observer", facing=DIR[min(meta & 7, 5)], powered="false"))
    reg(501, "motion_sensor_active", lambda meta, c: state("observer", facing=DIR[min(meta & 7, 5)], powered="false"))
    reg(510, "repeater_idle", lambda meta, c: repeater(meta, False))
    reg(511, "repeater_active", lambda meta, c: repeater(meta, True))
    reg(512, "timer", lambda meta, c: state("repeater", facing=diode_facing(meta), delay=str(((meta & 12) >> 2) + 1)))

    reg(520, "piston_base", lambda meta, c: piston_base("piston", meta))
    reg(521, "piston_base_sticky", lambda meta, c: piston_base("sticky_piston", meta))
    reg(522, "piston_head", lambda meta, c: piston_head(meta, ((meta >> 3) & 3) == 1))
    reg(523, "piston_moving", lambda meta, c: AIR)  # resolved from the tile entity by the chunk converter
    reg(524, "piston_base_steel", lambda meta, c: piston_base("piston", meta))
    reg(525, "piston_head_steel", lambda meta, c: piston_head(meta, False))
    reg(530, "noteblock", lambda meta, c: state("note_block", note=str(min(meta & 63, 24)), powered="false"))
    reg(540, "rail", lambda meta, c: rail("rail", meta, False))
    reg(541, "rail_powered", lambda meta, c: rail("powered_rail", meta, True))
    reg(542, "rail_detector", lambda meta, c: rail("detector_rail", meta, True))
    reg(550, "spikes", lambda meta, c: spikes(meta))
    reg(560, "dispenser_cobble_stone",
        lambda meta, c: state("dispenser", facing=DIR[min(meta & 7, 5)], triggered="false"))
    reg(561, "activator_cobble_netherrack",
        lambda meta, c: state("dropper", facing=DIR[min(meta & 7, 5)], triggered="false"))

    reg(570, "trapdoor_planks_oak", lambda meta, c: trapdoor(c.palette.oak_wood + "_trapdoor", meta))
    reg(571, "trapdoor_iron", lambda meta, c: trapdoor("iron_trapdoor", meta))
    reg(572, "trapdoor_glass", lambda meta, c: trapdoor("waxed_copper_trapdoor", meta))
    reg(573, "trapdoor_planks_oak_painted", lambda meta, c: trapdoor(wood(c, meta >> 4) + "_trapdoor", meta))
    reg(574, "trapdoor_steel", lambda meta, c: trapdoor("iron_trapdoor", meta))
    reg(580, "tnt", simple("tnt"))
    reg(590, "door_planks_oak_bottom", lambda meta, c: door(c.palette.oak_wood + "_door", meta, False))
    reg(591, "doors_planks_oak_top", lambda meta, c: door(c.palette.oak_wood + "_door", meta, True))
    reg(592, "door_iron_bottom", lambda meta, c: door("iron_door", meta, False))
    reg(593, "door_iron_top", lambda meta, c: door("iron_door", meta, True))
    reg(594, "door_planks_oak_painted_bottom", lambda meta, c: door(wood(c, meta >> 4) + "_door", meta, False))
    reg(595, "door_planks_oak_painted_top", lambda meta, c: door(wood(c, meta >> 4) + "_door", meta, True))
    reg(596, "door_glass_bottom", lambda meta, c: door("waxed_copper_door", meta, False))
    reg(597, "door_glass_top", lambda meta, c: door("waxed_copper_door", meta, True))
    reg(598, "door_steel_bottom", lambda meta, c: door("iron_door", meta, False))
    reg(599, "door_steel_top", lambda meta, c: door("iron_door", meta, True))
    reg(600, "mesh", simple("waxed_exposed_copper_grate"))
    reg(601, "mesh_gold", simple("waxed_copper_grate"))
    reg(610, "bed", lambda meta, c: state("red_bed", facing=bed_facing(meta), part="head" if meta & 8 else "foot",
                                          occupied="false"))
    reg(611, "seat", simple("oak_slab", type="bottom"))
    reg(620, "cobweb", simple("cobweb"))
    reg(630, "fire", lambda meta, c: state("fire", age=str(meta & 15)))
    reg(631, "brazier_inactive", simple("campfire", lit="false", signal_fire="false"))
    reg(632, "brazier_active", simple("campfire", lit="true", signal_fire="false"))
    reg(633, "fire_cold", simple("soul_fire"))
    reg(634, "fire_sulfuric", lambda meta, c: state("fire", age=str(meta & 15)))
    reg(640, "mobspawner", simple("spawner"))
    reg(641, "mobspawner_deactivated", simple("spawner"))
    reg(650, "workbench", simple("crafting_table"))
    reg(660, "furnace_stone_idle", lambda meta, c: state("furnace", facing=horizontal_dir(meta), lit="false"))
    reg(661, "furnace_stone_active", lambda meta, c: state("furnace", facing=horizontal_dir(meta), lit="true"))
    reg(662, "furnace_blast_idle", lambda meta, c: state("blast_furnace", facing=horizontal_dir(meta), lit="false"))
    reg(663, "furnace_blast_active", lambda meta, c: state("blast_furnace", facing=horizontal_dir(meta), lit="true"))
    reg(670, "trommel_idle", simple("barrel", facing="up", open="false"))
    reg(671, "trommel_active", simple("barrel", facing="up", open="false"))
    # legacy chests carry no direction: the post processor applies BTA's own legacy-chest pairing
    reg(680, "chest_legacy", simple("chest", facing="north", type="single"))
    reg(681, "chest_legacy_painted", simple("chest", facing="north", type="single"))
    reg(682, "chest_planks_oak", lambda meta, c: chest(meta))
    reg(683, "chest_planks_oak_painted", lambda meta, c: chest(meta))
    reg(690, "crops_wheat", lambda meta, c: state("wheat", age=str(meta & 7)))
    reg(691, "crops_pumpkin", lambda meta, c: state("pumpkin_stem", age=str(min(7, (meta & 7) * 7 // 4))))
    reg(700, "farmland_dirt", lambda meta, c: state("farmland", moisture=str(min(7, meta & 15))))
    reg(710, "sign_post_planks_oak", lambda meta, c: state(c.palette.oak_wood + "_sign", rotation=str(meta & 15)))
    reg(711, "sign_wall_planks_oak", lambda meta, c: state(c.palette.oak_wood + "_wall_sign", facing=wall_facing(meta)))
    reg(712, "flag", simple("white_banner", rotation="0"))
    reg(713, "sign_post_planks_oak_painted",
        lambda meta, c: state(wood(c, meta >> 4) + "_sign", rotation=str(meta & 15)))
    reg(714, "sign_wall_planks_oak_painted",
        lambda meta, c: state(wood(c, meta >> 4) + "_wall_sign", facing=wall_facing(meta)))
    reg(720, "layer_snow", lambda meta, c: state("snow", layers=str((meta & 7) + 1)))
    reg(721, "layer_leaves_oak", lambda meta, c: state("oak_leaves", persistent="true", distance="7") if (meta & 7) >= 4
        else state("leaf_litter", segment_amount="4"))
    reg(722, "layer_slate", lambda meta, c: state("tuff") if (meta & 7) == 7
        else state("tuff_slab", type="double" if (meta & 7) >= 4 else "bottom"))
    reg(723, "layer_ash", lambda meta, c: state("gray_carpet") if (meta & 7) == 0 else state("gray_wool") if (meta & 7) == 7
        else state("gray_wool_slab", type="double" if (meta & 7) >= 4 else "bottom"))
    reg(730, "ice", simple("ice"))
    reg(731, "permaice", simple("packed_ice"))
    reg(740, "block_snow", simple("snow_block"))
    reg(741, "block_ash", simple("smooth_basalt"))
    reg(750, "cactus", lambda meta, c: state("cactus", age=str(meta & 15)))
    reg(760, "block_clay", simple("clay"))
    reg(770, "sugarcane", lambda meta, c: state("sugar_cane", age=str(meta & 15)))
    reg(771, "block_sugarcane", axis("bamboo_block"))
    reg(772, "block_sugarcane_baked", axis("stripped_bamboo_block"))
    reg(780, "jukebox", simple("jukebox", has_record="false"))
    reg(790, "pumpkin", simple("pumpkin"))
    reg(791, "pumpkin_carved_idle", lambda meta, c: state("carved_pumpkin", facing=horizontal_dir(meta)))
    reg(792, "pumpkin_carved_active", lambda meta, c: state("jack_o_lantern", facing=horizontal_dir(meta)))
    reg(793, "pumpkin_redstone", lambda meta, c: state("jack_o_lantern", facing=horizontal_dir(meta)))

    reg(800, "cobble_netherrack", simple("netherrack"))
    reg(801, "magma", simple("magma_block"))
    reg(802, "cobble_netherrack_mossy", simple("netherrack"))
    reg(803, "netherrack", simple("netherrack"))
    reg(804, "brick_netherrack", simple("cinnabar_bricks"))
    reg(805, "slab_netherrack_carved", slab("polished_cinnabar_slab"))
    reg(806, "slab_cobble_netherrack", slab("cinnabar_slab"))
    reg(807, "slab_brick_netherrack", slab("cinnabar_brick_slab"))
    reg(808, "stairs_cobble_netherrack", stairs("cinnabar_stairs"))
    reg(809, "stairs_brick_netherrack", stairs("cinnabar_brick_stairs"))
    reg(810, "soulsand", simple("soul_sand"))
    reg(811, "soulschist", simple("soul_soil"))
    reg(820, "glowstone", simple("glowstone"))
    reg(821, "rubyglass_column", simple("red_stained_glass"))
    reg(822, "rubyglass_block", simple("red_stained_glass"))
    reg(823, "rubyglass_crystal", lambda meta, c: state("amethyst_cluster", facing="up"))
    reg(824, "conduit", simple("red_stained_glass"))
    reg(825, "rubyglass_growth", lambda meta, c: state("amethyst_cluster", facing=DIR[min(meta & 7, 5)]))
    reg(826, "rubyglass_node", simple("red_stained_glass"))
    reg(827, "rubyglass_brick", simple("red_stained_glass"))
    reg(830, "portal_nether", lambda meta, c: state("nether_portal", axis="z" if meta & 1 else "x"))
    reg(831, "portal_drift", lambda meta, c: state(c.palette.drift_portal))
    reg(840, "cake", lambda meta, c: state("cake", bites=str(min(6, meta & 7))))
    reg(841, "pumpkin_pie", lambda meta, c: state("cake", bites=str(min(6, (meta & 3) * 7 // 4))))
    reg(850, "lamp_idle", simple("redstone_lamp", lit="false"))
    reg(851, "lamp_active", simple("redstone_lamp", lit="true"))
    reg(852, "lamp_inverted_idle", lambda meta, c: colored_light(meta))
    reg(853, "lamp_inverted_active", simple("redstone_lamp", lit="false"))
    reg(860, "stone_polished", simple("smooth_stone"))
    reg(861, "granite_polished", simple("polished_granite"))
    reg(862, "limestone_polished", simple("smooth_sandstone"))
    reg(863, "basalt_polished", simple("polished_deepslate"))
    reg(864, "slate_polished", simple("polished_tuff"))
    reg(865, "permafrost_polished", simple("polished_diorite"))
    reg(866, "netherrack_polished", simple("polished_cinnabar"))
    reg(867, "gloomstone_polished", simple("polished_blackstone"))
    reg(870, "lantern_firefly_green", lambda meta, c: state("copper_lantern", hanging="true" if meta & 1 else "false"))
    reg(871, "lantern_firefly_blue", lambda meta, c: state("soul_lantern", hanging="true" if meta & 1 else "false"))
    reg(872, "lantern_firefly_orange", lambda meta, c: state("lantern", hanging="true" if meta & 1 else "false"))
    reg(873, "lantern_firefly_red", lambda meta, c: state("lantern", hanging="true" if meta & 1 else "false"))
    reg(874, "jar_glass", lambda meta, c: flower_jar(c.tile_entity))
    reg(880, "overlay_pebbles", simple("stone_button", face="floor", facing="north"))
    reg(890, "fence_chainlink", simple("iron_bars"))
    reg(891, "fence_paper_wall", simple("white_stained_glass_pane"))
    reg(892, "fence_steel", simple("iron_bars"))
    reg(900, "basket", simple("barrel", facing="up", open="false"))
    reg(910, "paper_wall", simple("mushroom_stem"))
    reg(920, "jar_butterfly_blue", simple("flower_pot"))
    reg(921, "jar_butterfly_orange", simple("flower_pot"))
    reg(922, "jar_butterfly_pink", simple("flower_pot"))
    reg(923, "jar_butterfly_silver", simple("flower_pot"))

    reg(998, "slab_brick_rubyglass", slab("red_concrete_slab"))
    reg(999, "slab_brick_diamond", slab("prismarine_brick_slab"))
    reg(1000, "slab_brick_sandstone", slab("cut_sandstone_slab"))
    reg(1001, "slab_cobble_permafrost", slab("diorite_slab"))
    reg(1002, "slab_brick_permafrost", slab("polished_diorite_slab"))
    reg(1003, "slab_permafrost_carved", slab("polished_diorite_slab"))
    reg(1004, "slab_brick_iron", slab("light_gray_concrete_slab"))
    reg(1005, "slab_brick_gold", slab("sulfur_brick_slab"))
    reg(1006, "slab_brick_steel", slab("deepslate_tile_slab"))
    reg(1007, "slab_brick_lapis", slab("blue_concrete_slab"))
    reg(1008, "slab_brick_olivine", slab("lime_concrete_slab"))
    reg(1009, "slab_brick_quartz", slab("pink_concrete_slab"))

    # statues become armor stands (made from the tile entity); the blocks themselves are removed
    for i in range(1010, 1022):
        reg(i, f"statue_{i}", simple("air"))
    reg(1025, "thermal_vent", simple("magma_block"))
    reg(1030, "bone_pile", simple("skeleton_skull", rotation="0"))
    reg(1031, "soul_catcher", simple("crimson_roots"))
    reg(1032, "gloomstone", simple("blackstone"))
    reg(1033, "cobble_gloomstone", simple("blackstone"))
    reg(1034, "brick_gloomstone", simple("polished_blackstone_bricks"))
    reg(1035, "slab_gloomstone_carved", slab("polished_blackstone_slab"))
    reg(1036, "slab_cobble_gloomstone", slab("blackstone_slab"))
    reg(1037, "slab_brick_gloomstone", slab("polished_blackstone_brick_slab"))
    reg(1038, "stairs_cobble_gloomstone", stairs("blackstone_stairs"))
    reg(1039, "stairs_brick_gloomstone", stairs("polished_blackstone_brick_stairs"))
    reg(1040, "matcher", lambda meta, c: state("observer", facing=matcher_facing(meta), powered="false"))
    reg(1041, "matcher_active", lambda meta, c: state("observer", facing=matcher_facing(meta), powered="false"))
    reg(1048, "stairs_brick_rubyglass", stairs("red_concrete_stairs"))
    reg(1049, "stairs_brick_diamond", stairs("prismarine_brick_stairs"))
    reg(1050, "stairs_brick_iron", stairs("light_gray_concrete_stairs"))
    reg(1051, "stairs_brick_gold", stairs("sulfur_brick_stairs"))
    reg(1052, "stairs_brick_steel", stairs("deepslate_tile_stairs"))
    reg(1053, "stairs_brick_lapis", stairs("blue_concrete_stairs"))
    reg(1054, "stairs_brick_olivine", stairs("lime_concrete_stairs"))
    reg(1055, "stairs_brick_quartz", stairs("pink_concrete_stairs"))
    reg(1060, "boulder_magmatic", simple("magma_block"))
    reg(1061, "boulder_sulfuric", simple("sulfur_spike", vertical_direction="up", thickness="tip"))
    reg(1062, "fluid_acid_flowing", fluid("water"))
    reg(1063, "fluid_acid_still", fluid("water"))
    reg(1065, "ember", simple("magma_block"))
    reg(1070, "slate_carved", simple("chiseled_tuff"))
    reg(1071, "slab_slate_carved", slab("polished_tuff_slab"))
    reg(1072, "log_scorched", axis("dark_oak_log"))
    for i in range(1075, 1083):
        reg(i, f"statue_{i}", simple("air"))
    reg(1085, "brimsand", simple("soul_soil"))
    reg(1086, "brimstone", simple("cobbled_deepslate"))
    reg(1087, "slab_brimstone", slab("cobbled_deepslate_slab"))
    reg(1088, "stairs_brimstone", stairs("cobbled_deepslate_stairs"))
    reg(1089, "brick_brimstone", simple("deepslate_bricks"))
    reg(1090, "slab_brick_brimstone", slab("deepslate_brick_slab"))
    reg(1091, "stairs_brick_brimstone", stairs("deepslate_brick_stairs"))
    reg(1092, "brimthaw", simple("magma_block"))
    reg(1098, "sulfur", simple("sulfur"))

    blackstone = ("polished_blackstone_pressure_plate", "polished_blackstone_button")
    stone = ("stone_pressure_plate", "stone_button")
    for i, host, kind in ((1100, "cobble_basalt", blackstone), (1101, "cobble_limestone", stone),
                          (1102, "cobble_granite", stone), (1103, "cobble_permafrost", stone),
                          (1104, "cobble_netherrack", blackstone), (1105, "cobble_gloomstone", blackstone),
                          (1110, "basalt", blackstone), (1111, "limestone", stone), (1112, "granite", stone),
                          (1113, "permafrost", stone), (1114, "netherrack", blackstone), (1115, "gloomstone", blackstone),
                          (1116, "sandstone", stone), (1117, "brimstone", blackstone), (1118, "marble", stone),
                          (1119, "slate", stone)):
        reg(i, f"pressure_plate_{host}", pressure_plate(*kind))
    for i, host, name in ((1120, "basalt", "polished_blackstone_button"), (1121, "limestone", "stone_button"),
                          (1122, "granite", "stone_button"), (1123, "permafrost", "stone_button"),
                          (1124, "netherrack", "polished_blackstone_button"),
                          (1125, "gloomstone", "polished_blackstone_button"), (1126, "sandstone", "stone_button"),
                          (1127, "brimstone", "polished_blackstone_button"), (1128, "marble", "stone_button"),
                          (1129, "slate", "stone_button")):
        reg(i, f"button_{host}", button_m(name))


_table()


def is_statue_lower(bid: int) -> bool:
    return (1010 <= bid <= 1021 and (bid - 1010) % 2 == 0) or (1075 <= bid <= 1082 and (bid - 1075) % 2 == 0)


def mapping_table(palette: Optional[Palette] = None) -> str:
    """Markdown table of every BTA block (metadata 0, plus the painted colour variants) and its 26.3 result."""
    ctx = MapCtx(palette or Palette())
    lines = ["| ID | BTA block | Java 26.3 block (metadata 0) |", "|---:|---|---|"]
    for bid in sorted(TABLE):
        if bid == 0:
            continue
        name = BTA_NAMES[bid]
        out = map_block(bid, 0, ctx).key.replace("minecraft:", "")
        if "painted" in name or name == "wool":
            variants = []
            for col in range(16):
                meta = col if name in ("planks_oak_painted", "fence_planks_oak_painted", "wool") else col << 4
                v = COLORS[col] + " → " + map_block(bid, meta, ctx).name.replace("minecraft:", "")
                if v not in variants:
                    variants.append(v)
            out = "<br>".join(variants)
        lines.append(f"| {bid} | {name} | {out} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(mapping_table(), end="")

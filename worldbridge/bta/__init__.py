"""Better than Adventure (BTA 8.0.1, a Beta 1.7.3 based mod) -> Minecraft Java Edition 26.3.

BTA saves are read directly (their own NBT dialect, region layout and
chunk versions) and written as a Minecraft 1.18.2-format world (DataVersion 2975) that Minecraft
26.3 upgrades on first load with its own DataFixer, which also marks every converted chunk for
terrain blending.  Only this direction exists: nothing is ever written in the BTA format.
"""

DATA_VERSION = 2975          # chunks: 1.18.2 (negative heights, pre-26 palette layout)
LEVEL_DATA_VERSION = 2730    # level.dat / players: 1.17.1 layout (legacy WorldGenSettings)
TARGET = "26.3"

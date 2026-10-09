# Fix history

This file records the problems found while developing and testing WorldBridge, and how each one
was fixed. It is a development log, not user documentation: for what WorldBridge does today see the
[README](../README.md), and for how it is verified see [VERIFICATION.md](VERIFICATION.md).

Each entry gives the symptom, the root cause and the fix. Fixes 1–49 keep the numbers used in the
test log; later fixes continue the sequence. "Found in game" means the problem was seen by playing
a converted world, not by an automated check.

## Contents

- [Before the test matrix](#before-the-test-matrix)
- [Found by the test matrix (1–7)](#found-by-the-test-matrix-17)
- [Bedrock, in game (8–16)](#bedrock-in-game-816)
- [Heights and sea level (17–20, 24, 28, 32)](#heights-and-sea-level)
- [The ring and the terrain generators (21–23, 25–27, 29–31, 34–49)](#the-ring-and-the-terrain-generators)
- [Blocks and content (30, 33, 38)](#blocks-and-content)
- [Later fixes (50–57)](#later-fixes-5057)
- [0.2.1 (65–81)](#021)
- [0.2.2 (82–173)](#022)

---

## Before the test matrix

These were found on real saves before the numbered list started.

- **LCE → Java: Minecraft regenerated every chunk that held an entity.** LCE stores entity UUIDs
  as strings (`"ent<32 hex>"`) and attributes with numeric ids. Minecraft's DataFixer throws on the
  string UUID (`EntityStringUuidFix`), and a chunk whose upgrade throws is discarded and generated
  again. On a 5,678-chunk Windows64 save this replaced 374 chunks, which were all the built areas.
  The Java writer now converts LCE entities to the Java 1.12 layout (UUIDMost/UUIDLeast, attribute
  names), the level.dat player included.
- **LCE → Java: `Failed to decode value '""' from field 'Owner'`.** LCE writes `"Owner": ""` for
  untamed mobs. Empty owners are now removed, hex UUID owners become `OwnerUUID`, and player names
  are kept.
- **PS Vita (Aquatic) → Java: player inventory lost.** The Aquatic player data carries
  DataVersion 922, which made Minecraft skip the numeric item-id fixes, so every item failed to
  decode. The player is written in the legacy layout without a DataVersion.
- **`Failed to load chunk` for every empty chunk.** Amulet wrote an `entities/` record without the
  `Position` field Minecraft reads before upgrading. Empty records are removed and `Position` is
  added where missing.
- **Bedrock → Java: numeric-era items with Damage 0 lost** (`log`, `sapling`, `wool`). They now
  resolve to `oak_log`, `oak_sapling`, `white_wool`, and so on.
- **Biomes mirrored on the x = z diagonal.** Amulet Core 1.9 swapped x and z when decoding and
  encoding Java 1.2–1.14 biomes. WorldBridge patches the two coders at start-up.
- **Old Java versions showed an empty world slot.** The Alpha/Beta NBT reader only knows tag types
  1–10: a single `TAG_Int_Array` (the player UUID of Java 1.16+) made `level.dat` unreadable. It
  also reads each field with a fixed type (`Health` as a short). Player and `level.dat` are now
  rebuilt from per-version field lists with exact types, and content newer than the target is
  removed.
- **Java 1.16+ worlds with players aborted on the way to LCE and PE 0.x.** The writer called
  `int()` on `"minecraft:overworld"`. One helper now reads both dimension forms.

## Found by the test matrix (1–7)

1. The Bedrock source was opened by LevelDB in write mode (a `LOCK` file, and a possible change to
   the original), and Amulet wrote `session.lock` into modern Java worlds. Sources are now read
   from a copy.
2. Unreadable chunks and truncated region files were skipped silently. A warning is now shown
   and the chunk count is correct.
3. Pocket Edition 0.8: the player was not written.
4. Tamed animals lost their owner when coming from Java 1.13+ and from Bedrock.
5. Bedrock: the player's ender chest arrived empty; hunger and experience were not written.
6. Flower pots and note blocks lost the plant and the note to and from Java 1.13+ and Bedrock. The
   Java 1.7–1.12 and LCE writers also dropped the plant.
7. Bedrock → Java 1.13–1.16: every mob appeared twice, one copy in Bedrock format and broken.

## Bedrock, in game (8–16)

Found by playing an LCE world converted to Bedrock (mcpelauncher on Linux), and a Bedrock world
converted to Beta 1.7.3.

8. The player moved seven times too fast: the movement-speed attribute was missing.
9. Game-mode changes were ignored: the personal game mode was fixed, there were no operator
   permissions, and `cheatsEnabled` was off.
10. Item frames with maps disappeared. In Bedrock a frame is a block with a block entity, and the
    map data was not written.
11. No blending with the new terrain: every chunk's height map was 0.
12. Found while fixing 10: maps from Java 1.13+ did not reach LCE and older versions, and were not
    copied to modern Java through Amulet.
13. Bedrock → Beta: empty inventory. A player saved by the Bedrock game contains binary strings,
    and the NBT reader dropped the whole player silently.
14. Bedrock → Beta, and any target that trusts the stored light: everything was lit at night. The
    light was left at full brightness; it is now computed from the blocks.
15. Bedrock, LCE or Java → Alpha and Beta: converted oceans were one block below the Beta sea (y 62
    instead of 63). Raising only the water made walls of water on low shores; the whole converted
    world is now raised by one block, with players and spawn.
16. Bedrock or Java 1.18+ → Java ≤ 1.12, LCE, Alpha and Beta: blocks unknown to Java 1.12 became
    air, leaving holes at the bottom of the world (deepslate) and air pockets under water (kelp).
    They now become the closest old block: stone, the plain ore, water, log, leaves.

## Heights and sea level

17. Java 26.3 Amplified → Java 1.1 (and any 128-block-high world): mountains were cut at y 127,
    leaving flat stone plateaus with floating pieces. They are now compressed (see the README).
18. Java 26.3 or Bedrock → Java 1.18–1.21.x: everything below y 0 and above y 255 was lost. Amulet
    read the new world's height limits from a `level.dat` that did not contain them yet, and fell
    back to 0–255.
19. Java 26.1+ → Java 1.13–1.21.x: an Amplified (or Large Biomes) world became a normal one. In
    26.1+ the world type is in `data/minecraft/world_gen_settings.dat`, which was not carried over.
20. Compression (fix 17), seen in game: village houses were warped and leaves detached on slopes,
    because every column moved down by a different amount. A building now moves down as one piece
    and leaves and branches follow their trunk. On the Amplified test world, detached leaves went
    from 17.9 % to 11.7 %; the original world has 10.6 %, because the game leaves some too.
24. PE 0.8 → Java 26.3, seen in game: the converted sea was at y 63 and the generated sea around it
    at y 62. Alpha 1.2 – Beta 1.7.3 and PE 0.x have the sea one block higher than every later game.
    The world now moves by one block in the right direction for every target, with players and
    spawn.
28. Compression was too aggressive on normal worlds: mountains up to y 134 were compressed from
    y 80 upwards. It now starts only where needed (y 100 in that case), and at y 80 only for very
    tall worlds such as Amplified ones. Anvil targets (1.2+, 256 blocks) are never compressed; the
    part below y 0 is removed.
32. Converted chunks had no bedrock at y 0: the underground of a 1.18+ world was cut at y 0 and
    left stone. Every target that starts at y 0 now gets the old games' bedrock floor (solid at
    y 0, thinning out up to y 4), only where the terrain is natural.

## The ring and the terrain generators

21. Java → 1.0 / 1.1 (and Beta 1.8): no ring, so the converted world ended with a step against the
    generated terrain. These versions now have the ring with their own generator (biomes identical
    to cubiomes, terrain checked on 1,023 chunks of Minecraft 1.0).
22. Java 1.16+ and 26.x sources → Alpha, Beta, 1.0–1.1: the ring was generated with seed 0, because
    the seed was only looked up in `RandomSeed`. The written `level.dat` had the right seed, so the
    game generated other terrain and the ring's outer edge had a step.
23. The Beta 1.8 – 1.1 ring had no caves and used two estimated heights. After reading the 1.0 and
    1.1 code: the cave seed uses XOR, the π and sine-table constants differ, grass over carved
    holes is the biome's top block, and ravines exist. In 1.1 Extreme Hills and Ice Mountains are
    lower (1.3 and 1.2 instead of 1.8). Caves and ravines now match the game block for block.
25. LCE: the whole map was filled even when huge (320 × 320 chunks: 108 MB). Filling is now only
    done on 54- and 64-chunk maps.
26. Java 26.3 → 1.0, seen in game: tall isolated rock blocks inside the converted world. They were
    chunks the game had not finished generating (status `structure_starts`, `biomes`, `terrain`… at
    the edge of the explored area), converted as if complete. From Java 1.14+ only `full` chunks
    are converted, and from Bedrock only chunks with `FinalizedState` 2.
27. The ring, seen in game: straight stripes and steps along chunk borders. Each ring chunk only
    looked at the converted chunks "near it", and the width changed in jumps. Every column now
    considers the whole border at the same distance, the width changes gradually, and a light noise
    bends the contour lines. Jumps between ring chunks now equal those inside chunks (mean 0.34,
    ≥ 3 blocks 1.3 %; before: 0.69 and 6.5 %).
29. The ring, seen in game: unrealistic, no trees, "looks like Indev". It rebuilt each column from a
    height map (grass, 3 dirt, stone), which made regular terraces and radial stripes. The ring is
    now **the game generator's real terrain, lifted**: the rock of each column moves up or down by
    a smooth amount, solved once over the whole ring (a harmonic function equal to the converted
    minus generated height at the border and 0 at the outer edge). The generator then builds the
    surface, beaches, caves and ravines as in the game, and the ring receives the border's trees.
31. The ring, seen in game: visible circles, huge craters in Extreme Hills, some ring chunks with
    no grass or trees.
    - The rock was moved by whole blocks after the caves were carved, so a mountain lowered by
      40 blocks had its caves opened at the surface. The lift now acts on the generator's density
      field, in fractions of a block, and caves move with the rock.
    - A noise bends the lift lines, and the lift always returns to zero before the outer edge.
    - Trees at the border were not counted (mangroves stand on roots that 1.0 does not have; acacia
      and dark oak have few trunks and huge crowns). Trees are now counted from crown cover and from
      trunks within 5 blocks of the ground.
    - The ring also receives the border's tall grass and flowers, thinning out outwards.
34. neoLegacy worlds were read with misplaced chunks. New neoLegacy worlds have a
    `region_format_16` marker and 16 × 16-chunk regions, which were read as 32 × 32 regions.
35. neoLegacy (Windows64, TU31) had no border remedy. WorldBridge now has neoLegacy's generator
    (4J's biome stack, terrain, biome surfaces, the map edge that sinks into the sea, caves and
    ravines) and writes a ring around the converted world.
36. Java 1.2–1.6 (numeric Anvil) had no ring and warned about a step. The ring now uses those
    versions' generator (jungle and Large Biomes, the 1.2 and 1.6 biome heights, caves and
    ravines), up to y 255 next to a converted world taller than 128 blocks.
37. Java 1.7–1.12 had no ring. A new generator for those versions (1.7+ biomes, 256-high terrain,
    biome surfaces, caves and ravines) supports Default, Large Biomes and Amplified worlds;
    Customized worlds warn that a step will remain.
39. Java 1.13–1.17 (Amulet route) had no ring. WorldBridge now writes it with those versions'
    density and biome surfaces and leaves caves, ravines, lakes, ores and trees to the game (status
    `surface`, `base` in 1.13). Amulet wrote every chunk as `full`; ring chunks now get the right
    status.
40. Walls of water at the edge of the ring (seen in game, 26.3 → 1.6.4). Dry canyons below sea
    level, normal since 1.18 and impossible in older generators, were cut by the selection edge:
    the ring went down to their floor, below the sea, and the generator filled it with water that
    stood as a wall against the canyon's air. The ring no longer goes below the sea where the
    converted border is dry, and a final pass seals every spot where ring water would touch
    converted air (or the opposite). The converted world is never touched. Measured with
    `tools/seamcheck.py`: 48 leaking spots → 0 on 1.6.4, 1.12.2 and 1.13.2.
41. Direct Amulet conversions (Java 1.13+ or Bedrock → Java 1.13–1.17) with a chunk selection, or
    with unfinished chunks left out: the final clean-up of the selection also deleted the ring. The
    ring is now written last.
42. Ocean temperature (1.13–1.17 biomes): the noise was sampled with swapped axes (the game calls
    `noise(x / 8, z / 8, 0)`, with z in the y slot). It matched near spawn by chance; elsewhere it
    gave warm oceans instead of cold and frozen ones. Biomes are now 100 % identical on every chunk
    of the 1.15.2 (1,519), 1.16.5 (26,350) and 1.17.1 (2,401) reference worlds.
43. Badlands (1.13–1.17) and mesa (1.7–1.12) terracotta bands: the loop that places the orange
    bands lacked the `+1` of the Java `for`, so all bands were shifted. The top blocks now match at
    98–99.9 % (1.16.5) and 94–99 % (1.12.2; before: 3–51 %). neoLegacy really uses a `while`
    without `+1`, so its generator is unchanged.
44. Java 1.17: the density's bottom slide (15, 3, 0), absent in 1.16. Everything else (aquifers,
    noise caves and deepslate off, surface builders) is identical to 1.16.
45. Beta 1.8: the ocean has scale 0.5 (the 1.0 value is 0.4). Surface height on the game's world
    went from 72.3 % to 96.5 %.
46. Java 1.7: no swamp puddles. In 1.7 the chunk's air is `null` and the swamp loop stops at the
    first block (a bug of the game itself, read from the 1.7.10 jar); puddles arrive with 1.8.
    Surface height on the 1.7.10 reference world went from 94.6 % to 96.9 %.
47. End 1.13: the default surface builder, with the End sea at y 0, removes the first block of each
    end-stone layer where its noise is low (6 different blocks in 400 chunks before the fix, 100 %
    after).
48. 3D ring: signed distances capped at 16 blocks all vanished together halfway through the ring
    (jumps of 42 % between neighbouring columns), and with the vertical distance alone an all-rock
    column next to a cavern jumped by 53 %. The distance is now the nearest along x, z or y, with no
    cap: 18.8 % at most, below the natural 21.1 %.
49. 3D ring: rock carried outwards in a straight line formed prisms with straight sides, and game
    islands entering the ring were cut parallel to the border. The point that looks up the border
    column and the lines of equal weight are now bent by a noise that is zero at both edges.

## Blocks and content

30. Mud and newer blocks: towards Java 1.13–1.18 and Bedrock before 1.19, mud, packed mud, muddy
    mangrove roots, rooted dirt, moss, suspicious gravel, tuff, calcite and 2024–2026 blocks (pale
    oak, resin, crafter…) became **air**, leaving holes in swamps and caves. Every block the target
    lacks now takes the closest older block for every target: mud and roots become dirt, moss
    grass, tuff andesite, calcite diorite, suspicious gravel gravel.
33. Bamboo became stone; bushes and short dry grass became dandelions. Bamboo now becomes a fence,
    bushes tall grass, dry grass a dead bush, where the target lacks them.
38. Map view of Java 26.x worlds: the block palette has new forms (plain strings,
    `{"id", "properties"}`, strings wrapped in `{"": name}` when a list mixes them) that were read
    as air, so the map showed the caves. The surface is now shown.

## Later fixes (50–57)

50. **Ring crash on large selections** (Java 26.3 → neoLegacy, 5,816 selected chunks): the
    over-relaxation of large, not fully converged ring pieces can overshoot below 0, and numpy's
    Poisson sampler failed with `lam < 0 or lam is NaN`. The planned amount of trees, grass and
    flowers is now clamped.
51. **Big worlds opened slowly.** Listing chunks read whole region files, the map loaded in a fixed
    order and the conversion waited for the preview. Listing now reads only the 4 KiB region
    headers, map tiles load in rings around the view, and the preview pauses while a conversion
    runs.
52. **Copper chests (Java 1.21.9+) became invisible, empty chests on LCE and old Java.** They were
    mapped to wooden chests without their block entity, and LCE draws chests through the block
    entity. Their block entity is now translated, and any chest still without one gets an empty
    one, with a warning.
53. **Rows of double chests were half invisible on LCE and Java ≤ 1.12.** Those games pair a chest
    with any chest of the same kind beside it and draw a double chest only from one half, so every
    second pair in a row vanished. The LCE writer also dropped the block entity of every trapped
    chest. Rows are now re-paired two by two, pairs alternate chest and trapped chest (which never
    join each other), and trapped chests keep their contents.
54. **Offset rows, 2 × 2 blocks, columns and L shapes of chests** could still leave a chest touching
    two of its kind. Pairs now sit on a lattice along the double chest's axis and alternate by pair
    and by row, so every chest touches at most its partner. Checked on 2,000 random groups.
55. **neoLegacy: the main player lost inventory and position.** neoLegacy loads the host from
    `players/<XUID>.dat`, where the XUID is a number the game assigns per installation, not the
    nickname. The GUI now reads the XUID from a world already played on that PC, and warns when a
    nickname is given instead.
56. **neoLegacy TU31 crashed while loading a Java 26.3 world.** The save contained things TU31 does
    not know: banners under Java's item id 425 (neoLegacy registers them as 176), 1.9+ items
    (shield, elytra, nuggets, tipped and spectral arrows, wooden boats…), Sweeping Edge and curses,
    the fishing enchantments at Java's ids (neoLegacy uses 64 and 65), and parrots. The main
    player, now loaded as soon as the world opens, was a raw Paper server player with fields and
    types the game does not write, and another player had no position. Items, enchantments and
    entities are now checked against neoLegacy's source and mapped to the closest one or removed
    (counted in the report); player files are rebuilt with neoLegacy's own fields and types, armour
    from Java 1.20.5+ `equipment` goes back to slots 100–103, and a player without a position is
    placed at the spawn.
57. **Swamp in the open sea around the ring** (neoLegacy, seen in game). The ring's biomes are the
    generator's; where the ring slopes down to a converted sea floor, land biomes stayed on water
    columns, and the game decorated them as land: lily pads and swamp trees in the ocean. Columns
    the ring lowers under water now get an ocean biome (frozen ocean in cold biomes). On a Java
    26.3 → LCE test conversion, ring columns under 3+ blocks of water with a land biome went from
    19,271 to 4,152 (swamp: 3,989 → 396); the rest is the game's own terrain.
58. **Big worlds: memory per chunk.** Measured on a synthetic world of 998,784 chunks. The Java chunk
    index held a dictionary entry per chunk, copied by every worker process (1.39 GB in all). It now
    keeps one entry per region file, with a 1024-bit mask of its chunks: 0.63 GB.
59. **Big worlds: region files read and written over and over.** Chunks were converted in column
    order across the whole world: each source region was read once per column of chunks, and a world
    wider than the writers' cache of 64 regions would have rewritten and merged the same output files
    again and again. Chunks now go region by region.
60. **LCE and PE 0.x read the whole world for a finite map.** Every chunk was read and prepared, and
    those outside the map dropped by the writer; from Java 1.13+ and Bedrock the whole world first went
    through Amulet. Only the chunks that reach the map (and an 18-chunk margin for the ring) are now
    read and translated: 998,784 chunks → LCE went from 6 min 30 s to 2 min, with the same map.
61. **Bedrock: every sub chunk of the world in memory.** The height maps were recomputed after loading
    every sub chunk of the database: 2.96 GB for 249,696 chunks, enough to run out of memory on a
    100 GB world. They are now computed one column of chunks at a time, on every core: 0.48 GB.
62. **Biomes of every chunk kept for a few unknown ones.** Into Bedrock and Java 1.13+, the biome
    filler kept the biomes of every chunk for the chunks whose biomes the game had not computed yet. It
    now reads the neighbours of those chunks back from the hub writer.
63. **Working copies of whole worlds.** A Bedrock source was copied whole before the conversion, and
    a Java 1.13+ source too when the output was on another disk. LevelDB never changes a table file
    once written, so they are hard links now, and the working copy goes next to the source when the
    output is on another disk.
64. **Bedrock on one core; then hung.** The Amulet translation into and from Bedrock ran on one core
    (249,696 chunks: 24 minutes). It now runs on every core (11 minutes): each worker writes a LevelDB of
    its own and the parts are merged. The first version hung on a Bedrock → Java conversion of 98,304
    chunks: the workers were forked from a process that had opened a LevelDB, and a forked copy waits
    forever for LevelDB's background thread when it closes its database. Those workers now start from
    the fork server; a test reproduces the hang with `fork`.

## 0.2.1

Found in game: a Bedrock 26.50 world converted to Java 26.3 had lost the cooked mutton from the
inventory, but not from the furnace. Looking for the cause turned up four more problems on the way
from a player's inventory to Java. The rules of Minecraft's data fixers quoted below were checked on
the game's code (`LevelStorageSource`, `ItemIdFix`, the item rename fixes).

65. **Items added in Java 1.8 – 1.12 became air on the way to Java 1.9+.** The furnace kept the
    cooked mutton because block entities reach Java 1.13+ with item names; the player went through the
    numeric hub and was written with numeric ids (cooked mutton = 424), left to Minecraft's data
    fixers. The game's numeric id fix (`ItemIdFix`, data version 102) only lists the ids of Java 1.7:
    items 409–416 and 423–453 (mutton, banners, doors other than oak, chorus fruit, beetroot, shields,
    elytra, boats other than oak, totems, shulker shells, iron nuggets…) and blocks 165–255 (slime
    blocks, prismarine, red sandstone, purpur, concrete…) became air, silently. Everything Java 1.9+
    upgrades now names its items the way Java 1.8 – 1.12 saved them, with the same Damage: the
    players' inventories and ender chests on every route to Java 1.9+, and where the game upgrades
    the world ("Java 1.9 → latest") also chests, furnaces, dropped items, item frames and mob
    equipment. The names match the game's table for every id it has. Targets before 1.9 keep numeric
    ids, which is what those games read.
66. **Bedrock → Java: every item newer than Java 1.12 lost from the player.** The Bedrock player was
    translated into the numeric layout of Java 1.12, where netherite, tridents, crossbows, copper,
    deepslate, spyglasses, maces… have no id: they were dropped. The off hand was never read. A
    Bedrock player now becomes a Java 1.15.2 player (data version 2230) with every item by name, off
    hand included; the targets that cannot hold these items (LCE, old Java, Pocket Edition) translate
    it like any Java 1.13+ player.
67. **The level.dat player was upgraded from the wrong version.** Minecraft upgrades the `Player`
    inside level.dat from the level's DataVersion, not from the player's own. The level.dat of every
    route through Amulet was rebuilt in the Java 1.12.2 layout (data version 1343), and a Java 1.13+
    player was put into it unchanged: the game ran the 1.13 – 1.17 fixes on it again, and its renames
    turned modern items into others (`melon` → `melon_slice`, `stone_slab` → `smooth_stone_slab`,
    `purple_shulker_box` → `shulker_box`, `weathered_cut_copper` → `oxidized_cut_copper`; 1.20.5+
    stacks were read as 1.12 ones). A Java 1.13+ source no newer than the target now keeps its own
    level.dat, with its DataVersion: the game upgrades level and player exactly as it would the
    original world (a selected spawn of a 1.21.9+ level goes into its `spawn` compound, and the 26.1+
    world generation settings stay in their own file). A world from Bedrock gets a level.dat of data
    version 2230, the version of its players: after the 1.13 – 1.14 renames, before the 1.16 world
    generation settings, which the game still builds from the 1.12 fields (a flat world gets the 1.13
    layers it would have got from the fixes). Every other source keeps the 1.12.2 level.dat with
    players in the numeric layout. playerdata files are upgraded from their own DataVersion and keep
    the players up to the target's.
68. **Item names for the wrong version.** WorldBridge's item names are those of Java 1.13 – 1.21, and
    they were written as they are whatever the DataVersion of the data: short grass (`grass` until
    1.20.3), turtle scutes, iron chains (`chain` until 1.21.9) and dirt paths reached the latest Java
    with names it no longer reads, and became air in chests. They are now written with the name of
    the data's version, following the game's renames, and read back from any of them. The numeric
    stone slab (44:0) was named `stone_slab`, the 1.13 name that Java 1.14 renamed `smooth_stone_slab`:
    as a 1.14+ name it is the plain stone slab, a different block.
69. **Bedrock block items read with the tables of Bedrock 1.21.0.** Block items (which carry a
    `Block` compound) were resolved with Bedrock 1.21.0's block table: names of later versions (the
    plain stone slab `normal_stone_slab`…) passed through unchanged, as names Java does not have. They
    are now resolved with the version recorded in the compound, and the Java name is the latest one.

`tests/test_item_ids.py` covers each of them: a Bedrock player with old and new items, armour and
off hand to Java 26.3 and 1.13.2, to LCE and back to Bedrock; the level.dat of a Bedrock world (flat
too) and of a Java 1.21.3 and 1.21.9 world; the names by data version; the numeric names against
the game's table; the chests and entities of the hub.

70. **World management: the inventory of a native Bedrock player looked empty.** A player saved by
    Bedrock lists every slot, the empty ones too (36 in the inventory, 4 of armour, 1 off hand, 27 in
    the ender chest, name `""`), and the table showed them all in slot order: with an empty hotbar its
    first rows were all empty. The table now lists where each item is (hotbar, inventory, armour, off
    hand, ender chest) and hides the empty slots unless asked. The Bedrock ender chest
    (`EnderChestInventory`) was not read at all. Saving a Bedrock player wrote its strings as plain
    UTF-8, but the game keeps raw bytes in some (actor storage keys): they are written back as read.
    A database locked by Minecraft left the player list empty without a word: it is now said.
71. **World management did not follow the world's version.**
    - The single player of a Java world (level.dat `Player`, the one the game loads for the world's
      owner) and of a Pocket Edition 0.x world was not listed; Java 26.1+ keeps it in
      `players/data/<singleplayer_uuid>.dat`, now marked as such.
    - Java 1.21.5+ armour and off hand (`equipment`) were missing from the inventory.
    - Java 1.21.11's game rules (`game_rules`, typed, new names) were not shown, and neither were
      Bedrock's number rules (spawn radius, sleeping percentage…).
    - Game modes offered Spectator where it does not exist: Bedrock's level value 3 is not Spectator,
      LCE has none, Java got it in 1.8 and Adventure in 1.3; Pocket Edition 0.x has Survival and
      Creative only.
    - Settings were offered for versions without them: difficulty before Java 1.8 (it was in
      options.txt), cheats before 1.3, the time of day as `DayTime` before 1.3 (then it was `Time`).
    - An item could not be named in a numeric-id world (Java before 1.8, LCE); a renamed Bedrock
      block item kept its old `Block` compound, which the game reads first.
72. **Java 1.21.5+ armour and off hand lost on the way to Bedrock and older Java.** Java 1.21.5 moved
    them from the inventory's slots 100–103 and -106 into `equipment`; the Bedrock writer and the
    numeric layout still looked in the inventory. Bedrock's `Offhand` was never written.
73. **Game modes between editions.** Bedrock's player modes 5 ("same as the world") and 6
    (Spectator) became Survival in Java: 6 is now Spectator and 5 leaves the mode to the world, as
    Java does without `playerGameType`. Java's Spectator became Creative in every Bedrock version;
    it is Spectator from Bedrock 1.21.40, which has it. LCE gets Creative for it.
74. **The world settings of Java 1.21.11+ and 26.x.** Java 1.21.11 turned `GameRules` into
    `game_rules` (typed values, new names, some inverted), and 26.1 moved difficulty into
    `difficulty_settings` and weather and game rules into data/minecraft/*.dat. The writers of
    Bedrock, LCE and older Java read the 1.21.10 keys and lost difficulty, hardcore, weather and every
    rule. Such a level is now read with those keys as well (the game's own 1.21.11 renames, read
    backwards); a Java target that keeps the source's level.dat does not get them. The difficulty
    also read 0 as "missing": a Peaceful world became Normal from Java to Bedrock and back. The game
    rules that both editions have (keepInventory, mobGriefing, doDaylightCycle… not randomTickSpeed,
    three times faster in Bedrock) now go from one edition to the other.
75. **Java 26.x → 26.x: the single player started anew.** Fix 67 kept the source's level.dat but put
    the host player back inside it, where Java 26.1+ no longer reads it, and the source's players/data
    went to playerdata/. The host now goes to players/data/<singleplayer_uuid>.dat (the UUID chosen in
    the "Giocatori" tab, if any), and players/ keeps the 26.1 layout; an older output level gets the
    old folders, which the game moves when it upgrades it.

`tests/test_manage.py`, `tests/test_version_quirks.py` and `tests/test_gui.py` cover them with
players and levels as each version writes them.

76. **Biomes of Java 26.2 – 26.3 and Bedrock 26.20 – 26.50 missing from the biome painter.** The
    biome list stopped at the pale garden: sulfur caves (Java 26.2, Bedrock 26.20) and the dappled
    forest (Java 26.3, Bedrock 26.50) could not be painted. Checked against the biomes of the Java 26.3
    client jar (data/minecraft/worldgen/biome, 67): those two were the only ones missing. The Bedrock
    list was the Java list of the same version number, but the two editions number their versions
    differently (Bedrock 26.20 came before Java 26.3's biomes; the pale garden came with Bedrock
    1.21.50, not 1.21.40): every biome since 1.19 now has its first Java and Bedrock version. The
    painting went through Java 1.21.4's biome table, which has neither: it uses the latest. Checked on
    a Bedrock 26.52 world: the painted chunks hold Bedrock's ids 195 and 194.
77. **Map colours of recent blocks.** The map's colours were a hand-made table with keywords: leaf
    litter (the floor of forests since 1.21.5) and about fifty other recent blocks fell on the grey
    for unknown blocks, the dappled forest's orange, red and yellow poplar leaves on the plain green
    of leaves. A Bedrock 26.52 world showed its forests grey and the dappled forest green. The colours
    are now generated from the game: `tools/mapcolors.py` reads the bytecode of a Java client jar
    (Blocks, MapColor, DyeColor and the block ids, with the 16-colour and copper families, the
    properties copied from other blocks and the colours computed per block state) and writes
    `worldbridge/mapcolors.py` with the map colour of each of the 1,286 blocks of Java 26.3. The blocks
    without a map colour (glass, torches, rails, buttons, flower pots…) are seen through, as on a game
    map; Bedrock names (normal_stone_slab, magma…) go through their Java name; the hand-made table is
    left for the names of older versions. On that world every block has its colour.
78. **"Edit the source world" lacked the newest biomes.** The painter for the converted world offered
    the dappled forest, the one for the source world did not, on the same Bedrock 26.52 world. The
    source world's version was misread on both editions. Bedrock 26.x stores its version as 1.26.x
    (`lastOpenedWithVersion` [1, 26, 52, 3, 0]), which compares as older than 26.20 and 26.50: the
    world got the biomes of 1.21.50. Java worlds took their version from a DataVersion table that
    ended at 1.21.4. `worldbridge/gameversion.py` now reads and writes versions as each game stores
    them: 1.26.x is 26.x (as PyMCTranslate already does), and a Java DataVersion gives the newest
    release PyMCTranslate knows with that DataVersion or lower. Every read of a world's version goes
    through it: the biome lists, the source world's game, the conversion's choice of terrain height,
    and the version shown in world management (26.52.3, not 1.26.52.3.0).
79. **Bedrock 26.x worlds written as a version far newer than the game.** The same quirk on the
    writing side: a conversion to Bedrock 26.50 wrote `lastOpenedWithVersion` and
    `MinimumCompatibleClientVersion` as [26, 50, 0, 0, 0], where the game writes [1, 26, 50, 0, 0]
    and compares the numbers to decide whether it can open the world. Written now as the game does;
    checked against the level.dat of a world saved by Bedrock 26.52.
80. **Block items with the wrong block version for Bedrock.** The `Block` of a block item (and a
    flower pot's plant) carried the target game's version (26.50 as 0x1A320000, 1.21.110 as
    1.21.110.0). Bedrock writes the version of its block states, which changes far less often: every
    block of the Bedrock 26.52 world, in chunks and in inventories, says 1.21.60.33. It now comes from
    PyMCTranslate's table of each Bedrock version, the same one Amulet writes in chunk palettes.

`tests/test_game_versions.py` covers them with worlds converted to Java 26.3 and Bedrock 26.50 and the
version numbers of the Bedrock 26.52 world.

81. **WorldBridge closed itself after an edit of the source world.** Found painting plains chunks of
    the Bedrock 26.52 world as dappled forest: the "Done" message appeared, then the program crashed.
    The edit runs in a worker thread, and its end was connected to plain functions (the message and
    the map's reload); PySide6 runs such functions in the thread that emits the signal, so the message
    box and the map's new reading thread were made outside the interface's thread, which Qt does not
    allow ("Cannot create children for a parent that is in a different thread"). The same held for
    the trimmed-world copy, the progress shown in the status line and the map's error message. A
    worker's signals now reach those functions through `GuiThread` (gui/widgets.py), which runs them
    in the interface's thread; `tests/test_gui.py` paints a Bedrock 26.50 world from the map and checks
    where the message runs.

Looked into at the same time: the empty chunks inside the explored area of that Bedrock world are not
in its database at all (read file by file, the write-ahead log included), and the world was never
trimmed: the game left them out of its files, and generates a missing chunk again from the seed. The
map and the converter cannot show or carry chunks that are not in the files (see the user guide).

## 0.2.2

0.2.2 is a review of the whole program against real worlds instead of worlds WorldBridge made itself.
110 real worlds were downloaded from the web and converted: Java Classic → 26.3, Bedrock 1.1 →
1.26.40, PE 0.x, and LCE saves of PS3, PS4, PS Vita, Wii U and Xbox 360. Then the converted worlds
were opened in the games themselves: four real worlds converted to 23 targets were loaded and saved
by real Java servers (1.2.5 → 26.3, Beta, Alpha) and Bedrock Dedicated Servers (1.12 → 26.52), and
seven worlds converted to LCE Windows64 were loaded, saved and closed by neoLegacy under Wine. Each
saved world was read back and compared with the converted one: blocks, block entities and entities
per id, and the game's log. The figures are in [VERIFICATION.md](VERIFICATION.md#in-game-tests).

"Found in game" below means the problem showed in a real server or in neoLegacy; the others were
found converting the downloaded worlds, or reading the code while fixing them.

### Crashes and worlds that could not be read (82–89)

82. **Indev levels with mobs crashed the conversion.** Indev stores `Pos` and `Motion` as lists of
    floats. Several places rebuilt `Pos` from the old elements plus new doubles, a mixed list that
    amulet_nbt refuses. Positions are now built from numbers (`nbt.pos_list`) everywhere, and the
    Indev reader turns them into doubles when it loads the level.
83. **Fitting a tall world into a lower game crashed on some columns** ("argmin of an empty
    sequence"). A column whose surface was under the start of the compression band had nothing to
    search. Such columns are now left alone.
84. **Chunks written by MCEdit 2 were unreadable.** MCEdit 2 wrapped a gzip stream inside the zlib
    payload, so a chunk was compressed twice. The second layer is now unwrapped.
85. **Real Xbox 360 saves were not recognised.** Every real `savegame.dat` checked (22 saves, TU0 to
    TU75, loose or in a CON package) starts with a big-endian u32 size and a u64 decompressed size;
    the reader tried LZX only when the first number was zero, which only WorldBridge's own files
    have. The real header is now read and written (old WorldBridge files are still read), and saves
    are also found as `savegame-*.dat` and in `Save<date>.bin` folders. Version 1 saves keep their
    player as `players_<XUID>.dat`.
86. **Xbox 360 conversions of big worlds took more than 15 minutes** in "Writing the final files": the
    LZX compressor is pure Python. Above 1 MiB the container is now written in LZX uncompressed blocks
    (seconds, and the game reads them); the real compressor is kept for small saves and never used
    above 16 MiB, the limit of its 24-bit block size.
87. **Worlds that are not worlds gave misleading errors or tracebacks.** A `level.dat` that was a Git
    LFS pointer read as "Java 1.13+ (DataVersion None)"; New Nintendo 3DS worlds, Bedrock folders
    without a LevelDB and Bedrock exports without terrain failed deep in the reader; `players` on an
    unknown format crashed. They now get a clear, translated message and exit code 1. Folders holding
    a single-file world (Classic `level.dat` / `.mine`, Indev `.mclevel`, `.mcworld`), one world among
    several subfolders, and console saves named `savegame.wii`, `GAMEDATA-N.bin` or by timestamp (Wii
    U) are recognised; a Java folder with only its `level.dat` (an output with no chunks) can be
    reopened.
88. **Bedrock item frames in a chunk without that sub chunk stopped the transfer** with a `KeyError`
    printed as raw bytes ("Entities / containers not fully transferred"). Such frames are skipped, and
    an error about a missing record names it.
89. **A command block whose last output held arrays stopped the transfer of every block entity and mob
    to Bedrock**: the output could not be converted, and the error ended the whole pass. The whole state
    of command blocks is now converted.

### Java, version by version (90–108)

90. **Java 1.13+ → the same or a newer Java lost book text, lore, leather dye and other item data**,
    on the default route too. The world was rebuilt through the converter's own model, which does not
    carry every item component. A 1.13+ source going to the same or a newer Java (1.18+, or without the
    ring) is now copied, and the game upgrades it itself, as it would the original.
91. **Items of 1.20.5+** (components): lore, dyed colour, written and writable books were neither
    written nor read; they are now. 1.21.5 data is written only under the DataVersion that has it.
92. **Java 1.21.5: names, enchantments and sign text in the old format** under the 1.21.5
    DataVersion: the game showed raw JSON and dropped the enchantments. Named chests showed
    `{"text": …}` on every version from 1.21.5, where block entity names are plain text.
93. **Mob equipment was never written to Java 1.13+**: armour, held items, saddles, horse armour,
    llama decor and villager professions (`Profession` / `Career` ↔ `VillagerData`, mapped as the
    game's own `VillagerProfessionFix` / `VillagerDataFix` do) now go through every route.
94. **Java 1.13 – 1.16 targets got every entity twice.** Before the entity split, the entities that
    WorldBridge converted were appended to the `Entities` list where Amulet had already put its own
    copies. They now replace them.
95. **`--move-to` lost entities and block entities** on the Java 1.13+ and Bedrock routes: they now
    move with their chunks.
96. **LZ4-compressed regions lost chests, signs and mobs** (`region-file-compression=lz4`, 1.20.5+).
    The game writes lz4-java's block stream (`LZ4Block` frames), not a bare LZ4 block, so decoding
    failed and the chunk read as empty. **Chunks over 1 MiB were dropped** instead of being written to
    `.mcc` files beside the region, as the game does.
97. **`--version 26.3` wrote 26.2, and `1.21` wrote 1.20.5**: a short version was not taken as its
    x.y.0 release. Short versions now mean x.y.0; releases WorldBridge does not list
    (1.21.11) are written as the nearest earlier one, with a note; unknown versions are refused.
98. **`--to java --version 1.20.4` with the default Java mode wrote 26.3** (the log said "26.3
    (latest)"): the mode chose the route before the version was looked at. The route is now resolved
    first: 1.13+ goes through Amulet to exactly that version, 1.12 and older to the numeric Anvil
    writer; conflicting options are refused, and the log says which route was taken.
99. **Orphan block entities in targets older than their block** (found in game: "Skipping BlockEntity"
    in 1.16.5 and 1.18.2). WorldBridge stores hanging signs, barrels, smokers and blast furnaces with
    the block entity of an older block (sign, chest, furnace), so they were written even where the
    block itself does not exist. They are dropped with the usual "left out" warning.
100. **Java 1.11 / 1.12 numeric worlds lost shulker boxes, illagers, vexes, llamas and parrots**
     (found in game). A chunk without a DataVersion is renamed by the game's fixer only for the ids it
     knew before 1.11, so newer mobs and block entities written with numeric-era names were unknown.
     They now carry their registry names (`minecraft:evocation_illager`, `minecraft:shulker_box`,
     `minecraft:bed`…), and the 1.11 species splits are written whole, so a zombie villager no longer
     gets a random profession.
101. **Attributes older games do not know** (`generic.armor`, `armorToughness`… logged by a 1.8
     server, found in game): every entity keeps only the attributes its target version registers.
102. **Entities stored in the chunk next to the one they stand in were dropped by Java 1.12+**
     ("Wrong location!", the Wandering Trader of a Bedrock world, found in game). Bedrock keeps a mob
     with the chunk it was loaded in, and lowering or moving a world shifts positions. Every Java and
     Bedrock writer now stores each entity in the chunk of its final position.
103. **Entities that shared a UUID in the source**: the game kept one of each pair and dropped the
     other. The duplicates get a new UUID.
104. **Java worlds converted from Bedrock carried the JPEG `world_icon` as `icon.png`** ("Must be 64
     pixels wide"): the icon is now written as a 64 × 64 PNG.
105. **Java 26.2+ has no bed block entity** (found in game). A 26.3 server's `block_entity_type`
     registry (`--reports`) lists 49 types and no `minecraft:bed`; the colour is in the block. Beds
     are not written for such a target any more (Amulet's own copies are removed too), are not counted
     as lost, and the colour is read from the block when the source has no block entity.
106. **Soul campfires, bee nests and spawners under ids no game registers**: the registry has
     `campfire`, `beehive` and `mob_spawner` only. They are written under those ids on every version.
107. **Java targets older than the source kept the newer content**: items in chests, mobs and the
     Bedrock host player's items stayed in a 1.20.4 or 1.18.0 world. They are removed and counted
     (Bedrock → 1.20.4: 185 items, 15 mobs, 153 block entities).
108. **Players beyond the host not linked to a Java account** (`--player`) were left out without a
     word: the count is now reported.

### Content tables (109–110)

109. **Names and ids by version**: 1.13 dye and stone-slab names, 1.13 – 1.15 zombie pigman eggs, Java
     1.9 – 1.12 spawn eggs (they were dropped), 1.11 mob ids (evokers, vindicators and illusioners
     vanished), `sweeping` / `sweeping_edge`, Bedrock ids that differ from Java's (`frame`,
     `wooden_door`, `empty_map`, `tropicalfish`, `thrown_trident`…), Bedrock 1.21 potions, the boats
     of 1.21.2+ and Bedrock boat variants; items inside Bedrock entities are written for the target
     version. Bedrock before 1.16.100 gets that era's item ids (`dye`, `bucket`, `boat` + Damage,
     `spawn_egg` + entity number, `record_*`, `horsearmor*`…) and is read back from them.
110. **Content too new for old games**: status effects limited to what each version registers (Java
     1.0 – 1.3: 1 – 19; 1.4 – 1.5: up to wither), map colours replaced by the nearest one the target
     has (old games crashed on an unknown colour id), the void biome offered on 1.9 – 1.12, tall grass
     and dead bush only from Beta 1.6, the inverted daylight detector as a daylight detector where
     there is no inverted one.

### Block entities (111–114)

111. **Block entities of Java 1.14+ and Bedrock reached the other edition with the source game's
     fields**: Java NBT under Bedrock ids and the reverse, so decorated pots lost their sherds,
     campfires their items, beehives their bees, lecterns their books. Decorated pots, campfires,
     beehives and bee nests, lecterns, chiseled bookshelves, suspicious sand and gravel, crafters,
     shelves, vaults, trial spawners and jigsaws are now converted field by field, and written only for
     the versions that have the block. Bedrock's shared ids (`Chest`, `Campfire`, `Beehive`) are told
     apart by the block, so trapped chests, soul campfires and bee nests stay what they were; the
     block states that depend on the block entity (a lectern's `has_book`, a bookshelf's slots) are
     set. Soul campfires, creaking hearts and copper golem statues were missing.
112. **Block entities WorldBridge did not know were dropped silently**: structure blocks, pistons
     (Bedrock has a `PistonArm` on every piston), lodestones, cauldrons with potions (Bedrock and PS4),
     test blocks. They are converted now, and any block entity still left out is listed by id in one
     warning.
113. **Loot tables** (`LootTable` / `LootTableSeed`) of chests, barrels, dispensers, hoppers and shulker
     boxes were lost between Java and Bedrock: unopened dungeon and village chests came out empty.
     They are carried both ways. Copper chests keep the id of their block in Java 1.21.9+.
114. **Ender chests of LCE TU69+ saves lost their block entity**: those saves spell the id
     `minecraft:ender_Chest`, which was not recognised.

### Bedrock and Java (115–120)

115. **Bedrock item frames became stone in Java** (PyMCTranslate maps the frame block, which Java does
     not have, to stone). Java dropped every frame, and the way back to Bedrock lost them all (2,364 on
     je2be's Bedrock → Java world). The block is air in Java, and frames are written in the palette of
     each Bedrock version (with the photo bit from 1.17.30, `{name, val}` palettes before 1.13,
     numeric before 1.2.13); those an old version cannot hold are reported.
116. **Items of Bedrock worlds before 1.13 got names Java does not know** (54,009 `planks`, `log`,
     `stonebrick`, `fence_gate`… in one world): the item's block was translated with the numeric-era
     Bedrock names. Before 1.13 the numeric id and Damage name the item, with the Java name.
117. **Pocket Edition 0.9 – 0.16 worlds lost every item and mob**: those versions save them by numeric
     id, which was not read.
118. **Java `stone_stairs` became cobblestone stairs in Bedrock** (Bedrock calls the cobblestone ones
     `stone_stairs`; the stone ones are `normal_stone_stairs`). **Block items carried a
     `block_data` state** on Bedrock 1.13+, which the game rejects: the item's Damage is now turned
     into the placed state, and a block with no state left has no `Block` compound.
119. **Mob details were lost between Bedrock and Java**: horse colour and markings, llama, parrot,
     axolotl, cat, rabbit, fox and mooshroom variants, saddles, horse armour and villager professions.
     They are written and read both ways.
120. **Spectator became Survival or Creative.** Bedrock Spectator (6) and "same as the world" became
     Survival in Java; Java Spectator (3) became Creative even in Bedrock 1.21.40+, which has it. It
     stays Spectator where the target has it.

### Bedrock → older Bedrock, level.dat and spawn (121–130)

121. **Entities were stored twice** going from Bedrock 1.18.30+ to 1.12 – 1.18.29 (offroaders: 108 →
     216): Amulet wrote a `0x32` list next to the source's `digp` / `actorprefix` records, which were
     also copied. `actorprefix` records that no chunk referenced stayed in 1.18.30+ outputs. Now there
     is one copy, in the format the target reads.
122. **Block entities, mobs, items and the player of a newer Bedrock were copied unchanged into older
     worlds**: blank signs, unknown flower pots, 1.21 items in a 1.12 world. They are rewritten for
     the target version, and what it cannot hold is dropped and counted ("Content that does not exist
     in …").
123. **Items an older Bedrock does not have**: a table of 1,014 items by release (1.11 → 26.30, from
     the game data of every release) drops and counts them; spawn eggs follow the mob table.
124. **Mobs an older Bedrock does not have** (parrot 1.2, fish and dolphins 1.4, turtle, phantom, cat,
     panda, pillager, fox, bee… camel husk, nautilus, sulfur cube) are removed and counted on every
     route. Villagers and zombie villagers become the pre-1.11 `villager` / `zombie_villager`, and
     trader llamas the pre-1.19.10 `llama`, instead of being dropped.
125. **Actors of chunks with a negative x were taken for orphans and removed**, and the depth move
     missed them. The database was scanned from `digp` up to the key `digp\xff`, which leaves out
     exactly the keys of chunks with a negative x (their first byte after the prefix is `0xff`). The
     scan now ends at `digq`.
126. **`--move-to` did not move the player** of a Bedrock → Bedrock conversion. **A player at x = −0.7
     was treated as outside the selection**: its chunk was computed with `int()`, which rounds toward
     zero (chunk 0), not `floor` (chunk −1).
127. **An explicit `--spawn` was replaced by the ground at the destination**, and with `--depth keep`
     it stayed at its source height while the world rose (LCE then clamped it to y 1).
128. **Chunks Bedrock had not finished were dropped** (villages, dungeons: 132 of 436 chunks and 133
     block entities of amulet_1_16_200). Chunks with `FinalizedState` < 2 are kept for Bedrock targets,
     where the game finishes them; other targets get a warning that says what they held.
129. **The level.dat of Bedrock targets disagreed with itself**: the number in the file header and
     `StorageVersion` follow the target (8 before 1.19.20, 9, 10 from 1.19.50), `NetworkVersion` is
     the target's protocol, and `InventoryVersion` is written.
130. **A Dedicated Server world with no spawn set** (`INT_MIN`) wrote that number to Java: it becomes
     the first player's position (or 0, 64, 0). A negative spawn y of a 1.18+ world was forced to 64;
     it is kept.

### Found in game on Bedrock Dedicated Servers (131–137)

131. **Signs of Java ≤ 1.19 and Console worlds were lost on Bedrock 1.18+** (an Xbox 360 TU75 world:
     6 signs → 0). PyMCTranslate could not translate the sign's block entity in those formats (JSON
     with a leading entry, or plain text) and left the block as `universal_minecraft:wall_sign`,
     which no game knows. The sign is normalised before the translation.
132. **Old numeric Nether portals (data 0 / 3)** stayed `portal[block_data=N]`: they get their x or z
     axis.
133. **Hanging signs, chiseled bookshelves, brushable and calibrated sculk blocks on Bedrock 1.19.x
     and older**: they start at 1.20.0 (1.19.50 – 1.19.80 have them only as an experiment). Older
     targets get the closest block (air, bookshelf), and the block entity is dropped and counted (8 →
     4 on 1.12 – 1.18 and 8 → 1 on 1.19.80 before the fix).
134. **Bedrock villagers carried invented component groups** (`+minecraft:villager_v2_adult`). They
     now get the groups of the vanilla `villager_v2.json` (adult or baby, profession, behaviour,
     schedule, biome skin), `Variant` and `MarkVariant`; the biome comes back to Java. The age groups
     of mooshrooms, rabbits, bees, goats, turtles, polar bears, piglins and others are the ones of the
     vanilla behaviour packs too.
135. **BDS 1.14 logged "Cannot find attribute" for every actor and player**: `minecraft:lava_movement`
     came with 1.16. Attributes the target lacks are no longer written, also for the actors kept raw.
136. **A numeric-Java record player with a record (data 1) stayed `jukebox[block_data=1]`**, a state
     Bedrock 1.14 – 1.18 reject while loading the chunk. It is `jukebox` for every Bedrock and has
     `has_record` in Java 1.13+.
137. **Map records carried `parentMapId: -1`**: Bedrock 1.17+ logged "Map item N has invalid
     parentMapId" at every load. It is no longer written.

### Heights: tall worlds into lower games (138–145)

138. **128-high targets cut floating islands and sky builds silently** (a bedwars map lost 10 of its 19
     signs and 907 blocks). The mountain compression lowered only columns with natural ground. Columns
     with blocks and no ground now join the rigid building pieces and come down whole with the ground
     near them, the band removed is preferably a run of air (caves, the void under an island) rather
     than rock, and whatever still cannot fit is cut and counted in one warning.
139. **The compression lost its state across worker processes**: the workers returned only part of
     what the first pass observed, and the second pass failed with a `KeyError`. The whole observed
     state is now merged.
140. **The Nether lost the top layer of its bedrock roof** on Alpha / Beta targets: the one-block
     sea-level raise (Java 62 → 63) applied to every dimension. It is for the Overworld only now;
     `--y-offset` still moves everything.
141. **Block entities and entities followed the old height, not their blocks**: with `--depth keep` or a
     compressed mountain, chests, signs, mobs and item frames under y 0 were dropped and the others
     stayed 64 blocks too low. They now end exactly where their blocks went, on every route, players
     included; those whose blocks were cut are counted.
142. **Flat or low worlds lost the whole Overworld by default** (superflat 1.18+ has its surface at
     y −61). The new default `--depth auto` samples the surface and keeps the underground when its
     median is under y 0, otherwise cuts as before; the log says which.
143. **The chunks emptied by the cut were reported as "unreadable (damaged or truncated)"**: they have
     their own message, which points to `--depth keep`.
144. **`--depth keep` sometimes left sections of "air" that were stone**: the cut took palette index 0
     for air, but Amulet builds the palette in a set's order, so index 0 can be any block. It also put
     the old games' ragged bedrock floor over the moved world (it overwrote the grass of flat worlds);
     a kept world gets no floor now.
145. **Numeric Java worlds with no Overworld** (only DIM-1 / DIM1) were not recognised.

### Legacy Console Edition (146–157)

146. **TU54+ targets wrote the old ids** (`Cow`, `EntityHorse` + `Type`, `Chest`). Every real save from
     Xbox 360 TU54 on (and PS3, PS4, Vita, Wii U) names entities and block entities the Java 1.11 way
     (`minecraft:zombie_pigman`, `minecraft:donkey`, `minecraft:chest`, `minecraft:ender_Chest` as the
     game spells it), with spawners in `SpawnData` / `SpawnPotentials`. TU31 / TU46 keep the old
     names.
147. **Console items were written by number**: every console save from TU31 / Wii U v112 on has them
     by name (`minecraft:egg`). Windows64 (neoLegacy) keeps the numbers, as it reads them.
148. **The End was cut to 18 × 18 chunks in every LCE target**, losing the outer islands of real saves
     (End cities, banners, chests, shulkers: 64 of 96 chunks of a PS3 save). 18 is the End of TU43 and
     older (`END_LEVEL_MAX_WIDTH` in the game's `ChunkSource.h`), but TU46+ saves have chunks at x −6..5,
     z −6..30. TU46 / TU54+ targets keep a 64 × 64 End, TU31 / neoLegacy 18 × 18, and LCE → LCE keeps
     every End chunk of the source.
149. **PS4 and Xbox One saves lost every mob, item and minecart**: those consoles keep entities in
     `entities.dat`, `DIM-1entities.dat` and `DIM1/entities.dat` (one `{Entities}` record per chunk),
     which were never read. They are read, and written the same way for those targets (checked
     against the game's `McRegionChunkStorage` and real saves).
150. **Mobs the target version does not have** (salmon, drowned… in TU54) were removed from LCE → LCE
     without a word; LCE items with no id in the target were dropped silently. Both are counted now.
151. **Chests of donkeys, mules and llamas were lost**, and a llama's carpet landed on the wrong slot.
     Each game numbers the slots differently (Java 2–16 before 1.20.5 and 0–14 after, Bedrock
     `ChestItems` 1–15, LCE 2–16); the chest, `ChestedHorse` / `Chested`, the `*_chested` definitions
     and the saddle and carpet slots now follow each one.
152. **Non-Sony targets wrote the host as `players/host.dat`**, a file no console loads, without a word:
     a warning now asks for `--player-id` (a XUID on Windows64 / Xbox, 32 hex digits on Wii U).
153. **The "chunks left out" warning** gave the Overworld's size for every dimension: it names the
     dimension and its own size (the Nether is smaller).
154. **A PS3 save made neoLegacy loop forever while loading** (found in game: an 8 GB log of `-- -1
     (0xffffffffffffffff) = -1`). `data/largeMapDataMappings.dat` was copied unchanged. The game reads
     it in `DirectoryLevelStorage::prepareLevel`: a count, then per player its id, a number n and n
     pairs (map key, map id), then a bit field of the map ids in use. The id is `sizeof(PlayerUID)`
     raw bytes: 8 on Windows64 and Xbox 360, 28 on PS3, Vita and PS4, 20 on Wii U. Read with the
     wrong size, the counts were garbage. The file is now parsed by source platform and rewritten for
     every target, with ids rebuilt from the target's player files; entries of players the target does
     not have are dropped with a warning, and the bit field is kept. Xbox One and Switch get an empty
     table, as their id size has never been seen in a real file.
155. **Converted worlds started on Peaceful in neoLegacy** (found in game: every hostile mob of Wii U,
     Vita and Indev worlds vanished, and the log said `Difficulty = 0` though `level.dat` said 1). The
     game reads its host options (difficulty, game type, world size, PvP, TNT, fire spread, structures,
     bonus chest) from a `4J_HOSTOPTIONS` text chunk of the thumbnail PNG (`GetGameHostOption`), not
     from `level.dat`, and WorldBridge's thumbnail had none, so every option was 0. The chunk is now
     written from `level.dat`, with the bit layout of the game's code and of real PS3 and PS4 chunks,
     for Windows64 (`thumbnails/thumbData.png`) and for PS3, PS4, Xbox One and Switch (`THUMB`). Wii U,
     Vita and Xbox 360 targets have no thumbnail PNG yet.
156. **Beds disappeared in neoLegacy** (found in game: 4 → 0 on a PS3 save): its
     `TileEntity::staticCtor` registers no bed. The Windows64 target writes only the 21 block entity
     ids the game registers.
157. **"Ignoring unknown attribute '4'" in neoLegacy's log** (found in game). Attribute 4 is attack
     damage, which only monsters, endermen and guardians register; the wolf of an Xbox 360 TU31 save
     carried it. The Windows64 target cuts each entity's attributes to the ones its class registers;
     console targets keep the source's.

Looked into at the same time, not bugs: on the Xbox 360 TU31 save the iron golem and a horse were
killed in game by a Wither next to the spawn, and primed TNT went off; on PS3, PS4 and Vita
saves the game despawned hostile mobs far from the player (Vita: 2,162 → 1,866 entities).

### Pocket Edition 0.x (158–162)

158. **pe-old → pe-old was not an identity**: the 16 × 16 map was centred on the spawn, so most chunks,
     all signs and the player could be lost. A PE 0.x source keeps its chunks where they are.
159. **Mobs and block entities PE 0.8 does not have** (wolves, squid, mob spawners…) were dropped
     silently: they are counted in the "does not exist in …" warning. The 1.11+ entity ids that the LCE
     hub gives (`minecraft:chicken`) are accepted next to the old ones.
160. **Sign text was JSON and `Health` a float** in the PE worlds that Java and LCE sources produced:
     plain lines of at most 15 characters and a short now, as in real saves. A `chunks.dat` record's
     length counts its own 4 bytes (82,180, as in real saves).
161. **PE 0.1 – 0.2 worlds**: the binary `level.dat` (storage version 1) and `player.dat` are read.
162. **The Nether reactor's block entity** was dropped from PE sources: it is kept.

### Interface and command line (163–173)

163. **A trim scan could finish after another world was opened**, and "Apply to the world" then removed
     the second world's chunks. Answers for a world that is no longer open are dropped, opening a world
     cancels the scan, and the trim and edit buttons stay off while a worker runs.
164. **Closing the window could abort the program**: focus-out started an analysis of the path while
     the window was closing. During a conversion, closing left Amulet's worker processes and
     `.worldbridge_*` folders behind: the window now cancels the conversion and waits for it to stop.
165. **A slower, older analysis overwrote a newer one**: answers carry a sequence number now.
166. **Painted biomes, Nether / End regeneration and "move" carried over to the next world**; unsaved
     world-management edits were discarded without asking (Save / Discard / Cancel now); a second save
     overwrote the `.wb-backup`, which now keeps the original.
167. **Map tab: switching world left a scan or a copy running on the previous one**, and late signals
     of the previous world's map overwrote the new one. Workers are cancelled on a switch (an edit in
     progress finishes first and keeps its world selected), nothing new starts while a map job or a
     conversion runs, and stale signals are ignored.
168. **A click selected chunks that did not exist**: an empty or still-loading dimension selected up to
     1,024 phantom chunks. Only present chunks are selected, and the CSV import says how many it left
     out. Cancelling the trimmed copy removes the partial folder.
169. **Select-all and the heat map repainted slowly** (the selection was grouped by region for every
     tile: quadratic), and a rubber band over a dimension still loading froze the program.
170. **Malformed options were a traceback after the world was read** (`--platform`, `--offset`,
     `--spawn`, `--depth`, `--chunks`…). They are checked first, with a message; negative coordinates
     work without `=` (`--spawn -20,-59,-20`); an empty or invalid `--chunks` file is an error, not an
     empty world.
171. **An output folder inside the source world** copied the world into itself until the path was too
     long: it is refused, as is the reverse.
172. **Progress stopped short of 100 %**, the copy routes showed no progress and could not be
     cancelled; Ctrl+C and SIGTERM now end cleanly and remove an empty output folder the run created.
     `info` looks inside archives; `trim` uses the world folder when given `level.dat`, lists the
     Overworld first and speaks the chosen language.
173. **Two conversions at once in one process** (the GUI's preview and a conversion) could mix their
     results: `parallel.ordered_map` kept the function and state of the last caller in a global. Each
     call has its own now.

The tests of these fixes are listed by area in [VERIFICATION.md](VERIFICATION.md#automated-tests).

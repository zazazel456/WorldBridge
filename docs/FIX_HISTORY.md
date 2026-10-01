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
- [0.2.1 (65–77)](#021)

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

Looked into at the same time: the empty chunks inside the explored area of that Bedrock world are not
in its database at all (read file by file, the write-ahead log included), and the world was never
trimmed: the game left them out of its files, and generates a missing chunk again from the seed. The
map and the converter cannot show or carry chunks that are not in the files (see the user guide).

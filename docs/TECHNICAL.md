# How WorldBridge works

This document describes WorldBridge's design: the conversion pipeline, the file formats it reads and
writes, how content is translated, and how heights, borders and speed are handled. The figures that
back each part are in [VERIFICATION.md](VERIFICATION.md).

## Contents

- [Pipeline](#pipeline)
- [Routes](#routes)
- [Formats](#formats)
- [Content translation](#content-translation)
- [What each target can load](#what-each-target-can-load)
- [Heights](#heights)
- [Borders](#borders)
- [Better than Adventure](#better-than-adventure)
- [Tools around the conversion](#tools-around-the-conversion)
- [Parallelism](#parallelism)
- [Runtime and interface](#runtime-and-interface)
- [Code layout](#code-layout)

## Pipeline

Every conversion goes through the same steps (`worldbridge/convert.py`):

1. **Detect** the format at the given path: a folder, a save file, `level.dat`, `.mcworld` or
   `.zip` (`detect.py`). Sources are read from a copy, so the original is never locked or modified.
2. **Choose the route** for the pair of source and target (below).
3. **Select:** chunks, spawn and players chosen in the map and players tabs (`selection.py`), plus
   unfinished chunks left out (`incomplete.py`).
4. **Read** the source into the route's intermediate form.
5. **Fit** the world to the target: underground depth, tall terrain, sea level, relocation, biome
   painting.
6. **Write** the target format, translating blocks, block entities, items, entities, players and
   `level.dat`.
7. **Close the border:** game blending, the ring or the fill (`terrain/policy.py`).
8. **Report:** replaced blocks, removed items and entities, excluded chunks, and the border remedy
   that was used.

## Routes

WorldBridge has two intermediate forms:

- **The numeric hub** (`model.py`): Java 1.12.2 conventions, with numeric block ids plus a 4-bit data
  value, namespaced entity and block entity names, and items with string ids and `Damage`. Every
  numeric format reads into it and writes from it: LCE, Java Alpha to 1.12, Pocket Edition 0.x,
  Classic and Indev. Blocks newer than 1.12 that LCE Aquatic saves store are kept aside as 1.13+
  block states and re-applied when the target supports them.
- **Amulet's universal chunks**, for Java 1.13+ and Bedrock. Amulet Core / PyMCTranslate translate
  block states between every Java and Bedrock version. Everything else (level data, players, block
  entity contents, entities, maps) is written by WorldBridge itself, because Amulet alone would lose
  it (`amulet_bridge.py`, `java/modern.py`, `bedrock/extra.py`).

**Java targets:**

| Mode | Route |
|---|---|
| `auto` (default) | Numeric sources become a classic Anvil world that Minecraft upgrades on first load with its own DataFixer, the most faithful way (villagers, potions, books all go through Mojang's code). Aquatic LCE saves and Java 1.13+ / Bedrock sources are converted explicitly to the latest version. |
| `dfu` | The DataFixer route, for any version from 1.9 on |
| `amulet` | Pre-converted to an exact version, 1.13 to 26.x |
| `numeric` | Anvil 1.2 – 1.12, limited to that version's blocks |
| `mcregion` | Beta 1.3 – 1.1 |
| `alpha` | Infdev, Alpha, Beta 1.0 – 1.2_02 |

A pre-1.18 Java or Bedrock world converted to the same edition at 1.18+ is copied untouched, so that
the game upgrades and blends it itself.

## Formats

### Legacy Console Edition

Implemented from the 4J source (`Minecraft.World`):

- **Container** `ConsoleSaveFileOriginal` (`saveData.ms`, `savegame.dat`, `GAMEDATA`): a UTF-16
  file table, save versions 1–11, big endian on Xbox 360 / PS3 / Wii U and little endian on Windows64
  / Vita / PS4 / Xbox One / Switch.
- **Compression per platform:** zlib (Windows64, Wii U, PS4, Xbox One, Switch, Vita chunks), raw
  deflate with a size header (PS3, EdgeZLib), XMemCompress LZX (Xbox 360), Vita's zero run-length
  encoding for the whole container, and 4J's RLE on every region chunk.
- **Split saves** (PS4, Xbox One): region files outside the container, in `GAMEDATA_DDDDXXZZ` files
  of 16 × 16-chunk regions.
- **Chunk formats:** NBT (TU0–TU13); 4J's compressed storage, versions 8–11
  (`CompressedTileStorage`, `SparseLightStorage`, `SparseDataStorage`, two 128-high halves), tested
  against a literal port of the C++; and Aquatic versions 12 and 13 (paletted 16 × 16 sections,
  16-bit block values with a waterlogged bit), read only. Writing uses NBT or compressed V8 / V9,
  which every version of the game loads.
- **Xbox 360 packages:** STFS (CON / LIVE / PIRS) read, to extract `savegame.dat`, the world's name
  and its thumbnail (`lce/stfs.py`, written from the Free60 description of the format).
- **Players:** `players/<XUID>.dat` on Windows64 and Xbox; Sony's `P_<hex>_<digits>_<name>.dat` on
  PS3, Vita and PS4.
- **neoLegacy regions:** 32 × 32 chunks, or 16 × 16 when the `region_format_16` marker is present.
- **World sizes:** Classic (54 × 54 chunks), Small (64), Medium (192), Large (320), with the Nether
  scale of each. Xbox 360, PS3 and Vita know only Classic.
- **Profiles:** Windows64 is neoLegacy TU31 (1.8 blocks); consoles have TU31 (1.8), TU46 (1.9) and
  TU54+ (1.12). LCE → LCE keeps terrain flags, height maps, ticks, `level.dat`, `data/` and player
  files byte for byte.

### Java Edition

- **Classic** (rd-132211 … 0.30): raw gzip before 0.0.13, then versions 1 and 2 of `level.dat` /
  `.mine`, the latter a Java-serialised `com.mojang.minecraft.level.Level` read by a minimal Java
  deserialiser (`java/classic.py`).
- **Indev** `.mclevel`: a finite block volume split into chunks (`java/finite.py`).
- **Alpha** (`c.X.Z.dat` in base-36 folders), **McRegion** (`.mcr`) and **numeric Anvil** (`.mca`
  with Sections) (`java/numeric.py`).
- **Anvil 1.13 → 26.x**, including every palette form of 26.x and the 26.1+ layout (`dimensions/`,
  `players/data`, `data/minecraft/world_gen_settings.dat`). Items with 1.20.5+ components,
  two-sided signs, 1.21.9+ spawn data.
- Chunk listing reads only the 4 KiB region headers, so listing a large world does not read
  gigabytes.

### Bedrock and Pocket Edition

- **Bedrock** 1.1 → 26.50 (LevelDB; `.mcworld` too). Block entities (tag `0x31`), entities (tag
  `0x32` before 1.18.30, `digp` / `actorprefix` records after), `~local_player` and
  `player_server_*` are written natively. Height maps are computed from the blocks (Amulet leaves
  them at 0, which breaks lighting, spawning and blending). Item frames become frame blocks with
  their contents, maps included.
- **Pocket Edition 0.1 – 0.8**: `chunks.dat` (a 32 × 32 sector index, YZX arrays, 16 × 16 chunks
  used), `level.dat` with its 8-byte header, and `entities.dat`.

## Content translation

- **Blocks.** Numeric ids with data, 1.13+ block states and Bedrock states. A block the target lacks
  becomes the closest block it has, through a chain (for example glazed terracotta → coloured
  terracotta → wool of the same colour; mud and roots → dirt; moss → grass; tuff → andesite; calcite
  → diorite; bamboo → fence), never air.
- **Block entities** (`tiles.py`): chests and every container, signs (colours and formatting
  flattened where needed), spawners, beds, banners, heads, jukeboxes, flower pots, note blocks,
  shulker boxes, lecterns, through one canonical form. Chests missing their block entity get an empty
  one, because LCE draws chests through it.
- **Items** (`items.py`): legacy numeric stacks, Java 1.13+ stacks and 1.20.5+ components, Bedrock
  stacks, with enchantments, names, lore, books, potions, dyes and maps.
- **Entities** (`entities.py`): mobs, dropped items, paintings, item frames, minecarts, boats, armour
  stands, with position, rotation, health, name, baby, colour, saddle, owner and inventory. LCE's
  string UUIDs and numeric attribute ids are rewritten as Java expects them, otherwise Minecraft
  discards the chunk. Paintings and frames are converted between the Java 1.8+ layout (the block in
  front of the wall) and the Java ≤ 1.7 / LCE layout (the wall block).
- **Players:** position, inventory, armour, ender chest, experience, health, hunger, game mode,
  abilities; linked to Java UUIDs (premium or offline), LCE XUIDs or the Bedrock local player.
- **Maps:** Java / LCE `map_<n>.dat` palettes ↔ Bedrock `map_<uuid>` RGBA records (`maps.py`).
- **Biomes:** ids preserved 1:1. LCE's value 255 ("not computed yet") stays 255 for LCE and numeric
  Java, which recompute it from the seed, and is filled from the nearest real biome for Amulet
  targets. Amulet Core 1.9 mirrored Java 1.2–1.14 biomes on the x = z diagonal; WorldBridge patches
  its coders at start-up.
- **Light:** computed from the blocks for targets that trust stored light.

## What each target can load

Older games do not skip what they do not know, so WorldBridge writes only what the target has:

- **Java Alpha – 1.8** (`java/oldcontent.py`). Their NBT reader knows tag types 1–10 only (one
  `TAG_Int_Array` makes `level.dat` unreadable and the world slot empty) and reads each field with a
  fixed type (`Health` as a short). Player and `level.dat` are rebuilt from per-version field lists
  with exact types; items, mobs and block entities newer than the version are removed or mapped back
  (chest minecarts → `Minecart` with `Type`). Tests read the output with a reader that follows
  Alpha / Beta's rules.
- **LCE** (`lce/compat.py`). Each target has its own item, enchantment and entity ids. neoLegacy's
  come from its source: the items of 1.8 plus beetroots and records, banners under 176 instead of
  425, Luck of the Sea and Lure at 65 and 64, Mending kept, Sweeping Edge and curses absent, 63
  entity types (no parrots). Spectral and tipped arrows become arrows, splash and lingering potions
  the classic splash potion, wooden boats the boat; items without an equivalent are removed and
  counted. The player file is rebuilt with the keys and tag types neoLegacy writes (`HealF` float
  plus `Health` short, the name as `UUID`), armour from 1.20.5+ `equipment` back in slots 100–103,
  and a player without a position placed at the spawn.
- **Chests on LCE and Java ≤ 1.12** (`chestfix.py`). These games pair a chest with any chest of the
  same kind beside it and draw a double chest only from one half, so rows of modern double chests
  would be half invisible. Groups are re-paired on a lattice along the double chest's axis, and pairs
  alternate chest and trapped chest (which never join), so every chest touches at most its partner
  and keeps its contents.

## Heights

- **Unfinished chunks.** Java 1.14+ keeps planned or bare-stone proto chunks at the edge of the
  explored area, and Bedrock marks them with `FinalizedState` < 2. They are left out, so the game or
  the ring generates them properly instead of leaving stone blocks and holes.
- **Sea level.** Alpha 1.2 – Beta 1.7.3 and PE 0.x have the sea at y 63, every later game at y 62.
  The converted world moves one block in the right direction, with players and spawn.
- **Underground of 1.18+ worlds** (`depthfit.py`), for targets that start at y 0: `cut` below y 0,
  `keep` everything (the world rises by 64), or keep from a chosen negative y. Worlds cut at y 0 get
  the old games' bedrock floor where the terrain is natural.
- **Tall terrain** (`heightfit.py`), for 128-block targets and for what no longer fits under y 256
  after `keep`:
  - nothing moves below a *knee* (y 80 for the tallest worlds, higher when the mountains are only a
    little too tall);
  - above it, each column loses a band of rock just under its surface, thicker for higher ground, so
    grass, snow, trees and buildings come down whole and peaks end about 10 blocks under the
    ceiling;
  - the band is smoothed between neighbouring columns and chunks;
  - a building comes down as one rigid piece with the ground under it, and every tree follows its
    trunk;
  - if the band would cross built blocks (bases dug into a mountain, mines), it is taken lower;
  - chests, mobs, the player and the spawn follow their column. `cut` restores the plain cut at
    y 127.

## Borders

See [SEAMLESS_BORDERS.md](SEAMLESS_BORDERS.md). In short:

- Java and Bedrock 1.18+: the chunks of a pre-1.18 world are written in a pre-1.18 format (Java
  1.17 or the classic Anvil of the DataFixer route, Bedrock 1.17.40). When the game upgrades them it
  marks them for blending, blends heights and biomes with new terrain and generates the depth below
  y 0.
- Java Alpha 1.2 – 1.17 and neoLegacy: a ring of the game's own terrain, from each version's exact
  generator, lifted to meet the converted world. The Nether and End get a 3D ring.
- Small finite worlds (PE 0.x, LCE 54 / 64 chunks): every chunk of the map is written.

## Better than Adventure

`worldbridge/bta/` reads BTA 8.0.1 saves directly (also the older ones with `region/*.mcr`), with
their own NBT dialect, region layout and chunk versions, and writes them as a 1.18.2-format world
(DataVersion 2975). Minecraft 26.3 upgrades it on first load with
its own DataFixer, which also marks every converted chunk for blending. Only this direction exists.

- Every one of the 455 BTA blocks is listed explicitly; metadata layouts come from BTA's block
  classes. Every state is validated against 26.3's registry, and only entity types that exist in
  1.17 are written.
- Neighbour-dependent shapes (stairs, fences, panes, redstone, leaves, double chests, BTA's legacy
  chests) are recomputed with 26.3's rules; neighbouring chunks are read-only.
- Height: "extended" BTA worlds have the sea at y 128, vanilla ones at y 63. The Overworld is lowered
  so the seas match (65 blocks for extended, 1 for classic types); BTA's underground goes below y 0,
  down to −64. The Nether keeps its heights.
- Nothing is lost: items that do not fit the vanilla block (the 4th slot of a blast furnace, quiver
  arrows beyond 64, flag dyes) become dropped items that never despawn.
- A report `worldbridge-bta-report.txt` stays in the converted world.

The full block table is in [BTA_BLOCK_MAPPING.md](BTA_BLOCK_MAPPING.md).

## Tools around the conversion

- **Map** (`mapview.py`): the top block of every column, shaded by the height difference with its
  northern neighbour and darkened by water depth. Numeric worlds are read through the hub reader,
  Java 1.13+ region files and Bedrock sub-chunks are parsed directly; Java 1.13+ reads only the top
  sections. Tiles load in rings around the view.
- **Selections** (`selection.py`): MCA Selector's CSV format (`regionX;regionZ;chunkX;chunkZ`, or
  `regionX;regionZ` for a whole region).
- **Relocation** (`relocate.py`): the centre of the selection moves to the chosen point (the
  Nether's point is the Overworld's divided by 8), by whole chunks, with entities, block entities and
  scheduled ticks, on the hub route and on Amulet's universal chunks.
- **In-place edits** (`chunkedit.py`): remove chunks, keep only some, paint a biome, on Java (raw
  region rewrite), LCE (biome bytes patched in the payload) and Bedrock (through Amulet), after
  copying every changed file to `<world>.wb-backup-<date>/`.
- **Trim** (`trim.py`): scans `InhabitedTime`, keeps used chunks plus a protective ring, the spawn
  area, force-loaded chunks and unreadable ones; a trimmed copy keeps chunks byte for byte and cleans
  `entities/` and `poi/`.
- **World editor** (`manage.py`): every NBT document of a world (Java, Bedrock, PE, LCE, BTA),
  saved back in its own format (compression, endianness, headers) after a `*.wb-backup` copy.

## Parallelism

`parallel.py` spreads the heavy steps over every core: reading, transforming and writing chunks, the
ring (Nether and End included), Amulet's translation (split by region file), the Bedrock height maps
and the map preview. The work is pure Python and numpy, so it goes to worker processes (`fork`) that
inherit the state they need; only the items and the results travel between processes. `ordered_map`
yields the results in the items' order, exactly as the plain loop would, so **the output does not
depend on the number of cores**. `WORLDBRIDGE_WORKERS=N` sets the number of processes.

- **Bedrock.** A LevelDB can be opened by one process only: into Bedrock, each Amulet worker writes
  a LevelDB of its own and the parts are merged (their chunks are disjoint); from Bedrock, each worker
  reads a copy of its own whose table files are hard links. Workers that open a LevelDB start from the
  fork server (`process_context`): a forked copy of a process that had used LevelDB would wait forever
  for LevelDB's background thread, which a fork does not copy. Elsewhere, Bedrock sources are read in
  the main process.
- **Big worlds.** Chunks are converted region by region, so every source region is read once and
  every written region finished before the next. The Java chunk index keeps one entry per region file
  (a 1024-bit mask), the biome filler reads its neighbours back from the hub writer, and the Bedrock
  height maps are fixed one column of chunks at a time: memory stays flat as the world grows. Finite
  maps (LCE, PE 0.x) read only the chunks that reach them, with an 18-chunk margin for the ring;
  from Java 1.13+ and Bedrock only that area goes through Amulet.

## Runtime and interface

- **Self-contained runtime** (`run.sh`, `_bootstrap.py`): a portable Python, pinned dependencies as
  prebuilt wheels only, everything inside `.runtime/`. The three Amulet packages that PyPI ships as
  source are prebuilt with Zig for manylinux2014 (`tools/build_wheels.py`). Unused Qt modules are
  pruned (`tools/prune_qt.py`), keeping the Qt Quick / QML libraries Breeze links.
- **Desktop theme** (`gui/theme.py`). Qt reads Plasma's `kdeglobals` for colours, fonts and icons.
  The widget style (Breeze, Kvantum…) is a plugin of the system's Qt, while WorldBridge runs on
  PySide6's Qt:
  - the plugin is accepted only if its metadata declares the same major version and a minor version
    not newer than PySide6's;
  - PySide6's own Qt libraries needed by the plugin are preloaded, following the plugin's ELF
    `DT_NEEDED` closure, so it never pulls the system's copies;
  - the style is tried first in a separate process that builds the whole main window, and the answer
    is cached;
  - if anything fails, Fusion with the desktop's palette is used.
- **Languages** (`i18n.py`, `i18n_it.py`). Every message is written in English and passed through
  `tr()`, with named placeholders; `i18n_it.py` holds the Italian texts. The interface's **EN | IT**
  switch rebuilds the window in the other language and carries over the world and every choice
  (conversion settings, map selection, spawn, biomes, players). The language comes from the switch,
  `--lang`, `WORLDBRIDGE_LANG` or the system locale; worker processes inherit it. Qt's own dialog
  texts come from Qt's translations.
- **Interface layout** (`gui/`), after the KDE Human Interface Guidelines: the source is chosen once,
  each page shows only the options that apply, long help behind ⓘ buttons, inline messages instead
  of dialogs, palette colours only, the primary action at the bottom right, window state remembered.

## Code layout

```
worldbridge/
  convert.py       pipeline and routes            cli.py        command line
  detect.py        format detection               model.py      the numeric hub
  amulet_bridge.py Amulet Core / PyMCTranslate    blocks.py, ids.py   block registries and fallbacks
  items.py, entities.py, tiles.py, maps.py        content translation
  depthfit.py, heightfit.py, incomplete.py        heights and unfinished chunks
  chestfix.py      chest pairing for LCE / old Java
  relocate.py, selection.py, chunkedit.py, trim.py, manage.py, mapview.py, biomes.py
  parallel.py      multi-core, ordered results
  i18n.py          tr() and the language; i18n_it.py: the Italian texts
  lce/             container, compression, region, chunk, world, compat, stfs; vendor/ (LZX)
  java/            classic, finite (Indev), numeric (Alpha, McRegion, Anvil), modern, oldcontent, region
  bedrock/         extra (LevelDB records), terrain (height maps, frames), pe_old (PE 0.x)
  bta/             Better than Adventure → Java 26.3
  terrain/         generators, ring, 3D ring, fill, border policy
  gui/             app, map, players, world management, trim, theme, widgets
tools/             matrix.py, seamcheck.py, bta_compare.py, build_wheels.py, fetch_syslibs.py, prune_qt.py
tests/             pytest suite
```

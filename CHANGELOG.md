# Changelog

## Unreleased – review against real worlds (alpha)

A full review of the code with 110 real worlds downloaded from the web (Java Classic → 26.3, Bedrock
1.1 → 1.26.40, PE 0.x, LCE on PS3 / PS4 / Vita / Wii U / Xbox 360). Fixed so far:

**Java, by version**
- **Java 1.13+ → the same or a newer Java lost book text, lore, leather dye** and other item data,
  on the default route too: the world is now copied and upgraded by the game itself (1.18+ targets,
  or without the ring).
- **1.20.5+ items**: lore, dyed colour, written and writable books are written and read.
- **Java 1.21.5**: names, enchantments and sign text were written in the old format under the
  1.21.5 DataVersion (shown as raw JSON, enchantments invalid); named chests showed `{"text": …}`
  on every version from 1.21.5.
- **Mob equipment was never written to Java 1.13+**: armour, held items, saddles, horse armour,
  llama decor and villager professions now go through every route (Java of every era, LCE, Bedrock).
- **Java 1.13 – 1.16 targets got every entity twice**; `--move-to` lost the entities and block
  entities on the Java 1.13+ and Bedrock routes.
- **LZ4-compressed regions** (`region-file-compression=lz4`, 1.20.5+) lost chests, signs and mobs;
  chunks over 1 MiB were dropped instead of written to `.mcc` files.
- **`--version 26.3` wrote 26.2** (and `1.21` wrote 1.20.5): short versions now mean x.y.0;
  releases WorldBridge does not list (1.21.11) are written as the nearest earlier one with a note,
  unknown versions are refused with a clear message.

**Legacy Console Edition**
- **Real Xbox 360 saves were not recognised** (`savegame.dat` starts with `[BE u32 size][BE u64
  decompressed size]`, not with a zero): they are read, loose, in a CON package, in a `Save<date>.bin`
  folder or as `savegame-*.dat`; saves of version 1 (`players_<XUID>.dat`) show their player. New
  Xbox 360 saves are written with the same header.
- **Xbox 360 conversions of big worlds took more than 15 minutes** in "Writing the final files":
  above 1 MiB the container is stored in LZX uncompressed blocks (seconds), the real compressor is
  kept for small ones.
- **The End was cut to 18 × 18 chunks in every LCE target**, losing the outer islands of real saves
  (End cities, banners, chests, shulkers: 64 of 96 chunks of a PS3 save). The End is 18 × 18 up to TU43
  and TU46+ saves have chunks at x −6..5, z −6..30: TU46 / TU54+ targets keep a 64 × 64 End (chunks −32..31,
  the four `DIM1` region files), TU31 / neoLegacy 18 × 18, and an LCE → LCE conversion keeps every End
  chunk of the source.
- **Ender chests of TU69+ saves** (block entity id `minecraft:ender_Chest`) lost their block entity in
  every conversion that rewrites the chunks (LCE → LCE, numeric Java).
- **Mobs the target version does not have (salmon, drowned … in TU54) were removed without a word** from
  the LCE → LCE conversion: they are now listed in the "does not have … removed" warning.
- **PS4 and Xbox One saves lost every mob, item and minecart**: the game keeps their entities in
  `entities.dat`, `DIM-1entities.dat` and `DIM1/entities.dat` (one `{Entities}` record per chunk), which were
  never read. They are read now, and written the same way for the PS4 and Xbox One targets.
- **LCE targets that are not Sony consoles wrote the host as `players/host.dat`** without a word, and no
  console loads it: a warning now asks for `--player-id` (a XUID on Windows64 / Xbox, 32 hex digits on Wii U).

**Pocket Edition 0.x**
- **pe-old → pe-old was not an identity**: the 16 × 16 map was centred on the spawn, so most chunks, all signs
  and the player could be lost. A PE 0.x source now keeps its chunks where they are.
- **Mobs and block entities PE 0.8 does not have (wolves, squid, mob spawners …) were dropped silently**: they
  are counted in the "does not exist in …" warning, and the entity ids of 1.11+ (`minecraft:chicken`, as the
  LCE hub gives them) are accepted next to the old ones.
- **Sign text was JSON and `Health` a float** in what Java and LCE worlds wrote: plain lines of at most 15
  characters and a short now, as in real saves; `chunks.dat` records have the length of real saves (82180).
- **PE 0.1 – 0.2 worlds**: the binary `level.dat` (storage version 1) and `player.dat` are read.

**Java targets**: players beyond the host that are not linked to a Java account (`--player`) are not written;
the count is now reported.

**Caves & Cliffs worlds into games that start at y 0 (Java ≤ 1.17, LCE, Bedrock ≤ 1.17, older)**
- **Block entities and entities followed the old height, not their blocks**: with `--depth keep`
  (or a compressed mountain) chests, signs, mobs and item frames under y 0 were dropped and the
  others stayed 64 blocks too low; they now end exactly where their blocks went, on every route
  (also Java ↔ Bedrock and Bedrock → Bedrock, players included). Those whose blocks were cut are
  counted and reported.
- **Flat or low worlds lost the whole Overworld by default** (superflat 1.18+ has its surface at
  y -61): the new default `--depth auto` looks at the surface of a sample of chunks and keeps the
  underground when its median is under y 0, otherwise cuts as before; the log says which.
- The chunks emptied by the cut were reported as "unreadable (damaged or truncated)": they have their
  own message now, which points to `--depth keep`.
- Numeric Java worlds with no Overworld (only DIM-1 / DIM1) are recognised again.
- `--depth keep` put the old games' ragged bedrock floor over the moved world (it overwrote the grass
  of flat worlds), and the air of a chunk was taken to be palette index 0, which depends on the order
  of the chunk's blocks: the cut sometimes left sections of "air" that were stone.

**Content tables**
- 1.13 dye and stone-slab names, 1.13 – 1.15 zombie pigman eggs, Java 1.9 – 1.12 spawn eggs (were
  dropped), 1.11 mob ids (evokers, vindicators, illusioners vanished), `sweeping` /
  `sweeping_edge` by version, Bedrock ids that differ (`frame`, `wooden_door`, `empty_map`,
  `tropicalfish`, `thrown_trident`…), Bedrock 1.21 potions, 1.21.2+ boats and Bedrock boat
  variants, items inside Bedrock entities written for the target version.
- Status effects too new for Java 1.0 – 1.5 players, map colours too new for the target version
  (crash in old games), the void biome on 1.9 – 1.12, tall grass and dead bush from Beta 1.6, the
  inverted daylight detector, old Bedrock bucket / boat / horse armour items.

**Block entities of Java 1.14+ / Bedrock**
- Decorated pots, campfires, beehives and bee nests, lecterns, chiseled bookshelves, suspicious
  sand / gravel, crafters, shelves, vaults, trial spawners and jigsaws reached the other edition
  with the source game's fields (Java NBT under Bedrock ids and the reverse): sherds, items, bees,
  books and slots are now converted, and only for the versions that have each block entity.
- Soul campfires, creaking hearts and copper golem statues were missing; trapped chests, soul
  campfires and bee nests read from Bedrock became chests, campfires and beehives.
- Ender chests of LCE TU69+ saves (`minecraft:ender_Chest`) lost their block entity.

**Interface**
- A trim scan of a world could finish after another world was opened and "Apply to the world"
  then removed the second world's chunks; the trim button stays off while a scan runs.
- Closing the window could abort the program (an analysis started on focus-out), and during a
  conversion it left Amulet's worker processes and `.worldbridge_*` folders behind: the window now
  waits for the cancel. A slower, older analysis no longer overwrites a newer one.
- Painted biomes, Nether / End regeneration and "move" no longer carry over to the next world;
  unsaved world-management edits ask before being discarded; the `.wb-backup` keeps the original.
- Map: select-all and the heat map repaint in a fraction of the time, and a rubber band over a
  dimension still loading no longer freezes the program. The error banner is shortened.

**Command line**
- Malformed options (`--platform`, `--offset`, `--spawn`, `--move-to`, `--depth`, `--chunks`,
  `--biome`, `--size`, `--profile`, `--java-limit`, `--bta-palette`, `--min-time`) are refused
  before the world is read, with a message instead of a traceback; negative coordinates work
  without `=` (`--spawn -20,-59,-20`). An empty or invalid `--chunks` file is an error, not an
  empty world.
- An output folder inside the source world (or the other way round) is refused; it used to copy
  the world into itself until the path was too long.
- Progress reaches 100%, the copy routes show progress and can be cancelled; Ctrl+C and SIGTERM
  end cleanly and remove an empty output folder the run created.
- `info` looks inside archives; `trim` uses the world folder when given `level.dat`, lists the
  Overworld first and speaks the chosen language; LCE "outside the limits" counts per dimension.
- Running two conversions at once in one process (the GUI's preview and a conversion) could mix
  their results (`parallel.ordered_map`).

**Tools**
- `tools/matrix.py`: the probe read only numeric item ids and failed every route since 0.2.1.

## 0.2.1 – bug fix (alpha)

Items lost or changed in the players' inventories on the way to Java (found in game: Bedrock 26.50 →
Java 26.3, the cooked mutton gone from the inventory but not from the furnace). Details in
[fixes 65–69](docs/FIX_HISTORY.md#021).

- **Bedrock → Java: every item newer than Java 1.12 was lost from the player** (netherite, tridents,
  crossbows, copper, deepslate, spyglasses, maces, honey, cherry wood…), and the off hand was never
  carried over. The Bedrock player now becomes a Java player that keeps every item by name.
- **Items added in Java 1.8 – 1.12 became air on the way to Java 1.9+** (mutton, cooked mutton,
  banners, doors, shields, elytra, totems, prismarine, slime blocks, red sandstone, concrete…): they
  were written with numeric ids that Minecraft's own upgrade does not know. Players, chests, furnaces,
  dropped items and mob equipment now carry the item names.
- **Java 1.13+ → latest Java: some items of the player changed into others** (melons into melon
  slices, stone slabs into smooth stone slabs, weathered cut copper into oxidized cut copper, purple
  shulker boxes into plain ones): the game upgraded the player again as if it came from 1.12. The
  source's own level.dat is kept, so the game upgrades the world exactly as it would the original.
- **Item names written for the wrong version**: short grass, turtle scutes, iron chains and dirt paths
  in chests reaching the latest Java with names the game no longer reads; the 1.12 stone slab named
  as the plain stone slab of 1.14+; block items saved by recent Bedrock versions (the plain stone slab
  `normal_stone_slab`…) read with the tables of Bedrock 1.21.0 and lost.

World management and the settings of a world between versions ([fixes 70–75](docs/FIX_HISTORY.md#021)):

- **World management: the inventory of a native Bedrock player looked empty.** Bedrock saves every
  slot, the empty ones too, and the table listed them all in slot order. The items are now listed
  by place (hotbar, inventory, armour, off hand, ender chest), with the empty slots on request. The
  Bedrock ender chest is shown, a player edited in Bedrock keeps the raw bytes the game stores in some
  strings, and a world open in Minecraft (database locked) says so instead of showing no players.
- **World management follows the world's version:** the single player stored in a Java or Pocket
  Edition 0.x level.dat (26.1+: in players/data) is listed; Java 1.21.5+ armour and off hand
  (`equipment`), Java 1.21.11 game rules (`game_rules`), Bedrock number rules; game modes and settings
  only as the version has them (no Spectator in Bedrock, LCE and before Java 1.8; no difficulty before
  1.8, no `DayTime` before 1.3…).
- **Java 1.21.5+ armour and off hand lost on the way to Bedrock and to older Java**; Bedrock's off
  hand never written.
- **Game modes between editions:** Bedrock Spectator and "same as the world" became Survival in Java;
  Java Spectator became Creative even in Bedrock 1.21.40+, which has it.
- **World settings of Java 1.21.11+ / 26.x lost** on the way to Bedrock, LCE and older Java
  (difficulty, hardcore, weather, game rules); a Peaceful world became Normal between Java and
  Bedrock; the game rules both editions have (keepInventory…) now go across.
- **Java 26.x → 26.x: the single player started anew** (0.2.1's own fix 67): it stays in
  players/data, where Java 26.1+ reads it.

Biomes and map colours of the latest versions ([fixes 76–77](docs/FIX_HISTORY.md#021)):

- **The biome painter lacked the newest biomes**: dappled forest (Java 26.3, Bedrock 26.50) and sulfur
  caves (Java 26.2, Bedrock 26.20). The list of each version now matches the game's (Java 26.3: its
  67 biomes), and Bedrock follows its own version numbers (the pale garden was offered from Bedrock
  1.21.40, it came with 1.21.50).
- **The map drew recent blocks grey or in the wrong colour** (leaf litter, the dappled forest's
  poplars, pale moss, bushes, sulfur, cinnabar, tuff…). The colours are now the game's own map
  colours of every Java 26.3 block, read from its jar, and the blocks a game map sees through (glass,
  torches, rails) are seen through.

The version of each world read and written as the game itself does ([fixes 78–80](docs/FIX_HISTORY.md#021)):

- **"Edit the source world" lacked the newest biomes** (dappled forest, sulfur caves) on Bedrock 26.x
  and Java 26.x worlds, while the painter for the converted world had them: Bedrock 26.x stores its
  version as 1.26.x, read as older than 1.21, and Java worlds newer than 1.21.4 were taken for 1.21.4.
- **Bedrock 26.x worlds written as a version far newer than the game**: the level.dat said 26.50
  where the game writes 1.26.50, and the game compares the two numbers to decide whether it can open
  the world.
- **Block items written for Bedrock with the game's version in place of the block-state version**
  (26.50 in place of the 1.21.60.33 that 26.x writes), in inventories, chests and flower pots.
- **WorldBridge closed itself after an edit of the source world** (painted biomes, deleted or kept
  chunks), right after the message saying it was done ([fix 81](docs/FIX_HISTORY.md#021)).

## 0.2.0 – first public release (alpha)

The first version published. 0.1.0 was never released.

- Conversion between Java (Classic to 26.3), Bedrock (1.1 to 26.50), Legacy Console Edition (eight
  platforms), Pocket Edition 0.1 – 0.8, and from Better than Adventure 8.0.1.
- Seamless borders: game blending for Java and Bedrock 1.18+, the ring of the game's own terrain for
  Java Alpha 1.2 – 1.17 and neoLegacy, a 3D ring for the Nether and the End, and filled finite worlds.
- Tall 1.18+ terrain fitted into 128- and 256-high games (cut, kept, or compressed).
- Map with MCA Selector-compatible chunk selection, chunk moving, biome painting, trim, in-place chunk
  edits and an NBT editor, with automatic backups.
- Every CPU core, with output identical to a single-core run; worlds of about a million chunks
  converted in minutes with under 1 GB of memory.
- Interface and command line in English and Italian.

Everything measured for this release is in [docs/VERIFICATION.md](docs/VERIFICATION.md); what is
known not to work yet is in the README's [Known limitations](README.md#known-limitations).

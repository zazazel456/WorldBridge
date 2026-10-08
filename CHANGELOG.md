# Changelog

## Unreleased – review against real worlds (alpha)

A full review of the code with 110 real worlds downloaded from the web (Java Classic → 26.3, Bedrock
1.1 → 1.26.40, PE 0.x, LCE on PS3 / PS4 / Vita / Wii U / Xbox 360). Fixed so far:

**Found by opening converted worlds in real Bedrock Dedicated Servers (1.14 - 26.52)**
- Bedrock → older Bedrock: attributes the target lacks are no longer written (`minecraft:lava_movement` came with
  1.16; BDS 1.14 logged "Cannot find attribute" for every actor and player), also for the actors kept raw.
- A numeric-Java record player with a record (data 1) is `jukebox` for every Bedrock (it stayed
  `jukebox[block_data=1]`, a state Bedrock 1.14 - 1.18 reject while loading the chunk) and has `has_record` in Java 1.13+.
- Map records no longer carry `parentMapId: -1` (Bedrock 1.17+ logged "Map item N has invalid parentMapId" at every load).
- The age component groups of mooshroom (`minecraft:cow_adult`), rabbit (`adult`, `baby`, `coat_*`), bee, goat, turtle,
  polar bear, piglin and others are the ones of the vanilla behaviour packs (the converter invented `minecraft:<mob>_adult`).

**Java, by version**
- **Java 26.2+ has no bed block entity** (a 26.3 server's registry lists 49 block entity types and no
  `minecraft:bed`; the colour is in the block): beds are no longer written for such a target (chunks written in
  the older blending format included, and Amulet's own copies go too), they are not counted as lost, and the
  colour is read from the block when the source has none. The soul campfire and the bee nest are written
  under the registry's `campfire` / `beehive` ids, and spawners as `mob_spawner` on every version (the
  1.20.5+ files had an unknown `minecraft:spawner`).
- **`--to java --version X` with the default Java mode ignored the version** (a 1.20.4 request wrote the latest,
  26.3): an explicit version now picks the route that writes exactly it (Amulet from 1.13, the numeric Anvil
  format up to 1.12) and the log says so. Hanging signs, barrels, smokers and blast furnaces no longer leave
  orphan block entities in targets older than the block (the game logged "Skipping BlockEntity").
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
- **Java 1.11 / 1.12 numeric worlds lost shulker boxes, illagers, vexes, llamas and parrots** (a chunk without
  DataVersion is only renamed by the game for the ids it knew before 1.11: they now carry their registry names,
  `minecraft:evocation_illager`, `minecraft:shulker_box`, `minecraft:bed`…, and the 1.11 species splits are
  written whole, so a zombie villager no longer gets a random profession).
- **Attributes older games do not know** (`generic.armor`, `armorToughness`… in a 1.8 world) are no longer written.
- **Entities stored in the chunk next to the one they stand in** (Bedrock keeps a mob with the chunk it was
  loaded in; a lowered or moved world shifts positions) were dropped by Java 1.12+ ("Wrong location!", the
  Wandering Trader of a Bedrock world): every Java and Bedrock writer now stores each entity in the chunk of its
  final position. Entities that shared a UUID in the source (one was dropped at load) get a new one.
- **Java worlds converted from Bedrock carried the JPEG `world_icon` as `icon.png`** ("Must be 64 pixels wide"):
  the icon is written as a 64 × 64 PNG.
- **LZ4-compressed regions** (`region-file-compression=lz4`, 1.20.5+) lost chests, signs and mobs;
  chunks over 1 MiB were dropped instead of written to `.mcc` files.
- **Chests of donkeys, mules and llamas were lost** (and a llama's carpet landed on the wrong slot): the
  chest, `ChestedHorse` / `Chested`, the `*_chested` definitions and the saddle / carpet slots now follow
  each game's layout (Java slots 2-16 before 1.20.5 and 0-14 after, Bedrock `ChestItems` 1-15, LCE 2-16).
- **Bedrock targets older than the source**: mobs the old game lacks (parrot 1.2, fish and dolphins 1.4, turtle,
  phantom, cat, panda, pillager, fox, bee... camel husk, nautilus, sulfur cube) are removed and counted on every
  route, villagers / zombie villagers become the pre-1.11 `villager` / `zombie_villager` and trader llamas the
  pre-1.19.10 `llama`, instead of being dropped.
- **`--version 26.3` wrote 26.2** (and `1.21` wrote 1.20.5): short versions now mean x.y.0;
  releases WorldBridge does not list (1.21.11) are written as the nearest earlier one with a note,
  unknown versions are refused with a clear message.

**Legacy Console Edition**
- **TU54+ targets wrote the old ids** (`Cow`, `EntityHorse` + `Type`, `Chest`): as in every real save from
  Xbox 360 TU54 on (and PS3 / PS4 / Vita / Wii U), entities and block entities are now named the Java 1.11 way
  (`minecraft:zombie_pigman`, `minecraft:donkey`, `minecraft:chest`, `minecraft:ender_Chest`), spawners carry
  `SpawnData` / `SpawnPotentials`; TU31 / TU46 keep the old names.
- **Console items are written by name** (`minecraft:egg`), as every console save from TU31 / Wii U v112 on
  has them; Windows64 (neoLegacy) keeps the numbers.
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
- **128-high targets cut floating islands and sky builds silently** (a bedwars map lost 10 of its 19 signs and
  900 blocks): the mountain compression only lowered columns with natural ground. Floating pieces now come down
  whole with the ground near them, air (caves, the void under an island) is removed before rock, and what still
  cannot fit is counted in one warning instead of disappearing.
- **The Nether lost the top layer of its bedrock roof** on Alpha / Beta targets: the one-block sea-level raise
  (Java 62 → 63) applied to every dimension; it is now for the Overworld only (`--y-offset` still moves all).
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
- **Loot tables** (`LootTable` / `LootTableSeed`) of chests, barrels, dispensers, hoppers and shulker
  boxes are carried between Java and Bedrock; copper chests keep the id of their block in Java 1.21.9+.

**Bedrock ↔ Java: frames, items, mobs**
- **Bedrock item frames became stone blocks in Java** (PyMCTranslate maps the frame block to stone),
  so Java dropped every frame and the way back to Bedrock lost them all (je2be b2j: 2364): the block is
  air in Java, and frames are written in the palette of each Bedrock version (with the photo bit from
  1.17.30, `{name, val}` before 1.13, numeric before 1.2.13); those an old version cannot hold are
  reported.
- **Items of Bedrock worlds before 1.13** got Bedrock names Java does not know (54,009 `planks`,
  `log`, `stonebrick`, `fence_gate`…): they get the Java names. **PE 0.9 – 0.16 worlds** lost every
  item and mob (numeric ids): they are read.
- Java `stone_stairs` became cobblestone stairs in Bedrock; block items carried an invalid
  `block_data` state on Bedrock 1.13+.
- **Mob details between Bedrock and Java**: horse colour and markings, llama, parrot, axolotl, cat,
  rabbit, fox and mooshroom variants, saddles, horse armour and villager professions are written and
  read both ways. Spectator stays Spectator (Creative in Bedrock before 1.21.40).

**Bedrock → older Bedrock, versions and spawn**
- **Entities were stored twice** (Bedrock 1.18.30+ → 1.12 – 1.18.29: a `0x32` list from Amulet next to
  the source's `digp` / `actorprefix`; offroaders 108 → 216) and `actorprefix` records no chunk
  referenced stayed in 1.18.30+ outputs. Now there is one copy, in the format the target reads.
- **Block entities, mobs, items and the player of a newer Bedrock** were copied unchanged into older
  worlds (blank signs, unknown flower pots, 1.21 items in a 1.12 world): they are rewritten for the
  target version, and what it cannot hold is dropped and counted ("Content that does not exist in …").
- **`--move-to` did not move the player** of a Bedrock → Bedrock conversion; a player at x = −0.7 was
  treated as outside the selection; an explicit `--spawn` was replaced by the ground at the
  destination and (with `--depth keep`) did not rise with the world.
- **Chunks Bedrock had not finished** (villages, dungeons: 132 of 436 chunks, 133 block entities of
  amulet_1_16_200) were dropped even toward Bedrock; they are kept (the game finishes them). Other
  targets get a warning that says what they held.
- **level.dat of Bedrock targets**: the file header and `StorageVersion` agree and follow the target
  (8 before 1.19.20, 9, 10 from 1.19.50), `NetworkVersion` is the target's protocol, `InventoryVersion`
  is written.
- **A Dedicated Server world with no spawn set** (INT_MIN) no longer writes it to Java; a negative
  spawn y of a 1.18+ world is kept.
- **Java targets older than the source** (1.20.4, 1.18.0…) kept the newer items, mobs and block
  entities: they are removed and reported.

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
- A Java Alpha / Beta / McRegion world with only its `level.dat` (a source with no blocks) could not be
  reopened ("World format not recognised").
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

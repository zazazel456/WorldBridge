# Changelog

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

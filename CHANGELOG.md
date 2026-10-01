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

# Changelog

## 0.2.1 – bug fix (alpha)

- **Items lost from the player's inventory on the way to Java 1.9 and later** (found in game:
  Bedrock 26.50 → Java 26.3, cooked mutton gone from the inventory but not from the furnace). The
  player was written with numeric item ids, and Minecraft's own numeric id fix only knows the items
  of Java 1.7: cooked and raw mutton, banners, doors other than oak, chorus fruit, beetroot, shields,
  elytra, totems, prismarine, slime blocks, red sandstone, concrete and every other item added from
  Java 1.8 on became air. The player's inventory and ender chest now carry the item names (with the
  same Damage), from every source. Chests, furnaces, dropped items and mob equipment of the worlds
  upgraded by the game ("Java 1.9 → latest") had the same problem and are fixed too.
  See [fix 65](docs/FIX_HISTORY.md#021).

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

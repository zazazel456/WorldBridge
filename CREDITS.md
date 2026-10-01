# Credits and third-party material

WorldBridge's own code is licensed under the PolyForm Noncommercial License 1.0.0 (see
[LICENSE](LICENSE)). The material listed here keeps its own licence.

WorldBridge builds on the work of many people. This file lists everything taken from elsewhere:
code that is included, algorithms that were ported, the libraries it runs on, the sources it was
written from and the tools used to verify it. Licences are quoted from each project's own licence
file.

## Code included in this repository

| Component | Where | Origin | Licence |
|---|---|---|---|
| XMemCompress LZX codec (Xbox 360 saves) | `worldbridge/lce/vendor/lzx_codec.py` | [LCEStudio](https://github.com/mrtitanic777/LCEStudio) by mrtitanic777. Its LZX core is a reimplementation of the lzxd algorithm of [libmspack](https://github.com/kyz/libmspack) (LGPL 2.1). | MIT, © 2026 mrtitanic777 (`worldbridge/lce/vendor/LICENSE-LCEStudio`) |
| Reference Aquatic (format 12) chunk encoder, used only by the tests | `tests/lcestudio_format12.py` | LCEStudio. Its header credits the format documentation by UtterEvergreen1 (Team-Lodestone) and the zugebot/LegacyEditor decoder. | MIT, © 2026 mrtitanic777 |
| Minecraft 26.3 registries (blocks, block states, items, biomes, tags) | `worldbridge/bta/data/*-26.3.txt*` | Exported from Minecraft Java Edition 26.3. Game data. | © Mojang |

## Ported algorithms

| What | Where | From |
|---|---|---|
| Biome layer stacks of Beta 1.8 – 1.6 and 1.7 – 1.17 | `worldbridge/terrain/genlayers.py`, `worldbridge/terrain/layers17.py` | A numpy port of [cubiomes](https://github.com/Cubitect/cubiomes) by Cubitect, MIT, © 2020 Cubitect. The biome snapshots in `tests/*_snapshot.py` were computed with cubiomes. |
| BTA legacy id table | `worldbridge/bta/legacyids.py` | Copied from the decompiled Better than Adventure 8.0.1 source. BTA block metadata layouts were read from its decompiled block classes. |
| LCE save container, compression, regions and chunk storage | `worldbridge/lce/` | Written from the 4J Studios Legacy Console Edition source (`Minecraft.World`: `FileHeader`, `compression`, `RegionFile`, `OldChunkStorage`, `LevelChunk`, `CompressedTileStorage`, `SparseLightStorage`, `SparseDataStorage`), the codebase of the PC ports [MinecraftConsoles](https://github.com/smartcmd/MinecraftConsoles), [LCEMP](https://github.com/LCEMP/LCEMP) and neoLegacy. |
| neoLegacy's generator, biome layers, caves, item / enchantment / entity tables and player file layout | `worldbridge/terrain/neogen.py`, `worldbridge/terrain/neolayers.py`, `worldbridge/terrain/carvers.py`, `worldbridge/lce/compat.py` | Read from the [neoLegacy](https://git.neolegacy.dev/neoStudiosLCE/neoLegacy) source by neoStudiosLCE (`Layer.cpp`, `Biome.cpp`, `Item.cpp`, `Enchantment.cpp`, `EntityIO.cpp` and others). |
| Terrain, Nether and End generators of Java Alpha 1.2 – 1.17 | `worldbridge/terrain/` | Reimplemented from the code of the Minecraft Java Edition jars (© Mojang), read decompiled for reference only. The quirks of the Beta 1.7.3 generator were cross-checked against [Modern Beta](https://github.com/b3spectacled/modernbeta) by b3spectacled (MIT). |

No game code, jar or decompiled source is included in WorldBridge.

## Libraries WorldBridge runs on

These are installed at first start into `.runtime/` (versions pinned in `requirements.lock`); only
amulet-nbt, amulet-leveldb and amulet-mutf8 are shipped, as prebuilt wheels in `vendor/wheels/`.

| Library | Used for | Licence |
|---|---|---|
| [Amulet Core](https://github.com/Amulet-Team/Amulet-Core) 1.9.48 | Java 1.13+ and Bedrock world access | The licence file shipped with 1.9.48 reads: "Copyright (c) 2025 Amulet-Team. All rights reserved. A licence must be purchased to use this software. See https://www.amuletmc.com/ for more details." |
| [PyMCTranslate](https://github.com/gentlegiantJGC/PyMCTranslate) 1.2.49 | block state translation between Java and Bedrock versions | Same text as Amulet Core |
| [amulet-nbt](https://github.com/Amulet-Team/Amulet-NBT), amulet-leveldb | NBT, Bedrock LevelDB | Amulet Team License 1.0.0 (non-commercial). Required Notice: Copyright Amulet Team. (https://www.amuletmc.com/) |
| amulet-leveldb's bundled [leveldb-mcpe](https://github.com/Amulet-Team/leveldb-mcpe) and zlib | Bedrock database | BSD 3-Clause (© The LevelDB Authors / Mojang); zlib licence (© Jean-loup Gailly and Mark Adler) |
| amulet-mutf8 | modified UTF-8 | MIT, © Tyler Kennedy |
| amulet-rocksdb, lz4, platformdirs, portalocker | Amulet Core's own dependencies | their own licences (lz4: BSD, © Steeve Morin; platformdirs: MIT; portalocker: BSD-3-Clause) |
| [NumPy](https://numpy.org) | every array operation | BSD 3-Clause, © NumPy Developers |
| [PySide6 / Qt for Python](https://www.qt.io/qt-for-python) 6.11 | the interface | LGPL-3.0 (or GPL-2.0 / GPL-3.0) |
| [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | the portable Python 3.11 of `run.sh` | MPL-2.0 (build scripts); CPython under the PSF licence |
| [Zig](https://ziglang.org) 0.16.0 | building the portable wheels (`tools/build_wheels.py`), and compiling a missing package on the user's machine | MIT |
| [zlib](https://github.com/madler/zlib) 1.3.1 | linked statically into the wheels | zlib licence |
| Ubuntu packages of libxcb and xkbcommon | X11 libraries some distributions lack (`tools/fetch_syslibs.py`, downloaded only when missing) | MIT / X11 |

The desktop's widget styles (Breeze, Kvantum, qt6ct) are loaded from the user's own system when
available; WorldBridge does not ship them.

## Sources consulted

Used as references for formats and behaviour. No code was copied from them.

| Source | Consulted for | Licence |
|---|---|---|
| [LegacyEditor](https://github.com/zugebot/LegacyEditor) by zugebot (Jerrin Shirks) | LCE chunk formats and variants | GPL-3.0 |
| [libLCE](https://github.com/DexrnZacAttack/libLCE) by DexrnZacAttack | LCE save formats | MIT |
| [LCE-Save-Converter](https://github.com/dtentiion/LCE-Save-Converter) by dtentiion | LCE platform variants | GPL-3.0 |
| [Team-Lodestone documentation](https://github.com/Team-Lodestone/Documentation) | LCE file formats (Aquatic format documented by UtterEvergreen1) | CC BY 4.0 |
| [Free60 wiki, "STFS"](https://github.com/Free60Project/wiki/blob/master/docs/System-Software/Formats/STFS.md) | the Xbox 360 package format, from which `worldbridge/lce/stfs.py` is written | – |
| [MCA Selector](https://github.com/Querz/mcaselector) by Querz | the map and chunk selection design; the selection CSV format, which WorldBridge reads and writes; the trim threshold recommended by its guides | MIT |
| [Thanos](https://github.com/aternosorg/thanos) by Aternos | trim rules: never remove force-loaded chunks or chunks whose InhabitedTime cannot be read; its known issue of builds cut at the border | MIT |
| Hosting guides for MCA Selector (Pufferfish, GGServers, Falix) | the `InhabitedTime < 1 minute` trim default | – |
| [Chunker](https://github.com/HiveGamesOSS/Chunker) by Hive Games, Amulet issue reports and the [Amulet FAQ](https://www.amuletmc.com/faq) | test cases: what other converters lose | Chunker: MIT |
| [Minecraft Wiki](https://minecraft.fandom.com/wiki/Tutorials/Updating_old_terrain) | terrain blending of old chunks | CC BY-NC-SA |
| [KDE Human Interface Guidelines](https://develop.kde.org/hig/) | the interface layout, messages and colours | – |
| [mcpelauncher](https://github.com/minecraft-linux/mcpelauncher-manifest) | where Bedrock worlds live on Linux | GPL-3.0 |

## Tools used for verification

Used only to check WorldBridge's output. None of them, and none of the game files, are distributed.

- **Minecraft Java Edition jars** (© Mojang): the terrain generator harness calls each version's own
  generator.
- **Minecraft 26.3's DataFixer**, run by a harness built from the decompiled 26.3 client and
  Mojang's [DataFixerUpper](https://github.com/Mojang/DataFixerUpper) (MIT).
- [Vineflower](https://github.com/Vineflower/vineflower) (Apache-2.0) to read the jars, and the
  Eclipse Java compiler to build the harnesses.
- **cubiomes**, for the biome snapshots.
- The games themselves (Java, Bedrock through mcpelauncher, neoLegacy) for in-game tests. Xenia,
  RPCS3, Cemu and Vita3K are the emulators the console targets are meant for.

## Trademarks

Minecraft is a trademark of Mojang Synergies AB / Microsoft. WorldBridge is an unofficial tool and is
not affiliated with or endorsed by Mojang, Microsoft, 4J Studios, the Better than Adventure team or
the neoLegacy developers.

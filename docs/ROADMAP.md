# Roadmap

WorldBridge is a general toolkit for Minecraft worlds: conversion between editions and versions,
seamless borders with the game's terrain, a map with chunk selection, trimming and world management.
The border work has its own document: [SEAMLESS_BORDERS.md](SEAMLESS_BORDERS.md).

## Done

| Feature | Notes |
|---|---|
| **LCE on PC = neoLegacy TU31 only** | Windows64 has a single target version, the current neoLegacy (TU31), updated along with it. Consoles keep their own title updates (TU31, TU46, TU54). |
| **Two separate border options** | *Game blending* (Java / Bedrock 1.18+: chunks written as pre-1.18 so the game blends them and generates the depth below y 0) and *Ring* (WorldBridge writes the game's terrain around the converted world for games that do not blend: Java Alpha 1.2 – 1.17, neoLegacy, and the fill of small finite LCE / PE maps). |
| **Underground of 1.18+ worlds** | For targets that start at y 0 (Java 1.2 – 1.17, LCE, Bedrock ≤ 1.17): *cut* below y 0, *keep everything* (the world rises by 64 blocks) or *keep from a chosen y*; what does not fit at the top is compressed (mountains come down whole) or cut. GUI *Sottosuolo dei mondi 1.18+*, CLI `--depth cut\|keep\|Y`. |
| **Map tab** | Regenerate the Nether and End from there; paint a biome on the selected chunks (CLI `--biome BIOME=[DIM:]FILE.csv`). |
| **World management** | A full NBT editor (every tag, editable) for Java, Bedrock (old Pocket Edition too) and LCE, with quick settings per world type: name, seed, game mode, difficulty, spawn, time and weather, game rules, players and inventories. Every save leaves a `*.wb-backup` copy; LCE saves inside an Xbox 360 STFS package are read-only. |
| **In-place edits** | From the map: delete or keep only the selected chunks, trim, paint a biome, directly on Java, LCE and Bedrock worlds, with a backup of the changed files. |
| **Biomes per game and version** | The list and names follow the target (conversion) or the opened world (in-place edit). |
| **Move the selected chunks** | To the world centre or to chosen coordinates, on every target (CLI `--move-to`). |
| **Speed on every core** | Conversion, ring, Amulet translation (Java → Java) and map on every CPU core; faster generators and reading; output identical to single-core (bit for bit on 16 of 18 test conversions, the other 2 identical in content). `WORLDBRIDGE_WORKERS=N` sets the number of processes. |
| **Reorganised interface and desktop theme** | Following the KDE Human Interface Guidelines: the world is chosen once at the top, each tab shows only the options that apply, long explanations behind ⓘ buttons, messages inside the window, *Converti* at the bottom right; the map has a toolbar and a side panel. The desktop's style, colours, fonts and icons (Breeze, Kvantum, qt6ct, GNOME). No feature removed: 400 combinations of choices give the same conversion as before. |
| **English and Italian** | The whole program (interface, conversion messages, command line) in English, with Italian as the second language: **EN | IT** at the top right rebuilds the window in the other language keeping every choice; `--lang` on the command line. A test checks that every text has its Italian translation. |
| **neoLegacy content** | Items, enchantments, entities and player files match what neoLegacy has, checked against its source. |

## In progress

| Feature | Needs |
|---|---|
| **LCE consoles:** tests on every platform (Xbox 360, PS3, Vita, Wii U, PS4, Xbox One, Switch), clearer title update and format handling | saves from those consoles |
| **Minecraft PS Vita "Enhanced"** (PG Team mod): reading and writing its saves | a sample save |

## Waiting

- A ring for versions before Alpha 1.2 (Infdev, Alpha 1.0 – 1.1): needs their jars and a reference
  world. The Beta-form Nether caves wait for a Beta jar to be compared with.

## Later

- Java → Better than Adventure 8.0.1 (today: BTA → Java).
- Further toolkit improvements as they are needed.

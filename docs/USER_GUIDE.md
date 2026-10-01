# User guide

How to install WorldBridge, convert a world with the interface or the command line, and put the
result where each game will find it. What WorldBridge does and how it is verified is in the
[README](../README.md).

## Contents

- [Install and run](#install-and-run)
- [The window](#the-window)
- [Language](#language)
- [Conversion tab](#conversion-tab)
- [Map and chunks tab](#map-and-chunks-tab)
- [World trim](#world-trim)
- [Players tab](#players-tab)
- [World management tab](#world-management-tab)
- [Desktop theme](#desktop-theme)
- [Command line](#command-line)
- [Where to put converted worlds](#where-to-put-converted-worlds)
- [Environment variables](#environment-variables)

## Install and run

```bash
./run.sh                                                 # the interface
./run.sh convert <source> <output folder> --to java      # the command line
./run.sh --clean                                         # delete the local runtime
```

Nothing has to be installed: **no Python, pip, compilers, `-dev` packages or `sudo`**. On the first
start (about 20 s and 430 MB) `run.sh` prepares everything in `.runtime/`, next to the program:

- a **portable Python 3.11** (python-build-standalone, SHA-256 checked);
- the exact versions in `requirements.lock` (Amulet Core, amulet-nbt, amulet-leveldb,
  PyMCTranslate, numpy, PySide6-Essentials), **as prebuilt packages only**. amulet-nbt,
  amulet-leveldb and amulet-mutf8, which PyPI has only as source, ship prebuilt in `vendor/wheels/`
  (manylinux2014). If a machine still lacks a package, it is compiled there with a portable Zig
  compiler downloaded into `.runtime/`;
- if needed, the few X11 libraries (xcb, xkbcommon) that Qt uses and some distributions do not
  install, in `.runtime/syslibs/` (Ubuntu packages checked by SHA-256).

Caches, settings and logs (pip, Amulet, Qt, fontconfig) stay in `.runtime/`, never in `~/.cache`,
`~/.config`, `~/.local` or the system. To uninstall, delete the program's folder.

`python3 -m worldbridge` also works with a system Python 3.11 or 3.12: dependencies go to
`.runtime/site-packages/`. With other Python versions it switches to `run.sh` by itself.

**Requirements:** Linux x86_64 with glibc ≥ 2.34 (Ubuntu 22.04, Debian 12, Fedora 35 or later), and
`curl` or `wget`. For the interface: the OpenGL / EGL and fontconfig libraries every Linux desktop
has.

## The window

- **World** (at the top, shared by every tab). Drop the world folder or save file (`.mcworld` and
  `.zip` too), or use **Open folder…** (Ctrl+O) / **Open file…** (Ctrl+Shift+O). The format is
  recognised automatically, and name, platform, chunks and spawn appear below.
- **Tabs:** **Conversion**, **Map and chunks**, **Players**, **World management**.
- **Convert**, at the bottom right (Ctrl+Enter). The world is created in a new folder inside the
  output folder. When it finishes, a message in the window says where, lists any warnings (replaced
  blocks, excluded chunks…) and offers to open the folder. The detailed log is under **Conversion
  log**.
- **EN | IT**, at the top right: the language of the interface (see [Language](#language)).

The window remembers its size, the output folder, the chosen game and the language.

## Language

The interface and the command line speak English and Italian.

- **In the window:** the **EN | IT** switch at the top right. The window is rebuilt at once in the
  other language, with the same world, conversion choices, map selection, spawn, biomes and
  players. It is not available while a conversion runs or while the world management tab has unsaved
  changes.
- **First start:** the system's language (an Italian locale gives Italian, any other English); the
  choice made with the switch is remembered.
- **Command line:** `--lang en` or `--lang it` before the command, for example
  `./run.sh --lang it convert …`; otherwise the system's language.
- **Environment:** `WORLDBRIDGE_LANG=en` or `it` overrides the system's language.

## Conversion tab

Choose the **Game** and the **Version**. Only the options that apply to that target are shown:

- **LCE:** **Platform**, **Game version**, **World size**, the **Area** (**Centre on the spawn**, or
  a chosen chunk) and, on Windows64 and Xbox, the **Player ID**. **From my world…** reads the id from
  a world already played on that PC.
- **Terrain:**
  - **Game blending**, for Java and Bedrock 1.18+;
  - **Transition ring**, for games that do not blend;
  - **Underground of 1.18+ worlds** and **Tall mountains**, only for games whose world starts at
    y 0 or is 128 blocks high.
- **Better than Adventure** sources: **Wood palette** (a palette file) and **Lower the Overworld**
  (automatic by default).
- **What is converted** summarises the choices made in the map and players tabs; **Choose on the
  map…** and **Choose the players…** jump there.
- **Result:** **World name** and **Output folder**.

Long explanations are behind the ⓘ buttons.

**Java targets** (**Version**):

| Choice | What is written |
|---|---|
| Latest (26.3), best route automatically | Numeric worlds (LCE, old Java, PE…): classic Anvil that **Minecraft upgrades itself** on first load, through its own DataFixer (villagers, potions, books, everything). Aquatic LCE saves and Java 1.13+ / Bedrock sources: converted explicitly to 26.3. |
| 1.9 → latest, upgraded by Minecraft | The DataFixer route, for any version from 1.9 on |
| 1.13 – 26.x | Pre-converted to that exact version (Amulet) |
| 1.2 – 1.12 | Numeric Anvil, limited to the blocks of that version |
| Beta 1.3 – Beta 1.8, 1.0, 1.1 | McRegion |
| Beta 1.0 – 1.2_02; Alpha 1.0 – 1.2.6 and Infdev | Alpha format, in a `World1` … `World5` folder |

## Map and chunks tab

As soon as a source world is chosen, a top-down map is drawn: one pixel per block, shaded relief,
darker water where it is deep. In the Nether the terrain under the bedrock roof is shown. It works
with every format: LCE on every console, Java from Classic to 26.x, Bedrock and Pocket Edition.

**Toolbar:** the **Dimension** shown; what a click does (**Pan**, **Select**, **Spawn**); the
**Selection** menu; **Fit** (Ctrl+0); **World trim** and its settings.

- **Mouse wheel:** zoom at the cursor. **Middle button**, **Space** or **Pan** mode: pan.
- **Select mode** (as in [MCA Selector](https://github.com/Querz/mcaselector)): drag to select,
  **Ctrl** or the right button to deselect, **Shift+click** for a whole region (32 × 32 chunks),
  click for one chunk.
- **Selection menu:** **Select all** (Ctrl+A), **Deselect all** (Ctrl+Shift+A), **Invert
  selection** (Ctrl+I), **Import / Export selection…** in **MCA Selector's CSV format**, so
  selections can also be prepared there.
- **Status bar:** coordinates, chunk, region and block under the cursor.
- Large worlds open at once: chunks are drawn in rings from the point being viewed (the spawn at
  first) outwards, and moving the view moves the priority there. During a conversion the preview
  pauses, so the conversion reads the world at full speed.

**Side panel**, first the choices for the conversion:

- **Selected chunks only:** only those chunks are converted; dimensions without selected chunks are
  left out. With game blending, Minecraft generates the rest of the world around them and blends it
  in.
- **Move the selected chunks:** the centre of the selection goes to the world centre (0, 0) or to
  chosen coordinates, with entities, chests and ticks. Spawn and players on the moved chunks follow;
  the others start at the new spawn. Useful above all for finite worlds (LCE, PE), where a build at
  x 900, z 16,180 would be outside the map. CLI: `--move-to center` or `--move-to X,Z` (with
  `--chunks`).
- **Spawn:** click on the map in **Spawn** mode (Y = the highest block + 1) or type X / Y / Z;
  **Restore the original** puts it back. The map also shows the original spawn and the players.
- **Nether and End:** **Regenerate … from scratch** leaves the dimension to the game, which
  generates it anew.
- **Biome of the selected chunks**, **Apply** / **Remove:** the list is the target game's and
  version's, with its names (LCE and Java up to 1.12: *Swampland*, *Extreme Hills*…; Java 1.13 –
  1.17: `swamp`, `mountains`…; 1.18+: `windswept_hills`, `cherry_grove`…). In Italian the Italian
  name is shown alongside. Java Alpha / Beta and Pocket Edition 0.x store no biomes.

Then, separately, **Edit the source world**, without converting, like an NBT editor:

- **Delete the selected chunks…** (the game generates them again);
- **Keep only the selected chunks…**;
- **Give the biome to the selected chunks…** (from the opened world's own game);
- the trim's **Apply to the world**.

These work on Java (Anvil 1.2 → 26.x), LCE (every platform) and Bedrock. The changed files are first
copied to `<world>.wb-backup-<date>/` next to the world. The game must be closed.

## World trim

**World trim** keeps only the chunks that were really used, as is done with MCA Selector. Minecraft
Java 1.6.1+ and Legacy Console Edition store `InhabitedTime` in every chunk: how long players have
spent near it (20 ticks per second). Chunks generated only while passing by have almost none;
removing them frees space and lets Minecraft generate them again with current terrain.

Defaults, from community practice:

- **chunks with InhabitedTime < 1 minute are removed**, the threshold MCA Selector's guides
  recommend (Pufferfish, GGServers, Falix…): higher values become destructive for little extra
  space;
- **a 1-chunk protective ring** around every used chunk: it avoids trees and builds cut in half at
  the border, the known issue of trims (Aternos' Thanos);
- **the spawn ± 2 chunks** is always kept; **force-loaded chunks** (`data/chunks.dat` or
  `chunk_tickets.dat`) and **chunks without readable data** are never removed, as Thanos does.

The result appears on the map as a selection, with a summary per dimension; a dimension that would
end up empty is reported. From there:

- **Use for the conversion:** only the kept chunks are converted;
- **Save trimmed world…** (Java): a copy in the same format without the unused chunks. Kept chunks
  are copied byte for byte (compression, `.mcc` files, timestamps), and `entities/` and `poi/` are
  cleaned too. The original is never modified;
- **Apply to the world:** the unused chunks are deleted from the source world itself, after a backup
  of the changed files;
- **Undo trim.**

The **Trim settings** button next to it holds the threshold (seconds / minutes / hours), protective
ring, spawn radius, force-loaded and unreadable chunks, and the **heat map**: red for chunks below
the threshold, yellow to green for more and more used ones, grey without data. The cursor shows each
chunk's InhabitedTime. Changing a value updates the selection at once, and the choices are
remembered. Bedrock, Pocket Edition, Better than Adventure and Java before 1.6 do not record the
time, so trim is not available for them.

## Players tab

Lists the players saved in the world, with position and item count (for PlayStation also the PSN
name, for Java servers the name from `usercache.json`). Choose which to transfer, which becomes the
**main player** (the one who finds their inventory when opening the world in single player) and
which **nickname** to link them to:

- **Java:** the nickname becomes `playerdata/<UUID>.dat`. With **Premium** the account's UUID is
  looked up on Mojang's servers; otherwise the offline UUID is used (non-premium servers, LAN).
- **LCE:** the player id is the file name in `players/`. On neoLegacy it is the **XUID**, a number
  the game assigns to each installation, **not the nickname**: with a nickname the file is not read
  (empty inventory, start at spawn).
- **Bedrock / Pocket Edition 0.x:** the main player is transferred.

## World management tab

Opens the world chosen at the top (or another one; **Use the world opened at the top** goes back to
it) without converting it, and shows all its NBT documents:

- **Java:** `level.dat`, player files, and for 26.x also `data/minecraft/*.dat` (generator settings,
  game rules, weather, clocks);
- **Bedrock:** `level.dat` and the players stored in the database (local player and
  `player_server_*`);
- **old Pocket Edition:** `level.dat` with its header;
- **LCE:** `level.dat` and the players inside the save.

Features:

- **Quick settings**, different per world type: name, seed, game mode, difficulty, spawn, time,
  weather, cheats… For a player: position, health, hunger, experience, game mode and the
  **inventory** (double-click to change an item or a count).
- **Full NBT tree:** double-click a value to change it; right-click to add, rename or remove a tag.
- **Save changes** rewrites the files in their own format (compression, endianness, headers) and
  leaves a `*.wb-backup` copy of the original next to them. Xbox 360 saves still inside an STFS
  package open read-only.

## Desktop theme

WorldBridge has no theme of its own: it uses the desktop's, like a KDE application, following the
[KDE Human Interface Guidelines](https://develop.kde.org/hig/): colours from the colour scheme, the
theme's icons, messages inside the window instead of dialogs, explanations behind ⓘ buttons.

- **KDE Plasma:** colour scheme, fonts and icons from `kdeglobals`. The **widget style** chosen in
  System Settings (**Breeze**, **Kvantum** with its active theme, or another) is loaded from the
  system's Qt.
- **qt6ct / `QT_STYLE_OVERRIDE`:** the style chosen there (for example `kvantum`).
- **GNOME and others:** the system's light or dark colours (GTK / XDG portal) with Qt's Fusion style.

The desktop's style is a plugin of the system's Qt, while WorldBridge runs on PySide6's Qt. The first
time, the plugin is tried in a separate process that builds the whole window (a few seconds, once;
the answer is remembered until the plugin or Qt changes). If it does not work, Fusion with the
desktop's colours is used, without errors. `run.sh` lets the interface read the desktop's settings
(`~/.config`, `~/.local/share`), but everything it writes stays in `.runtime/`.

## Command line

```bash
python -m worldbridge info     <path>                 # recognise a world's format
python -m worldbridge --lang it <command> …           # messages in Italian (en, it)
python -m worldbridge versions                        # Java and Bedrock versions supported
python -m worldbridge players  <world>                # list the players saved in a world
python -m worldbridge convert  <source> <output> --to java|bedrock|lce|pe-old [options]
python -m worldbridge trim     <world> [<output>] [options]
```

`./run.sh` accepts the same commands.

**Examples:**

```bash
# Java
worldbridge convert <source> <output> --to java                                   # latest (26.3)
worldbridge convert <source> <output> --to java --java-mode amulet --version 1.20.1
worldbridge convert <source> saves/World1 --to java --java-mode alpha --java-limit b1.2   # Beta 1.0 – 1.2_02
worldbridge convert <source> saves/World2 --to java --java-mode alpha --java-limit alpha  # Alpha 1.0 – 1.2.6
worldbridge convert <source> <output> --to java --java-mode mcregion --java-limit b1.7   # Beta 1.7.3

# Bedrock, LCE, Pocket Edition 0.x
worldbridge convert <source> <output> --to bedrock --version 26.50.0
worldbridge convert <source> <output> --to lce --platform win64 --player-id <XUID>
worldbridge convert <source> <output> --to lce --platform ps3 --profile tu54
worldbridge convert <source> <output> --to pe-old

# Better than Adventure → Java 26.3
worldbridge convert <BTA world> <output> --to java
worldbridge convert <BTA world> <output> --to java --bta-y-offset 0 --bta-palette woods.properties

# Selections, spawn, players
worldbridge convert <world> <output> --to java \
    --chunks base.csv --chunks nether:nether.csv \        # MCA Selector CSV selections
    --spawn 120,70,-40 \
    --player <KEY>=Steve --player <KEY>=Alex              # the first becomes the main player

# Trim
worldbridge trim <world> <trimmed copy>                          # with the recommended values
worldbridge trim <world> --dry-run --min-time 5m --ring 2        # summary only
worldbridge convert saveData.ms <output> --to java --trim        # convert only the used chunks
```

**`convert` options:**

| Option | Meaning |
|---|---|
| `--to java\|bedrock\|lce\|pe-old` | target edition |
| `--java-mode auto\|dfu\|numeric\|mcregion\|alpha\|amulet` | Java route: `auto` = latest version by the best route; `dfu` = a world upgraded by the game; `amulet` = pre-converted to `--version` |
| `--java-limit` | the version inside the chosen format: `numeric` 1.2 … 1.12; `mcregion` b1.3 … b1.8, 1.0, 1.1; `alpha` `alpha` (Alpha 1.0 – 1.2.6, Infdev) or `b1.2` (Beta 1.0 – 1.2_02, default) |
| `--version` | target version (for example 1.20.1 or 26.50.0) |
| `--platform` | LCE platform: `win64`, `xbox360`, `ps3`, `wiiu`, `vita`, `ps4`, `xboxone`, `switch` |
| `--profile` | LCE console version: `tu54` (default), `tu46`, `tu31`. Windows64 is always neoLegacy TU31 |
| `--size` | LCE world width in chunks: 54, 64, 192, 320 (default 320 on Windows64 / PS4 / Xbox One / Switch / Wii U, 54 on Xbox 360 / PS3 / Vita) |
| `--center-on-spawn`, `--offset X,Z` | which source chunk becomes the centre of the LCE world |
| `--name` | the target world's name |
| `--player-id` | LCE PC / Xbox: the XUID (file name in `players/`) for the main player |
| `--no-blend` | Java / Bedrock 1.18+: no game blending |
| `--no-ring` | no ring (Java Alpha 1.2 – 1.17, neoLegacy, Nether and End) and no fill of finite maps (PE 0.x, LCE 54 / 64 chunks) |
| `--tall-terrain compress\|cut` | 128-block targets: compress tall mountains (default) or cut them at y 127 |
| `--depth cut\|keep\|Y` | 1.18+ worlds to games that start at y 0: `cut` below y 0 (default), `keep` everything (the world rises by 64), or keep from a negative Y |
| `--regen nether\|end` | do not convert that dimension: the game generates it anew (repeatable) |
| `--chunks [DIM:]FILE` | convert only the chunks of an MCA Selector CSV (DIM = overworld, nether, end; repeatable); dimensions without a file are left out |
| `--biome BIOME=[DIM:]FILE` | give a biome (name or number) to the chunks of a CSV; repeatable |
| `--spawn X,Y,Z` | new world spawn |
| `--move-to center\|X,Z` | move the selected chunks: their centre goes to 0, 0 (`center`) or to X, Z |
| `--player KEY[=NICKNAME]` | players to transfer (the first is the main one) and their nicknames; KEY as shown by `players`; repeatable |
| `--offline` | Java: offline UUIDs (non-premium servers) |
| `--bta-palette FILE`, `--bta-y-offset N` | Better than Adventure: wood palette, and how far to lower the Overworld (automatic by default) |
| `--trim`, `--trim-min-time`, `--trim-ring`, `--trim-spawn-radius`, `--trim-drop-forced`, `--trim-drop-unknown` | convert only used chunks, with the trim settings below |

**`trim` options:** `--dry-run` (summary only), `--csv FILE` (save the kept Overworld chunks as an
MCA Selector selection), `--min-time` (for example 30s, 1m, 5m, 2h or ticks; default 1m), `--ring N`
(default 1), `--spawn-radius N` (default 2, −1 = none), `--drop-forced`, `--drop-unknown`.

## Where to put converted worlds

| Game | Where |
|---|---|
| **Java** | copy the folder into `.minecraft/saves/`. With the automatic route, worlds from numeric formats (LCE, old Java, Pocket Edition…) are written as classic Anvil and **Minecraft upgrades them to your version** on first start. 26.1+ worlds are written in the classic layout and migrated by the game (`dimensions/`, `players/`). |
| **Java Alpha and Beta up to 1.2_02** | the game lists only the folders **`World1` … `World5`** of `.minecraft/saves/` (the folder name *is* the slot; there is no `LevelName` yet). The interface names the output folder `World1` (or the first free slot): copy it as it is. From Beta 1.3 worlds have free names. |
| **Bedrock** | copy the folder into `minecraftWorlds/` (or zip it as `.mcworld`). With the Linux launcher [mcpelauncher](https://github.com/minecraft-linux/mcpelauncher-manifest) the folder is `~/.var/app/io.mrarm.mcpelauncher/data/mcpelauncher/games/com.mojang/minecraftWorlds/` (Flatpak) or `~/.local/share/mcpelauncher/games/com.mojang/minecraftWorlds/`; copying the folder works better than importing the `.mcworld`. |
| **neoLegacy (LCE on PC)** | copy the generated folder (it holds `saveData.ms` and `thumbnails/thumbData.png`) into `Windows64/GameHDD/`. The main player is loaded from `players/<XUID>.dat`. |
| **Xbox 360 (Xenia), PS3 (RPCS3), Wii U (Cemu), Vita (Vita3K), PS4 / Xbox One / Switch** | the generated file replaces the one of an existing save of the same console (`savegame.dat`, `GAMEDATA`, the `GAMEDATA_*` files). Signing saves for real consoles (PARAM.PFD, CON packages) is done with each console's own tools. Xbox 360, PS3 and Vita only know the **Classic** world (54 × 54 chunks); the other consoles and the PC also have Small, Medium and Large. |

## Environment variables

| Variable | Effect |
|---|---|
| `WORLDBRIDGE_LANG=en\|it` | language of the messages, instead of the system's |
| `WORLDBRIDGE_WORKERS=N` | number of processes used (`1` = a single core) |
| `WORLDBRIDGE_NATIVE_STYLE=0` | do not load the desktop's widget style; use Fusion with the desktop's colours |
| `WORLDBRIDGE_QT_PLUGIN_DIRS` | extra folders where the desktop's Qt style plugins are looked for |
| `WB_DFU_HARNESS` | path of the DataFixer harness used by `tools/matrix.py` to check Java outputs |

# Test plan

This is the sequence for testing WorldBridge against every scenario, from the automated tests that
run on their own to the checks made by hand in the game, on small and large worlds. Each phase says
**what to do**, **what to look at** and **what is expected** (known limits), so that a real problem
can be told apart from an intended limit. Results are recorded in [VERIFICATION.md](VERIFICATION.md).

| Phase | Who | Time | Purpose |
|---|---|---|---|
| 0. Preparation | tester | 30 min | backups, game versions, emulators |
| 1. Automated tests | computer | 5 min + 1 h | every format to every format, read back and checked |
| 2. Robustness and scale | computer | 20–60 min | broken files, odd input, large worlds |
| 3. The museum | tester | 1–2 h per edition | a world with everything that usually breaks |
| 4. In-game paths | tester | 15 min per path | convert the museum and check it in the target game |
| 5. Real and large worlds | tester | varies | real saves, up to tens of thousands of chunks |
| 6. Interface | tester | 30 min | map, selection, trim, players, cancellation |
| 7. After every change | computer | 10 min | regressions |

---

## Phase 0 · Preparation

1. **Back up** every save you will use. WorldBridge never modifies the original when converting: it
   always writes to a new folder and reads Bedrock worlds from a copy. The backup is for comparing.
2. Install these versions (launcher: *Installations → New → Version*):
   - Java **26.3** (main), **1.20.1**, **1.16.5**, **1.12.2**, **1.8.9**, **1.0**, **Beta 1.7.3**,
     **Beta 1.2_02**, **Alpha 1.2.6**. Alpha and Beta appear after enabling "Show historical
     versions" in the launcher options.
   - The latest Bedrock (Windows, Android, or mcpelauncher on Linux).
   - LCE: neoLegacy on PC and, if you want, the Xenia (Xbox 360), RPCS3 (PS3), Cemu (Wii U) and
     Vita3K (Vita) emulators.
   - Better than Adventure 8.0.1, to test BTA.
3. Keep the game's **`latest.log`** open during every test (Java: `.minecraft/logs/latest.log`).
   Lines with `Failed to`, `Couldn't load`, `Skipping` or `regenerat` are the first thing to report.

## Phase 1 · Automated tests

```bash
.runtime/python/bin/python3 -m pip install -q pytest       # once, after the first ./run.sh
.runtime/python/bin/python3 -m pytest -q tests              # ~5 min: formats, mappings, generators, trim, BTA…
.runtime/python/bin/python3 tools/matrix.py quick           # ~5 min: the main paths
.runtime/python/bin/python3 tools/matrix.py full            # ~1 h: every source × every target
```

What `tools/matrix.py` does:

1. **Builds a sample world** with everything converters most often break:
   - containers: a named double chest, a burning furnace, a dispenser, a hopper, a dropper, a full
     red shulker box, an ender chest, a jukebox with a disc, a spawner;
   - items: a named enchanted sword, a written book, a potion, dyed leather armour, stacks of 64;
   - blocks: a sign with accents and €, a red bed, a patterned banner, a flower pot, heads, redstone
     (lever, wire, repeater, lamp, piston), a door, stairs, slabs, fences, panes, a trapdoor, rails,
     a wall torch, 1.8–1.12 blocks;
   - entities: a sitting wolf with its owner, a saddled horse with armour, a villager, a saddled pig,
     a named zombie with armour, an item frame with an item, a painting, an armour stand, a chest
     minecart, a boat, a dropped item;
   - a player with armour, ender chest and experience;
   - three dimensions, negative coordinates and far-away chunks (x 16,000).
2. **Writes it in every source format:** Java Anvil / McRegion / Alpha / 1.20.1 / 26.3, the latest
   Bedrock and 1.16, every LCE console, Pocket Edition 0.8 and Better than Adventure.
3. **Converts every source to every target:** Java 26.3, 1.20.1, 1.16.5, 1.12, 1.8, 1.0, Beta 1.7
   and 1.2, the latest Bedrock and 1.18, every LCE console, PE 0.8.
4. **Checks every result:**
   - the format is recognised and the map opens;
   - the result is converted again to Java 1.12 and inspected: chunks per dimension, blocks, chest
     contents, sign text, block entities, entities, player;
   - Alpha and Beta outputs go through an NBT reader with those games' rules;
   - with `WB_DFU_HARNESS` set, Java outputs go through **Minecraft 26.3's own DataFixer**.
5. **Writes a report** to `matrix-out/report.md`: for every pair the outcome, time, chunks, size and
   the **"lost compared with the sample"** column, that is what did not survive. Compare it with the
   known limits at the end of this document.

`--real FILE` adds real saves as extra sources, for example
`tools/matrix.py full --real saveData.ms --real GAMEDATA.bin`.

## Phase 2 · Robustness and large worlds (automated)

```bash
tools/matrix.py robust    # broken files and odd input
tools/matrix.py scale     # 6,144 and 24,576 chunks: time, memory, size
```

`robust` covers:
- a chunk of random bytes, a region file cut in half, a 100-byte region file: the conversion
  finishes and the broken chunk is skipped with a warning;
- a world without `level.dat`: a clear error, no crash;
- a path with spaces, accents, € and Japanese characters;
- a `.zip` archive as the source, or `level.dat` chosen instead of the folder;
- a non-empty output folder: the conversion refuses;
- cancelling halfway: no temporary folders left behind;
- selection, spawn, player and trim together;
- LCE → the same LCE (lossless);
- far-away chunks to LCE, which has a finite world: they are left out with a warning.

`scale` builds large worlds and measures chunks per second and peak memory. It converts them to Java
26.3, LCE and Bedrock, opens the map, runs the trim scan and converts a 4,096-chunk BTA world.

---

## Phase 3 · The museum (built by hand, once per source edition)

In each source game you want to test (LCE, a Java version, Bedrock, BTA), build near the spawn, in
creative mode, an area with these elements, one per cell. Take a screenshot of each row before
converting.

**A · Blocks with a direction or shape** (the most fragile)
- stairs in a row, inner and outer corners, upside down;
- connected fences and walls, connected glass panes, iron bars;
- single and double doors, right-hinged, open and closed; trapdoors open / closed, top and bottom;
- top, bottom and double slabs;
- logs and quartz pillars in all three directions;
- torches, levers and buttons on walls, floors and ceilings;
- beds in all four directions and in several colours;
- straight, curved and sloped rails; powered rails on;
- wall and standing signs in 4 directions, with coloured text and accents;
- wall and standing banners with patterns; heads (mob and player); pots with flowers, saplings,
  mushrooms and cacti (the plant must stay the same).

**B · Redstone** (it must still work)
- wire with crossings and slopes;
- repeaters with delays 1–4 and a locked one; a comparator in subtract mode;
- extended normal and sticky pistons; an observer;
- a 2 × 2 piston door and a hopper clock;
- a dispenser with arrows, droppers and hoppers in a chain;
- note blocks tuned to different notes: after conversion they must play the same note.

**C · Containers** (contents and slot positions)
- a **double chest** with different items in every slot: the left and right halves must not swap;
- a named chest;
- a barrel, shulker boxes of every colour with names and items;
- a furnace while smelting, a blast furnace, a smoker;
- a dispenser, dropper, hopper, lectern with a book, jukebox with a disc;
- an ender chest, whose contents travel with the player;
- rows of double chests side by side, and a trapped chest (LCE and Java ≤ 1.12 targets).

**D · Items** (in a chest)
- a sword with several high-level enchantments, an enchanted book, a half-damaged pickaxe;
- a renamed item with colour, an item with lore;
- a written and signed book, a book and quill;
- an explored map, also in an item frame;
- normal, splash and lingering potions; tipped arrows;
- dyed leather armour, fireworks with a star, a patterned banner;
- a player head; full stacks of 64 and 16 (eggs, pearls).

**E · Entities**
- a sitting wolf with a coloured collar, a tamed cat / ocelot, a parrot: they must stay tamed,
  sitting and collared; stand them up and walk away to see if they follow;
- a saddled horse with armour, a donkey or mule with a chest, a llama with a carpet;
- a villager with a profession and trades, a baby villager;
- iron and snow golems;
- a zombie with a name tag and armour held and worn, a large slime, coloured and sheared sheep,
  babies;
- an animal on a lead tied to a fence;
- an item frame with a rotated item, paintings of every size, an armour stand with armour and a
  pose;
- minecarts (plain, chest, furnace, hopper, TNT), a boat, items left on the ground.

**F · Player**
- a full inventory, a selected slot, full armour, an offhand item;
- XP, hunger and health below the maximum, an active potion effect;
- a bed as the respawn point;
- in multiplayer at least two players (split-screen on consoles);
- one test with the player standing **in the Nether** when saving.

**G · World**
- note the seed, time of day, weather, difficulty, cheats and a changed game rule
  (`keepInventory`);
- a lit Nether portal with its counterpart;
- the dragon killed and the End portal;
- an automatic farm (wheat with an observer, a mob farm);
- a natural village;
- a spawner.

## Phase 4 · Paths to test in game

Convert the museum with the GUI and open it in the target game. Priority: **P1** are the paths that
matter most, **P2** and **P3** complete the picture.

| P | From → to | Where the result goes | What to look at |
|---|---|---|---|
| P1 | LCE (neoLegacy / Vita / PS3 / Xbox 360…) → Java 26.3 | `.minecraft/saves` | no regenerated chunks (log!), blending at the edges, double chests, signs, maps in frames, horses |
| P1 | LCE → latest Bedrock | `minecraftWorlds` | block states, inventory, entities, chests; normal player speed, game-mode change, frames with maps, edge blending |
| P1 | Java 26.3 → Bedrock | `minecraftWorlds` | shulker boxes, banners, books, armour stands, frames with maps |
| P1 | Bedrock → Java 26.3 | `saves` | as above in reverse; seed and heights |
| P1 | Java 26.3 → neoLegacy TU31 | `Windows64/GameHDD` | the world loads; newer blocks and items replaced or removed (report); rows of chests; the host player (XUID); the ring |
| P1 | Better than Adventure → Java 26.3 | `saves` | painted woods, legacy chests, statues → armour stands, sea height (65 blocks down) |
| P1 | World trim + conversion | – | only used chunks, no holes inside bases, emptied dimensions reported |
| P2 | Java 1.12.2 / 1.8.9 → Java 26.3 | `saves` | the game's own upgrade, no DataFixer errors |
| P2 | Java 26.3 → Java 1.20.1 / 1.16.5 / 1.12.2 / 1.8.9 | `saves` | the world opens in the old version and missing blocks are replaced |
| P2 | Java → Beta 1.7.3 (McRegion) and Beta 1.2 / Alpha (World1…World5) | `saves/World1` | the world appears in the list (!), inventory, no crash when opening chests |
| P2 | LCE console A → LCE console B (e.g. Vita → PS3, PC → Xbox 360) | an existing save of that console | world size, host, thumbnail |
| P2 | Bedrock 1.16 → latest Bedrock / Java | – | old numeric blocks |
| P3 | Pocket Edition 0.8 ↔ Java / Bedrock | – | 256 × 256 area; the player keeps position and health but not the inventory (known limit) |
| P3 | Classic / Indev → Java / Bedrock / LCE | – | world shape, water and lava |

For every path, fill in a line:

```
Path: LCE Vita → Java 26.3 · World: museum_vita · Date: …
[ ] Opens without errors (clean latest.log)        [ ] No regenerated chunks
[ ] A blocks/directions   [ ] B redstone works     [ ] C containers (slot order)
[ ] D items (enchantments, names, books, maps)     [ ] E entities (owners, saddles, names)
[ ] F player (inventory, armour, XP, position)     [ ] G world (seed, spawn, time, game rules, portals)
Notes / screenshots:
```

**Quick checks in game (Java):**
- **Position and targeted block:** F3 shows where you are and, on the right, the block with all its
  properties.
- **Entity data:** `/data get entity @e[type=wolf,limit=1,sort=nearest]` shows owner, collar and
  health.
- **Block contents:** `/data get block ~ ~-1 ~` shows the contents of a chest below you.
- **Regenerated chunks:** search `latest.log` for `Recreating` and `Failed to read chunk`.

### Ring tests (Java Alpha 1.2 – 1.17 and neoLegacy targets)

For each target, convert **only part** of the world (a selection in the **Map and chunks** tab), so the
edge is close. Then open the world and:

1. walk or fly along **the whole** edge between the converted area and the ring, above and below
   ground;
2. fly about ten chunks past the ring (its outer edge, where the game's terrain starts);
3. for every defect (step, hole, standing or leaking water, cut tree, interrupted cave, wrong biome
   decoration) take a screenshot with **F3** open;
4. close the game and measure the source world, the converted world and the world after playing:

   ```bash
   python tools/seamcheck.py SOURCE_WORLD CONVERTED_WORLD [WORLD_AFTER_PLAYING] --chunks selection.csv
   ```

   For each pair of neighbouring columns (converted, ring, game) it gives the height jump of the
   ground and the spots where water leaks.

| Target | Format | What to look at |
|---|---|---|
| Java 1.6.4 | numeric Anvil ("1.6.x") | the ring's caves and ravines (carved by WorldBridge as the game does), trees and ores (added by the game) |
| Java 1.12.2 | numeric Anvil ("1.12.x") | as above, with the 1.7+ surfaces (giant taiga, mesa, shattered savanna) |
| Java 1.13.2 | pre-converted (Amulet) | caves, trees and ores in the ring are made by **the game** (status "base"): they must be there |
| neoLegacy TU31 | LCE Windows64 | the ring meets the map edge; biomes under the sea are oceans |

### Nether and End ring test (optional, once)

The Nether and End generators are already checked block for block against the jars
([SEAMLESS_BORDERS.md](SEAMLESS_BORDERS.md)), so **one** in-game test is enough. Convert a world with
an explored Nether and End **from another edition** (LCE or Bedrock, so the generator differs) to
**Java 1.16.5**, go through the portal and fly along the edge of the converted part. Floors, roofs
and the lava sea must pass smoothly to the game's terrain in about 4 chunks, with the soul sand
valleys, basalt deltas and forests the game adds by itself. In the End: the main island and, beyond
1,000 blocks, the outer islands. To skip converting them, tick **Regenerate the Nether / the End from scratch**
(CLI: `--regen nether --regen end`).

## Phase 5 · Real and large worlds

1. **Order:** start with the smallest world, then try the largest.
2. **Before converting:** open the world in the GUI and look at the map, then use **World trim**
   with the heat map: it shows at once where people have played.
3. **During the conversion:** note duration and peak memory. On Linux, `/usr/bin/time -v ./run.sh
   convert …` shows the "Maximum resident set size".
4. **After:** open the world and fly to the four corners of the explored area (the edges are where
   blending shows). Also check 2–3 important builds and the Nether.
5. **Cross-check with MCA Selector (Java):** open the converted world in MCA Selector and check that
   the chunk count matches the one WorldBridge reported.
6. **Edge cases to try at least once:**
   - an LCE "Large" world (320 × 320 chunks);
   - a Java world with chunks at ±30 million blocks;
   - a world with a corrupted chunk: WorldBridge skips and reports it;
   - a world open in Minecraft during the conversion;
   - an almost full disk: a clear error, not a half-written folder.

## Phase 6 · Interface

- **Source:** drop a folder, an `.ms` file, an `.mcworld` and a `.zip`. Each one must be recognised
  with name, chunks and players.
- **Map:** zoom with the wheel, pan with the middle button or Space. Rectangle selection, Ctrl to
  deselect, Shift+click for a whole region, Invert. Export the selection to CSV, open it in **MCA
  Selector** and import it back: it must be identical.
- **Spawn:** pick a new one with a click and check that you respawn there in game.
- **Players:** link one player to a premium nickname and one to an offline one. On a non-premium
  server the player must find the inventory again.
- **World trim:** change threshold and ring in the trim settings (the selection must update at
  once). Turn on the heat map, then try **Undo trim** and **Save trimmed world…**.
- **Cancel** a long conversion halfway: no `.worldbridge_*` folders left next to the output.
- **Desktop theme:** on KDE Plasma the window follows the colour scheme, icons and widget style
  (Breeze or Kvantum); `WORLDBRIDGE_NATIVE_STYLE=0` falls back to Fusion.
- **Language:** switch **EN | IT** with a world open, a map selection and a changed spawn: the window
  comes back in the other language with the same choices; `--lang it` gives the command line in
  Italian.
- **Clean install:** `./run.sh --clean`, then `./run.sh` (downloads everything again). A second start
  **without internet** must work.

## Phase 7 · After every change

Run `pytest` and `tools/matrix.py quick` again and compare `report.md` with the previous one: the
"lost" column must not get worse.

---

## Known limits (not bugs)

| Path | What happens | Why |
|---|---|---|
| → Bedrock | frames with maps keep the drawing; blending with new terrain is done by the game and is less smooth than Java's | Bedrock blends only heights and biomes at the edge of old chunks |
| → Java Alpha / Beta / 1.x, LCE | items, mobs and block entities newer than the target are removed or replaced (report at the end) | the old game would crash |
| → Java 1.18+ and Bedrock 1.18+ | Nether and End converted from another generator or seed keep a step at the edge | the game's blending covers the Overworld only; *Regenerate* is available |
| → Bedrock 1.1 – 1.17, LCE consoles with 192 / 320-chunk maps, Customized Java worlds | no border remedy: the conversion warns | their generators are not reproduced |
| → PE 0.x, LCE with 54 / 64-chunk maps | the whole map is written, with natural terrain around the converted world; on PE the fill has no trees | small finite worlds: no exposed edge |
| → LCE | chunks outside the map (54 / 64 / 192 / 320 chunks) are left out; blocks newer than the title update are replaced | LCE worlds are finite |
| → Pocket Edition 0.8 | 256 × 256 area, Overworld only; the player keeps position and health but not the inventory | the 0.x client format is undocumented |
| Better than Adventure | only to Java 26.3; projectiles, fireflies and butterflies are not converted; maps become empty | no vanilla equivalent |
| Entities between different editions | position, health, name, colour, baby, saddle, owner and inventory are kept; villager trades and very specific data pass only between LCE and Java | the same as other converters (Chunker does not convert entities; Amulet loses trades and poses) |
| Trim | Bedrock, PE, BTA and Java before 1.6 do not record InhabitedTime | the data does not exist |
| A selection of part of the world | trees and builds crossing the edge stay cut; the game generates new terrain next to them but does not rebuild them (detached leaves decay) | true for every converter and editor; widen the selection by a chunk if the cut shows |
| Tamed animals between Bedrock and Java / LCE | they stay tamed, sitting and collared; the owner becomes the converted world's player. With a different account the animal stays tamed but does not follow you | Bedrock identifies players by a number, Java by an account UUID |
| Mountains taller than the target (Alpha, Beta, 1.0 – 1.1, PE 0.8: 128 blocks) | with *Compress* (default) the terrain is lowered only where needed; buildings and trees stay whole, but the tips of the tallest trees on the highest peaks are cut and the ground can show a step at a building's edge. *Cut* leaves flat plateaus at y 127 | a world up to 320 blocks high cannot fit 128 without changing shape |
| Flower pots from Java 1.13+ to older versions | plants newer than 1.12 (cornflower, bamboo, new flowers…) leave the pot empty | the old version does not know them |

## Reporting a problem

Include:
1. the path (from → to, version, platform);
2. the GUI log (**Conversion log**) or the command output;
3. the game's `latest.log`;
4. the coordinates and a screenshot with F3;
5. if possible, the save or just the affected region file: `r.X.Z.mca` with X = floor(x / 512).

## Sources for the test cases

- [Chunker (Hive Games)](https://github.com/HiveGamesOSS/Chunker): what it converts and what it
  does not (entities, inventories, structures).
- Amulet bug reports on double chests, signs, empty inventories and empty chunks:
  [#655](https://github.com/Amulet-Team/Amulet-Map-Editor/issues/655),
  [#779](https://github.com/Amulet-Team/Amulet-Map-Editor/issues/779),
  [#1393](https://github.com/Amulet-Team/Amulet-Map-Editor/issues/1393).
- [Amulet FAQ](https://www.amuletmc.com/faq): entities and items between editions.
- [Minecraft Wiki – Updating old terrain](https://minecraft.fandom.com/wiki/Tutorials/Updating_old_terrain):
  blending and old chunks.
- [MCA Selector – Chunk Filter](https://github.com/Querz/mcaselector/wiki/Chunk-Filter) and
  [Thanos (Aternos)](https://github.com/aternosorg/thanos) for the trim.

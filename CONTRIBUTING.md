# Contributing to WorldBridge

WorldBridge is in **alpha**. The most useful thing you can do is use it on a copy of a real world and
say what happened. Reports of conversions that worked are welcome too: they tell which paths are safe.

## Before you start

- **Always work on a copy of your world.** In-place edits make a backup of the files they change, but
  an alpha is an alpha.
- Run the latest version: `git pull`, then `./run.sh`.

## Test reports

Open a [test report](https://github.com/zazazel456/WorldBridge/issues/new?template=test_report.yml)
after converting a world and opening it in the target game. Useful details:

- source game, version and platform, and how the world was made (survival world, creative build,
  downloaded map, very old save…);
- target game, version and platform, and the options you chose (ring / blending, height, chunk
  selection);
- what you checked in the game: the border, chests and signs, mobs, your inventory, the Nether / End;
- the report WorldBridge shows at the end of the conversion (or the command line output).

**Console saves** (Xbox 360, PS3, Wii U, PS4, Xbox One, Switch) are implemented from the formats but
have not been tested on real files yet. A report on any of them, in either direction, is the most
valuable test there is.

## Bug reports

Open a [bug report](https://github.com/zazazel456/WorldBridge/issues/new?template=bug_report.yml).
Include the command or the steps in the interface, the full error, and your Linux distribution. If
you can share the world (or a small part of it, selected on the map), attach it or link it: most
conversion bugs can only be fixed with the world that shows them.

Do not attach anything you do not want public: worlds can contain player names and account ids.

## Pull requests

- Open an issue first for anything larger than a small fix, so we can agree on the approach.
- Keep changes focused; one topic per pull request.
- Run the tests before sending:

  ```bash
  .runtime/python/bin/python3 -m pip install -q pytest   # after the first ./run.sh
  .runtime/python/bin/python3 -m pytest -q tests
  .runtime/python/bin/python3 tools/matrix.py quick
  ```
- New conversion behaviour needs a test in `tests/`.
- Text shown to users goes through `tr()` and needs its Italian line in `worldbridge/i18n_it.py`
  (`tests/test_i18n.py` checks it).
- Never include game code or files (jars, decompiled sources, assets). Port behaviour, and say in
  [CREDITS.md](CREDITS.md) where it comes from.

## Licence of contributions

WorldBridge is source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE). By
sending a contribution you agree that it is published under the same licence, with the same
additional permission for converted worlds described in the README.

"""Command line interface.

Examples::

    worldbridge info  path/to/world
    worldbridge convert path/to/saveData.ms out/ --to java
    worldbridge convert myworld/ out/ --to lce --platform win64
    worldbridge convert myworld/ out/ --to bedrock --version 1.21.0
    worldbridge players path/to/world
    worldbridge convert world/ out/ --to java --chunks base.csv --spawn 120,70,-40 --player host=Steve
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from . import APP_NAME, __version__, i18n
from . import amulet_bridge as ab
from .convert import TargetSpec, convert
from .detect import detect
from .i18n import tr
from .model import ConversionCancelled, ConversionError, Progress


def _parse_version(s: str, family: str = "java"):
    """--version as the version actually written (26.3 -> 26.3.0; 1.21.11 -> the newest known before it)."""
    try:
        v = tuple(int(x) for x in s.strip().split("."))
    except ValueError:
        raise SystemExit(tr("--version: '{version}' is not a version number (e.g. 1.20.1 or 26.3)", version=s))
    if family not in ("java", "bedrock"):
        return v
    try:
        got, exact = ab.resolve_version(family, v)
    except ValueError:
        raise SystemExit(tr("--version: {version} is not a {edition} version WorldBridge knows "
                            "(see 'worldbridge versions')", version=s, edition=family.capitalize()))
    if not exact:
        print(tr("Note: {version} is written as {known}, the newest version WorldBridge knows before it; "
                 "the game upgrades it when the world is opened.", version=s, known=ab.version_str(got)))
    return got


def _selection(args):
    from .model import NETHER, OVERWORLD, THE_END
    from .selection import PlayerLink, Selection, load_csv

    sel = Selection()
    if args.chunks:
        sel.chunks = {}
        dims = {"overworld": OVERWORLD, "nether": NETHER, "end": THE_END, "the_nether": NETHER, "the_end": THE_END}
        for spec in args.chunks:
            dim, path = OVERWORLD, spec
            head, _, rest = spec.partition(":")
            if rest and head.lower() in dims:
                dim, path = dims[head.lower()], rest
            sel.chunks.setdefault(dim, set()).update(load_csv(path))
    dims = {"overworld": OVERWORLD, "nether": NETHER, "end": THE_END, "the_nether": NETHER, "the_end": THE_END}
    for spec in getattr(args, "biome", None) or []:
        from .biomes import parse

        name, _, rest = spec.partition("=")
        dim, path = OVERWORLD, rest
        head, _, tail = rest.partition(":")
        if tail and head.lower() in dims:
            dim, path = dims[head.lower()], tail
        bid = parse(name)
        sel.biomes.setdefault(dim, {}).update({c: bid for c in load_csv(path)})
    if args.spawn:
        sel.spawn = tuple(int(float(v)) for v in args.spawn.split(","))
    move = getattr(args, "move_to", None)
    if move:
        if sel.chunks is None:
            raise SystemExit(tr("--move-to moves the selected chunks: give --chunks too"))
        sel.move_to = (0, 0) if move.lower() in ("centro", "center", "0") else tuple(
            int(float(v)) for v in move.split(","))[:2]
    if args.player:
        sel.players = []
        for i, spec in enumerate(args.player):
            key, _, nick = spec.partition("=")
            sel.players.append(PlayerLink(key=key, host=i == 0, nickname=nick or None, online=not args.offline))
    return sel if sel.active else None


def _trim_args(p, prefix: str) -> None:
    p.add_argument(f"--{prefix}min-time", default="1m", metavar=tr("DURATION"),
                   help=tr("minimum time spent near a chunk to keep it (e.g. 30s, 1m, 5m, 2h or ticks; default 1m)"))
    p.add_argument(f"--{prefix}ring", type=int, default=1, metavar="N",
                   help=tr("chunks kept around every used chunk (default 1)"))
    p.add_argument(f"--{prefix}spawn-radius", type=int, default=2, metavar="N",
                   help=tr("chunks around the spawn always kept (default 2, -1 = none)"))
    p.add_argument(f"--{prefix}drop-forced", action="store_true", help=tr("do not protect the chunks loaded with /forceload"))
    p.add_argument(f"--{prefix}drop-unknown", action="store_true",
                   help=tr("also remove the chunks whose InhabitedTime cannot be read"))


def _trim_options(args, prefix: str):
    from .trim import TrimOptions, parse_duration

    g = lambda k: getattr(args, (prefix + k).replace("-", "_"))  # noqa: E731
    return TrimOptions(min_ticks=parse_duration(g("min-time")), ring=max(0, g("ring")), spawn_radius=g("spawn-radius"),
                       keep_forced=not g("drop-forced"), keep_unknown=not g("drop-unknown"))


def _cmd_trim(args) -> int:
    from . import trim
    from .model import ConversionError
    from .selection import save_csv

    opt = _trim_options(args, "")
    prog = Progress(lambda f, m: (sys.stdout.write(f"\r[{int(f * 100):3d}%] {m[:70]:<70}"), sys.stdout.flush()),
                    lambda m: print("\n" + m))
    try:
        sc = trim.scan(args.world, prog)
    except ConversionError as ex:
        print("\n" + tr("Trim not available: {error}", error=ex))
        return 1
    keep = trim.plan(sc, opt)
    print(f"\n{opt.describe()}")
    names = {0: "overworld", -1: "nether", 1: "end"}
    for dim in trim.trim_dims(sc):
        tot = len(sc.inhabited[dim])
        print("  " + tr("{dim}: kept {kept} / {total}", dim=names.get(dim, dim), kept=len(keep[dim]), total=tot))
    print(tr("Total: {summary}", summary=trim.summary(sc, keep)))
    if args.csv:
        save_csv(args.csv, keep.get(0, set()))
        print(tr("Selection saved to {path}", path=args.csv))
    if args.dry_run or not args.output:
        if not args.output and not args.dry_run:
            print(tr("Give an output folder to write the trimmed world (the original world is not touched)."))
        return 0
    if not sc.can_copy:
        print(tr("For this format the trim is applied while converting: use 'convert ... --trim'."))
        return 1
    before = trim.folder_size(args.world)
    n = trim.trimmed_copy(args.world, args.output, keep, prog)
    after = trim.folder_size(args.output)
    print("\n" + tr("Done: {n} chunks removed · {before} → {after}  ({path})", n=n, before=trim.human_size(before),
                     after=trim.human_size(after), path=args.output))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="worldbridge",
                                description=f"{APP_NAME} {__version__} – " + tr("universal Minecraft world converter"))
    p.add_argument("--lang", choices=tuple(i18n.LANGUAGES), default=None,
                   help=tr("language of the messages (default: the system's)"))
    sub = p.add_subparsers(dest="cmd")
    i = sub.add_parser("info", help=tr("recognise the format of a world"))
    i.add_argument("path")
    c = sub.add_parser("convert", help=tr("convert a world"))
    c.add_argument("source")
    c.add_argument("output", help=tr("output folder (it will be created)"))
    c.add_argument("--to", required=True, choices=["java", "bedrock", "lce", "pe-old"])
    c.add_argument("--java-mode", default="auto", choices=["auto", "dfu", "numeric", "mcregion", "alpha", "amulet"],
                   help=tr("auto = latest version by the best route; dfu = a world upgraded by the game; "
                           "amulet = pre-converted to --version"))
    c.add_argument("--java-limit", default=None,
                   help=tr("target version inside the chosen format: --java-mode numeric 1.2 … 1.12; "
                           "mcregion b1.3, b1.4, b1.5, b1.6, b1.7, b1.8, 1.0, 1.1; alpha: alpha (Alpha 1.2.x), b1.2 "
                           "(Beta 1.0 – 1.2_02, default)"))
    c.add_argument("--version", default=None, help=tr("target version (e.g. 1.20.1 or 1.21.0)"))
    c.add_argument("--platform", default="win64",
                   help=tr("LCE platform: win64, xbox360, ps3, wiiu, vita, ps4, xboxone, switch"))
    c.add_argument("--profile", default="", help=tr("LCE console version: tu54 (default), tu46, tu31. "
                                                    "Windows64 is always neoLegacy TU31"))
    c.add_argument("--size", type=int, default=0,
                   help=tr("width of the LCE world in chunks (54, 64, 192, 320; default 320 for "
                           "Windows64/PS4/XB1/Switch/Wii U, 54 for X360/PS3/Vita)"))
    c.add_argument("--center-on-spawn", action="store_true", help=tr("centre the LCE world on the spawn"))
    c.add_argument("--offset", default="0,0", help=tr("source chunk that becomes the centre of the LCE world (x,z)"))
    c.add_argument("--name", default=None, help=tr("name of the target world"))
    c.add_argument("--player-id", default=None,
                   help=tr("LCE PC/Xbox: the XUID (file name in players/) for the main player"))
    c.add_argument("--y-offset", type=int, default=0)
    c.add_argument("--no-blend", action="store_true",
                   help=tr("Java / Bedrock 1.18+: no game blending (the chunks of a pre-1.18 world are written in the "
                           "new format: the game does not blend them with new terrain nor generate the part below y 0)"))
    c.add_argument("--no-ring", action="store_true",
                   help=tr("no WorldBridge ring (Java Alpha 1.2 – 1.17, neoLegacy, Nether and End) and no filling of "
                           "finite maps (PE 0.x, LCE 54 / 64 chunks)"))
    c.add_argument("--tall-terrain", choices=("compress", "cut"), default="compress",
                   help=tr("128-block-high worlds (Alpha, Beta, Java 1.0 – 1.1, PE 0.x): taller mountains are "
                           "compressed (default: the surface comes down whole) or cut at y 127"))
    c.add_argument("--depth", default="cut", metavar="cut|keep|Y",
                   help=tr("1.18+ worlds to games that start at y 0: cut = the underground below y 0 is dropped "
                           "(default), keep = everything kept (the world rises by 64), negative Y = kept from that y"))
    c.add_argument("--regen", action="append", default=[], choices=("nether", "end"),
                   help=tr("do not convert the Nether / the End: the game generates them anew when first entered "
                           "(repeatable)"))
    c.add_argument("--chunks", action="append", default=[], metavar="[DIM:]FILE",
                   help=tr("convert only the chunks of an MCA Selector CSV file (DIM = overworld, nether, end; "
                           "repeatable). Dimensions without a file are left out"))
    c.add_argument("--biome", action="append", default=[], metavar=tr("BIOME") + "=[DIM:]FILE",
                   help=tr("give a biome (name or number, e.g. plains, swampland, cherry_grove) to the chunks of an "
                           "MCA Selector CSV; repeatable"))
    c.add_argument("--spawn", default=None, metavar="X,Y,Z", help=tr("new world spawn point"))
    c.add_argument("--move-to", default=None, metavar="center|X,Z",
                   help=tr("move the selected chunks (--chunks): their centre goes to the world centre (0, 0) or to "
                           "the given X,Z coordinates, with the entities, spawn and players on them"))
    c.add_argument("--player", action="append", default=[], metavar=tr("KEY") + "[=NICKNAME]",
                   help=tr("players to transfer (the first becomes the main player) and the nicknames to link them "
                           "to; KEY as shown by 'worldbridge players'. Repeatable"))
    c.add_argument("--offline", action="store_true", help=tr("Java: use offline UUIDs (non-premium servers)"))
    c.add_argument("--bta-palette", default=None, metavar="FILE",
                   help=tr("Better than Adventure: .properties file choosing the vanilla woods of BTA's painted wood "
                           "(see worldbridge/bta/data/palette.example.properties)"))
    c.add_argument("--bta-y-offset", type=int, default=None, metavar="N",
                   help=tr("Better than Adventure: how many blocks to lower the Overworld (default automatic: the "
                           "BTA sea ends at y 63, e.g. 65 for \"extended\" worlds)"))
    c.add_argument("--trim", action="store_true",
                   help=tr("convert only the chunks really used (world trim by InhabitedTime; default: < 1 minute = "
                           "removed, 1-chunk protective ring, spawn ±2 chunks)"))
    _trim_args(c, "trim-")
    tp = sub.add_parser("trim", help=tr("copy of the world without the chunks never used (world trim by InhabitedTime)"))
    tp.add_argument("world")
    tp.add_argument("output", nargs="?", default=None, help=tr("folder of the trimmed world (it will be created)"))
    tp.add_argument("--dry-run", action="store_true", help=tr("only show how many chunks would be removed"))
    tp.add_argument("--csv", default=None, metavar="FILE",
                    help=tr("save the chunks to keep (Overworld) as an MCA Selector selection"))
    _trim_args(tp, "")
    pl = sub.add_parser("players", help=tr("list the players saved in a world"))
    pl.add_argument("path")
    sub.add_parser("versions", help=tr("list the supported Java / Bedrock versions"))
    return p


def _early_language(argv) -> None:
    """--lang must be known before the help texts are built."""
    argv = list(sys.argv[1:] if argv is None else argv)
    for k, a in enumerate(argv):
        if a == "--lang" and k + 1 < len(argv):
            i18n.set_language(argv[k + 1])
        elif a.startswith("--lang="):
            i18n.set_language(a.split("=", 1)[1])


def main(argv=None) -> int:
    _early_language(argv)
    args = build_parser().parse_args(argv)
    if args.cmd == "info":
        d = detect(args.path)
        if not d:
            print(tr("Format not recognised"))
            return 1
        print(f"{d.description}\n  " + tr("path: {path}", path=d.path))
        if d.kind == "bta":
            from .bta.world import BtaWorld, DIMENSION_NAMES, auto_shift, ocean_y

            w = BtaWorld(d.path)
            wt = w.world_type()
            print("  " + tr("name: {name} · save version {version}", name=w.name, version=w.save_version))
            print("  " + tr("Overworld “{type}” (sea at y {sea}): it will be lowered by {blocks} blocks",
                            type=wt or "?", sea=ocean_y(wt), blocks=auto_shift(wt)))
            for dim in w.dimensions():
                print("  " + tr("{dim}: {n} regions", dim=DIMENSION_NAMES[dim], n=len(w.regions(dim))))
            print("  " + tr("possible target: Java 26.3 (--to java)"))
        return 0
    if args.cmd == "players":
        from .mapview import open_map

        src = open_map(args.path)
        try:
            print(f"{src.description}  ·  spawn {src.spawn}")
            for p in src.players:
                pos = ", ".join(f"{v:.0f}" for v in p.pos) if p.pos else "?"
                print(f"  {p.key:<44} {p.label if p.label != p.key else '':<28} pos {pos}  dim {p.dim}")
        finally:
            src.close()
        return 0
    if args.cmd == "trim":
        return _cmd_trim(args)
    if args.cmd == "versions":
        print("Java:   ", ", ".join(ab.version_str(v) for v in ab.versions("java")))
        print("Bedrock:", ", ".join(ab.version_str(v) for v in ab.versions("bedrock")))
        return 0
    if args.cmd == "convert":
        fam = {"pe-old": "pe_old"}.get(args.to, args.to)
        ox, oz = (int(v) for v in args.offset.split(","))
        t = TargetSpec(family=fam, java_mode=args.java_mode, java_version_limit=args.java_limit,
                       version=_parse_version(args.version, fam) if args.version else None, lce_platform=args.platform,
                       lce_profile=args.profile, lce_world_size=args.size, lce_offset=(ox, oz),
                       lce_center_on_spawn=args.center_on_spawn, lce_player_id=args.player_id, world_name=args.name,
                       y_offset=args.y_offset, blend=not args.no_blend, ring=not args.no_ring, bta_palette=args.bta_palette,
                       bta_y_offset=args.bta_y_offset, tall_terrain=args.tall_terrain,
                       regen=tuple({"nether": -1, "end": 1}[d] for d in dict.fromkeys(args.regen)),
                       depth=args.depth if args.depth in ("cut", "keep") else int(args.depth))
        t.selection = _selection(args)
        if args.trim:
            t.trim = _trim_options(args, "trim_")
        last = [-1]

        def on_progress(frac, msg):
            pct = int(frac * 100)
            if pct != last[0]:
                last[0] = pct
                sys.stdout.write(f"\r[{pct:3d}%] {msg[:70]:<70}")
                sys.stdout.flush()

        prog = Progress(on_progress, lambda m: print("\n" + m))
        if fam == "java" and args.java_mode == "alpha" and \
                not re.fullmatch(r"World[1-5]", os.path.basename(os.path.normpath(args.output))):
            print(tr("Note: Alpha and Beta up to 1.2_02 only see the World1 … World5 folders of .minecraft/saves: "
                     "rename the output folder to one of them."))
        try:
            res = convert(args.source, args.output, t, prog)
        except ConversionCancelled:
            print("\n" + tr("Cancelled"))
            return 2
        except ConversionError as ex:
            print("\n" + tr("Error: {error}", error=ex))
            return 1
        print("\n" + tr("Done: {path}  ({n} chunks, {seconds}s)", path=res.output, n=res.chunks, seconds=f"{res.seconds:.1f}"))
        for w in res.warnings:
            print("  ⚠", w)
        return 0
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Generate worldbridge/mapcolors.py from a Minecraft Java client jar: the map colour (MapColor) of
every block, as the game draws it on a map, and the blocks a map sees through (MapColor.NONE).

    python3 tools/mapcolors.py minecraft-26.3-client.jar

It reads with ``javap`` (a JDK is needed) the bytecode of
* net/minecraft/world/level/block/Blocks: each block's properties, where the colour is
  ``mapColor(MapColor.X)``, a colour handed to a helper (``logProperties(top, side)`` gives the
  top), the colour of another block (``ofFullCopy``, ``ofLegacyCopy``, ``defaultMapColor``, the
  helpers that copy: ``registerLegacyStair``...), or, for the 16-colour families (wool, concrete...),
  what the family's properties lambda does with its DyeColor;
* net/minecraft/world/level/material/MapColor: the RGB of each colour;
* net/minecraft/world/item/DyeColor: the 16 colours, their names and map colours;
* net/minecraft/references/BlockItemIds, BlockIds: the block names.
The jar must not be obfuscated (Java 26.x jars are not).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile

CLASSES = {
    "blocks": "net/minecraft/world/level/block/Blocks.class",
    "mapcolor": "net/minecraft/world/level/material/MapColor.class",
    "dyecolor": "net/minecraft/world/item/DyeColor.class",
    "itemids": "net/minecraft/references/BlockItemIds.class",
    "blockids": "net/minecraft/references/BlockIds.class",
}
FIELD = re.compile(r"// Field (?:([\w/$]+)\.)?(\w+):L([\w/$]+)[;<]")
METHOD = re.compile(r"// (?:Interface)?Method (?:([\w/$]+)\.)?([\w<>$]+):(\S*)")
INDY = re.compile(r"// InvokeDynamic #(\d+):")
HEADER = re.compile(r"^  (?:(?:private|public|protected|static|final|synchronized) )*[\w.$<>\[\], ?]+ ([\w$]+)\((.*)\);$")


def javap(jar: str, entry: str, tmp: str, verbose: bool = False) -> str:
    with zipfile.ZipFile(jar) as z:
        path = os.path.join(tmp, entry)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(z.read(entry))
    args = ["javap", "-c", "-p"] + (["-v"] if verbose else []) + [path]
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def methods(code: str) -> dict:
    """method name -> its bytecode lines (static {} is "<clinit>")."""
    out, name, body = {}, None, []
    for line in code.splitlines():
        m = HEADER.match(line)
        if m or line.strip() == "static {};":
            if name:
                out.setdefault(name, body)
            name, body = (m.group(1) if m else "<clinit>"), []
        elif name:
            body.append(line)
    if name:
        out.setdefault(name, body)
    return out


def bootstrap_lambdas(verbose: str) -> dict:
    """bootstrap index -> the Blocks.lambda$... method it makes."""
    out, idx = {}, None
    text = verbose[verbose.find("BootstrapMethods:"):]
    for line in text.splitlines():
        m = re.match(r"\s+(\d+): #\d+ REF_invoke", line)
        if m:
            idx = int(m.group(1))
            continue
        m = re.search(r"REF_invoke\w+ [\w/$]+/Blocks\.([\w$]+):", line)
        if m and idx is not None and idx not in out:
            out[idx] = m.group(1)
    return out


def ids(code: str) -> dict:
    """FIELD -> "name" from BlockItemIds / BlockIds (ldc "name"; ... putstatic FIELD).  With two
    names (``create("redstone_wire", "redstone")``) the first is the block's, the second its item's."""
    out, last = {}, None
    for line in code.splitlines():
        m = re.search(r"// String (\S+)$", line)
        if m:
            last = last or m.group(1)
            continue
        f = FIELD.search(line)
        if "putstatic" in line and f and last:
            out[f.group(2)] = last
            last = None
    return out


def map_colors(code: str) -> dict:
    """MapColor FIELD -> (r, g, b) (new MapColor(id, rgb); putstatic FIELD)."""
    out, ints = {}, []
    for line in methods(code).get("<clinit>", []):
        f = FIELD.search(line)
        if "putstatic" in line and f and f.group(3).endswith("MapColor"):
            if len(ints) >= 2:
                rgb = ints[-1] & 0xFFFFFF
                out[f.group(2)] = ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)
            ints = []
            continue
        m = re.search(r"\b(?:bipush|sipush)\s+(-?\d+)|iconst_(\d)|// int (-?\d+)", line)
        if m:
            ints.append(int(next(g for g in m.groups() if g is not None)))
    return out


def dye_colors(code: str) -> list:
    """[(name, MapColor FIELD)] of the 16 DyeColors, in their order."""
    out, name, color = [], None, None
    for line in methods(code).get("<clinit>", []):
        m = re.search(r"// String (\w+)$", line)
        if m and name is None:
            name = m.group(1)
        f = FIELD.search(line)
        if f and "getstatic" in line and f.group(3).endswith("MapColor") and color is None:
            color = f.group(2)
        if f and "putstatic" in line and f.group(3).endswith("DyeColor"):
            if name and color:
                out.append((name, color))
            name, color = None, None
    return out


def _classify(body: list, helpers: dict, meth: dict = None, lambdas: dict = None, depth: int = 0) -> str:
    """What a properties lambda (DyeColor -> Properties) gives its block: "DYE", "TERRACOTTA",
    a MapColor FIELD or "NONE".  A colour computed per block state (``mapColor(state -> ...)``,
    beds: the dye on the foot, wool on the head) is read from that nested lambda."""
    text = "\n".join(body)
    if depth < 2 and meth and lambdas:
        for line in body:
            d = INDY.search(line)
            nested = lambdas.get(int(d.group(1))) if d else None
            if nested and nested in meth:
                kind = _classify(meth[nested], helpers, meth, lambdas, depth + 1)
                if kind != "NONE":
                    return kind
    if "DyeColor.getMapColor" in text or re.search(r"mapColor:\(Lnet/minecraft/world/item/DyeColor;\)", text):
        return "DYE"
    if "erracotta" in text:
        return "TERRACOTTA"
    for line in body:
        f = FIELD.search(line)
        if f and "getstatic" in line and f.group(3).endswith("MapColor"):
            return f.group(2)
        m = METHOD.search(line)
        if m and m.group(1) is None and helpers.get(m.group(2), {}).get("color"):
            return helpers[m.group(2)]["color"]
    return "NONE"


def _copper_kind(meth: dict, lambdas: dict, lam, depth: int = 0):
    """What a copper family's properties (WeatherState -> Properties) give its blocks: "STATE:<4
    MapColors>" (one per weather state, unaffected first, as a switch on the state), "COPY:<family>"
    (``ofFullCopy`` of another family's block of the same state), a MapColor FIELD, or None."""
    body = meth.get(lam or "", [])
    cols, fam = [], None
    for line in body:
        f = FIELD.search(line)
        if f and "getstatic" in line and f.group(3).endswith("MapColor"):
            cols.append(f.group(2))
        elif f and "getstatic" in line and f.group(1) is None and f.group(3).endswith("WeatheringCopperCollection"):
            fam = f.group(2)
        d = INDY.search(line)
        if d and depth < 2:                  # mapColor(state -> ...): the colour per block state
            k = _copper_kind(meth, lambdas, lambdas.get(int(d.group(1))), depth + 1)
            if k and k.startswith(("STATE:", "COPY:")):
                return k
    if len(cols) >= 4:
        return "STATE:" + ",".join(cols[:4])
    text = "\n".join(body)
    if fam and ("ofFullCopy" in text or "defaultMapColor" in text):
        return "COPY:" + fam
    return cols[0] if cols else None


def block_colors(code: str, verbose: str, names: dict) -> dict:
    """block name -> MapColor FIELD, "DYE:<dye>", "TERRACOTTA:<dye>" or "NONE"."""
    meth = methods(code)
    lambdas = bootstrap_lambdas(verbose)
    helpers = {}
    for name, body in meth.items():
        if name == "<clinit>":
            continue
        text = "\n".join(body)
        color = next((FIELD.search(l).group(2) for l in body if "getstatic" in l and FIELD.search(l)
                      and FIELD.search(l).group(3).endswith("MapColor")), None)
        helpers[name] = {"color": color, "copies": "ofFullCopy" in text or "ofLegacyCopy" in text}
    blocks, collections, coppers = {}, {}, {}
    cur = None
    for line in meth["<clinit>"]:
        f, m, d = FIELD.search(line), METHOD.search(line), INDY.search(line)
        if f and "getstatic" in line:
            owner, field, typ = f.groups()
            if owner and owner.endswith(("BlockItemIds", "BlockIds")) and cur is None:
                cur = {"name": names.get(field, field.lower()), "colors": [], "copy": None, "last": None,
                       "dye": None, "helper": None, "lambdas": [], "base": None,
                       "collection": typ.endswith("ColorCollection")}
            elif cur is None:
                continue
            elif typ.endswith("MapColor"):
                cur["colors"].append(field)
            elif typ.endswith("DyeColor"):
                cur["dye"] = field
            elif owner is None and typ.endswith("level/block/Block"):
                cur["last"] = field
            elif owner is None and typ.endswith("ColorCollection"):
                cur["base"] = field
        elif cur is not None and d:
            cur["lambdas"].append(lambdas.get(int(d.group(1))))
        elif cur is not None and m:
            owner, name, _sig = m.groups()
            if name in ("ofFullCopy", "ofLegacyCopy", "defaultMapColor") and cur["last"]:
                cur["copy"] = cur["last"]
            elif name == "mapColor" and "DyeColor" in line and cur["dye"]:
                cur["colors"].append("DYE:" + cur["dye"])
            elif name == "mapColor" and "Function" in line and cur["lambdas"]:
                # mapColor(state -> ...): the first colour of that lambda (wheat: PLANT, then yellow)
                body = meth.get(cur["lambdas"][-1] or "", [])
                for l in body:
                    fl = FIELD.search(l)
                    if fl and "getstatic" in l and fl.group(3).endswith("MapColor"):
                        cur["colors"].append(fl.group(2))
                        break
                    if fl and "getstatic" in l and fl.group(1) is None and fl.group(3).endswith("level/block/Block"):
                        cur["copy"] = fl.group(2)
                        break
            elif owner is None and name in helpers:
                h = helpers[name]
                if h["copies"] and cur["last"]:
                    cur["copy"] = cur["last"]
                elif h["color"] and not cur["helper"]:
                    cur["helper"] = h["color"]
        if f and "putstatic" in line and cur is not None:
            field, typ = f.group(2), f.group(3)
            if typ.endswith("WeatheringCopperCollection"):
                kind = None
                for lam in cur["lambdas"]:
                    k = _copper_kind(meth, lambdas, lam)
                    if k and (kind is None or k.startswith(("STATE:", "COPY:"))):
                        kind = k
                coppers[field] = (cur["name"], kind)
                cur = None
            elif typ.endswith("ColorCollection"):
                kind = None
                for lam in cur["lambdas"]:
                    body = meth.get(lam or "", [])
                    sig = next((l for l in code.splitlines() if HEADER.match(l) and HEADER.match(l).group(1) == lam), "")
                    if "DyeColor)" in sig and "Properties " in sig:
                        kind = _classify(body, helpers, meth, lambdas)
                collections[field] = (cur["name"], kind, cur["base"])
                cur = None
            elif typ.endswith("level/block/Block"):
                blocks[field] = (cur["name"], cur["colors"][0] if cur["colors"] else cur["helper"], cur["copy"])
                cur = None
            else:
                cur = None                                  # something else kept in Blocks
    out = {}

    def color_of(field, seen=()):
        name, color, copy = blocks[field]
        if color is None and copy in blocks and copy not in seen:
            return color_of(copy, seen + (field,))
        return color or "NONE"

    for field, (name, _c, _p) in blocks.items():
        out[name] = color_of(field)
    out["__collections__"] = collections
    out["__coppers__"] = coppers
    return out


# the four weather states of copper: the prefix of their blocks' names
COPPER_STATES = ("", "exposed_", "weathered_", "oxidized_")


def copper_names(base: str) -> list:
    """The 8 blocks of a copper family, by state then waxed: copper_block's family is named
    copper_block, exposed_copper, weathered_copper, oxidized_copper (and waxed_...)."""
    if base in ("copper", "copper_block"):
        plain = ["copper_block"] + [p + "copper" for p in COPPER_STATES[1:]]
    else:
        plain = [p + base for p in COPPER_STATES]
    return plain + ["waxed_" + n for n in plain]


def main(jar: str, dest: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code = {k: javap(jar, v, tmp) for k, v in CLASSES.items()}
        verbose = javap(jar, CLASSES["blocks"], tmp, verbose=True)
    names = {**ids(code["blockids"]), **ids(code["itemids"])}
    rgb = map_colors(code["mapcolor"])
    dyes = dye_colors(code["dyecolor"])
    blocks = block_colors(code["blocks"], verbose, names)
    collections = blocks.pop("__collections__")
    coppers = blocks.pop("__coppers__")
    by_base = {base: kind for base, kind in coppers.values()}

    def copper_kind(base, seen=()):
        kind = by_base.get(base)
        if kind and kind.startswith("COPY:") and kind[5:] in coppers and base not in seen:
            return copper_kind(coppers[kind[5:]][0], seen + (base,))
        if kind is None and base not in seen:   # cut_copper_stairs...: as their family (cut_copper)
            parent = base.rsplit("_", 1)[0]
            return copper_kind(parent, seen + (base,)) if parent in by_base else "NONE"
        return kind or "NONE"

    for base, _kind in coppers.values():
        kind = copper_kind(base)
        states = kind[6:].split(",") if kind.startswith("STATE:") else [kind] * 4
        for i, name in enumerate(copper_names(base)):
            blocks[name] = states[i % 4]

    by_base = {base: field for field, (base, _k, _s) in collections.items()}

    def family(field, seen=()):
        base, kind, src = collections[field]
        # wool_stairs, concrete_slab...: zipped with their family, the properties copied from it
        src = src or by_base.get(base.rsplit("_", 1)[0])
        if kind is None and src in collections and src not in seen:
            return family(src, seen + (field,))
        return kind or "NONE"

    for field, (base, _kind, _src) in collections.items():
        kind = family(field)
        for dye, dye_color in dyes:
            terracotta = "TERRACOTTA_" + dye.upper()
            if terracotta not in rgb:              # lime: TERRACOTTA_LIGHT_GREEN, as its dye colour
                terracotta = "TERRACOTTA_" + dye_color.replace("COLOR_", "")
            color = {"DYE": dye_color, "TERRACOTTA": terracotta}.get(kind, kind)
            blocks[f"{dye.lower()}_{base}"] = color
    for name, c in list(blocks.items()):
        if c.startswith("DYE:"):
            blocks[name] = dict((d.upper(), mc) for d, mc in dyes).get(c[4:], "NONE")
    with zipfile.ZipFile(jar) as z:
        version = re.search(r'"name": "([^"]+)"', z.read("version.json").decode()).group(1)
    colors = {n: rgb[c] for n, c in sorted(blocks.items()) if c in rgb and c != "NONE"}
    clear = sorted(n for n, c in blocks.items() if c == "NONE" or c not in rgb)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(f'"""Map colours of Minecraft Java {version} (MapColor), generated by tools/mapcolors.py from the\n'
                'game\'s client jar: do not edit by hand."""\n\n')
        f.write(f"VERSION = {version!r}\n\n")
        f.write("# block -> the colour a map draws it with\n")
        f.write("MAP_COLORS = {\n")
        for n, c in colors.items():
            f.write(f"    {n!r}: {c},\n")
        f.write("}\n\n# blocks a map sees through (MapColor.NONE): it draws the block under them\n")
        f.write("SEE_THROUGH = frozenset({\n")
        for n in clear:
            f.write(f"    {n!r},\n")
        f.write("})\n")
    print(f"{len(colors)} colours, {len(clear)} see-through blocks -> {dest}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "..", "worldbridge", "mapcolors.py"))

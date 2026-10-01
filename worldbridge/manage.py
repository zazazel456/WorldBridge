"""World management: the NBT documents of a world (its level.dat and its players), for the editor of
the "Gestione mondo" tab and for scripts.

Every kind of world opens as a list of documents, each a compound tag that can be edited freely and
saved back in the world's own format:

* Java (Alpha to the latest, and Better than Adventure): level.dat (gzip) and the player files
  (players/, playerdata/, players/data/);
* Bedrock and Pocket Edition 0.9+ (LevelDB): level.dat (8 byte header, little endian) and the
  players stored in the database (~local_player, player_server_...);
* Pocket Edition 0.1 - 0.8 (chunks.dat): level.dat (its player is inside it);
* Legacy Console Edition: level.dat and the player files inside the save container (an Xbox 360
  save packed in an STFS package can be read but not written back).

``quick_fields`` lists the common settings (name, seed, game mode, difficulty, spawn, time,
weather...) as paths into the documents, which differ from one kind of world to the other; the
editor shows them as a form above the tree of every tag.  Saving first copies the files it replaces
(``*.wb-backup``), so a change can always be undone by hand.
"""

from __future__ import annotations

import glob
import os
import shutil
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import nbt
from .i18n import N_, tr


@dataclass
class Doc:
    key: str                       # where it lives: "level.dat", "players/<uuid>.dat", "~local_player"...
    label: str                     # what the editor shows
    root: nbt.CompoundTag          # the document (for level.dat of Java: the whole file, with "Data")
    kind: str = "level"            # "level" | "player"
    dirty: bool = False


@dataclass
class QuickField:
    label: str
    doc: str                       # Doc.key
    path: Tuple[str, ...]          # keys from the document's root
    kind: str                      # "text" | "int" | "long" | "bool" | "choice" | "float"
    choices: Optional[Dict[int, str]] = None


GAME_MODES = {0: N_("Survival"), 1: N_("Creative"), 2: N_("Adventure"), 3: N_("Spectator")}
DIFFICULTIES = {0: N_("Peaceful"), 1: N_("Easy"), 2: N_("Normal"), 3: N_("Hard")}


@dataclass
class WorldDocs:
    path: str
    kind: str                      # "java" | "bedrock" | "pe_old" | "lce"
    description: str
    docs: List[Doc] = field(default_factory=list)
    read_only: bool = False
    _save: Optional[Callable[["WorldDocs"], None]] = None

    def doc(self, key: str) -> Optional[Doc]:
        return next((d for d in self.docs if d.key == key), None)

    # ------------------------------------------------------------------ quick settings
    def quick_fields(self) -> List[QuickField]:
        if self.kind == "java":
            return _java_fields(self)
        if self.kind in ("bedrock", "pe_old"):
            return _bedrock_fields(self)
        if self.kind == "lce":
            return _lce_fields(self)
        return []

    def player_fields(self, doc: Doc) -> List[QuickField]:
        """The common values of a player: where it is, its health, experience and game mode."""
        r = doc.root
        out = []
        if isinstance(nbt.get_tag(r, "Pos"), nbt.ListTag):
            out += [QuickField(tr("Position {axis}", axis=a), doc.key, ("Pos", str(i)), "float") for i, a in enumerate("XYZ")]
        for key, label, kind in (("Health", tr("Health"), "float"), ("foodLevel", tr("Hunger"), "int"),
                                 ("XpLevel", tr("Experience level"), "int"), ("PlayerLevel", tr("Experience level"), "int"),
                                 ("Score", tr("Score"), "int")):
            if key in r:
                out.append(QuickField(label, doc.key, (key,), kind))
        if "playerGameType" in r:
            out.append(QuickField(tr("Game mode"), doc.key, ("playerGameType",), "choice", GAME_MODES))
        if "PlayerGameMode" in r:                           # Bedrock: 5 follows the world's mode
            out.append(QuickField(tr("Game mode"), doc.key, ("PlayerGameMode",), "choice",
                                  {0: GAME_MODES[0], 1: GAME_MODES[1], 2: GAME_MODES[2], 5: tr("Same as the world"),
                                   6: tr("Spectator")}))
        dim = nbt.get_tag(r, "Dimension")
        if dim is not None:
            out.append(QuickField(tr("Dimension"), doc.key, ("Dimension",), "text" if isinstance(dim, nbt.StringTag) else "int"))
        return out

    def get(self, f: QuickField):
        d = self.doc(f.doc)
        tag = d.root if d else None
        for k in f.path:
            if isinstance(tag, _ARRAYS):
                return int(tag[int(k)]) if int(k) < len(tag) else None
            if not isinstance(tag, (nbt.CompoundTag, nbt.ListTag)):
                return None
            tag = tag[int(k)] if isinstance(tag, nbt.ListTag) else nbt.get_tag(tag, k)
        return None if tag is None else tag.py_data

    def set(self, f: QuickField, value) -> None:
        d = self.doc(f.doc)
        if d is None:
            return
        parent = d.root
        for k in f.path[:-1]:
            nxt = parent[int(k)] if isinstance(parent, nbt.ListTag) else nbt.get_tag(parent, k)
            if nxt is None:
                nxt = nbt.CompoundTag()
                parent[k] = nxt
            parent = nxt
        last = f.path[-1]
        if isinstance(parent, _ARRAYS):                  # an element of an int / long / byte array
            vals = [int(v) for v in parent]
            vals[int(last)] = int(value)
            grand = d.root
            for k in f.path[:-2]:
                grand = grand[int(k)] if isinstance(grand, nbt.ListTag) else nbt.get_tag(grand, k)
            grand[f.path[-2]] = type(parent)(vals)
            d.dirty = True
            return
        old = parent[int(last)] if isinstance(parent, nbt.ListTag) else nbt.get_tag(parent, last)
        new = _like(old, value, f.kind)
        if isinstance(parent, nbt.ListTag):
            parent[int(last)] = new
        else:
            parent[last] = new
        d.dirty = True

    # ------------------------------------------------------------------ saving
    def save(self) -> None:
        if self.read_only or self._save is None:
            raise PermissionError(tr("This world is read-only."))
        self._save(self)
        for d in self.docs:
            d.dirty = False


_ARRAYS = (nbt.IntArrayTag, nbt.LongArrayTag, nbt.ByteArrayTag)


def _like(old, value, kind: str):
    """A tag of the old one's type (or of ``kind``) holding ``value``."""
    t = type(old) if old is not None else None
    if t is None:
        t = {"text": nbt.StringTag, "int": nbt.IntTag, "long": nbt.LongTag, "bool": nbt.ByteTag,
             "choice": nbt.IntTag, "float": nbt.FloatTag}[kind]
    if t is nbt.StringTag or kind == "text" or isinstance(value, str) and not str(value).lstrip("-").isdigit():
        return nbt.StringTag(str(value))
    if t in (nbt.FloatTag, nbt.DoubleTag):
        return t(float(value))
    return t(int(value))


def _backup(path: str) -> None:
    if os.path.isfile(path):
        shutil.copy2(path, path + ".wb-backup")


# ============================================================ Java

def _java_player_files(world: str) -> List[str]:
    out = []
    for sub in ("players", "playerdata", os.path.join("players", "data")):
        out += sorted(glob.glob(os.path.join(world, sub, "*.dat")))
    return out


def _open_java(path: str) -> WorldDocs:
    with open(os.path.join(path, "level.dat"), "rb") as f:
        raw = f.read()
    gz = raw[:2] == b"\x1f\x8b"
    root = nbt.load(raw, compressed=gz).tag
    data = nbt.get_tag(root, "Data") or root
    ver = nbt.get_tag(data, "Version")
    name = nbt.get(ver, "Name") if isinstance(ver, nbt.CompoundTag) else None
    desc = f"Java Edition {name}" if name else tr("Java Edition (up to 1.8)") if "version" not in data else \
        "Java Edition " + tr("(format {version})", version=nbt.get(data, "version"))
    w = WorldDocs(path, "java", desc)
    w.docs.append(Doc("level.dat", tr("World (level.dat)"), root))
    # Java 26.x keeps the seed, the game rules, the weather and the clocks in files of their own
    for name, label in (("world_gen_settings", tr("Generation (seed)")), ("game_rules", tr("Game rules")),
                        ("weather", tr("Weather")), ("world_clocks", tr("Clocks"))):
        p = os.path.join(path, "data", "minecraft", name + ".dat")
        if os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    draw = f.read()
                w.docs.append(Doc(os.path.relpath(p, path), label, nbt.load(draw, compressed=draw[:2] == b"\x1f\x8b").tag))
            except Exception:  # noqa: BLE001
                pass
    for p in _java_player_files(path):
        try:
            with open(p, "rb") as f:
                praw = f.read()
            w.docs.append(Doc(os.path.relpath(p, path), tr("Player {name}", name=os.path.splitext(os.path.basename(p))[0]),
                              nbt.load(praw, compressed=praw[:2] == b"\x1f\x8b").tag, "player"))
        except Exception:  # noqa: BLE001
            pass
    w._save = _save_java
    return w


def _save_java(w: WorldDocs) -> None:
    for d in w.docs:
        if not d.dirty:
            continue
        p = os.path.join(w.path, d.key)
        _backup(p)
        with open(p, "wb") as f:
            f.write(nbt.dump(d.root, "", compressed=True))


def _java_fields(w: WorldDocs) -> List[QuickField]:
    data = nbt.get_tag(w.doc("level.dat").root, "Data")
    base = ("Data",) if data is not None else ()
    data = data if data is not None else w.doc("level.dat").root
    out = [QuickField(tr("Name"), "level.dat", base + ("LevelName",), "text")]
    wgs = os.path.join("data", "minecraft", "world_gen_settings.dat")
    if w.doc(wgs) is not None:                                                   # Java 26.x
        out.append(QuickField("Seed", wgs, ("data", "seed"), "long"))
        out += [QuickField(tr("Game mode"), "level.dat", base + ("GameType",), "choice", GAME_MODES),
                QuickField(tr("Difficulty"), "level.dat", base + ("difficulty_settings", "difficulty"), "choice",
                           {"peaceful": tr("Peaceful"), "easy": tr("Easy"), "normal": tr("Normal"), "hard": tr("Hard")}),
                QuickField("Hardcore", "level.dat", base + ("difficulty_settings", "hardcore"), "bool"),
                QuickField(tr("Commands (cheats)"), "level.dat", base + ("allowCommands",), "bool")]
        out += [QuickField(f"Spawn {a}", "level.dat", base + ("spawn", "pos", str(i)), "int") for i, a in enumerate("XYZ")]
        weather = os.path.join("data", "minecraft", "weather.dat")
        if w.doc(weather) is not None:
            out += [QuickField(tr("Rain"), weather, ("data", "raining"), "bool"),
                    QuickField(tr("Thunderstorm"), weather, ("data", "thundering"), "bool")]
        rules = os.path.join("data", "minecraft", "game_rules.dat")
        d = w.doc(rules)
        data_rules = nbt.get_tag(d.root, "data") if d is not None else None
        if isinstance(data_rules, nbt.CompoundTag):
            for k in sorted(data_rules.keys()):
                kind = "bool" if isinstance(data_rules[k], nbt.ByteTag) else "int"
                out.append(QuickField(tr("Rule: {name}", name=k.removeprefix("minecraft:")), rules, ("data", k), kind))
        return out
    if isinstance(nbt.get_tag(data, "WorldGenSettings"), nbt.CompoundTag):
        out.append(QuickField("Seed", "level.dat", base + ("WorldGenSettings", "seed"), "long"))
    else:
        out.append(QuickField("Seed", "level.dat", base + ("RandomSeed",), "long"))
    out += [QuickField(tr("Game mode"), "level.dat", base + ("GameType",), "choice", GAME_MODES),
            QuickField(tr("Difficulty"), "level.dat", base + ("Difficulty",), "choice", DIFFICULTIES),
            QuickField("Hardcore", "level.dat", base + ("hardcore",), "bool"),
            QuickField(tr("Commands (cheats)"), "level.dat", base + ("allowCommands",), "bool")]
    sp = nbt.get_tag(data, "spawn")
    if isinstance(sp, nbt.CompoundTag) and nbt.get_tag(sp, "pos") is not None:          # 1.21.9+
        out += [QuickField(f"Spawn {a}", "level.dat", base + ("spawn", "pos", str(i)), "int") for i, a in enumerate("XYZ")]
    else:
        out += [QuickField(f"Spawn {a}", "level.dat", base + (f"Spawn{a}",), "int") for a in "XYZ"]
    out += [QuickField(tr("Time of day (ticks)"), "level.dat", base + ("DayTime",), "long"),
            QuickField(tr("Rain"), "level.dat", base + ("raining",), "bool"),
            QuickField(tr("Thunderstorm"), "level.dat", base + ("thundering",), "bool")]
    rules = nbt.get_tag(data, "GameRules")
    if isinstance(rules, nbt.CompoundTag):
        for k in sorted(rules.keys()):
            out.append(QuickField(tr("Rule: {name}", name=k), "level.dat", base + ("GameRules", k), "text"))
    return out


# ============================================================ Bedrock / Pocket Edition

def _read_bedrock_level(path: str) -> Tuple[int, nbt.CompoundTag]:
    with open(os.path.join(path, "level.dat"), "rb") as f:
        raw = f.read()
    version = struct.unpack_from("<i", raw, 0)[0]
    return version, nbt.load(raw[8:], little_endian=True, compressed=False).tag


def _write_bedrock_level(path: str, version: int, root: nbt.CompoundTag) -> None:
    body = nbt.dump(root, "", little_endian=True)
    p = os.path.join(path, "level.dat")
    _backup(p)
    with open(p, "wb") as f:
        f.write(struct.pack("<ii", version, len(body)) + body)


def _open_bedrock(path: str) -> WorldDocs:
    version, root = _read_bedrock_level(path)
    old = not os.path.isdir(os.path.join(path, "db"))
    ver = nbt.get_tag(root, "lastOpenedWithVersion")
    vs = ".".join(str(int(v.py_data)) for v in ver) if ver is not None else ""
    desc = "Pocket Edition 0.1 – 0.8 (chunks.dat)" if old else f"Bedrock Edition {vs}".strip()
    w = WorldDocs(path, "pe_old" if old else "bedrock", desc)
    w.docs.append(Doc("level.dat", tr("World (level.dat)"), root))
    w._storage = version  # type: ignore[attr-defined]
    if not old:
        try:
            from leveldb import LevelDB

            db = LevelDB(os.path.join(path, "db"))
            try:
                for key in [b"~local_player"] + [k for k, _v in db.iterate() if k.startswith(b"player_server_")]:
                    try:
                        blob = db.get(key)
                    except KeyError:
                        continue
                    if blob:
                        label = tr("Local player") if key == b"~local_player" else tr("Player {name}", name=key.decode()[14:])
                        w.docs.append(Doc(key.decode(), label, nbt.load(blob, little_endian=True).tag, "player"))
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            pass
    w._save = _save_bedrock
    return w


def _save_bedrock(w: WorldDocs) -> None:
    lvl = w.doc("level.dat")
    if lvl is not None and lvl.dirty:
        _write_bedrock_level(w.path, getattr(w, "_storage", 10), lvl.root)
    players = [d for d in w.docs if d.kind == "player" and d.dirty]
    if players:
        from leveldb import LevelDB

        db = LevelDB(os.path.join(w.path, "db"))
        try:
            for d in players:
                db.put(d.key.encode(), nbt.dump(d.root, "", little_endian=True))
        finally:
            db.close()


def _bedrock_fields(w: WorldDocs) -> List[QuickField]:
    root = w.doc("level.dat").root
    out = [QuickField(tr("Name"), "level.dat", ("LevelName",), "text"),
           QuickField("Seed", "level.dat", ("RandomSeed",), "long"),
           QuickField(tr("Game mode"), "level.dat", ("GameType",), "choice", GAME_MODES),
           QuickField(tr("Difficulty"), "level.dat", ("Difficulty",), "choice", DIFFICULTIES)]
    out += [QuickField(f"Spawn {a}", "level.dat", (f"Spawn{a}",), "int") for a in "XYZ"]
    out += [QuickField(tr("Time of day (ticks)"), "level.dat", ("Time",), "long")]
    if w.kind == "bedrock":
        out += [QuickField(tr("Commands (cheats)"), "level.dat", ("commandsEnabled",), "bool"),
                QuickField(tr("Rain level"), "level.dat", ("rainLevel",), "float"),
                QuickField(tr("Lightning level"), "level.dat", ("lightningLevel",), "float")]
        rules = ("commandblockoutput", "dodaylightcycle", "doentitydrops", "dofiretick", "domobloot", "domobspawning",
                 "dotiledrops", "doweathercycle", "keepinventory", "mobgriefing", "naturalregeneration", "pvp",
                 "showcoordinates", "tntexplodes", "falldamage", "firedamage", "drowningdamage", "doimmediaterespawn")
        for k in rules:
            if k in root:
                out.append(QuickField(tr("Rule: {name}", name=k), "level.dat", (k,), "bool"))
    return out


# ============================================================ Legacy Console Edition

def _open_lce(path: str) -> WorldDocs:
    from .lce.container import SaveContainer

    c = SaveContainer.load(path)
    stfs = open(c.source_path, "rb").read(4) in (b"CON ", b"LIVE", b"PIRS")
    w = WorldDocs(path, "lce", f"Legacy Console Edition – {c.platform.label} (save v{c.version})", read_only=stfs)
    w._container = c  # type: ignore[attr-defined]
    w._gzip = {}  # type: ignore[attr-defined]
    for name in ["level.dat"] + sorted(n for n in c.files if n.endswith(".dat") and n != "level.dat"):
        blob = c.files.get(name)
        from .lce.world import _SONY_PLAYER

        if not blob or not (name == "level.dat" or name.startswith("players/") or _SONY_PLAYER.match(name)):
            continue
        try:
            root = nbt.load(blob, compressed=blob[:2] == b"\x1f\x8b").tag
        except Exception:  # noqa: BLE001
            continue
        w._gzip[name] = blob[:2] == b"\x1f\x8b"  # type: ignore[attr-defined]
        kind = "level" if name == "level.dat" else "player"
        label = tr("World (level.dat)") if kind == "level" else tr("Player {name}", name=os.path.splitext(name.rsplit("/", 1)[-1])[0])
        w.docs.append(Doc(name, label, root, kind))
    w._save = _save_lce
    return w


def _save_lce(w: WorldDocs) -> None:
    c = w._container  # type: ignore[attr-defined]
    for d in w.docs:
        if d.dirty:
            c.files[d.key] = nbt.dump(d.root, "", compressed=w._gzip.get(d.key, False))  # type: ignore[attr-defined]
    folder, name = os.path.split(c.source_path)
    _backup(c.source_path)
    stamp = time.time()
    c.save(folder, name)
    os.utime(c.source_path, (stamp, stamp))


def _lce_fields(w: WorldDocs) -> List[QuickField]:
    root = w.doc("level.dat").root
    base = ("Data",) if nbt.get_tag(root, "Data") is not None else ()
    out = [QuickField(tr("Name"), "level.dat", base + ("LevelName",), "text"),
           QuickField("Seed", "level.dat", base + ("RandomSeed",), "long"),
           QuickField(tr("Game mode"), "level.dat", base + ("GameType",), "choice", GAME_MODES),
           QuickField(tr("Difficulty"), "level.dat", base + ("Difficulty",), "choice", DIFFICULTIES)]
    out += [QuickField(f"Spawn {a}", "level.dat", base + (f"Spawn{a}",), "int") for a in "XYZ"]
    out += [QuickField(tr("Time of day (ticks)"), "level.dat", base + ("DayTime",), "long"),
            QuickField(tr("Rain"), "level.dat", base + ("raining",), "bool")]
    return out


# ============================================================ entry point

def open_world(path: str) -> WorldDocs:
    """The documents of the world at ``path`` (a folder, or an LCE save file)."""
    from . import detect as det

    d = det.detect(path)
    if d.kind == "lce":
        return _open_lce(d.path)
    if d.kind in ("bedrock", "pe_old"):
        return _open_bedrock(d.path)
    if d.kind in ("java_modern", "java_numeric", "bta") or os.path.isfile(os.path.join(d.path, "level.dat")):
        return _open_java(d.path)
    raise ValueError(tr("This kind of world has no editable documents: {world}", world=d.description))


# ============================================================ inventories

def inventory(doc: Doc) -> List[nbt.CompoundTag]:
    """The item stacks of a player document (Java: Inventory; Bedrock: Inventory / Armor / Offhand)."""
    out = []
    for key in ("Inventory", "Armor", "Offhand", "EnderItems"):
        lst = nbt.get_tag(doc.root, key)
        if isinstance(lst, nbt.ListTag):
            out += [t for t in lst if isinstance(t, nbt.CompoundTag)]
    return out


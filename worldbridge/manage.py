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

from . import gameversion as gv
from . import nbt
from .i18n import N_, tr


@dataclass
class Doc:
    key: str                       # where it lives: "level.dat", "players/<uuid>.dat", "~local_player"...
    label: str                     # what the editor shows
    root: nbt.CompoundTag          # the document (for level.dat of Java: the whole file, with "Data")
    kind: str = "level"            # "level" | "player"
    dirty: bool = False
    # a compound inside another document (the single player of a Java or Pocket Edition 0.x
    # level.dat): edited on its own, saved with that document
    parent: Optional["Doc"] = None


@dataclass
class QuickField:
    label: str
    doc: str                       # Doc.key
    path: Tuple[str, ...]          # keys from the document's root
    kind: str                      # "text" | "int" | "long" | "bool" | "choice" | "float"
    choices: Optional[Dict[int, str]] = None


GAME_MODES = {0: N_("Survival"), 1: N_("Creative"), 2: N_("Adventure"), 3: N_("Spectator")}
DIFFICULTIES = {0: N_("Peaceful"), 1: N_("Easy"), 2: N_("Normal"), 3: N_("Hard")}


def _modes(*values: int) -> Dict[int, str]:
    return {v: GAME_MODES[v] for v in values}


# the game modes a world's GameType / playerGameType can hold: Adventure came with Java 1.3 and
# Spectator with 1.8; Bedrock, LCE and Pocket Edition never stored Spectator there (Bedrock's
# value 3 is not Spectator), Pocket Edition 0.x knows Survival and Creative only
JAVA_MODES = _modes(0, 1, 2, 3)
OLD_JAVA_MODES = _modes(0, 1, 2)
BETA_MODES = _modes(0, 1)
BEDROCK_MODES = _modes(0, 1, 2)


@dataclass
class WorldDocs:
    path: str
    kind: str                      # "java" | "bedrock" | "pe_old" | "lce"
    description: str
    docs: List[Doc] = field(default_factory=list)
    read_only: bool = False
    warning: str = ""              # what could not be read (shown by the editor)
    game_modes: Dict[int, str] = field(default_factory=lambda: dict(JAVA_MODES))
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
            out.append(QuickField(tr("Game mode"), doc.key, ("playerGameType",), "choice", self.game_modes))
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
        for d in self.docs:
            if d.dirty and d.parent is not None:
                d.parent.dirty = True
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
    """The first save keeps the original as ``.wb-backup``; the next saves never replace it."""
    if os.path.isfile(path) and not os.path.exists(path + ".wb-backup"):
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
    era = _java_era(data)
    w.game_modes = {"modern": JAVA_MODES, "anvil": OLD_JAVA_MODES}.get(era, BETA_MODES)
    level = Doc("level.dat", tr("World (level.dat)"), root)
    w.docs.append(level)
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
    if isinstance(nbt.get_tag(data, "Player"), nbt.CompoundTag):
        # the world's owner in single player: the game loads this one, not its playerdata file
        w.docs.append(Doc("level.dat:Player", tr("Single player (in level.dat)"), data["Player"], "player", parent=level))
    single = _uuid_of(nbt.get_tag(data, "singleplayer_uuid"))          # 26.1+: players/data/<uuid>.dat
    for p in _java_player_files(path):
        name = os.path.splitext(os.path.basename(p))[0]
        label = tr("Single player ({name})", name=name) if single and name == single else tr("Player {name}", name=name)
        try:
            with open(p, "rb") as f:
                praw = f.read()
            w.docs.append(Doc(os.path.relpath(p, path), label, nbt.load(praw, compressed=praw[:2] == b"\x1f\x8b").tag,
                              "player"))
        except Exception:  # noqa: BLE001
            pass
    w._save = _save_java
    return w


def _uuid_of(tag) -> Optional[str]:
    """A Java 1.16+ int-array UUID as text."""
    if not isinstance(tag, nbt.IntArrayTag) or len(tag) != 4:
        return None
    import uuid as _uuid

    vals = [int(v) & 0xFFFFFFFF for v in tag]
    return str(_uuid.UUID(int=(vals[0] << 96) | (vals[1] << 64) | (vals[2] << 32) | vals[3]))


def _save_java(w: WorldDocs) -> None:
    for d in w.docs:
        if not d.dirty or d.parent is not None:
            continue
        p = os.path.join(w.path, d.key)
        _backup(p)
        with open(p, "wb") as f:
            f.write(nbt.dump(d.root, "", compressed=True))


def _java_era(data: nbt.CompoundTag) -> str:
    """modern: DataVersion (1.9+); anvil: 1.2 - 1.8; mcregion: Beta 1.3 - 1.1; alpha: before."""
    if nbt.get(data, "DataVersion") is not None:
        return "modern"
    return {19133: "anvil", 19132: "mcregion"}.get(int(nbt.get(data, "version", 0) or 0), "alpha")


def _java_fields(w: WorldDocs) -> List[QuickField]:
    data = nbt.get_tag(w.doc("level.dat").root, "Data")
    base = ("Data",) if data is not None else ()
    data = data if data is not None else w.doc("level.dat").root
    era = _java_era(data)
    out = [QuickField(tr("Name"), "level.dat", base + ("LevelName",), "text")]
    wgs = os.path.join("data", "minecraft", "world_gen_settings.dat")
    if w.doc(wgs) is not None:                                                   # Java 26.x
        out.append(QuickField("Seed", wgs, ("data", "seed"), "long"))
        out += [QuickField(tr("Game mode"), "level.dat", base + ("GameType",), "choice", w.game_modes),
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
            out += _typed_rules(data_rules, rules, ("data",))
        return out

    def has(key: str, *eras: str) -> bool:
        """``key`` is in the level.dat, or the world's version writes it (the editor may add it)."""
        return key in data or era in eras

    if isinstance(nbt.get_tag(data, "WorldGenSettings"), nbt.CompoundTag):
        out.append(QuickField("Seed", "level.dat", base + ("WorldGenSettings", "seed"), "long"))
    else:
        out.append(QuickField("Seed", "level.dat", base + ("RandomSeed",), "long"))
    if has("GameType", "modern", "anvil", "mcregion"):                           # Beta 1.8+
        out.append(QuickField(tr("Game mode"), "level.dat", base + ("GameType",), "choice", w.game_modes))
    if has("Difficulty", "modern"):                                              # 1.8+ (before: options.txt)
        out.append(QuickField(tr("Difficulty"), "level.dat", base + ("Difficulty",), "choice", DIFFICULTIES))
    if has("hardcore", "modern", "anvil", "mcregion"):
        out.append(QuickField("Hardcore", "level.dat", base + ("hardcore",), "bool"))
    if has("allowCommands", "modern"):                                           # 1.3+
        out.append(QuickField(tr("Commands (cheats)"), "level.dat", base + ("allowCommands",), "bool"))
    sp = nbt.get_tag(data, "spawn")
    if isinstance(sp, nbt.CompoundTag) and nbt.get_tag(sp, "pos") is not None:          # 1.21.9+
        out += [QuickField(f"Spawn {a}", "level.dat", base + ("spawn", "pos", str(i)), "int") for i, a in enumerate("XYZ")]
    else:
        out += [QuickField(f"Spawn {a}", "level.dat", base + (f"Spawn{a}",), "int") for a in "XYZ"]
    # DayTime came with 1.3; before, Time was both the world's age and the time of day
    day = "DayTime" if has("DayTime", "modern") else "Time"
    out.append(QuickField(tr("Time of day (ticks)"), "level.dat", base + (day,), "long"))
    if has("raining", "modern", "anvil", "mcregion"):                            # Beta 1.5+
        out += [QuickField(tr("Rain"), "level.dat", base + ("raining",), "bool"),
                QuickField(tr("Thunderstorm"), "level.dat", base + ("thundering",), "bool")]
    rules = nbt.get_tag(data, "game_rules")
    if isinstance(rules, nbt.CompoundTag):                                       # 1.21.11+: typed, new names
        out += _typed_rules(rules, "level.dat", base + ("game_rules",))
    rules = nbt.get_tag(data, "GameRules")
    if isinstance(rules, nbt.CompoundTag):                                       # 1.4.2 - 1.21.10: strings
        for k in sorted(rules.keys()):
            out.append(QuickField(tr("Rule: {name}", name=k), "level.dat", base + ("GameRules", k), "text"))
    return out


def _typed_rules(rules: nbt.CompoundTag, doc: str, base: Tuple[str, ...]) -> List[QuickField]:
    out = []
    for k in sorted(rules.keys()):
        kind = "bool" if isinstance(rules[k], nbt.ByteTag) else "int" if isinstance(rules[k], nbt.IntTag) else "text"
        out.append(QuickField(tr("Rule: {name}", name=k.removeprefix("minecraft:")), doc, base + (k,), kind))
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
    vs = gv.bedrock_label([int(v.py_data) for v in ver]) if ver is not None else ""
    desc = "Pocket Edition 0.1 – 0.8 (chunks.dat)" if old else f"Bedrock Edition {vs}".strip()
    w = WorldDocs(path, "pe_old" if old else "bedrock", desc)
    w.game_modes = BETA_MODES if old else BEDROCK_MODES
    level = Doc("level.dat", tr("World (level.dat)"), root)
    w.docs.append(level)
    w._storage = version  # type: ignore[attr-defined]
    if old:
        if isinstance(nbt.get_tag(root, "Player"), nbt.CompoundTag):     # Pocket Edition 0.x: inside level.dat
            w.docs.append(Doc("level.dat:Player", tr("Single player (in level.dat)"), root["Player"], "player",
                              parent=level))
    else:
        try:
            from leveldb import LevelDB

            db = LevelDB(os.path.join(path, "db"))
        except Exception as e:  # noqa: BLE001
            # LevelDB is locked while the game has the world open
            w.warning = tr("The players cannot be read ({error}): close Minecraft if the world is open in it.", error=e)
            db = None
        if db is not None:
            try:
                keys = [b"~local_player"] + sorted(k for k, _v in db.iterate(b"player_server_", b"player_server_\xff")
                                                   if k.startswith(b"player_server_"))
                for key in keys:
                    try:
                        blob = db.get(key)
                    except KeyError:
                        continue
                    if not blob:
                        continue
                    label = tr("Local player") if key == b"~local_player" else tr("Player {name}", name=key.decode()[14:])
                    try:
                        w.docs.append(Doc(key.decode(), label, nbt.load(blob, little_endian=True).tag, "player"))
                    except Exception as e:  # noqa: BLE001
                        w.warning = tr("{player}: unreadable ({error})", player=label, error=e)
            finally:
                db.close()
    w._save = _save_bedrock
    return w


def _save_bedrock(w: WorldDocs) -> None:
    lvl = w.doc("level.dat")
    if lvl is not None and lvl.dirty:
        _write_bedrock_level(w.path, getattr(w, "_storage", 10), lvl.root)
    players = [d for d in w.docs if d.kind == "player" and d.dirty and d.parent is None]
    if players:
        from leveldb import LevelDB

        db = LevelDB(os.path.join(w.path, "db"))
        try:
            for d in players:
                # the game keeps raw bytes in some strings (actor storage keys): written back as read
                db.put(d.key.encode(), nbt.dump(d.root, "", little_endian=True, escape=True))
        finally:
            db.close()


# Bedrock game rules, all kept in level.dat: a byte for a switch, an int for a number
BEDROCK_RULES = ("commandblockoutput", "commandblocksenabled", "dodaylightcycle", "doentitydrops", "dofiretick",
                 "doimmediaterespawn", "doinsomnia", "dolimitedcrafting", "domobloot", "domobspawning", "dotiledrops",
                 "doweathercycle", "drowningdamage", "falldamage", "firedamage", "freezedamage", "functioncommandlimit",
                 "keepinventory", "locatorbar", "maxcommandchainlength", "mobgriefing", "naturalregeneration",
                 "playerssleepingpercentage", "projectilescanbreakblocks", "pvp", "randomtickspeed", "recipesunlock",
                 "respawnblocksexplode", "sendcommandfeedback", "showbordereffect", "showcoordinates",
                 "showdaysplayed", "showdeathmessages", "showrecipemessages", "showtags", "spawnradius",
                 "tntexplodes", "tntexplosiondropdecay")


def _bedrock_fields(w: WorldDocs) -> List[QuickField]:
    root = w.doc("level.dat").root
    out = [QuickField(tr("Name"), "level.dat", ("LevelName",), "text"),
           QuickField("Seed", "level.dat", ("RandomSeed",), "long"),
           QuickField(tr("Game mode"), "level.dat", ("GameType",), "choice", w.game_modes)]
    if w.kind == "bedrock" or "Difficulty" in root:                     # Pocket Edition 0.x: none
        out.append(QuickField(tr("Difficulty"), "level.dat", ("Difficulty",), "choice", DIFFICULTIES))
    out += [QuickField(f"Spawn {a}", "level.dat", (f"Spawn{a}",), "int") for a in "XYZ"]
    out += [QuickField(tr("Time of day (ticks)"), "level.dat", ("Time",), "long")]
    if w.kind == "bedrock":
        out += [QuickField(tr("Commands (cheats)"), "level.dat", ("commandsEnabled",), "bool"),
                QuickField(tr("Rain level"), "level.dat", ("rainLevel",), "float"),
                QuickField(tr("Lightning level"), "level.dat", ("lightningLevel",), "float")]
        for k in BEDROCK_RULES:
            if k in root:
                kind = "int" if isinstance(root[k], nbt.IntTag) else "bool"
                out.append(QuickField(tr("Rule: {name}", name=k), "level.dat", (k,), kind))
    return out


# ============================================================ Legacy Console Edition

def _open_lce(path: str) -> WorldDocs:
    from .lce.container import SaveContainer

    c = SaveContainer.load(path)
    stfs = open(c.source_path, "rb").read(4) in (b"CON ", b"LIVE", b"PIRS")
    w = WorldDocs(path, "lce", f"Legacy Console Edition – {c.platform.label} (save v{c.version})", read_only=stfs)
    w.game_modes = BEDROCK_MODES
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
           QuickField(tr("Game mode"), "level.dat", base + ("GameType",), "choice", w.game_modes),
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
    if d is None:
        raise ValueError(tr("World format not recognised."))
    if d.kind == "lce":
        return _open_lce(d.path)
    if d.kind in ("bedrock", "pe_old"):
        return _open_bedrock(d.path)
    if d.kind in ("java_modern", "java_numeric", "bta") or os.path.isfile(os.path.join(d.path, "level.dat")):
        return _open_java(d.path)
    raise ValueError(tr("This kind of world has no editable documents: {world}", world=d.description))


# ============================================================ inventories

@dataclass
class Stack:
    """One slot of a player's inventory, as the editor lists it."""
    section: str                   # N_ text: "Hotbar", "Inventory", "Armour"...
    slot: str                      # the slot as the game numbers (or names) it
    tag: nbt.CompoundTag           # the item, edited in place

    @property
    def empty(self) -> bool:
        return not item_name(self.tag) or item_count(self.tag) <= 0 or item_name(self.tag).endswith(":air")


_ARMOUR_SLOTS = {100: "feet", 101: "legs", 102: "chest", 103: "head"}
_BEDROCK_ARMOUR = ("head", "chest", "legs", "feet")


def inventory(doc: Doc) -> List[Stack]:
    """The slots of a player document, in the layout of its edition and version:

    * Java and LCE: ``Inventory`` (0 - 8 hotbar, 9 - 35, 100 - 103 armour, -106 off hand) and
      ``EnderItems``; Java 1.21.5+ keeps armour and off hand in ``equipment`` (by name);
    * Bedrock: ``Inventory`` (every slot, the empty ones too), ``Armor`` (head, chest, legs,
      feet), ``Offhand`` and ``EnderChestInventory``."""
    r = doc.root
    out: List[Stack] = []

    def lst(key):
        v = nbt.get_tag(r, key)
        return [t for t in v if isinstance(t, nbt.CompoundTag)] if isinstance(v, nbt.ListTag) else []

    for i, t in enumerate(lst("Inventory")):
        slot = int(nbt.get(t, "Slot", i) or 0)
        section = (N_("Hotbar") if 0 <= slot < 9 else N_("Armour") if slot in _ARMOUR_SLOTS
                   else N_("Off hand") if slot == -106 else N_("Inventory"))
        out.append(Stack(section, _ARMOUR_SLOTS.get(slot, str(slot)), t))
    eq = nbt.get_tag(r, "equipment")                                     # Java 1.21.5+
    if isinstance(eq, nbt.CompoundTag):
        for k in ("head", "chest", "legs", "feet", "offhand", "body", "saddle"):
            t = nbt.get_tag(eq, k)
            if isinstance(t, nbt.CompoundTag):
                out.append(Stack(N_("Off hand") if k == "offhand" else N_("Armour"), k, t))
    for i, t in enumerate(lst("Armor")):                                  # Bedrock
        out.append(Stack(N_("Armour"), _BEDROCK_ARMOUR[i] if i < 4 else str(i), t))
    for i, t in enumerate(lst("Offhand")):
        out.append(Stack(N_("Off hand"), str(i), t))
    for key in ("EnderItems", "EnderChestInventory"):
        for i, t in enumerate(lst(key)):
            out.append(Stack(N_("Ender chest"), str(int(nbt.get(t, "Slot", i) or 0)), t))
    return out


def item_name(t: nbt.CompoundTag) -> str:
    """Java / LCE ``id`` (a number before Java 1.8), Bedrock ``Name`` ("" = empty slot)."""
    v = nbt.get(t, "id", nbt.get(t, "Name", ""))
    return "" if v is None else str(v)


def item_count(t: nbt.CompoundTag) -> int:
    """``count`` from Java 1.20.5, ``Count`` before and in Bedrock / LCE."""
    try:
        return int(nbt.get(t, "count", nbt.get(t, "Count", 1)))
    except (TypeError, ValueError):
        return 0


def set_item_name(t: nbt.CompoundTag, text: str) -> None:
    """Change the item of a stack, in the stack's own format."""
    text = text.strip()
    if "id" in t:
        old = t["id"]
        if isinstance(old, nbt.StringTag):
            t["id"] = nbt.StringTag(text if ":" in text or not text else "minecraft:" + text)
        else:                                                       # numeric ids: Java before 1.8, LCE
            from . import ids

            num = int(text) if text.lstrip("-").isdigit() else ids.item_id_from_name(text)
            if num is None:
                raise ValueError(tr("Unknown item: {name}", name=text))
            t["id"] = type(old)(num)
        return
    # Bedrock: a block item also names its block in "Block", which the game reads first
    t["Name"] = nbt.StringTag(text if ":" in text or not text else "minecraft:" + text)
    if "Block" in t:
        del t["Block"]
    if text and item_count(t) <= 0:
        set_item_count(t, 1)


def set_item_count(t: nbt.CompoundTag, n: int) -> None:
    key = "count" if "count" in t else "Count"
    old = nbt.get_tag(t, key)
    t[key] = (type(old) if old is not None else nbt.ByteTag)(int(n))

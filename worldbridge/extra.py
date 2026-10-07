"""Everything Amulet does not carry over by itself: level metadata, players,
block entity contents (chests, signs, …) and entities."""

from __future__ import annotations

import math
import os
from typing import Optional

from . import amulet_bridge as ab
from . import nbt
from .model import OVERWORLD, Progress, WorldInfo, dimension_of
from .i18n import tr


_DIFFICULTY = {"peaceful": 0, "easy": 1, "normal": 2, "hard": 3}


def _side_data(world: str, name: str) -> Optional[nbt.CompoundTag]:
    """Java 26.1+: data/minecraft/<name>.dat ({"data": {...}})."""
    p = os.path.join(world, "data", "minecraft", name + ".dat")
    if not os.path.exists(p):
        return None
    try:
        root = nbt.load(open(p, "rb").read()).tag
    except Exception:  # noqa: BLE001
        return None
    data = nbt.get_tag(root, "data")
    return data if isinstance(data, nbt.CompoundTag) else root


def classic_java_level(info: WorldInfo, world: str) -> None:
    """A Java 1.21.11+ / 26.x level read with the keys of 1.12 - 1.21.10 as well, for the writers
    of the other editions and versions (see WorldInfo.derived_level_keys)."""
    from .gamerules import classic_java_rules

    lv = info.level

    def add(key, tag):
        if key not in lv and tag is not None:
            lv[key] = tag
            info.derived_level_keys.append(key)

    wgs = _side_data(world, "world_gen_settings")                      # 26.1+
    if wgs is not None:
        add("WorldGenSettings", wgs)
    ds = nbt.get_tag(lv, "difficulty_settings")                          # 26.1+
    if isinstance(ds, nbt.CompoundTag):
        d = nbt.get(ds, "difficulty")
        if d is not None:
            add("Difficulty", nbt.ByteTag(_DIFFICULTY.get(str(d).lower(), int(d) if str(d).isdigit() else 2)))
        if "hardcore" in ds:
            add("hardcore", nbt.ByteTag(1 if nbt.get(ds, "hardcore") else 0))
        if "locked" in ds:
            add("DifficultyLocked", nbt.ByteTag(1 if nbt.get(ds, "locked") else 0))
    weather = _side_data(world, "weather")                               # 26.1+
    if weather is not None:
        for keys, dst, cls in ((("raining",), "raining", nbt.ByteTag), (("thundering",), "thundering", nbt.ByteTag),
                               (("rain_time", "rainTime"), "rainTime", nbt.IntTag),
                               (("thunder_time", "thunderTime"), "thunderTime", nbt.IntTag),
                               (("clear_weather_time", "clearWeatherTime"), "clearWeatherTime", nbt.IntTag)):
            v = next((nbt.get(weather, k) for k in keys if k in weather), None)
            if v is not None:
                add(dst, cls(int(v)))
    rules = nbt.get_tag(lv, "game_rules")                                # 1.21.11
    if not isinstance(rules, nbt.CompoundTag):
        rules = _side_data(world, "game_rules")                          # 26.1+
    if isinstance(rules, nbt.CompoundTag):
        add("GameRules", classic_java_rules(rules))


def read_amulet_info(d) -> WorldInfo:
    info = WorldInfo()
    if d.kind == "bedrock":
        try:
            root = ab.read_bedrock_level_dat(d.path)
            info.level = ab.bedrock_info_to_java(root)
        except Exception:  # noqa: BLE001
            info.level = nbt.CompoundTag({"LevelName": nbt.StringTag(os.path.basename(d.path))})
        try:
            from .bedrock.extra import read_bedrock_players

            info.players.update(read_bedrock_players(d.path))
        except Exception:  # noqa: BLE001
            pass
        try:
            if ab.bedrock_spawn_unset(root) and info.players:   # never set: the first player's position is the spawn
                host = next(iter(info.players.values()))
                pos = nbt.get_tag(host, "Pos")
                if pos is not None and len(pos) == 3 and dimension_of(host) == OVERWORLD:
                    x, y, z = (math.floor(float(v.py_data)) for v in pos)
                    for k, v in zip(("SpawnX", "SpawnY", "SpawnZ"), (x, y, z)):
                        info.level[k] = nbt.IntTag(v)
        except Exception:  # noqa: BLE001
            pass
        try:
            from .bedrock.extra import _db
            from .maps import bedrock_maps_as_java

            db = _db(d.path)
            try:
                info.extra_files.update(bedrock_maps_as_java(db))
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            pass
        icon = os.path.join(d.path, "world_icon.jpeg")
        info.source_description = "Bedrock Edition"
    else:
        root = nbt.load(open(os.path.join(d.path, "level.dat"), "rb").read()).tag
        info.level = nbt.get_tag(root, "Data") or root
        classic_java_level(info, d.path)
        p = nbt.get_tag(info.level, "Player")
        if p is not None:
            info.players["host"] = p
        try:
            from .maps import legacy_map_files

            info.extra_files.update(legacy_map_files(d.path))
        except Exception:  # noqa: BLE001
            pass
        # 26.1+: singleplayer player lives in players/data/<uuid>.dat
        sp = nbt.get_tag(info.level, "singleplayer_uuid")
        host_file = None
        new_pd = os.path.join(d.path, "players", "data")
        if sp is not None and os.path.isdir(new_pd):
            try:
                import uuid as _uuid

                vals = [int(v) & 0xFFFFFFFF for v in sp.np_array.tolist()]
                u = _uuid.UUID(int=(vals[0] << 96) | (vals[1] << 64) | (vals[2] << 32) | vals[3])
                f = os.path.join(new_pd, f"{u}.dat")
                if os.path.exists(f):
                    info.players["host"] = nbt.load(open(f, "rb").read()).tag
                    host_file = f"{u}.dat"
            except Exception:  # noqa: BLE001
                pass
        for pd in (os.path.join(d.path, "playerdata"), new_pd):
            if not os.path.isdir(pd):
                continue
            for fn in sorted(os.listdir(pd)):
                    if fn.endswith(".dat") and fn != host_file and len(info.players) < 64:
                        try:
                            info.players.setdefault(fn[:-4], nbt.load(open(os.path.join(pd, fn), "rb").read()).tag)
                        except Exception:  # noqa: BLE001
                            pass
        icon = os.path.join(d.path, "icon.png")
        info.source_description = "Java Edition"
    if os.path.exists(icon):
        info.thumbnail_png = open(icon, "rb").read()
    return info


def attach_source_extras(world, d, progress: Progress, depth=None) -> None:
    """Called after an Amulet-native world was converted into the numeric hub.  ``depth``: the
    depthfit.DepthFit that moved the Overworld's blocks into 0 - 255 (None: they did not move)."""
    info = read_amulet_info(d)
    world.info = info
    try:
        if d.kind == "bedrock":
            from .bedrock.extra import BedrockExtras

            world.extras = BedrockExtras(d.path, progress)
        else:
            from .java.modern import JavaModernExtras

            world.extras = JavaModernExtras(d.path, progress)
        _wrap_reader(world, depth)
    except Exception as ex:  # noqa: BLE001
        progress.warn(tr("Entities / containers not transferred: {error}", error=ex))


def _wrap_reader(world, depth=None) -> None:
    """Replace block entities & entities of every chunk read from the hub with the ones translated
    directly from the original world.  They come at their height there: in an Overworld moved into
    0 - 255 (depthfit) they follow their blocks, and what is still out of 0 - 255 (its blocks were
    cut) is dropped; ``NumericChunk.cut_extras`` counts it."""
    orig = world.read_chunk

    def read_chunk(dim, cx, cz):
        c = orig(dim, cx, cz)
        if c is None:
            return None
        ents, tiles = world.extras.chunk_extras(dim, cx, cz)
        if tiles is None or ents is None:
            return c                                          # unreadable: the hub's own (already moved)
        c.tile_entities, c.entities = tiles, ents
        lost_t = lost_e = 0
        if depth is not None and depth.active and dim == OVERWORLD:
            lost_t, lost_e = depth.move_numeric(c)
        kept = [t for t in c.tile_entities if 0 <= _int(nbt.get(t, "y")) < 256]
        lost_t += len(c.tile_entities) - len(kept)
        c.tile_entities = kept
        kept = [e for e in c.entities if _entity_inside(e)]
        lost_e += len(c.entities) - len(kept)
        c.entities = kept
        c.cut_extras = (lost_t, lost_e)
        return c

    def emptied_extras(dim, cx, cz):
        """Block entities and entities of a chunk whose blocks were all cut: all of them are lost."""
        ents, tiles = world.extras.chunk_extras(dim, cx, cz)
        return len(tiles or ()), len(ents or ())

    world.read_chunk = read_chunk
    world.emptied_extras = emptied_extras


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _entity_inside(e) -> bool:
    pos = nbt.get_tag(e, "Pos")
    if pos is None or len(pos) != 3:
        return True
    return 0 <= float(pos[1].py_data) < 256


def inject_target_extras(hub_dir: str, out_dir: str, target, info: WorldInfo, progress: Progress, version=None) -> None:
    """After Amulet produced the target from the numeric hub: write block
    entities, entities and players in the target's native format."""
    try:
        if target.family == "bedrock":
            from .bedrock.extra import inject_from_hub

            inject_from_hub(hub_dir, out_dir, version or target.version, info, progress)
        else:
            from .java.modern import inject_from_hub as inject_java

            inject_java(hub_dir, out_dir, info, progress)
            _copy_maps(hub_dir, out_dir, _map_colors(target, version))
    except Exception as ex:  # noqa: BLE001
        progress.warn(tr("Entities / containers not fully transferred: {error}", error=ex))
    _tidy_java_entities(out_dir, target)


def _tidy_java_entities(out_dir: str, target) -> None:
    if target.family != "java":
        return
    from .java.modern import tidy_entity_regions

    tidy_entity_regions(out_dir)


def direct_extras(d, out_dir: str, target, info: WorldInfo, progress: Progress, version=None, move=None,
                  depth=None) -> None:
    """Amulet -> Amulet conversions (Java 1.13+ <-> Bedrock); ``move``: the chunks moved (relocate);
    ``depth``: the depthfit.DepthFit that moved the blocks of the Overworld (they go with them)."""
    try:
        if target.family == "bedrock" and d.kind == "java_modern":
            from .bedrock.extra import inject_from_java_modern

            inject_from_java_modern(d.path, out_dir, version or target.version, info, progress, move, depth)
        elif target.family == "java" and d.kind == "bedrock":
            from .java.modern import inject_from_bedrock

            inject_from_bedrock(d.path, out_dir, info, progress, move, depth)
            for name, blob in info.extra_files.items():  # maps
                if name.startswith("data/map_"):
                    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)
                    with open(os.path.join(out_dir, name), "wb") as f:
                        f.write(blob)
        elif target.family == "java" and d.kind == "java_modern":
            from .java.modern import inject_from_java

            inject_from_java(d.path, out_dir, info, progress, move, depth)
            _copy_java_side_files(d.path, out_dir, bool(info.player_links), _map_colors(target, version))
        elif target.family == "bedrock" and d.kind == "bedrock":
            from .bedrock.extra import copy_bedrock_extras

            copy_bedrock_extras(d.path, out_dir, progress, depth)
    except Exception as ex:  # noqa: BLE001
        progress.warn(tr("Entities / containers not fully transferred: {error}", error=ex))
    _tidy_java_entities(out_dir, target)


def _map_colors(target, version=None) -> int:
    """The base map colours of the Java target (see maps.java_map_colors)."""
    from .maps import java_map_colors

    try:
        return java_map_colors(tuple(getattr(target, "version", None) or version or (99,)))
    except Exception:  # noqa: BLE001
        return java_map_colors(version or (99,))


def _copy_map_file(s: str, t: str, max_base: Optional[int]) -> None:
    """Copy one ``map_<n>.dat``, with the colours the target game lacks replaced by the nearest
    ones it has (a colour id past its palette crashes it when the map is drawn)."""
    import shutil

    if max_base is None:
        shutil.copy2(s, t)
        return
    from .maps import capped_map_file

    with open(s, "rb") as f:
        blob = f.read()
    new = capped_map_file(blob, max_base)
    if new is blob:
        shutil.copy2(s, t)
    else:
        with open(t, "wb") as f:
            f.write(new)


def _copy_maps(src: str, dst: str, max_base: Optional[int] = None) -> None:
    """Map files of the hub (Amulet only writes the terrain); the game upgrades them."""
    import shutil

    data = os.path.join(src, "data")
    if not os.path.isdir(data):
        return
    for fn in os.listdir(data):
        if fn.startswith("map_") or fn == "idcounts.dat":
            os.makedirs(os.path.join(dst, "data"), exist_ok=True)
            if not os.path.exists(os.path.join(dst, "data", fn)):
                if fn.startswith("map_"):
                    _copy_map_file(os.path.join(data, fn), os.path.join(dst, "data", fn), max_base)
                else:
                    shutil.copy2(os.path.join(data, fn), os.path.join(dst, "data", fn))


def _copy_java_side_files(src: str, dst: str, selected_players: bool = False, max_base: Optional[int] = None) -> None:
    """Maps, statistics, advancements, player files of a Java world.  Java 26.1 moved the players'
    files into players/ (players/data...): they stay there when the output keeps the source's 26.1+
    level.dat, and go back to playerdata/, stats/, advancements/ when the output level is older
    (the game moves them itself when it upgrades it).  Files already written are kept; with players
    chosen in the "Giocatori" tab the source's player files are not copied (the chosen ones are
    written by the level.dat writer)."""
    import shutil

    try:
        out_level = nbt.load(open(os.path.join(dst, "level.dat"), "rb").read()).tag
        split = nbt.get_tag(nbt.get_tag(out_level, "Data") or out_level, "singleplayer_uuid") is not None
    except Exception:  # noqa: BLE001
        split = False
    moves = [("stats", "stats"), ("advancements", "advancements"), ("data", "data"), ("datapacks", "datapacks")]
    if not selected_players:
        moves.append(("playerdata", "playerdata"))
    if split:
        moves += [(os.path.join("players", k), os.path.join("players", k)) for k in ("stats", "advancements")
                  ] + ([] if selected_players else [(os.path.join("players", "data"), os.path.join("players", "data"))])
    else:
        moves += [(os.path.join("players", "stats"), "stats"), (os.path.join("players", "advancements"), "advancements")]
        if not selected_players:
            moves.append((os.path.join("players", "data"), "playerdata"))
    for a, b in moves:
        s, d = os.path.join(src, a), os.path.join(dst, b)
        if not os.path.isdir(s):
            continue
        for root, _dirs, files in os.walk(s):
            rel = os.path.relpath(root, s)
            os.makedirs(os.path.join(d, rel), exist_ok=True)
            for fn in files:
                t = os.path.join(d, rel, fn)
                if not os.path.exists(t):
                    if a == "data" and fn.startswith("map_") and fn.endswith(".dat"):  # colours the target knows
                        _copy_map_file(os.path.join(root, fn), t, max_base)
                    else:
                        shutil.copy2(os.path.join(root, fn), t)

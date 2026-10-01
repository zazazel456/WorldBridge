"""Everything Amulet does not carry over by itself: level metadata, players,
block entity contents (chests, signs, …) and entities."""

from __future__ import annotations

import os
from typing import Optional

from . import amulet_bridge as ab
from . import nbt
from .model import Progress, WorldInfo
from .i18n import tr


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
        wgs_file = os.path.join(d.path, "data", "minecraft", "world_gen_settings.dat")
        if "WorldGenSettings" not in info.level and os.path.exists(wgs_file):  # 26.1+
            try:
                wgs = nbt.load(open(wgs_file, "rb").read()).tag
                info.level["WorldGenSettings"] = nbt.get_tag(wgs, "data") or wgs
                info.split_world_gen = True
            except Exception:  # noqa: BLE001
                pass
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


def attach_source_extras(world, d, progress: Progress) -> None:
    """Called after an Amulet-native world was converted into the numeric hub."""
    info = read_amulet_info(d)
    world.info = info
    try:
        if d.kind == "bedrock":
            from .bedrock.extra import BedrockExtras

            world.extras = BedrockExtras(d.path, progress)
        else:
            from .java.modern import JavaModernExtras

            world.extras = JavaModernExtras(d.path, progress)
        _wrap_reader(world)
    except Exception as ex:  # noqa: BLE001
        progress.warn(tr("Entities / containers not transferred: {error}", error=ex))


def _wrap_reader(world) -> None:
    """Replace block entities & entities of every chunk read from the hub with
    the ones translated directly from the original world."""
    orig = world.read_chunk

    def read_chunk(dim, cx, cz):
        c = orig(dim, cx, cz)
        if c is None:
            return None
        ents, tiles = world.extras.chunk_extras(dim, cx, cz)
        if tiles is not None:
            c.tile_entities = tiles
        if ents is not None:
            c.entities = ents
        return c

    world.read_chunk = read_chunk


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
            _copy_maps(hub_dir, out_dir)
    except Exception as ex:  # noqa: BLE001
        progress.warn(tr("Entities / containers not fully transferred: {error}", error=ex))
    _tidy_java_entities(out_dir, target)


def _tidy_java_entities(out_dir: str, target) -> None:
    if target.family != "java":
        return
    from .java.modern import tidy_entity_regions

    tidy_entity_regions(out_dir)


def direct_extras(d, out_dir: str, target, info: WorldInfo, progress: Progress, version=None) -> None:
    """Amulet -> Amulet conversions (Java 1.13+ <-> Bedrock)."""
    try:
        if target.family == "bedrock" and d.kind == "java_modern":
            from .bedrock.extra import inject_from_java_modern

            inject_from_java_modern(d.path, out_dir, version or target.version, info, progress)
        elif target.family == "java" and d.kind == "bedrock":
            from .java.modern import inject_from_bedrock

            inject_from_bedrock(d.path, out_dir, info, progress)
            for name, blob in info.extra_files.items():  # maps
                if name.startswith("data/map_"):
                    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)
                    with open(os.path.join(out_dir, name), "wb") as f:
                        f.write(blob)
        elif target.family == "java" and d.kind == "java_modern":
            from .java.modern import inject_from_java

            inject_from_java(d.path, out_dir, info, progress)
            _copy_java_side_files(d.path, out_dir)
        elif target.family == "bedrock" and d.kind == "bedrock":
            from .bedrock.extra import copy_bedrock_extras

            copy_bedrock_extras(d.path, out_dir, progress)
    except Exception as ex:  # noqa: BLE001
        progress.warn(tr("Entities / containers not fully transferred: {error}", error=ex))
    _tidy_java_entities(out_dir, target)


def _copy_maps(src: str, dst: str) -> None:
    """Map files of the hub (Amulet only writes the terrain); the game upgrades them."""
    import shutil

    data = os.path.join(src, "data")
    if not os.path.isdir(data):
        return
    for fn in os.listdir(data):
        if fn.startswith("map_") or fn == "idcounts.dat":
            os.makedirs(os.path.join(dst, "data"), exist_ok=True)
            if not os.path.exists(os.path.join(dst, "data", fn)):
                shutil.copy2(os.path.join(data, fn), os.path.join(dst, "data", fn))


def _copy_java_side_files(src: str, dst: str) -> None:
    """Maps, statistics, advancements, player files of a Java world."""
    import shutil

    for sub in ("stats", "advancements", "playerdata", os.path.join("players", "data"), "data", "datapacks"):
        s = os.path.join(src, sub)
        d = os.path.join(dst, sub if sub != os.path.join("players", "data") else "playerdata")
        if os.path.isdir(s) and not os.path.exists(d):
            shutil.copytree(s, d, dirs_exist_ok=True)

"""level.dat and player data in the 1.17.1 layout (upgraded by the vanilla DataFixer on first load)."""

from __future__ import annotations

import os
import time
import uuid as _uuid
from typing import Dict, List, Optional

from .. import nbt
from . import LEVEL_DATA_VERSION, items, stats
from .entities import dlist, flist, uuid_ints
from .nbtio import gb, gc, gi, gl, glist, gs, num
from .palette import Palette
from .world import DRIFT, NETHER, OVERWORLD, BtaWorld


def dimension_id(bta_dim: int) -> str:
    return {NETHER: "minecraft:the_nether", DRIFT: "minecraft:the_end"}.get(bta_dim, "minecraft:overworld")


def game_type(bta_gamemode: Optional[str]) -> int:
    """BTA writes "minecraft:gamemode/survival"; older saves "survival"."""
    g = (bta_gamemode or "").lower()
    g = g[max(g.rfind("/"), g.rfind(":")) + 1:]
    return {"creative": 1, "adventure": 2, "spectator": 3}.get(g, 0)


def player_uuid(file_name: str) -> _uuid.UUID:
    """A BTA player file name (UUID or legacy user name) -> UUID; names map to the offline UUID."""
    try:
        return _uuid.UUID(file_name)
    except ValueError:
        import hashlib

        h = bytearray(hashlib.md5(("OfflinePlayer:" + file_name).encode("utf-8")).digest())
        h[6] = (h[6] & 0x0F) | 0x30
        h[8] = (h[8] & 0x3F) | 0x80
        return _uuid.UUID(bytes=bytes(h))


def convert_player(p: dict, uid: _uuid.UUID, palette: Palette, overworld_shift: int) -> nbt.CompoundTag:
    out = nbt.CompoundTag({"DataVersion": nbt.IntTag(LEVEL_DATA_VERSION)})
    pos = glist(p, "Pos")
    x, y, z = 0.0, 100.0, 0.0
    if pos is not None and len(pos) == 3:
        x, y, z = num(pos[0]), num(pos[1]), num(pos[2])
    if gi(p, "Dimension", 0) == OVERWORLD:
        y -= overworld_shift
    out["Pos"] = dlist(x, y, z)
    out["Motion"] = dlist(0, 0, 0)
    rot = glist(p, "Rotation")
    out["Rotation"] = flist(num(rot[0]), num(rot[1])) if rot is not None and len(rot) == 2 else flist(0, 0)
    out["FallDistance"] = nbt.FloatTag(0)
    out["Fire"] = nbt.ShortTag(-20)
    out["Air"] = nbt.ShortTag(300)
    out["OnGround"] = nbt.ByteTag(1 if gb(p, "OnGround") else 0)
    out["Invulnerable"] = nbt.ByteTag(0)
    out["PortalCooldown"] = nbt.IntTag(0)
    out["UUID"] = uuid_ints(uid)
    out["Health"] = nbt.FloatTag(float(max(1, min(20, gi(p, "Health", 20)))))
    out["HurtTime"] = nbt.ShortTag(0)
    out["HurtByTimestamp"] = nbt.IntTag(0)
    out["DeathTime"] = nbt.ShortTag(0)
    out["AbsorptionAmount"] = nbt.FloatTag(0)
    gt = game_type(gs(p, "Gamemode", "survival"))
    out["playerGameType"] = nbt.IntTag(gt)
    out["previousPlayerGameType"] = nbt.IntTag(-1)
    out["Dimension"] = nbt.StringTag(dimension_id(gi(p, "Dimension", 0)))
    out["SelectedItemSlot"] = nbt.IntTag(max(0, min(8, gi(p, "CurrentItem", 0))))
    out["foodLevel"] = nbt.IntTag(20)
    out["foodSaturationLevel"] = nbt.FloatTag(5.0)
    out["foodExhaustionLevel"] = nbt.FloatTag(0.0)
    out["foodTickTimer"] = nbt.IntTag(0)
    out["XpLevel"] = nbt.IntTag(0)
    out["XpP"] = nbt.FloatTag(0.0)
    out["XpTotal"] = nbt.IntTag(0)
    out["Score"] = nbt.IntTag(gi(p, "Score", 0))
    if "SpawnX" in p:
        sx, sy, sz = gi(p, "SpawnX"), gi(p, "SpawnY"), gi(p, "SpawnZ")
        if not (sx == 0 and sy == 0 and sz == 0) and sy > 0:
            out["SpawnX"] = nbt.IntTag(sx)
            out["SpawnY"] = nbt.IntTag(sy - overworld_shift)
            out["SpawnZ"] = nbt.IntTag(sz)
            out["SpawnAngle"] = nbt.FloatTag(0.0)
            out["SpawnForced"] = nbt.ByteTag(0)
            out["SpawnDimension"] = nbt.StringTag("minecraft:overworld")
    creative = gt == 1
    out["abilities"] = nbt.CompoundTag({
        "invulnerable": nbt.ByteTag(int(creative)), "mayfly": nbt.ByteTag(int(creative)),
        "instabuild": nbt.ByteTag(int(creative)), "flying": nbt.ByteTag(int(creative and gb(p, "Noclip"))),
        "mayBuild": nbt.ByteTag(1), "flySpeed": nbt.FloatTag(0.05), "walkSpeed": nbt.FloatTag(0.1)})
    # inventory: main 0-35 identical; armour 100-103 placed by item type (100 feet .. 103 head)
    inv = nbt.ListTag([], 10)
    overflow: List[nbt.CompoundTag] = []
    used = [False] * 36
    armor: List[nbt.CompoundTag] = []
    for c in glist(p, "Inventory") or []:
        if not isinstance(c, dict):
            continue
        slot = gi(c, "Slot") & 0xFF
        it = items.convert(c, palette, overflow)
        if it is None:
            continue
        if slot < 36 and not used[slot]:
            used[slot] = True
            it["Slot"] = nbt.ByteTag(slot)
            inv.append(it)
        elif 100 <= slot < 104:
            vs = 100 + items.armor_slot_for(it, slot - 100)
            if any(int(a["Slot"].py_data) == vs for a in armor):
                overflow.append(it)
            else:
                it["Slot"] = nbt.ByteTag(vs)
                armor.append(it)
        else:
            overflow.append(it)
    for a in armor:
        inv.append(a)
    ender = nbt.ListTag([], 10)
    free = ender_slot = 0
    for extra in overflow:  # extra stacks (arrows from a quiver...) -> free slots, then the ender chest
        while free < 36 and used[free]:
            free += 1
        if free < 36:
            used[free] = True
            extra["Slot"] = nbt.ByteTag(free)
            inv.append(extra)
        elif ender_slot < 27:
            extra["Slot"] = nbt.ByteTag(ender_slot)
            ender_slot += 1
            ender.append(extra)
        else:
            stats.inc("player.items_lost_no_space")
    out["Inventory"] = inv
    out["EnderItems"] = ender
    return out


def _world_gen_settings(seed: int) -> nbt.CompoundTag:
    def source(t: str, preset: Optional[str] = None) -> nbt.CompoundTag:
        bs = nbt.CompoundTag({"type": nbt.StringTag(t), "seed": nbt.LongTag(seed)})
        if t == "minecraft:vanilla_layered":
            bs["large_biomes"] = nbt.ByteTag(0)
        if preset is not None:
            bs["preset"] = nbt.StringTag(preset)
        return bs

    def dim(t: str, settings: str, bs: nbt.CompoundTag) -> nbt.CompoundTag:
        gen = nbt.CompoundTag({"type": nbt.StringTag("minecraft:noise"), "seed": nbt.LongTag(seed),
                               "settings": nbt.StringTag(settings), "biome_source": bs})
        return nbt.CompoundTag({"type": nbt.StringTag(t), "generator": gen})

    dims = nbt.CompoundTag({
        "minecraft:overworld": dim("minecraft:overworld", "minecraft:overworld", source("minecraft:vanilla_layered")),
        "minecraft:the_nether": dim("minecraft:the_nether", "minecraft:nether",
                                    source("minecraft:multi_noise", "minecraft:nether")),
        "minecraft:the_end": dim("minecraft:the_end", "minecraft:end", source("minecraft:the_end")),
    })
    return nbt.CompoundTag({"bonus_chest": nbt.ByteTag(0), "generate_features": nbt.ByteTag(1),
                            "seed": nbt.LongTag(seed), "dimensions": dims})


def _dump(path: str, tag: nbt.CompoundTag) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(nbt.dump(tag, "", compressed=True))
    os.replace(tmp, path)


def write_level(world: BtaWorld, out_dir: str, palette: Palette, level_name: Optional[str], has_end: bool,
                overworld_shift: int, spawn=None, player_links=None) -> int:
    """level.dat + playerdata/<uuid>.dat; returns the number of player files.

    ``spawn`` overrides the world spawn (BTA coordinates); ``player_links`` (from the "Giocatori"
    tab) chooses the players, the main one and the account each one is linked to."""
    b = world.level
    seed = gl(b, "RandomSeed", 0)
    d = nbt.CompoundTag({
        "DataVersion": nbt.IntTag(LEVEL_DATA_VERSION), "version": nbt.IntTag(19133),
        "Version": nbt.CompoundTag({"Id": nbt.IntTag(LEVEL_DATA_VERSION), "Name": nbt.StringTag("1.17.1"),
                                    "Series": nbt.StringTag("main"), "Snapshot": nbt.ByteTag(0)}),
        "LevelName": nbt.StringTag(level_name or gs(b, "LevelName", "Converted BTA world")),
    })
    players = world.players()
    last = gs(b, "LastPlayerUUID", "")
    host_key, host = world.host_player(players)
    files: Dict[str, dict] = dict(players)
    uuids: Dict[str, _uuid.UUID] = {k: player_uuid(k) for k in files}
    if player_links is not None:
        chosen = [ln for ln in player_links if ln.include]
        new_files: Dict[str, dict] = {}
        host = None
        for ln in chosen:
            src = files.get(ln.key)
            if ln.key == "host" and src is None:
                src = gc(b, "Player")
            if src is None:
                continue
            u = _uuid.UUID(ln.uuid) if getattr(ln, "uuid", None) else (
                player_uuid(ln.key) if ln.key != "host" else (_safe_uuid(last) or _uuid.uuid4()))
            key = str(u)
            new_files[key] = src
            uuids[key] = u
            if ln.host and host is None:
                host, last = src, key
        files = new_files
        if host is None and files:
            last = next(iter(files))
            host = files[last]
    gt = game_type(gs(host, "Gamemode", "survival")) if host is not None else 0
    d["GameType"] = nbt.IntTag(gt)
    d["Difficulty"] = nbt.ByteTag(max(0, min(3, gi(b, "Difficulty", 2))))
    d["DifficultyLocked"] = nbt.ByteTag(1 if gb(b, "DifficultyLock") else 0)
    d["hardcore"] = nbt.ByteTag(0)
    d["allowCommands"] = nbt.ByteTag(1 if gb(b, "CheatsEnabled") else 0)
    d["initialized"] = nbt.ByteTag(1)
    sx, sy, sz = (gi(b, "SpawnX"), gi(b, "SpawnY", 64), gi(b, "SpawnZ")) if spawn is None else (int(v) for v in spawn)
    d["SpawnX"] = nbt.IntTag(sx)
    d["SpawnY"] = nbt.IntTag(max(-63, sy - overworld_shift))
    d["SpawnZ"] = nbt.IntTag(sz)
    d["SpawnAngle"] = nbt.FloatTag(0.0)
    day = gl(b, "Time", 0)
    d["Time"] = nbt.LongTag(gl(b, "TotalTime", day))
    d["DayTime"] = nbt.LongTag(day)
    d["LastPlayed"] = nbt.LongTag(int(time.time() * 1000))
    for k, v in (("raining", nbt.ByteTag(0)), ("rainTime", nbt.IntTag(0)), ("thundering", nbt.ByteTag(0)),
                 ("thunderTime", nbt.IntTag(0)), ("clearWeatherTime", nbt.IntTag(0)),
                 ("WanderingTraderSpawnChance", nbt.IntTag(25)), ("WanderingTraderSpawnDelay", nbt.IntTag(24000)),
                 ("BorderCenterX", nbt.DoubleTag(0)), ("BorderCenterZ", nbt.DoubleTag(0)),
                 ("BorderSize", nbt.DoubleTag(5.9999968e7)), ("BorderSafeZone", nbt.DoubleTag(5)),
                 ("BorderWarningBlocks", nbt.DoubleTag(5)), ("BorderWarningTime", nbt.DoubleTag(15)),
                 ("BorderSizeLerpTarget", nbt.DoubleTag(5.9999968e7)), ("BorderSizeLerpTime", nbt.LongTag(0)),
                 ("BorderDamagePerBlock", nbt.DoubleTag(0.2))):
        d[k] = v
    d["GameRules"] = nbt.CompoundTag()
    d["DataPacks"] = nbt.CompoundTag({"Enabled": nbt.ListTag([nbt.StringTag("vanilla")], 8),
                                      "Disabled": nbt.ListTag([], 8)})
    d["ServerBrands"] = nbt.ListTag([nbt.StringTag("vanilla")], 8)
    d["WasModded"] = nbt.ByteTag(0)
    d["ScheduledEvents"] = nbt.ListTag([], 10)
    d["CustomBossEvents"] = nbt.CompoundTag()
    d["WorldGenSettings"] = _world_gen_settings(seed)
    if has_end:
        # the Drift became The End: never spawn a dragon (or scan for one) inside converted terrain
        fight = nbt.CompoundTag({"DragonKilled": nbt.ByteTag(1), "PreviouslyKilled": nbt.ByteTag(1),
                                 "NeedsStateScanning": nbt.ByteTag(0)})
        d["DimensionData"] = nbt.CompoundTag({"1": nbt.CompoundTag({"DragonFight": fight})})
    if host is not None:
        hu = _safe_uuid(last) or _uuid.uuid4()
        d["Player"] = convert_player(host, hu, palette, overworld_shift)
    os.makedirs(out_dir, exist_ok=True)
    _dump(os.path.join(out_dir, "level.dat"), nbt.CompoundTag({"Data": d}))
    n = 0
    pd = os.path.join(out_dir, "playerdata")
    for key, p in files.items():
        os.makedirs(pd, exist_ok=True)
        u = uuids.get(key) or player_uuid(key)
        _dump(os.path.join(pd, f"{u}.dat"), convert_player(p, u, palette, overworld_shift))
        stats.inc("players.converted")
        n += 1
    return n


def _safe_uuid(s: str) -> Optional[_uuid.UUID]:
    try:
        return _uuid.UUID(s) if s else None
    except ValueError:
        return None

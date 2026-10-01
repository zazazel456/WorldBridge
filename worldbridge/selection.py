"""What to take from the source world: which chunks, where the spawn is, which players.

Chosen in the "Mappa" and "Giocatori" tabs (or with ``--chunks``/``--spawn``/``--player`` on the
command line) and applied by :func:`worldbridge.convert.convert` on every conversion route.
The chunk selection files use the MCA Selector CSV format (``regionX;regionZ;chunkX;chunkZ``
lines, or ``regionX;regionZ`` for a whole region), so selections can be exchanged with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import nbt
from .model import NETHER, OVERWORLD, THE_END, Progress, WorldInfo
from .i18n import tr

Chunk = Tuple[int, int]


@dataclass
class PlayerLink:
    """One player of the source world and what becomes of it in the target."""

    key: str                         # key in WorldInfo.players ("host", file name, ...)
    include: bool = True
    host: bool = False               # becomes the single-player / main player
    nickname: Optional[str] = None   # Java: account name ; LCE: player id (file name)
    online: bool = True              # Java: look the premium UUID up (else offline UUID)
    uuid: Optional[str] = None       # resolved at conversion time


@dataclass
class Selection:
    # dimension -> selected chunks; None = the whole world.  With a selection, dimensions
    # without selected chunks are left out.
    chunks: Optional[Dict[int, Set[Chunk]]] = None
    spawn: Optional[Tuple[int, int, int]] = None
    players: Optional[List[PlayerLink]] = None
    # chunks never converted whatever the selection: those the game has not finished generating
    exclude: Optional[Dict[int, Set[Chunk]]] = None
    # dimensions left out entirely: the game generates them anew (Nether, End)
    drop: Set[int] = field(default_factory=set)
    # dimension -> chunk -> biome (numeric Java 1.12 id, see worldbridge.biomes) painted on the chunk
    biomes: Dict[int, Dict[Chunk, int]] = field(default_factory=dict)
    # the selected chunks moved: their centre lands on this block (x, z) (worldbridge.relocate)
    move_to: Optional[Tuple[int, int]] = None

    @property
    def active(self) -> bool:
        return (self.chunks is not None or self.spawn is not None or self.players is not None or bool(self.drop)
                or bool(self.biomes) or self.move_to is not None)

    @property
    def filters(self) -> bool:
        return self.chunks is not None or bool(self.exclude) or bool(self.drop)

    def wants(self, dim: int, cx: int, cz: int) -> bool:
        if dim in self.drop:
            return False
        if self.exclude and (cx, cz) in self.exclude.get(dim, ()):
            return False
        return self.chunks is None or (cx, cz) in self.chunks.get(dim, ())

    def filter(self, dim: int, coords: Iterable[Chunk]) -> List[Chunk]:
        return [c for c in coords if self.wants(dim, *c)]

    def count(self) -> int:
        return sum(len(v) for v in self.chunks.values()) if self.chunks is not None else -1


# ------------------------------------------------------------------ MCA Selector CSV


def save_csv(path: str, chunks: Set[Chunk]) -> None:
    """Write a selection in MCA Selector's format (whole regions collapsed to ``rx;rz``)."""
    by_region: Dict[Chunk, Set[Chunk]] = {}
    for cx, cz in chunks:
        by_region.setdefault((cx >> 5, cz >> 5), set()).add((cx, cz))
    with open(path, "w", encoding="utf-8") as f:
        for (rx, rz), cs in sorted(by_region.items()):
            if len(cs) == 1024:
                f.write(f"{rx};{rz}\n")
            else:
                for cx, cz in sorted(cs):
                    f.write(f"{rx};{rz};{cx};{cz}\n")


def load_csv(path: str) -> Set[Chunk]:
    out: Set[Chunk] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in re.split(r"[;,]", line.strip()) if p.strip()]
            try:
                nums = [int(p) for p in parts]
            except ValueError:
                continue
            if len(nums) == 2:
                rx, rz = nums
                out.update((rx * 32 + x, rz * 32 + z) for x in range(32) for z in range(32))
            elif len(nums) == 4:
                out.add((nums[2], nums[3]))
    return out


# ------------------------------------------------------------------ player identities


def offline_uuid(name: str) -> str:
    """UUID the Java server gives an offline-mode (non premium) player."""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(_uuid.UUID(bytes=bytes(h)))


def online_uuid(name: str, timeout: float = 4.0) -> Optional[str]:
    """Premium account UUID from Mojang's public API (None when offline / unknown)."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"https://api.mojang.com/users/profiles/minecraft/{name}", timeout=timeout) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read().decode("utf-8"))
        return str(_uuid.UUID(data["id"]))
    except Exception:  # noqa: BLE001
        return None


def resolve_links(links: List[PlayerLink], family: str, progress: Optional[Progress] = None) -> None:
    for ln in links:
        if not ln.include or not ln.nickname or family != "java":
            continue
        u = online_uuid(ln.nickname) if ln.online else None
        if ln.online and u is None and progress:
            progress.warn(tr("Premium UUID of “{name}” not found (offline?): using the offline UUID.", name=ln.nickname))
        ln.uuid = u or offline_uuid(ln.nickname)
        if progress:
            progress.log(tr("Player “{key}” → {name} ({uuid})", key=ln.key, name=ln.nickname, uuid=ln.uuid))


def apply_to_info(info: WorldInfo, sel: Selection, family: str, progress: Optional[Progress] = None) -> None:
    """Spawn override and player choice/order on the source information (host first)."""
    if sel.spawn is not None:
        x, y, z = (int(v) for v in sel.spawn)
        info.level["SpawnX"], info.level["SpawnY"], info.level["SpawnZ"] = nbt.IntTag(x), nbt.IntTag(y), nbt.IntTag(z)
        if "spawn" in info.level:  # 1.21.9+ spawn compound
            del info.level["spawn"]
    if sel.players is None:
        return
    resolve_links(sel.players, family, progress)
    links = [ln for ln in sel.players if ln.include and ln.key in info.players]
    links.sort(key=lambda ln: not ln.host)
    info.players = {ln.key: info.players[ln.key] for ln in links}
    info.player_links = {ln.key: ln for ln in links}


# ------------------------------------------------------------------ Java player files


def set_player_uuid(p: nbt.CompoundTag, u: str) -> None:
    v = _uuid.UUID(u).int
    dv = int(nbt.get(p, "DataVersion", 0) or 0)
    if dv >= 2514 or isinstance(nbt.get_tag(p, "UUID"), nbt.IntArrayTag):
        import numpy as np

        vals = [(v >> s) & 0xFFFFFFFF for s in (96, 64, 32, 0)]
        p["UUID"] = nbt.IntArrayTag(np.array([x - (1 << 32) if x >= 1 << 31 else x for x in vals], "int32"))
        for k in ("UUIDMost", "UUIDLeast"):
            if k in p:
                del p[k]
    else:
        def s64(x):
            return x - (1 << 64) if x >= 1 << 63 else x

        p["UUIDMost"] = nbt.LongTag(s64(v >> 64))
        p["UUIDLeast"] = nbt.LongTag(s64(v & ((1 << 64) - 1)))
        if isinstance(nbt.get_tag(p, "UUID"), (nbt.StringTag, nbt.IntArrayTag)):
            del p["UUID"]


def write_java_playerdata(out_dir: str, info: WorldInfo, prepare) -> int:
    """``playerdata/<uuid>.dat`` for every player linked to a nickname (``prepare`` turns the
    source compound into the target layout, e.g. :func:`java.numeric.java_player_nbt`)."""
    links = getattr(info, "player_links", None) or {}
    n = 0
    for key, p in info.players.items():
        ln = links.get(key)
        if ln is None or not ln.uuid:
            continue
        q = prepare(nbt.copy(p))
        set_player_uuid(q, ln.uuid)
        folder = os.path.join(out_dir, "playerdata")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{ln.uuid}.dat"), "wb") as f:
            f.write(nbt.dump(nbt.CompoundTag(q), "", compressed=True))
        n += 1
    return n


# ------------------------------------------------------------------ pruning the output


def _java_dim_folders(world: str, dim: int) -> List[str]:
    from .java.modern import _folder

    return [_folder(world, dim, sub) for sub in ("region", "entities", "poi")]


def prune_java(world: str, sel: Selection) -> int:
    """Remove unselected chunks from a Java world (region, entities and poi files); dimensions
    without selected chunks are emptied.  Kept chunks are copied byte for byte."""
    if not sel.filters:
        return 0
    from .trim import prune_java_raw

    keep = {}
    for dim in (OVERWORLD, NETHER, THE_END):
        base = sel.chunks.get(dim, set()) if sel.chunks is not None else _java_coords(world, dim)
        keep[dim] = {c for c in base if sel.wants(dim, *c)}
    return prune_java_raw(world, keep)


def _java_coords(world: str, dim: int) -> Set[Chunk]:
    """Every chunk stored in a Java world's region files."""
    from .incomplete import _JAVA_DIRS
    from .java.region import region_chunks

    out: Set[Chunk] = set()
    for sub in _JAVA_DIRS[dim]:
        d = os.path.join(world, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            parts = fn.split(".")
            if len(parts) == 4 and parts[3] == "mca":
                try:
                    rx, rz = int(parts[1]), int(parts[2])
                    out.update((rx * 32 + x, rz * 32 + z) for x, z in region_chunks(os.path.join(d, fn)))
                except Exception:  # noqa: BLE001
                    continue
    return out


_CHUNK_TAGS = set(range(0x2B, 0x3D)) | {0x76, 0x77}
_BEDROCK_DIM = {0: OVERWORLD, 1: NETHER, 2: THE_END}


def _bedrock_chunk_key(key: bytes) -> Optional[Tuple[int, int, int]]:
    n = len(key)
    if n in (9, 10):
        tag = key[8]
        if tag not in _CHUNK_TAGS or (n == 10 and tag != 0x2F):
            return None
        x, z = struct.unpack_from("<ii", key)
        return OVERWORLD, x, z
    if n in (13, 14):
        tag = key[12]
        d = struct.unpack_from("<i", key, 8)[0]
        if tag not in _CHUNK_TAGS or d not in (1, 2) or (n == 14 and tag != 0x2F):
            return None
        x, z = struct.unpack_from("<ii", key)
        return _BEDROCK_DIM[d], x, z
    return None


def prune_bedrock(world: str, sel: Selection) -> int:
    """Remove unselected chunks (terrain, block entities, entities) from a Bedrock world."""
    if not sel.filters:
        return 0
    from leveldb import LevelDB

    db = LevelDB(os.path.join(world, "db"))
    removed_chunks = set()
    try:
        drop = []
        for key, value in db.iterate():
            if key.startswith(b"digp") and len(key) in (12, 16):
                x, z = struct.unpack_from("<ii", key, 4)
                d = _BEDROCK_DIM.get(struct.unpack_from("<i", key, 12)[0] if len(key) == 16 else 0)
                if d is not None and not sel.wants(d, x, z):
                    drop.append(key)
                    drop.extend(b"actorprefix" + value[i:i + 8] for i in range(0, len(value) - 7, 8))
                continue
            c = _bedrock_chunk_key(key)
            if c is not None and not sel.wants(*c):
                drop.append(key)
                removed_chunks.add(c)
        for k in drop:
            try:
                db.delete(k)
            except KeyError:
                pass
    finally:
        db.close()
    return len(removed_chunks)


# ------------------------------------------------------------------ same-edition copies


def edit_java_copy(world: str, sel: Selection, info: WorldInfo, progress: Progress) -> None:
    """Apply spawn / players to a Java world copied as-is (the pre-1.18 -> latest route)."""
    path = os.path.join(world, "level.dat")
    root = nbt.load(open(path, "rb").read()).tag
    data = nbt.get_tag(root, "Data") or root
    if sel.spawn is not None:
        x, y, z = (int(v) for v in sel.spawn)
        data["SpawnX"], data["SpawnY"], data["SpawnZ"] = nbt.IntTag(x), nbt.IntTag(y), nbt.IntTag(z)
    if sel.players is not None and info.players:
        host_key = next(iter(info.players))
        data["Player"] = nbt.copy(info.players[host_key])
        ln = info.player_links.get(host_key)
        if ln is not None and ln.uuid:
            set_player_uuid(data["Player"], ln.uuid)
        pd = os.path.join(world, "playerdata")
        if os.path.isdir(pd):
            import shutil

            shutil.rmtree(pd)
        n = write_java_playerdata(world, info, lambda p: p)
        progress.log(tr("Players: {n} playerdata files written.", n=n))
    with open(path, "wb") as f:
        f.write(nbt.dump(root, "", compressed=True))


def edit_bedrock_copy(world: str, sel: Selection, info: WorldInfo, progress: Progress) -> None:
    from . import amulet_bridge as ab

    if sel.spawn is not None:
        p = os.path.join(world, "level.dat")
        raw = open(p, "rb").read()
        storage = struct.unpack_from("<i", raw, 0)[0]
        root = nbt.load(raw[8:], little_endian=True, compressed=False).tag
        x, y, z = (int(v) for v in sel.spawn)
        root["SpawnX"], root["SpawnY"], root["SpawnZ"] = nbt.IntTag(x), nbt.IntTag(y), nbt.IntTag(z)
        payload = nbt.dump(root, "", little_endian=True)
        with open(p, "wb") as f:
            f.write(struct.pack("<ii", storage, len(payload)) + payload)
    if sel.players is not None and info.players:
        host_key = next(iter(info.players))
        if host_key != "host":
            from .bedrock.extra import BedrockInjector, _game_type

            inj = BedrockInjector(world, ab.latest("bedrock"), progress)
            try:
                inj.put_player(info.players[host_key], _game_type(info))
            finally:
                inj.close()

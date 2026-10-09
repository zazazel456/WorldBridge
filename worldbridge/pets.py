"""Who owns the tamed animals of a converted world.

Java stores the owner of a wolf, cat, parrot, horse... as the owner's UUID, and a player always takes the UUID of the
account that logs in (the game ignores the UUID inside the player file).  A world that does not come from a Java account
(Bedrock...) has no such UUID, so there are two ways to make the animals recognise their player:

* ``account``      the host is linked to a Java account (``--player host=NAME``, the “Players” tab): the animals get
                   that account's UUID directly.  Exact, but the name has to be the right one (premium or offline).
* ``first-player`` no input: the animals get a tag and a tiny data pack (``datapacks/worldbridge_owner``) hands each
                   of them to the nearest player when its chunk loads, once.  In a single player world that is the host;
                   on a multiplayer server it is whoever is nearest.

The data pack needs functions with an ``Owner`` tag of four ints: Java 1.16 and later.
"""

from __future__ import annotations

import json
import os
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from .i18n import tr

TAG = "worldbridge_host_pet"
PACK = "worldbridge_owner"
MODES = ("auto", "account", "first-player")
OWNER_ARRAY_DV = 2566          # Java 1.16: Owner is a UUID of four ints (before: OwnerUUID, a string)
FUNCTION_RENAME_DV = 3953      # Java 1.21: data/<ns>/function and tags/function (before: functions)
MIN_FORMAT_DV = 4554           # Java 1.21.9: pack.mcmeta min_format / max_format (before: pack_format)
# data pack format by the first DataVersion that uses it (Java 1.16 - 1.21.8)
_PACK_FORMATS = ((2566, 5), (2578, 6), (2724, 7), (2860, 8), (2975, 9), (3105, 10), (3337, 12), (3463, 15), (3578, 18),
                 (3698, 26), (3837, 41), (3953, 48), (4082, 57), (4189, 61), (4325, 71), (4435, 80), (4438, 81))


@dataclass
class PetPlan:
    """What happens to the owned animals of this conversion."""

    mode: str = "none"                      # none | account | first-player
    owners: Dict[int, int] = field(default_factory=dict)   # source player UUID -> UUID of its Java account
    hosts: Set[int] = field(default_factory=set)          # first-player: UUIDs of the animals' players in the source
    remapped: int = 0
    tagged: int = 0

    def apply(self, canon) -> None:
        """Re-own / tag the animals of a list of canonical entities (in place)."""
        if self.mode == "none":
            return
        for c in canon:
            owner = c.get("owner") if isinstance(c, dict) else None
            if not owner:
                continue
            if self.mode == "account" and owner in self.owners:
                c["owner"] = self.owners[owner]
                self.remapped += 1
            elif self.mode == "first-player" and owner in self.hosts:
                c["pet_tag"] = True
                self.tagged += 1


def plan_for(requested: str, info, target_dv: Optional[int], progress, first_by_default: bool = True) -> PetPlan:
    """Decide the mode (``requested``: auto | account | first-player) for a conversion and log / warn about it.
    ``info``: the source WorldInfo with its players and links already applied; ``target_dv``: DataVersion of
    the Java target (None: unknown)."""
    from .selection import owner_map, player_uuid_of

    owners = owner_map(info)
    links = getattr(info, "player_links", None) or {}
    host_key = next(iter(info.players), None) if info.players else None
    host_linked = bool(host_key is not None and links.get(host_key) is not None
                       and getattr(links.get(host_key), "uuid", None))
    host_uuid = player_uuid_of(info.players[host_key]) if host_key is not None else None
    if requested not in ("account", "first-player") and not host_linked and not first_by_default:
        return PetPlan("none", owners=owners)        # the source's own accounts: nothing to bind unless asked
    mode = requested if requested in ("account", "first-player") else ("account" if host_linked else "first-player")
    if mode == "account" and not host_linked:
        progress.warn(tr("Pet owner “account” needs the host linked to a Java account (--player host=NAME, “Players” "
                         "tab): using “first player” instead."))
        mode = "first-player"
    if mode == "account":
        progress.log(tr("Tamed animals are given to the Java account of the linked player (UUID of the account name; "
                        "the name has to be the right one, premium or offline)."))
        return PetPlan("account", owners=owners)
    if host_uuid is None:
        return PetPlan("none", owners=owners)
    if target_dv is None or target_dv < OWNER_ARRAY_DV:
        progress.warn(tr("The tamed animals will not recognise the player: this Java version cannot run the data pack "
                         "that binds them to the first player, and no Java account is linked (--player host=NAME)."))
        return PetPlan("none", owners=owners)
    progress.log(tr("Tamed animals will be bound to the player who opens the world first (data pack “{pack}”; on a "
                    "multiplayer server they go to the nearest player when their chunk loads).", pack=PACK))
    return PetPlan("first-player", owners=owners, hosts={_uuid.UUID(host_uuid).int})


def pack_format(dv: int) -> int:
    fmt = _PACK_FORMATS[0][1]
    for first, f in _PACK_FORMATS:
        if dv >= first:
            fmt = f
    return fmt


def write_datapack(world_dir: str, target_dv: int, progress=None) -> str:
    """``datapacks/worldbridge_owner``: gives every animal tagged ``worldbridge_host_pet`` to the nearest player."""
    root = os.path.join(world_dir, "datapacks", PACK)
    folder = "function" if target_dv >= FUNCTION_RENAME_DV else "functions"
    if target_dv >= MIN_FORMAT_DV:
        meta = {"min_format": 88, "max_format": 1000}
    else:
        meta = {"pack_format": pack_format(target_dv)}
    meta["description"] = "WorldBridge: hands the converted tamed animals to the first player who opens the world"
    files = {
        "pack.mcmeta": json.dumps({"pack": meta}, indent=2),
        f"data/minecraft/tags/{folder}/tick.json": json.dumps({"values": ["worldbridge:tick"]}),
        f"data/worldbridge/{folder}/tick.mcfunction":
            f"execute as @e[tag={TAG}] at @s if entity @p run function worldbridge:bind\n",
        f"data/worldbridge/{folder}/bind.mcfunction":
            f"data modify entity @s Owner set from entity @p UUID\ntag @s remove {TAG}\n",
    }
    for rel, text in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return root

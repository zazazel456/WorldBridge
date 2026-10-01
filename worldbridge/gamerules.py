"""Game rules between versions and editions.

* Java up to 1.21.10 keeps them in level.dat as ``GameRules``: strings ("true", "3") under
  camelCase names.  WorldBridge's level information uses this form for every source.
* Java 1.21.11 (data version 4658) turned them into ``game_rules``: typed values (byte, int)
  under new names, some of them inverted (disableRaids -> raids); Java 26.1 moved that compound
  to data/minecraft/game_rules.dat.  The table below is the game's own fix, read backwards.
* Bedrock keeps them at the top of level.dat, lowercase, a byte for a switch and an int for a
  number.
"""

from __future__ import annotations

from typing import Dict, Tuple

from . import nbt

# Java 1.21.11 name -> (name up to 1.21.10, inverted)
_JAVA_1_21_11: Dict[str, Tuple[str, bool]] = {
    "allow_entering_nether_using_portals": ("allowEnteringNetherUsingPortals", False),
    "show_advancement_messages": ("announceAdvancements", False),
    "block_explosion_drop_decay": ("blockExplosionDropDecay", False),
    "command_block_output": ("commandBlockOutput", False),
    "command_blocks_work": ("commandBlocksEnabled", False),
    "max_block_modifications": ("commandModificationBlockLimit", False),
    "elytra_movement_check": ("disableElytraMovementCheck", True),
    "player_movement_check": ("disablePlayerMovementCheck", True),
    "raids": ("disableRaids", True),
    "advance_time": ("doDaylightCycle", False),
    "entity_drops": ("doEntityDrops", False),
    "immediate_respawn": ("doImmediateRespawn", False),
    "spawn_phantoms": ("doInsomnia", False),
    "limited_crafting": ("doLimitedCrafting", False),
    "mob_drops": ("doMobLoot", False),
    "spawn_mobs": ("doMobSpawning", False),
    "spawn_patrols": ("doPatrolSpawning", False),
    "block_drops": ("doTileDrops", False),
    "spawn_wandering_traders": ("doTraderSpawning", False),
    "spread_vines": ("doVinesSpread", False),
    "spawn_wardens": ("doWardenSpawning", False),
    "advance_weather": ("doWeatherCycle", False),
    "drowning_damage": ("drowningDamage", False),
    "ender_pearls_vanish_on_death": ("enderPearlsVanishOnDeath", False),
    "fall_damage": ("fallDamage", False),
    "fire_damage": ("fireDamage", False),
    "forgive_dead_players": ("forgiveDeadPlayers", False),
    "freeze_damage": ("freezeDamage", False),
    "global_sound_events": ("globalSoundEvents", False),
    "keep_inventory": ("keepInventory", False),
    "lava_source_conversion": ("lavaSourceConversion", False),
    "locator_bar": ("locatorBar", False),
    "log_admin_commands": ("logAdminCommands", False),
    "max_command_sequence_length": ("maxCommandChainLength", False),
    "max_command_forks": ("maxCommandForkCount", False),
    "max_entity_cramming": ("maxEntityCramming", False),
    "max_minecart_speed": ("minecartMaxSpeed", False),
    "mob_explosion_drop_decay": ("mobExplosionDropDecay", False),
    "mob_griefing": ("mobGriefing", False),
    "natural_health_regeneration": ("naturalRegeneration", False),
    "players_nether_portal_creative_delay": ("playersNetherPortalCreativeDelay", False),
    "players_nether_portal_default_delay": ("playersNetherPortalDefaultDelay", False),
    "players_sleeping_percentage": ("playersSleepingPercentage", False),
    "projectiles_can_break_blocks": ("projectilesCanBreakBlocks", False),
    "pvp": ("pvp", False),
    "random_tick_speed": ("randomTickSpeed", False),
    "reduced_debug_info": ("reducedDebugInfo", False),
    "send_command_feedback": ("sendCommandFeedback", False),
    "show_death_messages": ("showDeathMessages", False),
    "max_snow_accumulation_height": ("snowAccumulationHeight", False),
    "spawn_monsters": ("spawnMonsters", False),
    "respawn_radius": ("spawnRadius", False),
    "spawner_blocks_work": ("spawnerBlocksEnabled", False),
    "spectators_generate_chunks": ("spectatorsGenerateChunks", False),
    "tnt_explodes": ("tntExplodes", False),
    "tnt_explosion_drop_decay": ("tntExplosionDropDecay", False),
    "universal_anger": ("universalAnger", False),
    "water_source_conversion": ("waterSourceConversion", False),
}

# Java name (up to 1.21.10) -> Bedrock name, for the rules that mean the same thing in both.
# randomTickSpeed is left out: the same number is three times faster in Bedrock (default 1 vs 3).
JAVA_TO_BEDROCK = {n: n.lower() for n in (
    "commandBlockOutput", "commandBlocksEnabled", "doDaylightCycle", "doEntityDrops", "doFireTick",
    "doImmediateRespawn", "doInsomnia", "doLimitedCrafting", "doMobLoot", "doMobSpawning", "doTileDrops",
    "doWeatherCycle", "drowningDamage", "fallDamage", "fireDamage", "freezeDamage", "keepInventory",
    "locatorBar", "maxCommandChainLength", "mobGriefing", "naturalRegeneration", "playersSleepingPercentage",
    "projectilesCanBreakBlocks", "pvp", "sendCommandFeedback", "showDeathMessages", "spawnRadius", "tntExplodes",
    "tntExplosionDropDecay")}
BEDROCK_TO_JAVA = {b: j for j, b in JAVA_TO_BEDROCK.items()}
# numbers among them (the others are switches)
_INT_RULES = {"maxCommandChainLength", "playersSleepingPercentage", "spawnRadius"}


def classic_java_rules(game_rules: nbt.CompoundTag) -> nbt.CompoundTag:
    """Java 1.21.11+ ``game_rules`` as the ``GameRules`` of 1.21.10 (names and string values)."""
    out = nbt.CompoundTag()
    for key, tag in game_rules.items():
        name = key.split(":", 1)[-1]
        value = tag.py_data
        if name == "fire_spread_radius_around_player":       # was doFireTick + allowFireTicksAwayFromPlayer
            r = int(value)
            out["doFireTick"] = nbt.StringTag("false" if r == 0 else "true")
            if r < 0:
                out["allowFireTicksAwayFromPlayer"] = nbt.StringTag("true")
            continue
        old, inverted = _JAVA_1_21_11.get(name, (None, False))
        if old is None:
            continue                                         # a rule of 1.21.11+ only
        if isinstance(tag, nbt.ByteTag):
            value = ("false" if value else "true") if inverted else ("true" if value else "false")
        out[old] = nbt.StringTag(str(value))
    return out


def bedrock_rules(game_rules: nbt.CompoundTag) -> Dict[str, object]:
    """Java ``GameRules`` (string values) -> Bedrock level.dat tags, for the rules both editions have."""
    out = {}
    for name, bname in JAVA_TO_BEDROCK.items():
        v = nbt.get(game_rules, name)
        if v is None:
            continue
        v = str(v).strip().lower()
        if name in _INT_RULES:
            try:
                out[bname] = nbt.IntTag(int(v))
            except ValueError:
                pass
        elif v in ("true", "false"):
            out[bname] = nbt.ByteTag(1 if v == "true" else 0)
    return out


def java_rules_from_bedrock(root: nbt.CompoundTag) -> nbt.CompoundTag:
    """Bedrock level.dat -> Java ``GameRules`` (string values)."""
    out = nbt.CompoundTag()
    for bname, name in BEDROCK_TO_JAVA.items():
        tag = nbt.get_tag(root, bname)
        if tag is None or not hasattr(tag, "py_data"):
            continue
        v = tag.py_data
        out[name] = nbt.StringTag(str(int(v)) if name in _INT_RULES else ("true" if v else "false"))
    return out

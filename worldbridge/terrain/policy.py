"""Which remedy keeps a conversion's border without a seam (docs/SEAMLESS_BORDERS.md).

* ``game``  the target blends by itself (Java / Bedrock 1.18+) or generates the same terrain;
* ``ring``  WorldBridge writes a ring with the target's own generator (Alpha 1.2 - 1.12, neoLegacy);
* ``fill``  small finite world (PE 0.x, other LCE up to 64 x 64 chunks): every chunk of the map is written;
* ``missing`` no remedy yet: the conversion warns, so a seam never goes unannounced;
* ``off``   the user switched the border off (``target.ring`` for ring / fill, ``target.blend`` for
  the game's blending).
"""

from __future__ import annotations

from dataclasses import dataclass
from ..i18n import tr

from . import ring as ring_mod

CAVES_CLIFFS = (1, 18, 0)


@dataclass
class Plan:
    kind: str
    text: str


def _missing(what: str) -> Plan:
    return Plan("missing", tr("No terrain border yet for {target}: where the converted world ends the game will put its "
                              "own terrain with a step. For an edge without steps choose Java 1.18 or later (the "
                              "game's blending) or Java Alpha 1.2 – 1.12 (WorldBridge's ring).", target=what))


SMALL_LCE = 64      # chunks across: LCE maps up to this size are written whole (~3 MB)


def neo_legacy(target) -> bool:
    """The LCE target is neoLegacy (the only Windows64 target, TU31): WorldBridge has its generator."""
    return target.family == "lce" and getattr(target, "lce_platform", "") == "win64"


def decide(target, old_source: bool, source_kind: str = "", writer_opt=None) -> Plan:
    plan = _decide(target, old_source, source_kind, writer_opt)
    if plan.kind in ("ring", "fill") and not getattr(target, "ring", True):
        return Plan("off", tr("Ring turned off: at the edges of the converted world the game will put its own terrain "
                              "without a transition."))
    if plan.kind == "game" and old_source and not getattr(target, "blend", True):
        return Plan("off", tr("Game blending turned off: the chunks are written in the new format, so the game does "
                              "not blend them with the new terrain nor generate the part below y 0."))
    return plan


def _decide(target, old_source: bool, source_kind: str = "", writer_opt=None) -> Plan:
    fam = target.family
    if fam == "lce" and source_kind == "lce":
        return Plan("game", tr("LCE → LCE: the game generates the same terrain as the source world, the edge continues "
                               "by itself."))
    if fam == "pe_old" and source_kind == "pe_old":
        return Plan("game", "")
    if fam == "pe_old":
        return Plan("fill", tr("Pocket Edition 0.x: the world is small (256×256 blocks) and is written whole, with "
                               "natural terrain meeting the converted world around it: no steps."))
    if fam == "lce":
        if neo_legacy(target):
            return Plan("ring", tr("neoLegacy: around the converted world WorldBridge writes a ring with neoLegacy's "
                                   "generator (same seed, same biomes and terrain as the game) meeting the converted "
                                   "terrain: past the ring the game continues without steps."))
        size = getattr(writer_opt, "world_size", 0) or getattr(target, "lce_world_size", 0) or 0
        if size and size <= SMALL_LCE:
            return Plan("fill", tr("LCE: the map is small ({size}×{size} chunks) and is written whole, with natural "
                                   "terrain meeting the converted world around it: no steps.", size=size))
        return Plan("missing", tr("LCE: on large maps a border with the terrain the console generates is not available "
                                  "yet for this version (it is for neoLegacy: Windows64, TU31): a step will remain where "
                                  "the converted world ends. With a 54- or 64-chunk map the world is written whole, "
                                  "without steps."))
    if fam == "bedrock":
        v = tuple(target.version or (99,))
        if v >= CAVES_CLIFFS:
            return Plan("game", tr("Bedrock blends the new terrain with the converted one by itself.") if old_source else
                                tr("Bedrock 1.18+ generates the same terrain as Java 1.18+: the edge continues by itself."))
        return Plan("missing", tr("Bedrock before 1.18 does not blend terrain and its generator cannot be reproduced: a "
                                  "step will remain where the converted world ends. For an edge without steps choose "
                                  "Bedrock 1.18 or later."))
    # Java
    mode = getattr(target, "java_mode", "auto")
    if mode in ("mcregion", "alpha"):
        if ring_mod.supported(target):
            return Plan("ring", "")
        return _missing(f"Java {target.java_version_limit}")
    if mode == "numeric":
        if ring_mod.supported(target):
            return Plan("ring", "")
        return _missing(f"Java {target.java_version_limit or '1.12'}")
    if mode == "amulet" and tuple(target.version or (99,)) < CAVES_CLIFFS:
        if ring_mod.supported(target):
            return Plan("ring", "")
        return _missing("Java " + ".".join(str(x) for x in target.version))
    return Plan("game", tr("Minecraft blends the new terrain with the converted one by itself.") if old_source
                else tr("Java 1.18+ generates the terrain with the same generator: the edge continues by itself."))

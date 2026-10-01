"""Version numbers as each game stores them in its files.

* Bedrock 26.x stores its own version as 1.26.x (level.dat ``lastOpenedWithVersion`` and
  ``MinimumCompatibleClientVersion``: [1, 26, 52, 3, 0] for 26.52.3); PyMCTranslate and
  WorldBridge number those releases 26.x, so 1.26.x read from a world compares as 1.x (older
  than 1.21) unless it is turned into 26.x first, and 26.x written as such reads, to the game,
  as a version far newer than itself.
* Bedrock blocks (chunk palettes, the ``Block`` of block items, flower pots) carry the version
  of the block states, not the game's: 26.x still writes 1.21.60.33.  PyMCTranslate keeps it
  as the ``data_version`` of each Bedrock version.
* Java chunks and level.dat carry only a DataVersion; PyMCTranslate knows the one of each
  release.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple


def bedrock(v: Optional[Sequence[int]]) -> Optional[Tuple[int, ...]]:
    """A Bedrock version as WorldBridge numbers it: 1.26.52.3 -> 26.52.3 (others unchanged)."""
    if v is None:
        return None
    v = tuple(int(x) for x in v)
    if len(v) >= 2 and v[0] == 1 and v[1] >= 26:
        v = v[1:]
    return v


def bedrock_stored(v: Sequence[int], length: int = 5) -> Tuple[int, ...]:
    """A Bedrock version as the game stores it in level.dat: 26.50 -> [1, 26, 50, 0, 0]."""
    v = bedrock(v) or ()
    if v and v[0] >= 26:
        v = (1,) + v
    return (v + (0,) * length)[:length]


def bedrock_label(v: Optional[Sequence[int]]) -> str:
    """26.52.3, 1.21.50: trailing zeros past the second number left out."""
    v = list(bedrock(v) or ())
    while len(v) > 2 and v[-1] == 0:
        v.pop()
    return ".".join(str(x) for x in v)


def _tm():
    from .amulet_bridge import translation_manager

    return translation_manager()


def bedrock_block_version(version: Sequence[int]) -> int:
    """The block-state version Bedrock ``version`` writes in its block compounds."""
    try:
        dv = int(_tm().get_version("bedrock", tuple(version)).data_version)
        if dv > 0:
            return dv
    except Exception:  # noqa: BLE001
        pass
    v = list(bedrock_stored(version, 4))
    return (v[0] << 24) | (v[1] << 16) | (v[2] << 8) | v[3]


def java_from_data_version(dv: int) -> Optional[Tuple[int, ...]]:
    """The newest Java release whose DataVersion is ``dv`` or lower (None: older than any known)."""
    try:
        tm = _tm()
        known = sorted((tm.get_version("java", v).data_version, tuple(v)) for v in tm.version_numbers("java"))
    except Exception:  # noqa: BLE001
        return None
    best = None
    for d, v in known:
        if 0 < d <= dv:
            best = v
    return best

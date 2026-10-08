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


def bedrock_storage_version(v: Sequence[int]) -> int:
    """The level.dat ``StorageVersion`` (and the integer in front of the file) Bedrock ``v`` writes: 8 before
    1.19.20 (real 1.10 - 1.18.2 worlds), 9 from 1.19.20 (a 1.19.22 world), 10 from 1.19.50 (1.19.50
    and every later one).  1.19.30 / 1.19.40 are not in the samples: they get 9, the lower of the two possible
    values (the game upgrades an older storage version, never a newer one)."""
    s = bedrock_stored(v, 3)
    return 10 if s >= (1, 19, 50) else 9 if s >= (1, 19, 20) else 8


# level.dat ``NetworkVersion``: the protocol number of the game that wrote the world (first Bedrock version of
# each protocol).  From real worlds (1.10.1: 340, 1.11.4: 354, 1.16.200: 421, 1.16.220: 431, 1.17.20: 456, 1.17.40:
# 471, 1.18.0 / 1.18.2: 475, 1.19.22: 545, 1.19.50: 560, 1.20.0: 588, 1.20.51: 630, 1.20.72: 662, 26.40: 2168)
# and the public protocol list; the game rewrites it the next time it saves the world.
_PROTOCOLS = ((1, 2, 13, 160), (1, 4, 0, 223), (1, 6, 0, 261), (1, 8, 0, 282), (1, 10, 0, 340), (1, 11, 0, 354),
              (1, 12, 0, 361), (1, 13, 0, 388), (1, 14, 0, 389), (1, 16, 0, 407), (1, 16, 100, 419),
              (1, 16, 200, 421), (1, 16, 210, 428), (1, 16, 220, 431), (1, 17, 0, 440), (1, 17, 10, 448),
              (1, 17, 20, 456), (1, 17, 30, 465), (1, 17, 40, 471), (1, 18, 0, 475), (1, 18, 10, 486),
              (1, 18, 30, 503), (1, 19, 0, 527), (1, 19, 10, 534), (1, 19, 20, 545), (1, 19, 30, 554),
              (1, 19, 40, 557), (1, 19, 50, 560), (1, 19, 60, 567), (1, 19, 70, 575), (1, 19, 80, 582),
              (1, 20, 0, 589), (1, 20, 10, 594), (1, 20, 30, 618), (1, 20, 40, 622), (1, 20, 50, 630),
              (1, 20, 60, 649), (1, 20, 70, 662), (1, 20, 80, 671), (1, 21, 0, 685), (1, 21, 20, 712),
              (1, 21, 30, 729), (1, 21, 40, 748), (1, 21, 50, 766), (1, 21, 60, 776), (1, 21, 70, 786),
              (1, 21, 80, 800), (1, 21, 90, 818), (1, 21, 100, 827), (1, 21, 110, 844), (1, 21, 120, 859),
              (26, 40, 0, 2168))


def bedrock_protocol(v: Sequence[int]) -> int:
    """The protocol number (level.dat ``NetworkVersion``) of Bedrock ``v``: the one of the newest known
    version that is not newer than it."""
    s = bedrock(v) or ()
    s = (tuple(s) + (0, 0, 0))[:3]
    best = _PROTOCOLS[0][3]
    for *ver, proto in _PROTOCOLS:
        if tuple(ver) <= s:
            best = proto
    return best


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


def java_data_version(version: Sequence[int]) -> Optional[int]:
    """The DataVersion of Java release ``version`` (None: unknown)."""
    try:
        dv = int(_tm().get_version("java", tuple(version)).data_version)
        return dv if dv > 0 else None
    except Exception:  # noqa: BLE001
        return None


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

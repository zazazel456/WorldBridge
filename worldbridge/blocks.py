"""Numeric block registries of the old formats and the down-grade rules used
when a block does not exist in the target game version."""

from __future__ import annotations

import functools
from typing import Dict, FrozenSet, Iterable, Optional, Tuple

import numpy as np

# Java version (as an ordinal) in which each numeric block id appeared.
_V = {"alpha": 1, "b1.2": 2, "b1.3": 3, "b1.4": 4, "b1.5": 5, "b1.6": 6, "b1.7": 7, "b1.8": 8, "1.0": 9, "1.1": 10,
      "1.2": 11, "1.3": 12, "1.4": 13, "1.5": 14, "1.6": 15, "1.7": 16, "1.8": 17, "1.9": 18, "1.10": 19, "1.11": 20,
      "1.12": 21}


def version_rank(version: str) -> int:
    return _V[version]


def _intro_table() -> Dict[int, int]:
    t: Dict[int, int] = {}

    def s(ids: Iterable[int], v: str):
        for i in ids:
            t[i] = _V[v]

    s(list(range(0, 21)) + [35] + list(range(37, 92)), "alpha")
    s([21, 22, 23, 24, 25, 92], "b1.2")
    s([26, 93, 94], "b1.3")
    s([27, 28, 30], "b1.5")
    s([31, 32, 96], "b1.6")                              # tall grass, dead bush, trapdoor
    s([29, 33, 34, 36], "b1.7")
    s(range(97, 110), "b1.8")
    s(range(110, 123), "1.0")
    s([123, 124], "1.2")
    s(range(125, 137), "1.3")
    s(range(137, 146), "1.4")
    s(range(146, 159), "1.5")
    s([159, 170, 171, 172, 173], "1.6")
    s([95, 160, 161, 162, 163, 164, 174, 175], "1.7")
    s([165, 166, 167, 168, 169] + list(range(176, 198)), "1.8")
    s(list(range(198, 213)) + [255], "1.9")
    s(range(213, 218), "1.10")
    s(range(218, 235), "1.11")
    s(range(235, 253), "1.12")
    return t


INTRO = _intro_table()



def java_upto(version: str) -> FrozenSet[int]:
    lim = _V[version]
    return frozenset(i for i, v in INTRO.items() if v <= lim)


# replacement rules: id -> function(data) -> (id, data)
def _same(i):
    return lambda d: (i, d)


def _fixed(i, dd=0):
    return lambda d: (i, dd)


FALLBACK = {
    95: _fixed(20), 160: _fixed(102),
    159: lambda d: (35, d), 172: _fixed(35, 1),
    161: lambda d: (18, d & 12), 162: lambda d: (17, (d & 12) | (d & 1)),
    163: _same(53), 164: _same(53), 174: _fixed(79),
    175: lambda d: (0, 0) if d & 8 else (31, 1),
    165: _fixed(35, 5), 166: _fixed(0), 167: _same(96), 168: _fixed(98, 1), 169: _fixed(89),
    176: _fixed(0), 177: _fixed(0), 178: _same(151), 151: _fixed(0),
    179: lambda d: (24, d), 180: _same(128), 181: _fixed(43, 1), 182: lambda d: (44, (d & 8) | 1),
    183: _same(107), 184: _same(107), 185: _same(107), 186: _same(107), 187: _same(107),
    188: _fixed(85), 189: _fixed(85), 190: _fixed(85), 191: _fixed(85), 192: _fixed(85),
    193: _same(64), 194: _same(64), 195: _same(64), 196: _same(64), 197: _same(64),
    198: _fixed(50, 5), 199: _fixed(0), 200: _fixed(0), 201: _fixed(155), 202: _fixed(155, 2),
    203: _same(156), 204: _fixed(43, 7), 205: lambda d: (44, (d & 8) | 7), 206: _fixed(121),
    207: _same(59), 208: _fixed(2), 209: _fixed(0), 210: _fixed(137), 211: _fixed(137), 212: _fixed(79),
    255: _fixed(1), 213: _fixed(87), 214: _fixed(35, 14), 215: _fixed(112), 216: _fixed(155),
    217: _fixed(0), 218: _fixed(1),
    **{i: (lambda d: (54, d if 2 <= d <= 5 else 2)) for i in range(219, 235)},
    **{i: (lambda d, c=i - 235: (159, c)) for i in range(235, 251)},
    251: lambda d: (159, d), 252: lambda d: (159, d), 253: _fixed(0), 254: _fixed(0),
    137: _fixed(1), 138: _fixed(20), 146: _same(54), 147: _fixed(70), 148: _fixed(70),
    149: lambda d: (93, d & 3), 150: lambda d: (93, d & 3), 152: _fixed(35, 14), 154: _fixed(1),
    157: lambda d: (66, d & 7), 158: _same(23), 170: _fixed(35, 4), 173: _fixed(35, 15),
    # beta/alpha era down-grades
    123: _fixed(89), 124: _fixed(89), 125: _fixed(5), 126: lambda d: (44, (d & 8) | 2),
    127: _fixed(0), 128: _same(53), 129: _fixed(56), 130: _same(54), 131: _fixed(0), 132: _fixed(0),
    133: _fixed(57), 134: _same(53), 135: _same(53), 136: _same(53), 139: _fixed(4), 140: _fixed(0),
    141: _same(59), 142: _same(59), 143: _same(77), 144: _fixed(0), 145: _fixed(42), 153: _fixed(87),
    155: _fixed(42), 156: _same(67), 171: _fixed(0),
    110: _fixed(2), 111: _fixed(0), 112: _fixed(45), 113: _fixed(85), 114: _same(67), 115: _fixed(0),
    116: _fixed(49), 117: _fixed(0), 118: _fixed(0), 119: _fixed(0), 120: _fixed(1), 121: _fixed(1),
    122: _fixed(49), 97: _fixed(1), 98: _fixed(1), 99: _fixed(0), 100: _fixed(0), 101: _fixed(0),
    102: _fixed(20), 103: _fixed(86), 104: _fixed(0), 105: _fixed(0), 106: _fixed(0), 107: _fixed(85),
    108: _same(67), 109: _same(67), 29: _fixed(1), 33: _fixed(1), 34: _fixed(0), 36: _fixed(0),
    96: _fixed(0), 27: lambda d: (66, d & 7), 28: lambda d: (66, d & 7), 30: _fixed(0), 31: _fixed(0),
    32: _fixed(0), 26: _fixed(0), 93: _fixed(55), 94: _fixed(55), 21: _fixed(1), 22: _fixed(1),
    23: _fixed(4), 24: _fixed(12), 25: _fixed(5), 92: _fixed(0),
}
# LCE aquatic numeric ids (>255) are handled through ids.LCE_MODERN_BLOCKS


@functools.lru_cache(maxsize=None)
def _lut(allowed: FrozenSet[int]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(dest_id[4096*16], dest_data[4096*16], changed_mask) lookup indexed by id<<4|data."""
    from . import ids as _ids

    dst_id = np.zeros(4096 * 16, np.uint16)
    dst_data = np.zeros(4096 * 16, np.uint8)
    for bid in range(4096):
        for d in range(16):
            i, dd = bid, d
            for _ in range(8):
                if i in allowed:
                    break
                if i > 255 and i in _ids.LCE_MODERN_BLOCKS:
                    i, dd = _ids.lce_modern_fallback(i)
                    continue
                f = FALLBACK.get(i)
                if f is None:
                    i, dd = (1, 0) if i > 0 else (0, 0)
                    continue
                i, dd = f(dd)
            else:
                i, dd = 1, 0
            if i not in allowed:
                i, dd = 1, 0
            dst_id[bid << 4 | d] = i
            dst_data[bid << 4 | d] = dd
    key = np.arange(4096 * 16)
    changed = (dst_id != (key >> 4)) | (dst_data != (key & 15))
    return dst_id, dst_data, changed


def downgrade(blocks: np.ndarray, data: np.ndarray, allowed: Optional[FrozenSet[int]]) -> Tuple[np.ndarray, np.ndarray, int]:
    """Replace every block not in ``allowed``; returns (blocks, data, n_changed)."""
    if allowed is None:
        return blocks, data, 0
    dst_id, dst_data, changed = _lut(allowed)
    key = (blocks.astype(np.int64) << 4) | data.astype(np.int64)
    ch = changed[key]
    n = int(ch.sum())
    if not n:
        return blocks, data, 0
    return dst_id[key].astype(blocks.dtype), dst_data[key].astype(data.dtype), n


# tile entities that must follow a block replacement: new block id -> legacy TE id
TILE_FOR_BLOCK = {54: "Chest", 146: "Chest", 23: "Trap", 61: "Furnace", 62: "Furnace", 63: "Sign", 68: "Sign", 52: "MobSpawner",
                  84: "RecordPlayer", 25: "Music", 116: "EnchantTable", 117: "Cauldron", 144: "Skull",
                  130: "EnderChest", 138: "Beacon", 154: "Hopper", 158: "Dropper", 140: "FlowerPot",
                  149: "Comparator", 150: "Comparator", 151: "DLDetector", 178: "DLDetector", 176: "Banner",
                  177: "Banner", 137: "Control", 119: "Airportal", 209: "EndGateway", 26: "Bed",
                  **{i: "ShulkerBox" for i in range(219, 235)}}

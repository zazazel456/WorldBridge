"""BTA's ``ChunkConverter.converters[0]`` (save version 19132 -> 19133 block id remapping).

BTA still applies it lazily to item stacks and jukebox records written before save version 19133,
so the converter must do the same.  Table copied from the decompiled BTA 8.0.1 source.
"""

from __future__ import annotations

from typing import Callable, Dict, Tuple

_Conv = Callable[[int], Tuple[int, int]]
_MAP: Dict[int, _Conv] = {}


def _simple(old: int, new: int) -> None:
    _MAP[old] = lambda meta: (new, meta)


def _meta_to_id(old: int, ids, fallback: int = 0) -> None:
    _MAP[old] = lambda meta: (fallback, 0) if meta >= len(ids) else (ids[meta], 0)


def _leaves_meta_to_id(old: int, ids, fallback: int = 0) -> None:
    _MAP[old] = lambda meta: (fallback, 0) if (meta & 3) >= len(ids) else (ids[meta & 3], meta & 12)


def _complex(old: int, ids, metas, backup: int = 0) -> None:
    _MAP[old] = lambda meta: (backup, 0) if meta >= len(ids) else (ids[meta], metas[meta])


for _o, _n in ((1, 1), (2, 200), (3, 220), (4, 10), (5, 50), (7, 260), (8, 270), (9, 271), (10, 272), (11, 273),
               (12, 250), (13, 251), (19, 230), (20, 190), (22, 433), (23, 560), (24, 30), (25, 530), (26, 610),
               (27, 541), (28, 542), (29, 521), (30, 620), (32, 322), (33, 520), (34, 522), (35, 110), (36, 523),
               (37, 330), (38, 331), (39, 340), (40, 341), (41, 432), (42, 431), (45, 120), (46, 500), (47, 100),
               (48, 11), (49, 180), (50, 60), (51, 630), (52, 640), (53, 160), (54, 680), (55, 450), (57, 435),
               (58, 650), (59, 690), (60, 700), (61, 660), (62, 661), (63, 710), (64, 590), (65, 70), (66, 540),
               (67, 161), (68, 711), (69, 480), (70, 490), (71, 592), (72, 491), (75, 460), (76, 461), (77, 470),
               (78, 720), (79, 730), (80, 740), (81, 750), (82, 760), (83, 770), (84, 780), (85, 80), (86, 791),
               (87, 800), (88, 810), (89, 820), (90, 830), (91, 792), (92, 840), (93, 510), (94, 511), (96, 570),
               (97, 121), (98, 122), (99, 123), (100, 124), (101, 125), (102, 210), (103, 162), (104, 91), (105, 550),
               (106, 600), (107, 2), (108, 3), (109, 4), (111, 420), (112, 662), (113, 663), (114, 437), (115, 231),
               (116, 492), (117, 12), (118, 13), (119, 14), (120, 126), (121, 127), (122, 128), (123, 500),
               (124, 501), (125, 140), (126, 141), (127, 142), (128, 143), (129, 144), (130, 146), (131, 591),
               (132, 593), (134, 721), (135, 831), (136, 201), (137, 291), (138, 671), (139, 790), (140, 670),
               (141, 801), (142, 5), (143, 20), (144, 129), (145, 163), (146, 145), (147, 222), (148, 221)):
    _simple(_o, _n)
_meta_to_id(6, (310, 312, 313, 314))
_meta_to_id(14, (370, 371, 372, 373))
_meta_to_id(15, (360, 361, 362, 363))
_meta_to_id(16, (350, 351, 352, 353))
_meta_to_id(17, (280, 281, 282, 283))
_leaves_meta_to_id(18, (290, 292, 293, 294))
_meta_to_id(21, (380, 381, 382, 383))
_meta_to_id(31, (322, 320, 321))
_complex(43, (144, 142, 140, 141, 143), (1, 1, 1, 1, 1))
_complex(44, (144, 142, 140, 141, 143), (0, 0, 0, 0, 0))
_meta_to_id(56, (410, 411, 412, 413))
_meta_to_id(73, (390, 391, 392, 393))
_meta_to_id(74, (400, 401, 402, 403))
_meta_to_id(110, (240, 241, 242, 243))


def convert(bid: int, meta: int) -> Tuple[int, int]:
    """(new id, new meta); unmapped ids become air, exactly like BTA."""
    m = _MAP.get(bid) if 0 <= bid <= 148 else None
    if m is None:
        return 0, 0
    nid, nmeta = m(meta & 0xFF)
    return nid, nmeta & 0xFF

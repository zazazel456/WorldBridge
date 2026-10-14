"""tools/seam_check.py: the seam metric between a converted world and the terrain the game generated."""
import importlib.util
import os
import struct
import zlib

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "seam_check", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "seam_check.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


def _chunk(h, water=None):
    """A chunk's columns: ground ``h`` (a number or a [16, 16] [z, x] array), optional water surface."""
    g = np.full((16, 16), h, np.int32) if np.isscalar(h) else np.asarray(h, np.int32)
    w = np.full((16, 16), -1, np.int32) if water is None else np.full((16, 16), water, np.int32)
    return g, w


def _bumpy(seed, base=70, amp=2):
    return np.random.default_rng(seed).integers(base - amp, base + amp + 1, (16, 16))


def _world(sel_h, game_h, ring_h=None, n=3, ring_n=0, game_n=4):
    """A square selection of n x n chunks, a ring of ring_n chunks around it and game_n chunks of game terrain."""
    conv, game, sel = {}, {}, set()
    total = n + 2 * (ring_n + game_n)
    off = -(ring_n + game_n)
    for i in range(total):
        for j in range(total):
            c = (off + i, off + j)
            d = max(-c[0], c[0] - (n - 1), -c[1], c[1] - (n - 1))      # chunk distance to the selection
            if d <= 0:
                conv[c] = _chunk(sel_h(c) if callable(sel_h) else sel_h)
                sel.add(c)
            elif d <= ring_n:
                conv[c] = _chunk(ring_h(c) if callable(ring_h) else ring_h)
            else:
                game[c] = _chunk(game_h(c) if callable(game_h) else game_h)
    return conv, game, sel


def test_identical_terrain_is_ok():
    conv, game, sel = _world(70, 70)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    assert rep["verdict"] == "OK" and rep["outer"]["n"] == 4 * 3 * 16
    assert rep["outer"]["mean"] == 0 and rep["outer"]["max"] == 0
    assert rep["chunks"] == {"sel": 9, "ring": 0, "game": 112}
    assert not rep["ring_written"] and "inner" not in rep


def test_a_wall_along_the_edge_is_a_cut():
    conv, game, sel = _world(70, 90)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    o = rep["outer"]
    assert rep["verdict"] == "CUT" and o["mean"] == 20 and o["share_gt8"] == 1 and o["share_gt3"] == 1
    assert o["bias_a_minus_b"] == -20                      # converted side lower than the game's
    assert set(o["per_edge"]) == {"N", "S", "E", "W"} and all(v["n"] == 48 for v in o["per_edge"].values())


def test_a_wall_on_one_edge_is_a_step():
    # only the east side of the selection meets terrain 10 blocks higher: 1/4 of the border pairs
    conv, game, sel = _world(70, lambda c: 80 if c[0] > 2 else 70)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    assert rep["outer"]["share_gt8"] == pytest.approx(0.25, abs=0.01)
    assert rep["outer"]["per_edge"]["E"]["mean"] == 10 and rep["outer"]["per_edge"]["W"]["mean"] == 0
    assert rep["verdict"] == "STEP"


def test_the_games_own_roughness_is_not_a_seam():
    # the same bumpy terrain on both sides: the border is as rough as the terrain inside, the verdict is OK
    rough = lambda c: _bumpy(hash(c) & 0xFFFF, 70, 3)           # noqa: E731
    conv, game, sel = _world(rough, rough)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    assert rep["baseline"]["n"] > 200 and rep["baseline"]["mean"] > 1
    assert rep["outer"]["mean"] == pytest.approx(rep["baseline"]["mean"], abs=0.6)
    assert rep["verdict"] == "OK"


def test_baseline_is_taken_away_from_the_border():
    # game terrain is a staircase at the border (chunks 1 away) but flat from 2 chunks out
    conv, game, sel = _world(70, lambda c: 70 + 6 * ((max(-c[0], c[0] - 2, -c[1], c[1] - 2)) % 2), game_n=5)
    rep, _ = sc.seam_report_from_columns(conv, game, sel, baseline_margin=2)
    assert rep["baseline"]["n"] > 0
    assert rep["baseline"]["max"] == 6                      # the stair inside the game's area is the baseline
    rep3, _ = sc.seam_report_from_columns(conv, game, sel, baseline_margin=4)
    assert rep3["baseline"]["n"] < rep["baseline"]["n"]


def test_ring_groups_and_the_ring_option():
    # selection 70, ring 74 (a step of 4 at its start), game 74: the ring's outer edge is seamless
    conv, game, sel = _world(70, 74, ring_h=74, ring_n=2)
    rep, _ = sc.seam_report_from_columns(conv, game, sel, ring="include")
    assert rep["ring_written"] and rep["chunks"]["ring"] == 7 * 7 - 9
    assert rep["outer"]["mean"] == 0 and rep["verdict"] == "OK"                 # (sel + ring) | game
    assert rep["ring_game"]["mean"] == 0 and rep["verdict_ring_game"] == "OK"
    assert rep["inner"]["mean"] == 4 and rep["inner"]["share_gt3"] == 1         # where the ring starts
    assert rep["sel_game"]["n"] == 0                                            # no selection chunk touches the game
    ex, _ = sc.seam_report_from_columns(conv, game, sel, ring="exclude")
    assert ex["outer"]["mean"] == 4 and ex["outer"]["n"] == rep["inner"]["n"]   # sel | ring
    assert ex["verdict"] == "CUT" and rep["verdict"] == "OK"


def test_ring_that_does_not_reach_the_games_terrain():
    conv, game, sel = _world(70, 90, ring_h=70, ring_n=2)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    assert rep["inner"]["mean"] == 0 and rep["ring_game"]["mean"] == 20
    assert rep["verdict"] == "CUT" and rep["verdict_ring_game"] == "CUT" and rep["verdict_inner"] == "OK"


def test_water_land_mismatch_and_spill():
    conv, game, sel = _world(70, 70)
    for c in list(game):
        if c == (3, 1):                                    # east neighbour: a lake whose surface is above the shore
            game[c] = _chunk(60, water=69)
    for c in list(conv):
        if c == (2, 1):                                    # converted shore (dry, 70) next to it
            conv[c] = _chunk(70)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    o = rep["outer"]
    assert o["water_land_n"] == 16 and o["water_spill_n"] == 0       # 69 < 70: the water stays in its basin
    game[(3, 1)] = _chunk(60, water=72)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    assert rep["outer"]["water_spill_n"] == 16 and rep["outer"]["water_spill_share"] > 0


def test_void_columns_are_counted_not_measured():
    conv, game, sel = _world(70, 70)
    game[(3, 0)] = _chunk(sc.EMPTY)
    rep, _ = sc.seam_report_from_columns(conv, game, sel)
    assert rep["outer"]["void_pairs"] == 16 and rep["outer"]["n"] == 4 * 3 * 16 - 16


def test_converted_chunks_are_read_from_the_game_save_by_default():
    conv, game, sel = _world(70, 70)
    game[(0, 0)] = _chunk(75)                              # the game changed a converted chunk (upgrade, blending)
    from_game, _ = sc.seam_report_from_columns(conv, game, sel, converted_from="game")
    as_written, _ = sc.seam_report_from_columns(conv, game, sel, converted_from="converted")
    assert from_game["chunks"]["sel"] == as_written["chunks"]["sel"] == 9
    assert as_written["outer"]["mean"] == 0 and from_game["outer"]["max"] == 5


def test_tile_columns_ground_is_the_floor_under_the_water():
    from worldbridge.mapview import Tile
    h = np.full((16, 16), 64, np.int16)
    dep = np.zeros((16, 16), np.int16)
    dep[0, 0] = 5                                          # water surface 64 over a floor at 59
    h[1, 1] = -32768                                       # no block at all
    t = Tile(np.zeros((16, 16, 3), np.uint8), h, dep, ["stone"], np.zeros((16, 16), np.uint16))
    g, w = sc.tile_columns(t)
    assert g[0, 0] == 59 and w[0, 0] == 64 and g[2, 2] == 64 and w[2, 2] == -1 and g[1, 1] == sc.EMPTY


def test_foliage_does_not_count_as_ground():
    from worldbridge import mapview
    names = ["oak_leaves", "oak_log", "short_grass", "snow", "grass_block", "snow_block", "stone", "air", "tallgrass"]
    with sc.ground_mode():
        soft = [mapview.is_air(n) for n in names]
        nums = mapview._NUM_AIR[18 * 16] and mapview._NUM_AIR[17 * 16 + 3] and not mapview._NUM_AIR[2 * 16]
    assert soft == [True, True, True, True, False, False, False, True, True] and nums
    assert not mapview.is_air("oak_leaves") and not mapview._NUM_AIR[18 * 16]     # restored afterwards


def test_png_writer_and_render(tmp_path):
    conv, game, sel = _world(lambda c: 60 + 5 * c[0], 80, ring_h=70, ring_n=1)
    rep, grid = sc.seam_report_from_columns(conv, game, sel)
    p = tmp_path / "x.png"
    sc.render_png(grid, str(p))
    data = p.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    assert w > 100 and h > 100
    # IDAT decompresses to h rows of 1 + 3 * w bytes
    idat = b"".join(data[i + 4:i + 4 + n] for i, n in _png_chunks(data, b"IDAT"))
    assert len(zlib.decompress(idat)) == h * (1 + 3 * w)


def _png_chunks(data, tag):
    pos = 8
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        if data[pos + 4:pos + 8] == tag:
            yield pos + 4, n
        pos += 12 + n


def test_reads_a_real_world_and_measures_it(tmp_path):
    """A real Java 1.12 (Anvil) world written by WorldBridge: one converted chunk, one the game's."""
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
    from worldbridge.model import NumericChunk, Progress, WorldInfo

    def world(path, heights):
        w = JavaNumericWriter(str(path), JavaWriteOptions(kind="anvil"), Progress())
        for (cx, cz), h in heights.items():
            c = NumericChunk(cx, cz, 256)
            c.blocks[0] = 7
            c.blocks[1:h] = 1
            c.blocks[h] = 2
            c.blocks[h + 1, 3, 3] = 18              # a leaf above the ground: foliage, not ground
            w.add_chunk(0, c)
        w.finish(WorldInfo())
        return str(path)

    conv = world(tmp_path / "conv", {(0, 0): 70})
    game = world(tmp_path / "game", {(0, 0): 70, (1, 0): 80})
    cols = sc.read_columns(conv, 0)
    g, w = cols[(0, 0)]
    assert (g == 70).all() and (w == -1).all()               # the leaf at (3, 3) is not counted
    rep = sc.run(conv, game, {(0, 0)})
    assert rep["chunks"] == {"sel": 1, "ring": 0, "game": 1}
    assert rep["outer"]["n"] == 16 and rep["outer"]["mean"] == 10 and rep["outer"]["per_edge"]["E"]["n"] == 16
    assert rep["verdict"] in ("STEP", "CUT")
    assert sc.summary_line(rep, "x").startswith("x ")

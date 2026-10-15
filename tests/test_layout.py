"""Composition: groups of chunks of the source, each placed at its own destination (worldbridge.layout)."""
import numpy as np
import pytest

from worldbridge import amulet_bridge as ab
from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert, layout_bounds
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.layout import Group, Layout
from worldbridge.lce.world import LCEWorld
from worldbridge.model import OVERWORLD, NETHER, ConversionError, NumericChunk, Progress
from worldbridge.relocate import Relocation
from worldbridge.selection import Selection

from .helpers import SyntheticWorld, make_chunk

A = frozenset((100 + x, 1000 + z) for x in range(3) for z in range(2))        # 3 x 2, far away
B = frozenset((-300 + x, 700 + z) for x in range(2) for z in range(2))        # 2 x 2, far away the other way
A_OFF, B_OFF = (-100, -1000), (304, -700)                                      # A lands on x 0..2, B on x 4..5; z 0..1


def _layout():
    return Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, B, B_OFF)])


class TwoClusters(SyntheticWorld):
    def chunk_coords(self, dim):
        return sorted(A | B)

    def read_chunk(self, dim, cx, cz):
        return make_chunk(cx, cz, seed=dim)


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """A Java anvil (numeric) world holding A and B; the spawn is in A, the player in B."""
    src = TwoClusters(radius=2)
    sa = sorted(A)[0]
    sb = sorted(B)[0]
    src.info.level["SpawnX"], src.info.level["SpawnZ"] = nbt.IntTag(sa[0] * 16 + 3), nbt.IntTag(sa[1] * 16 + 3)
    src.info.players["host"]["Pos"] = nbt.ListTag([nbt.DoubleTag(sb[0] * 16 + 5.5), nbt.DoubleTag(65.0),
                                                   nbt.DoubleTag(sb[1] * 16 + 5.5)], 6)
    out = str(tmp_path_factory.mktemp("two") / "src")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    return out


@pytest.fixture(scope="module")
def modern(source, tmp_path_factory):
    out = str(tmp_path_factory.mktemp("modern") / "w")
    convert(source, out, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False))
    return out


def _dest(layout, c, dim=OVERWORLD):
    return layout.dest(dim, *c)


def _expected_dests(layout):
    return {layout.dest(g.dim, *c) for g in layout.groups for c in g.chunks}


# ------------------------------------------------------------------ the model
def test_dest_lookup_and_groups():
    lay = _layout()
    assert lay.dest(OVERWORLD, 100, 1000) == (0, 0) and lay.dest(OVERWORLD, -300, 700) == (4, 0)
    assert lay.dest(OVERWORLD, 0, 0) is None and lay.dest(NETHER, 100, 1000) is None
    assert len(lay.groups_of(OVERWORLD)) == 2 and lay.groups_of(NETHER) == []
    assert lay.source_chunks() == {OVERWORLD: set(A | B)}
    assert lay.placed()[OVERWORLD] == {(x, z) for x in (0, 1, 2, 4, 5) for z in (0, 1)}
    assert lay.problems() == []
    assert Selection(layout=lay).chunks == {OVERWORLD: set(A | B)}         # what is read: the union of the groups


def test_problems_overlap_duplicate_source_and_finite_bounds():
    over = Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, B, (301, -700))])
    # B moved onto A's destination: the destinations clash
    lines = over.problems()
    assert any("overlap" in m for m in lines), lines
    dup = Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, A | B, B_OFF)])
    assert any("two groups" in m for m in dup.problems())
    assert Layout([]).problems() and Layout([Group(OVERWORLD, frozenset(), (0, 0))]).problems()
    far = Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, B, (B_OFF[0] + 100, B_OFF[1]))])
    lce54 = TargetSpec(family="lce", lce_platform="xbox360", lce_world_size=54)
    bounds = layout_bounds(lce54, far)
    assert bounds[OVERWORLD] == (-27, 27, -27, 27)
    assert any("outside the map" in m for m in far.problems(bounds))
    assert _layout().problems(layout_bounds(lce54, _layout())) == []
    pe = layout_bounds(TargetSpec(family="pe_old"), _layout())
    assert pe[OVERWORLD][1] - pe[OVERWORLD][0] == 16
    assert layout_bounds(TargetSpec(family="java"), _layout()) is None


def test_json_round_trip_and_forms(tmp_path):
    lay = _layout()
    path = str(tmp_path / "l.json")
    lay.save(path)
    again = Layout.load(path)
    assert again.groups == lay.groups
    got = Layout.from_dict({"groups": [{"dimension": "nether", "chunks": "3,4;-3,5", "offset": [1, -2]},
                                       {"dimension": "end", "chunks": [[0, 0]], "offset": [0, 0]}]})
    assert got.groups[0].dim == NETHER and got.groups[0].chunks == {(3, 4), (-3, 5)} and got.groups[0].offset == (1, -2)
    for bad in ({}, {"groups": [{"chunks": "1,1"}]}, {"groups": [{"dimension": "moon", "chunks": [], "offset": [0, 0]}]},
                {"groups": [{"chunks": "a,b", "offset": [0, 0]}]}):
        with pytest.raises(ValueError):
            Layout.from_dict(bad)
    (tmp_path / "x.json").write_text("{nope")
    with pytest.raises(ValueError):
        Layout.load(str(tmp_path / "x.json"))


def test_move_to_is_a_one_group_layout_with_the_old_behaviour():
    chunks = {OVERWORLD: {(100 + x, 1000 + z) for x in range(4) for z in range(4)}, NETHER: {(10, 10), (12, 11)}}
    mv = Relocation(Selection(chunks=chunks, move_to=(1000, -2000)))
    assert mv.delta(OVERWORLD) == ((1000 >> 4) - 101, (-2000 >> 4) - 1001)         # the bounding-box centre lands there
    assert mv.delta(NETHER) == (((1000 // 8) >> 4) - 11, ((-2000 // 8) >> 4) - 10)   # the Nether point is divided by 8
    assert mv.offset(OVERWORLD, 100, 1000) == mv.delta(OVERWORLD) and mv.active
    assert len(mv.layout.groups) == 2
    with pytest.raises(ValueError):
        Selection(layout=_layout(), move_to=(0, 0))


def test_relocation_with_two_groups():
    mv = Relocation(Selection(layout=_layout()))
    assert mv.offset(OVERWORLD, 100, 1000) == A_OFF and mv.offset(OVERWORLD, -299, 701) == B_OFF
    assert mv.coords(OVERWORLD, [(100, 1000), (-300, 700)]) == [(0, 0), (4, 0)]
    with pytest.raises(ValueError):
        mv.delta(OVERWORLD)
    # a villager in A remembering a bed that lies in B: shifted by the group that holds the bed
    tl = []
    el = [{"pos": (100 * 16 + 1.0, 64, 1000 * 16 + 1.0),
           "poi": {"home": (-300 * 16 + 2, 64, 700 * 16 + 2), "job_site": (100 * 16 + 4, 64, 1000 * 16 + 4)}}]
    assert mv.canon_chunk(OVERWORLD, 100, 1000, tl, el) == (0, 0)
    assert el[0]["pos"][0] == 1.0 and el[0]["poi"]["home"] == (4 * 16 + 2, 64, 2) and el[0]["poi"]["job_site"] == (4, 64, 4)
    # players: in a group -> its offset; outside -> the new spawn
    sp = mv.spawn(_info((100 * 16 + 3, 64, 1000 * 16 + 3)))
    assert sp == (3, 64, 3)
    assert mv._moved(OVERWORLD, -300 * 16 + 5.5, 700 * 16 + 5.5) == (4 * 16 + 5.5, 5.5)
    assert mv._moved(OVERWORLD, 5000.5, 5000.5) is None


def _info(spawn):
    from worldbridge.model import WorldInfo

    i = WorldInfo()
    i.level = nbt.CompoundTag({"SpawnX": nbt.IntTag(spawn[0]), "SpawnY": nbt.IntTag(spawn[1]), "SpawnZ": nbt.IntTag(spawn[2])})
    return i


# ------------------------------------------------------------------ routes
def _check_numeric(w, lay, full_blocks=True):
    assert set(w.chunk_coords(0)) == _expected_dests(lay)                       # nothing else is written
    for g in lay.groups:
        for c in g.chunks:
            d = g.dest(*c)
            ch = w.read_chunk(0, *d)
            if full_blocks:
                assert np.array_equal(np.asarray(ch.blocks), make_chunk(*c).blocks), d
            assert ch.blocks[64, 5, 5] == 35                                       # the wool block
            assert [(int(nbt.get(t, "x")), int(nbt.get(t, "z"))) for t in ch.tile_entities] == [(d[0] * 16 + 6, d[1] * 16 + 6)]
            assert float(nbt.get_tag(ch.entities[0], "Pos")[0].py_data) == d[0] * 16 + 8.5
            assert float(nbt.get_tag(ch.entities[0], "Pos")[2].py_data) == d[1] * 16 + 8.5


def test_java_numeric_two_groups_moved_closer(source, tmp_path):
    lay = _layout()
    out = str(tmp_path / "num")
    convert(source, out, TargetSpec(family="java", java_mode="numeric", ring=False, selection=Selection(layout=lay)))
    w = JavaNumericWorld(out)
    _check_numeric(w, lay)
    lv = w.info.level
    sa = sorted(A)[0]
    assert (int(nbt.get(lv, "SpawnX")), int(nbt.get(lv, "SpawnZ"))) == (3, 3)      # the spawn moved with its group (A)
    p = next(iter(w.info.players.values()))                                       # the player stood in B
    sb = sorted(B)[0]
    assert float(nbt.get_tag(p, "Pos")[0].py_data) == (sb[0] + B_OFF[0]) * 16 + 5.5
    assert float(nbt.get_tag(p, "Pos")[2].py_data) == (sb[1] + B_OFF[1]) * 16 + 5.5
    assert sa  # (spawn chunk is A's first one)


def test_a_player_outside_every_group_goes_to_the_spawn(source, tmp_path):
    lay = Layout([Group(OVERWORLD, A, A_OFF)])                                    # B (with the player) is left out
    out = str(tmp_path / "num")
    convert(source, out, TargetSpec(family="java", java_mode="numeric", ring=False, selection=Selection(layout=lay)))
    w = JavaNumericWorld(out)
    assert set(w.chunk_coords(0)) == lay.placed()[OVERWORLD]
    p = next(iter(w.info.players.values()))
    assert 0 <= float(nbt.get_tag(p, "Pos")[0].py_data) < 48 and 0 <= float(nbt.get_tag(p, "Pos")[2].py_data) < 32


def _level_checks(path, lay, platform_players):
    level = ab.load_level(path)
    try:
        got = set(level.all_chunk_coords("minecraft:overworld"))
        assert got == _expected_dests(lay)
        for g in lay.groups:
            for c in g.chunks:
                d = g.dest(*c)
                ch = level.get_chunk(d[0], d[1], "minecraft:overworld")
                bes = list(ch.block_entities.values())
                assert bes and all(be.x >> 4 == d[0] and be.z >> 4 == d[1] for be in bes), d
                assert all(int(e.x) >> 4 == d[0] and int(e.z) >> 4 == d[1] for e in ch.entities), d
    finally:
        level.close()


def _java_level_dat(path):
    import os

    root = nbt.load(open(os.path.join(path, "level.dat"), "rb").read()).tag
    return nbt.get_tag(root, "Data") or root


def test_java_118_amulet_route(modern, tmp_path):
    lay = _layout()
    out = str(tmp_path / "back")
    convert(modern, out, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False,
                                    selection=Selection(layout=lay)))
    _level_checks(out, lay, None)
    data = _java_level_dat(out)
    assert (int(nbt.get(data, "SpawnX")), int(nbt.get(data, "SpawnZ"))) == (3, 3)
    pos = [float(v.py_data) for v in nbt.get_tag(nbt.get_tag(data, "Player"), "Pos")]
    sb = sorted(B)[0]
    assert pos[0] == (sb[0] + B_OFF[0]) * 16 + 5.5 and pos[2] == (sb[1] + B_OFF[1]) * 16 + 5.5


def test_bedrock_two_groups_moved_closer(modern, tmp_path):
    lay = _layout()
    out = str(tmp_path / "be")
    convert(modern, out, TargetSpec(family="bedrock", version=(1, 21, 0), ring=False, selection=Selection(layout=lay)))
    _level_checks(out, lay, None)
    from worldbridge.bedrock.extra import _db, _get

    db = _db(out)
    try:
        p = nbt.load(_get(db, b"~local_player"), little_endian=True, compressed=False).tag
        pos = [float(v.py_data) for v in p["Pos"]]
    finally:
        db.close()
    sb = sorted(B)[0]
    assert pos[0] == pytest.approx((sb[0] + B_OFF[0]) * 16 + 5.5) and pos[2] == pytest.approx((sb[1] + B_OFF[1]) * 16 + 5.5)


def test_lce_finite_map_takes_two_far_apart_groups(source, tmp_path):
    lay = _layout()
    t = TargetSpec(family="lce", lce_platform="xbox360", lce_world_size=54, ring=False, selection=Selection(layout=lay))
    out = str(tmp_path / "lce")
    convert(source, out, t)
    w = LCEWorld(out)
    got = set(w.chunk_coords(0))
    assert got == _expected_dests(lay)                                             # nothing else: 54 x 54 holds them
    for g in lay.groups:
        for c in g.chunks:
            d = g.dest(*c)
            ch = w.read_chunk(0, *d)
            assert [(int(nbt.get(x, "x")) >> 4, int(nbt.get(x, "z")) >> 4) for x in ch.tile_entities] == [d]
            assert int(float(nbt.get_tag(ch.entities[0], "Pos")[0].py_data)) >> 4 == d[0]


def test_a_layout_outside_the_finite_map_is_refused(source, tmp_path):
    lay = Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, B, (B_OFF[0] + 100, B_OFF[1]))])
    t = TargetSpec(family="lce", lce_platform="xbox360", lce_world_size=54, ring=False, selection=Selection(layout=lay))
    with pytest.raises(ConversionError, match="outside the map"):
        convert(source, str(tmp_path / "lce"), t)


def test_pocket_edition_16x16_map(source, tmp_path):
    from worldbridge.bedrock.pe_old import PEOldWorld

    lay = _layout()
    out = str(tmp_path / "pe")
    convert(source, out, TargetSpec(family="pe_old", ring=False, selection=Selection(layout=lay)))
    assert _expected_dests(lay) <= set(PEOldWorld(out).chunk_coords(0))


# ------------------------------------------------------------------ the border covers all the groups together
def test_close_groups_get_one_joined_ring_without_holes_or_duplicates(tmp_path):
    from worldbridge.terrain import ring as ring_mod

    class Flat:
        def chunk(self, cx, cz):
            b = np.zeros((16, 16, 128), np.uint8)
            b[:, :, 0] = 7
            b[:, :, 1:64] = 1
            b[:, :, 64] = 2
            return b, np.ones((16, 16), np.int64)

    lay = Layout([Group(OVERWORLD, frozenset({(0, 0), (1, 0)}), (0, 0)),
                  Group(OVERWORLD, frozenset({(50, 0), (51, 0)}), (-44, 0))])      # lands on x 6..7: a gap of 4 chunks
    placed = lay.placed()[OVERWORLD]
    assert placed == {(0, 0), (1, 0), (6, 0), (7, 0)}
    ring = ring_mod.Ring(Flat(), 62, sorted(placed))
    for cx, cz in sorted(placed):
        c = NumericChunk(cx, cz, 256)
        c.blocks[1:70] = 1
        c.blocks[70] = 2
        ring.observe(0, c)
    targets = ring.targets()
    assert len(targets) == len(set(targets)) and not (set(targets) & placed)         # no duplicate, never over a group
    assert all((x, 0) in set(targets) | placed for x in range(-3, 11))              # the gap between the groups is filled
    assert ring._piece_at((3, 0)) is not None and ring._piece_at((3, 0)) == ring._piece_at((-2, 0)) == ring._piece_at((9, 0))
    assert len(ring._pieces) == 1                                                    # one joined ring: a bridge


def test_conversion_to_old_java_puts_the_ring_around_both_groups(source, tmp_path):
    close = Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, B, (B_OFF[0] - 1, B_OFF[1]))])   # B on x 3..4: touching
    out = str(tmp_path / "ring")
    t = TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12", ring=True,
                   selection=Selection(layout=close))
    convert(source, out, t)
    w = JavaNumericWorld(out)
    got = set(w.chunk_coords(0))
    placed = close.placed()[OVERWORLD]
    assert placed <= got and len(got) > len(placed)                                   # a ring around them
    xs = [c[0] for c in got]
    zs = [c[1] for c in got]
    assert min(xs) < 0 and max(xs) > 4 and min(zs) < 0 and max(zs) > 1
    for c in placed:
        ch = w.read_chunk(0, *c)
        assert len(ch.tile_entities) == 1                                             # the source's chunk, not the ring's
    ringed = got - placed
    assert all(not w.read_chunk(0, *c).tile_entities for c in list(ringed)[:20])


# ------------------------------------------------------------------ command line
def test_cli_layout_option(tmp_path, monkeypatch, capsys):
    from worldbridge import cli
    from worldbridge.convert import ConversionResult

    seen = {}
    monkeypatch.setattr(cli, "convert", lambda src, out, t, prog: seen.update(sel=t.selection) or ConversionResult(out))
    good = str(tmp_path / "good.json")
    _layout().save(good)
    out = str(tmp_path / "o")
    assert cli.main(["convert", "x", out, "--to", "lce", "--size", "54", "--layout", good]) == 0
    assert seen["sel"].layout.groups == _layout().groups and seen["sel"].chunks == {OVERWORLD: set(A | B)}
    assert seen["sel"].move_to is None
    # outside the 54 x 54 map: refused before converting, with the list of problems
    far = Layout([Group(OVERWORLD, A, A_OFF), Group(OVERWORLD, B, (B_OFF[0] + 100, B_OFF[1]))])
    bad = str(tmp_path / "bad.json")
    far.save(bad)
    seen.clear()
    capsys.readouterr()
    assert cli.main(["convert", "x", out, "--to", "lce", "--size", "54", "--layout", bad]) != 0
    assert "outside the map" in capsys.readouterr().err and not seen
    csv = tmp_path / "c.csv"
    csv.write_text("0;0\n")
    for extra in (["--chunks", str(csv)], ["--move-to", "center"]):
        assert cli.main(["convert", "x", out, "--to", "lce", "--layout", good] + extra) != 0
        assert "--layout" in capsys.readouterr().err and not seen

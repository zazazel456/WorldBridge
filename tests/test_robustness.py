"""Broken input, untouched sources, Pocket Edition player (found by tools/matrix.py)."""
import gzip
import hashlib
import os
import zlib

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _anvil(path):
    src = SyntheticWorld(radius=2)
    w = JavaNumericWriter(str(path), JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    return str(path)


def _digest(folder):
    h = {}
    for root, _d, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            h[os.path.relpath(p, folder)] = hashlib.md5(open(p, "rb").read()).hexdigest()
    return h


def test_corrupted_chunk_is_skipped_with_a_warning(tmp_path):
    world = _anvil(tmp_path / "w")
    p = os.path.join(world, "region", "r.0.0.mca")
    data = bytearray(open(p, "rb").read())
    off = (int.from_bytes(data[0:4], "big") >> 8) * 4096
    data[off + 5:off + 100] = b"\xAB" * 95
    open(p, "wb").write(data)
    res = convert(world, str(tmp_path / "out"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    assert res.chunks == 15
    assert any("unreadable" in w for w in res.warnings)


def test_chunks_compressed_twice_are_read(tmp_path):
    """MCEdit 2 wrote zlib payloads that hold a gzip stream."""
    world = _anvil(tmp_path / "w")
    p = os.path.join(world, "region", "r.0.0.mca")
    reg = JavaRegion(p)
    raws = {c: reg.read(*c) for c in reg.chunks()}
    wr = RegionWriter()
    for c, raw in raws.items():
        wr.put_compressed(c[0], c[1], zlib.compress(gzip.compress(raw)))
    wr.write(p)
    reg = JavaRegion(p)
    assert {c: reg.read(*c) for c in reg.chunks()} == raws
    res = convert(world, str(tmp_path / "out"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    assert res.chunks == 16 and not any("unreadable" in w for w in res.warnings)


def test_modern_sources_are_never_touched(tmp_path):
    base = _anvil(tmp_path / "w")
    modern = str(tmp_path / "modern")
    convert(base, modern, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 1)))
    for f in ("session.lock",):
        if os.path.exists(os.path.join(modern, f)):
            os.remove(os.path.join(modern, f))
    before = _digest(modern)
    convert(modern, str(tmp_path / "lce"), TargetSpec(family="lce", ring=False))
    assert _digest(modern) == before  # no session.lock, no rewritten file
    bedrock = str(tmp_path / "bedrock")
    convert(base, bedrock, TargetSpec(family="bedrock"))
    before = _digest(bedrock)
    convert(bedrock, str(tmp_path / "back"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    assert _digest(bedrock) == before  # LevelDB never opened in place


def test_pocket_edition_player_is_written(tmp_path):
    base = _anvil(tmp_path / "w")
    pe = str(tmp_path / "pe")
    res = convert(base, pe, TargetSpec(family="pe_old"))
    raw = open(os.path.join(pe, "level.dat"), "rb").read()
    lvl = nbt.load(raw[8:], little_endian=True, compressed=False).tag
    p = lvl["Player"]
    assert len(p["Pos"]) == 3 and 0 <= float(p["Pos"][0].py_data) < 256
    assert any("inventory" in w for w in res.warnings)
    back = str(tmp_path / "back")
    convert(pe, back, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    player = nbt.load(open(os.path.join(back, "level.dat"), "rb").read()).tag["Data"]["Player"]
    assert isinstance(player["Pos"][0], nbt.DoubleTag)


# ------------------------------------------------------------------ the command line: no tracebacks


def _cli(argv, capsys):
    from worldbridge.cli import main

    rc = main(["--lang", "en"] + argv)
    cap = capsys.readouterr()
    assert "Traceback" not in cap.out + cap.err
    return rc, cap.out, cap.err


def test_malformed_options_fail_up_front_with_a_message(tmp_path, capsys):
    """A source that does not exist: if the options were only checked after the analysis, the error would be about it."""
    csv = tmp_path / "good.csv"
    csv.write_text("0;0\n1;1\n")
    bad = tmp_path / "bad.csv"
    bad.write_text("not;coordinates\n")
    src, out = str(tmp_path / "nowhere"), str(tmp_path / "out")
    cases = [
        (["--platform", "foo"], "invalid choice"),
        (["--offset", "3"], "expected 2 numbers"),
        (["--offset", "a,b"], "expected 2 numbers"),
        (["--spawn", "1,2"], "expected 3 numbers"),
        (["--spawn", "x,y,z"], "expected 3 numbers"),
        (["--move-to", "1"], "expected 2 numbers"),
        (["--depth", "foo"], "expected auto, cut, keep"),
        (["--chunks", str(tmp_path / "missing.csv")], "file not found"),
        (["--biome", "notabiome=" + str(csv)], "unknown biome"),
        (["--biome", "plains"], "expected BIOME"),
        (["--biome", "plains=" + str(tmp_path / "missing.csv")], "file not found"),
        (["--min-time", "abc"], None),
        (["--trim-min-time", "abc"], "invalid duration"),
        (["--bta-palette", str(tmp_path / "missing.properties")], "file not found"),
        (["--java-mode", "numeric", "--java-limit", "9.9"], "not valid for the numeric format"),
        (["--java-mode", "mcregion", "--java-limit", "b9"], "not valid for the mcregion format"),
        (["--chunks", str(bad)], "no chunk coordinates"),
        (["--chunks", str(tmp_path / "empty.csv")], "no chunk coordinates"),
    ]
    (tmp_path / "empty.csv").write_text("")
    for extra, text in cases:
        if text is None:
            continue
        rc, so, se = _cli(["convert", src, out, "--to", "java"] + extra, capsys)
        assert rc == 1 and text in so + se, (extra, so, se)
        assert not os.path.exists(out)
    for extra, text in [(["--platform", "xbox360", "--size", "320"], "not a world size xbox360 has"),
                        (["--platform", "xbox360", "--size", "7"], "not a world size xbox360 has"),
                        (["--platform", "ps4", "--size", "100"], "not a world size ps4 has"),
                        (["--profile", "foo"], "not a console version"),
                        (["--platform", "win64", "--profile", "tu54"], "not a console version")]:
        rc, so, se = _cli(["convert", src, out, "--to", "lce"] + extra, capsys)
        assert rc == 1 and text in so + se, (extra, so, se)
    # an explicit size / profile the platform has is fine (the error is then the missing source)
    rc, so, se = _cli(["convert", src, out, "--to", "lce", "--platform", "ps4", "--profile", "tu46", "--size", "192"], capsys)
    assert rc == 1 and "not recognised" in so


def test_negative_coordinates_work_without_an_equals_sign(tmp_path, monkeypatch, capsys):
    from worldbridge import cli
    from worldbridge.convert import ConversionResult

    csv = tmp_path / "c.csv"
    csv.write_text("0;0\n")
    seen = {}

    def fake(src, out, t, prog):
        seen["sel"], seen["offset"] = t.selection, t.lce_offset
        return ConversionResult(out)

    monkeypatch.setattr(cli, "convert", fake)
    rc, _so, _se = _cli(["convert", "x", str(tmp_path / "o"), "--to", "lce", "--spawn", "-20,-59,-20", "--chunks", str(csv),
                         "--move-to", "-5,3", "--offset", "-8,-2"], capsys)
    assert rc == 0
    assert seen["sel"].spawn == (-20, -59, -20) and seen["sel"].move_to == (-5, 3) and seen["offset"] == (-8, -2)
    rc, _so, _se = _cli(["convert", "x", str(tmp_path / "o"), "--to", "lce", "--chunks", str(csv), "--move-to", "center",
                         "--y-offset", "-64", "--depth", "-32"], capsys)
    assert rc == 0 and seen["sel"].move_to == (0, 0)


def test_ctrl_c_and_sigterm_say_cancelled(tmp_path, monkeypatch, capsys):
    import signal

    from worldbridge import cli

    def interrupted(*a):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "convert", interrupted)
    rc, so, _se = _cli(["convert", "x", str(tmp_path / "o"), "--to", "java"], capsys)
    assert rc == 130 and "Cancelled" in so
    before = signal.getsignal(signal.SIGTERM)

    def killed(*a):
        os.kill(os.getpid(), signal.SIGTERM)          # `kill` / `timeout` while converting
        raise AssertionError("the signal should have interrupted the run")

    monkeypatch.setattr(cli, "convert", killed)
    rc, so, _se = _cli(["--lang", "it", "convert", "x", str(tmp_path / "o"), "--to", "java"], capsys)
    assert rc == 130 and "Annullat" in so
    assert signal.getsignal(signal.SIGTERM) == before                    # the previous handler is back


def test_output_folder_inside_the_source_is_refused(tmp_path):
    import pytest

    from worldbridge.model import ConversionError

    world = _anvil(tmp_path / "w")
    t = TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12")
    with pytest.raises(ConversionError, match="inside the source world"):
        convert(world, os.path.join(world, "out"), t)
    with pytest.raises(ConversionError, match="inside the source world"):
        convert(os.path.join(world, "level.dat"), os.path.join(world, "region", "x"), t)   # the world is the folder
    with pytest.raises(ConversionError, match="inside the output folder"):
        convert(world, str(tmp_path), t)                                   # the source is inside the output
    assert not os.path.exists(os.path.join(world, "out"))
    assert not [f for f in os.listdir(world) if f.startswith(".worldbridge")]
    afile = tmp_path / "afile"
    afile.write_text("x")
    with pytest.raises(ConversionError, match="is a file"):
        convert(world, str(afile), t)


def test_a_failed_run_removes_the_empty_output_folder_it_created(tmp_path, monkeypatch):
    import pytest

    from worldbridge import convert as convert_mod

    world = _anvil(tmp_path / "w")
    t = TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12")

    def boom(tgt, out, *a, **k):
        os.makedirs(out, exist_ok=True)
        raise KeyboardInterrupt

    monkeypatch.setattr(convert_mod, "_make_writer", boom)
    out = tmp_path / "new"
    with pytest.raises(KeyboardInterrupt):
        convert(world, str(out), t)
    assert not out.exists() and not [f for f in os.listdir(tmp_path) if f.startswith(".worldbridge")]
    pre = tmp_path / "pre"                                   # an empty folder that was already there stays
    pre.mkdir()
    with pytest.raises(KeyboardInterrupt):
        convert(world, str(pre), t)
    assert pre.is_dir()


def test_info_looks_inside_archives(tmp_path, capsys):
    import zipfile

    world = _anvil(tmp_path / "w")
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as z:
        for root, _d, files in os.walk(world):
            for f in files:
                z.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), world))
    rc, so, _se = _cli(["info", str(good)], capsys)
    assert rc == 0 and "contains: Java Edition" in so
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "no world here")
    rc, so, _se = _cli(["info", str(empty)], capsys)
    assert rc == 1 and "does not contain a recognised world" in so and "World archive" not in so
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04" + b"\0" * 30)
    rc, so, _se = _cli(["info", str(broken)], capsys)
    assert rc == 1


def test_progress_reaches_100_percent_and_the_copy_reports_and_cancels(tmp_path):
    import pytest

    from worldbridge.model import ConversionCancelled, copy_tree

    seen = []
    world = _anvil(tmp_path / "w")
    convert(world, str(tmp_path / "out"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"),
            Progress(lambda f, m: seen.append(f)))
    assert seen[-1] == 1.0
    # the straight copy of a world the game upgrades itself (it ended at 95% before)
    modern = str(tmp_path / "modern")
    convert(world, modern, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 1)))
    seen.clear()
    convert(modern, str(tmp_path / "again"), TargetSpec(family="java", java_mode="amulet", version=(1, 21, 4)),
            Progress(lambda f, m: seen.append(f)))
    assert seen[-1] == 1.0
    # copy_tree: progress during the copy, and it stops when cancelled
    src = tmp_path / "many"
    src.mkdir()
    for i in range(40):
        (src / f"f{i}").write_bytes(b"x")
    marks = []
    copy_tree(str(src), str(tmp_path / "c1"), Progress(lambda f, m: marks.append(f)))
    assert len(marks) >= 2 and marks[-1] == 1.0
    p = Progress(lambda f, m: p.cancel() if f > 0.3 else None)
    with pytest.raises(ConversionCancelled):
        copy_tree(str(src), str(tmp_path / "c2"), p)
    assert len(os.listdir(tmp_path / "c2")) < 40

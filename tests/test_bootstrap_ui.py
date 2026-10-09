"""tools/bootstrap_ui.py: the first-start installer.  Pure parts (formatting, speed / ETA, pip's report,
hashes, language) and the downloader against a local HTTP server (resume, retries, bad hash, cancel)."""
import hashlib
import http.server
import importlib.util
import os
import sys
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("bootstrap_ui", os.path.join(HERE, "..", "tools", "bootstrap_ui.py"))
bu = importlib.util.module_from_spec(spec)
sys.modules["bootstrap_ui"] = bu          # dataclasses look the module up
spec.loader.exec_module(bu)


# ---- formatting ---------------------------------------------------------------------------------
def test_fmt_size():
    assert bu.fmt_size(0) == "0 B"
    assert bu.fmt_size(1023) == "1023 B"
    assert bu.fmt_size(1536) == "1.5 KB"
    assert bu.fmt_size(300 * 1024) == "300 KB"
    assert bu.fmt_size(12 * 1024 * 1024 + 600 * 1024) == "12.6 MB"
    assert bu.fmt_size(3 * 1024 ** 3) == "3.0 GB"
    assert bu.fmt_size(1536, "it") == "1,5 KB"            # decimal comma in Italian


def test_fmt_speed_and_eta():
    assert bu.fmt_speed(4.2 * 1024 * 1024) == "4.2 MB/s"
    assert bu.fmt_speed(None) == "– MB/s" and bu.fmt_speed(0) == "– MB/s"
    assert bu.fmt_eta(0) == "0:00"
    assert bu.fmt_eta(59.6) == "1:00"
    assert bu.fmt_eta(83) == "1:23"
    assert bu.fmt_eta(3723) == "1:02:03"
    for bad in (None, -1, float("nan"), 10 ** 9):
        assert bu.fmt_eta(bad) == "–:––"


def test_percent():
    assert bu.percent(0, 0) == 0
    assert bu.percent(50, 200) == 25
    assert bu.percent(199, 200) == 99         # never 100 before it is done
    assert bu.percent(300, 200) == 100
    assert bu.percent(-5, 200) == 0


def test_progress_line():
    line = bu.progress_line("en", 5 * 1024 * 1024, 20 * 1024 * 1024, 2 * 1024 * 1024, 7.5)
    assert line == "25%  ·  5.0 MB of 20.0 MB  ·  2.0 MB/s  ·  ETA 0:08"
    assert "di" in bu.progress_line("it", 1024, 2048, None, None)


def test_speed_meter_moving_window():
    now = [0.0]
    m = bu.SpeedMeter(window=5.0, clock=lambda: now[0])
    assert m.speed() is None and m.eta(100) is None
    m.add(0)
    now[0] = 0.2
    m.add(100)
    assert m.speed() is None                    # too short a span to say anything
    now[0] = 1.0
    m.add(1000)
    assert m.speed() == pytest.approx(1000.0)
    assert m.eta(5000) == pytest.approx(5.0)
    for t in range(2, 20):                      # the connection slows down to 100 B/s: the window follows
        now[0] = float(t)
        m.add(1000 + (t - 1) * 100)
    assert m.speed() == pytest.approx(100.0, rel=0.05)
    assert m.eta(0) == 0.0


# ---- pip's report -------------------------------------------------------------------------------
REPORT = {
    "version": "1",
    "install": [
        {"download_info": {"url": "https://files.pythonhosted.org/packages/aa/bb/numpy-1.26.4-cp311-cp311-"
                                  "manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                           "archive_info": {"hash": "sha256=" + "ab" * 32, "hashes": {"sha256": "AB" * 32}}},
         "metadata": {"name": "numpy", "version": "1.26.4"}},
        {"download_info": {"url": "file:///opt/app/vendor/wheels/amulet_nbt-2.1.8-cp311-cp311-x.whl",
                           "archive_info": {"hash": "sha256=" + "cd" * 32}},
         "metadata": {"name": "amulet-nbt", "version": "2.1.8"}},
        {"download_info": {"url": "https://example.org/a%2Bb-1.0-py3-none-any.whl"}, "metadata": {"name": "a+b"}},
    ],
}


def test_parse_report():
    w = bu.parse_report(REPORT)
    assert [x.name for x in w] == ["numpy", "amulet-nbt", "a+b"]
    assert w[0].sha256 == "ab" * 32 and w[0].local is None
    assert w[0].filename.startswith("numpy-1.26.4-cp311") and w[0].filename.endswith(".whl")
    assert w[1].local == "/opt/app/vendor/wheels/amulet_nbt-2.1.8-cp311-cp311-x.whl"
    assert w[1].sha256 == "cd" * 32                  # taken from the "hash" field when "hashes" is absent
    assert w[2].filename == "a+b-1.0-py3-none-any.whl" and w[2].sha256 == ""
    assert bu.parse_report({}) == []
    with pytest.raises(ValueError):
        bu.parse_report({"install": [{"download_info": {}, "metadata": {}}]})


# ---- hashes -------------------------------------------------------------------------------------
def test_verify_file(tmp_path):
    f = tmp_path / "x.whl"
    f.write_bytes(b"hello wheel")
    good = hashlib.sha256(b"hello wheel").hexdigest()
    assert bu.sha256_file(str(f)) == good
    assert bu.verify_file(str(f), good)
    assert bu.verify_file(str(f), good.upper())
    assert not bu.verify_file(str(f), "0" * 64)
    assert bu.verify_file(str(f), "")                # nothing to compare with


def test_classify_pip_error():
    assert bu.classify_pip_error("ERROR: No matching distribution found for amulet-nbt==2.1.8") == "no_wheel"
    assert bu.classify_pip_error("WARNING: Retrying ... Failed to establish a new connection: [Errno 111]\n"
                                 "ERROR: No matching distribution found for numpy") == "network"
    assert bu.classify_pip_error("ProxyError('Cannot connect to proxy.')") == "network"
    assert bu.classify_pip_error("something else") == "other"


def test_content_range():
    assert bu.parse_content_range("bytes 100-999/1000") == 1000
    assert bu.parse_content_range("bytes */1000") is None
    assert bu.parse_content_range("") is None


# ---- language and colours ------------------------------------------------------------------------
def test_pick_language(tmp_path):
    assert bu.pick_language({"WORLDBRIDGE_LANG": "it"}) == "it"
    assert bu.pick_language({"WORLDBRIDGE_LANG": "IT_it"}) == "it"
    assert bu.pick_language({"LANG": "it_IT.UTF-8"}) == "it"
    assert bu.pick_language({"LANG": "de_DE.UTF-8"}) == "en"
    assert bu.pick_language({}) == "en"
    assert bu.pick_language({"WORLDBRIDGE_LANG": "it", "LC_ALL": "en_US"}) == "it"
    conf = tmp_path / "config" / "WorldBridge"
    conf.mkdir(parents=True)
    (conf / "WorldBridge.conf").write_text("[ui]\nlanguage=it\n")
    assert bu.pick_language({"WORLDBRIDGE_LANG": "en"}, runtime=str(tmp_path)) == "it"   # the saved choice wins


def test_texts_complete():
    assert set(bu.TEXTS["en"]) == set(bu.TEXTS["it"])
    s = bu.Snapshot(stage="download", index=3, count=9, name="numpy 1.26.4")
    assert bu.stage_text("en", s) == "Downloading dependencies (3 of 9): numpy 1.26.4"
    assert bu.stage_text("it", s) == "Download delle dipendenze (3 di 9): numpy 1.26.4"


def test_detect_dark(tmp_path):
    assert bu.detect_dark({"WORLDBRIDGE_BOOTSTRAP_THEME": "dark"}) is True
    assert bu.detect_dark({"WORLDBRIDGE_BOOTSTRAP_THEME": "light"}) is False
    assert bu.detect_dark({"GTK_THEME": "Adwaita:dark"}) is True
    (tmp_path / "kdeglobals").write_text("[Colors:Window]\nBackgroundNormal=35,38,41\n")
    assert bu.detect_dark({"WORLDBRIDGE_USER_CONFIG": str(tmp_path)}) is True
    (tmp_path / "kdeglobals").write_text("[Colors:Window]\nBackgroundNormal=239,240,241\n")
    assert bu.detect_dark({"WORLDBRIDGE_USER_CONFIG": str(tmp_path), "PATH": ""}) is False


# ---- the downloader, against a local server ------------------------------------------------------
DATA = os.urandom(300_000)
SHA = hashlib.sha256(DATA).hexdigest()


class _Handler(http.server.BaseHTTPRequestHandler):
    cut_first = 0          # connections cut after this many bytes (the first `cuts` requests)
    cuts = 0
    ranges = True
    status = 200
    body = DATA
    requests = []

    def log_message(self, *a):
        pass

    def _send(self, head_only):
        cls = type(self)
        cls.requests.append(self.headers.get("Range"))
        if cls.status != 200:
            self.send_response(cls.status)
            self.end_headers()
            return
        start = 0
        rng = self.headers.get("Range")
        if rng and cls.ranges:
            start = int(rng.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(cls.body) - 1}/{len(cls.body)}")
        else:
            self.send_response(200)
        payload = cls.body[start:]
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if head_only:
            return
        if cls.cuts > 0 and cls.cut_first:
            cls.cuts -= 1
            self.wfile.write(payload[: cls.cut_first])
            self.wfile.flush()
            self.close_connection = True
            return                        # short body: an interrupted transfer
        self.wfile.write(payload)

    def do_GET(self):
        self._send(False)

    def do_HEAD(self):
        self._send(True)


@pytest.fixture
def server(monkeypatch):
    for v in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    _Handler.cut_first, _Handler.cuts, _Handler.ranges, _Handler.status = 0, 0, True, 200
    _Handler.body, _Handler.requests = DATA, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _wheel(server, sha=SHA):
    return bu.Wheel(name="demo", version="1.0", url=server + "/demo-1.0-py3-none-any.whl", sha256=sha)


def _get(server, tmp_path, w=None, cancel=None, retries=3):
    prog = bu.Progress()
    out = bu.download_wheel(bu.make_opener(), w or _wheel(server), 0, str(tmp_path), prog,
                            cancel or threading.Event(), retries=retries, sleep=lambda s: None)
    return out, prog


def test_download_ok_and_progress(server, tmp_path):
    out, prog = _get(server, tmp_path)
    assert open(out, "rb").read() == DATA
    assert not os.path.exists(out + ".part")
    s = prog.snapshot()
    assert s.done == len(DATA) and s.total == len(DATA)
    assert bu.head_size(bu.make_opener(), _wheel(server).url) == len(DATA)


def test_download_resumes_after_cut(server, tmp_path):
    _Handler.cut_first, _Handler.cuts = 100_000, 2           # two interrupted transfers, then a good one
    out, prog = _get(server, tmp_path, retries=1)             # progress made: they do not use up the attempts
    assert open(out, "rb").read() == DATA
    ranges = [r for r in _Handler.requests if r]
    assert ranges == ["bytes=100000-", "bytes=200000-"]
    assert prog.snapshot().done == len(DATA)


def test_download_resumes_a_part_file_from_an_earlier_run(server, tmp_path):
    (tmp_path / "demo-1.0-py3-none-any.whl.part").write_bytes(DATA[:123_456])
    out, _ = _get(server, tmp_path)
    assert open(out, "rb").read() == DATA
    assert _Handler.requests == ["bytes=123456-"]


def test_download_server_without_ranges_starts_over(server, tmp_path):
    _Handler.ranges = False
    (tmp_path / "demo-1.0-py3-none-any.whl.part").write_bytes(DATA[:1000])
    out, _ = _get(server, tmp_path)
    assert open(out, "rb").read() == DATA


def test_download_bad_hash_is_never_kept(server, tmp_path):
    with pytest.raises(bu.JobError):
        _get(server, tmp_path, _wheel(server, sha="0" * 64))
    assert os.listdir(tmp_path) == []


def test_download_keeps_a_good_file_and_replaces_a_bad_one(server, tmp_path):
    good = tmp_path / "demo-1.0-py3-none-any.whl"
    good.write_bytes(DATA)
    _get(server, tmp_path)
    assert _Handler.requests == []                            # already there and checked: not downloaded again
    good.write_bytes(b"corrupt")
    out, _ = _get(server, tmp_path)
    assert open(out, "rb").read() == DATA


def test_download_gives_up_after_three_fruitless_attempts(server, tmp_path):
    _Handler.status = 503
    with pytest.raises(bu.JobError):
        _get(server, tmp_path)
    assert len(_Handler.requests) == 3
    _Handler.requests.clear()
    _Handler.status = 404                                     # not worth retrying
    with pytest.raises(bu.JobError):
        _get(server, tmp_path)
    assert len(_Handler.requests) == 1


def test_download_cancel_keeps_the_part_and_nothing_final(server, tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(bu.Cancelled):
        _get(server, tmp_path, cancel=cancel)
    assert not any(n.endswith(".whl") for n in os.listdir(tmp_path))


def test_download_cancel_midway(server, tmp_path):
    prog = bu.Progress()
    cancel = threading.Event()
    orig = prog.set_bytes

    def spy(i, n, *rest):
        orig(i, n, *rest)
        if n > 50_000:
            cancel.set()
    prog.set_bytes = spy
    with pytest.raises(bu.Cancelled):
        bu.download_wheel(bu.make_opener(), _wheel(server), 0, str(tmp_path), prog, cancel, sleep=lambda s: None)
    names = os.listdir(tmp_path)
    assert names == ["demo-1.0-py3-none-any.whl.part"]       # resumable, and not mistaken for a finished wheel


def test_progress_totals_over_several_files():
    p = bu.Progress()
    p.set_size(0, 100)
    p.set_size(1, 300)
    p.set_bytes(0, 100)
    p.set_bytes(1, 50)
    s = p.snapshot()
    assert (s.done, s.total) == (150, 400)
    p.set_bytes(1, 0)                                          # a corrupt file dropped: progress goes back
    assert p.snapshot().done == 100
    assert bu.percent(s.done, s.total) == 37


def test_speed_ignores_files_already_on_disk():
    now = [0.0]
    p = bu.Progress(clock=lambda: now[0])
    p.set_size(0, 10_000_000)
    p.set_bytes(0, 5_000_000)                    # a file kept from an earlier run: not "downloaded" now
    for k in range(1, 6):
        now[0] = float(k)
        p.set_bytes(0, 5_000_000 + k * 100_000, 100_000)
    assert p.snapshot().speed == pytest.approx(100_000.0, rel=0.05)


def test_run_guarded_reports_cancel_and_failure(tmp_path, monkeypatch):
    ctx = bu.Context(app=str(tmp_path), runtime=str(tmp_path))
    for exc, rc in ((bu.Cancelled(), bu.EXIT_CANCEL), (bu.JobError("boom", "details"), bu.EXIT_FAIL),
                    (RuntimeError("bug"), bu.EXIT_FAIL)):
        def job(*a, _e=exc):
            raise _e
        monkeypatch.setattr(bu, "run_job", job)
        p = bu.Progress()
        assert bu.run_guarded(ctx, p, threading.Event()) == rc
        s = p.snapshot()
        assert s.finished and s.rc == rc and s.error
    monkeypatch.setattr(bu, "run_job", lambda *a: None)
    p = bu.Progress()
    assert bu.run_guarded(ctx, p, threading.Event()) == bu.EXIT_OK and p.snapshot().error == ""


def test_run_sh_is_valid_bash():
    import shutil
    import subprocess
    if not shutil.which("bash"):
        pytest.skip("no bash")
    assert subprocess.run(["bash", "-n", os.path.join(HERE, "..", "run.sh")]).returncode == 0

#!/usr/bin/env python3
"""First-start installer of WorldBridge's Python packages, with a progress window.

Run by ``run.sh`` with the portable Python, instead of a silent ``pip install``:

1. asks pip which exact wheels ``requirements.lock`` needs for this Python / platform, without
   installing anything (``pip install --dry-run --report``): that gives each wheel's URL and SHA-256;
2. downloads them itself with urllib (HTTPS_PROXY / SSL_CERT_FILE / REQUESTS_CA_BUNDLE are honoured,
   interrupted transfers are resumed, three fruitless attempts per file), checks every SHA-256 and so
   knows the real number of bytes: percentage, speed and remaining time are measured, not guessed.
   The wheels in ``vendor/wheels`` are local and are not downloaded;
3. installs them offline (``pip install --no-index --find-links <downloaded files>``), then runs the
   steps ``run.sh`` always had: tools/build_wheels.py when a package has no prebuilt wheel, then
   tools/prune_qt.py and tools/gui_selftest.py.

It shows a Tk window (tkinter ships with python-build-standalone) when there is a display; without
Tk, without a display or with ``--ui text`` it prints plain progress lines.  The log of the whole run
is ``<runtime>/logs/bootstrap.log``.

Exit status: 0 done, 1 failed, 3 cancelled by the user (nothing is marked as installed).
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Tuple

EXIT_OK, EXIT_FAIL, EXIT_CANCEL = 0, 1, 3
CHUNK = 64 * 1024
RETRIES = 3

# --------------------------------------------------------------------------------------------------
# texts (English / Italian, chosen like worldbridge/i18n.py does)
# --------------------------------------------------------------------------------------------------
TEXTS: Dict[str, Dict[str, str]] = {
    "en": {
        "title": "WorldBridge – first start",
        "intro": "WorldBridge is setting itself up. This happens only once.",
        "resolve": "Preparing the list of packages…",
        "download": "Downloading dependencies ({n} of {total}): {name}",
        "sizes": "{done} of {total}",
        "eta": "ETA {eta}",
        "install": "Installing…",
        "install_detail": "Installing the packages from the downloaded files.",
        "build": "Compiling the packages that have no prebuilt version (this can take several minutes)…",
        "prune": "Removing the parts of Qt that are not used…",
        "check": "Checking that the interface starts…",
        "restore": "Restoring the complete PySide6…",
        "pip": "Updating pip…",
        "done": "Ready.",
        "cancel": "Cancel",
        "cancelling": "Cancelling…",
        "cancelled": "Installation cancelled. Run WorldBridge again to continue where it stopped.",
        "failed": "The installation did not complete",
        "copy": "Copy log",
        "copied": "Log copied to the clipboard.",
        "close": "Close",
        "log_at": "Log: {path}",
        "err_network": "The package server could not be reached. Check the internet connection and the "
                       "proxy settings (HTTPS_PROXY, SSL_CERT_FILE).",
        "err_download": "Download failed for {name}: {error}",
        "err_hash": "{name}: the downloaded file does not match its SHA-256 checksum.",
        "err_resolve": "pip could not find a set of prebuilt packages for this system.",
        "err_install": "pip could not install the packages.",
        "err_build": "Compiling the missing packages failed.",
        "err_post": "The interface does not start after the installation.",
        "err_nohash": "no checksum available",
    },
    "it": {
        "title": "WorldBridge – primo avvio",
        "intro": "WorldBridge si sta preparando. Succede una sola volta.",
        "resolve": "Preparazione dell'elenco dei pacchetti…",
        "download": "Download delle dipendenze ({n} di {total}): {name}",
        "sizes": "{done} di {total}",
        "eta": "Mancano {eta}",
        "install": "Installazione…",
        "install_detail": "Installazione dei pacchetti dai file scaricati.",
        "build": "Compilazione dei pacchetti senza versione precompilata (può richiedere diversi minuti)…",
        "prune": "Rimozione delle parti di Qt non usate…",
        "check": "Verifica che l'interfaccia si avvii…",
        "restore": "Ripristino del PySide6 completo…",
        "pip": "Aggiornamento di pip…",
        "done": "Pronto.",
        "cancel": "Annulla",
        "cancelling": "Annullamento…",
        "cancelled": "Installazione annullata. Riavvia WorldBridge per proseguire da dove si era fermata.",
        "failed": "L'installazione non è stata completata",
        "copy": "Copia il log",
        "copied": "Log copiato negli appunti.",
        "close": "Chiudi",
        "log_at": "Log: {path}",
        "err_network": "Il server dei pacchetti non è raggiungibile. Controlla la connessione a internet e le "
                       "impostazioni del proxy (HTTPS_PROXY, SSL_CERT_FILE).",
        "err_download": "Download non riuscito per {name}: {error}",
        "err_hash": "{name}: il file scaricato non corrisponde al checksum SHA-256.",
        "err_resolve": "pip non ha trovato pacchetti precompilati adatti a questo sistema.",
        "err_install": "pip non è riuscito a installare i pacchetti.",
        "err_build": "La compilazione dei pacchetti mancanti non è riuscita.",
        "err_post": "L'interfaccia non si avvia dopo l'installazione.",
        "err_nohash": "checksum non disponibile",
    },
}


def t(lang: str, key: str, **values) -> str:
    text = TEXTS.get(lang, TEXTS["en"]).get(key) or TEXTS["en"][key]
    return text.format(**values) if values else text


def pick_language(env=None, runtime: str = "") -> str:
    """The language the app would use: the interface's saved choice, ``WORLDBRIDGE_LANG``, the locale."""
    env = os.environ if env is None else env
    if runtime:
        conf = os.path.join(runtime, "config", "WorldBridge", "WorldBridge.conf")
        try:
            cp = configparser.RawConfigParser(strict=False)
            cp.read(conf, encoding="utf-8")
            saved = cp.get("ui", "language", fallback="").strip().lower()[:2]
            if saved in TEXTS:
                return saved
        except (configparser.Error, OSError, UnicodeError):
            pass
    forced = env.get("WORLDBRIDGE_LANG", "").strip().lower()[:2]
    if forced in TEXTS:
        return forced
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = env.get(var, "")
        if value:
            return "it" if value.lower().startswith("it") else "en"
    return "en"


# --------------------------------------------------------------------------------------------------
# formatting and measuring (pure)
# --------------------------------------------------------------------------------------------------
def _num(value: float, decimals: int, lang: str) -> str:
    s = f"{value:.{decimals}f}"
    return s.replace(".", ",") if lang == "it" else s


def fmt_size(n: float, lang: str = "en") -> str:
    """12345678 -> '11.8 MB' (1 MB = 1024 * 1024 bytes)."""
    n = max(0.0, float(n))
    if n < 1024:
        return f"{int(n)} B"
    for unit, div in (("KB", 1024.0), ("MB", 1024.0 ** 2), ("GB", 1024.0 ** 3)):
        if n < div * 1024 or unit == "GB":
            v = n / div
            return f"{_num(v, 0 if v >= 100 and unit == 'KB' else 1, lang)} {unit}"
    return f"{int(n)} B"  # pragma: no cover


def fmt_speed(bps: Optional[float], lang: str = "en") -> str:
    if bps is None or bps <= 0:
        return "– MB/s"
    return fmt_size(bps, lang) + "/s"


def fmt_eta(seconds: Optional[float]) -> str:
    """Remaining time as m:ss or h:mm:ss; an unknown time is shown as an en dash."""
    if seconds is None or seconds != seconds or seconds < 0 or seconds > 99 * 3600:
        return "–:––"
    s = int(seconds + 0.5)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def percent(done: float, total: float) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, int(done * 100 // total)))


class SpeedMeter:
    """Speed over the last few seconds (a moving window, so that it follows the connection)."""

    def __init__(self, window: float = 5.0, clock: Callable[[], float] = time.monotonic):
        self.window = window
        self.clock = clock
        self.samples: Deque[Tuple[float, float]] = deque()

    def add(self, total_bytes: float) -> None:
        now = self.clock()
        self.samples.append((now, float(total_bytes)))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.window:
            self.samples.popleft()

    def speed(self) -> Optional[float]:
        if len(self.samples) < 2:
            return None
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        if t1 - t0 < 0.5:
            return None
        return max(0.0, (b1 - b0) / (t1 - t0))

    def eta(self, remaining: float) -> Optional[float]:
        sp = self.speed()
        if not sp:
            return None
        return max(0.0, remaining) / sp


def progress_line(lang: str, done: float, total: float, speed: Optional[float], eta: Optional[float]) -> str:
    """'45%  ·  60.2 MB of 130.0 MB  ·  4.1 MB/s  ·  ETA 0:17'."""
    return "  ·  ".join((f"{percent(done, total)}%",
                            t(lang, "sizes", done=fmt_size(done, lang), total=fmt_size(total, lang)),
                            fmt_speed(speed, lang), t(lang, "eta", eta=fmt_eta(eta))))


# --------------------------------------------------------------------------------------------------
# pip's report, hashes (pure)
# --------------------------------------------------------------------------------------------------
@dataclass
class Wheel:
    name: str
    version: str
    url: str
    sha256: str = ""
    size: Optional[int] = None
    local: Optional[str] = None       # path of a wheel that is already on this machine

    @property
    def filename(self) -> str:
        return urllib.parse.unquote(urllib.parse.urlsplit(self.url).path.rsplit("/", 1)[-1])


def parse_report(data: dict) -> List[Wheel]:
    """The wheels in a ``pip install --dry-run --report`` file, in install order."""
    out: List[Wheel] = []
    for item in data.get("install", []):
        info = item.get("download_info") or {}
        url = info.get("url") or ""
        meta = item.get("metadata") or {}
        arch = info.get("archive_info") or {}
        sha = (arch.get("hashes") or {}).get("sha256", "")
        if not sha and str(arch.get("hash", "")).startswith("sha256="):
            sha = arch["hash"].split("=", 1)[1]
        if not url:
            raise ValueError("a package in pip's report has no URL")
        w = Wheel(name=str(meta.get("name", "?")), version=str(meta.get("version", "")), url=url, sha256=sha.lower())
        if url.startswith("file:"):
            w.local = urllib.request.url2pathname(urllib.parse.urlsplit(url).path)
        out.append(w)
    return out


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_file(path: str, expected: str) -> bool:
    """True if ``path`` has the SHA-256 ``expected`` (an empty ``expected`` cannot be checked: True)."""
    if not expected:
        return True
    return sha256_file(path) == expected.lower()


def classify_pip_error(text: str) -> str:
    """'network' | 'no_wheel' | 'other' from the output of a failed pip run."""
    low = text.lower()
    for marker in ("failed to establish", "max retries exceeded", "proxyerror", "connection refused",
                   "temporary failure in name resolution", "network is unreachable", "connectionerror",
                   "name or service not known", "ssl: certificate", "certificate verify failed",
                   "read timed out", "connect timeout", "connection timed out", "tunnel connection failed"):
        if marker in low:
            return "network"
    if "no matching distribution" in low or "could not find a version" in low:
        return "no_wheel"
    return "other"


def parse_content_range(value: str) -> Optional[int]:
    """Total size from 'bytes 100-999/1000'."""
    m = re.match(r"\s*bytes\s+\d+-\d+/(\d+)\s*$", value or "")
    return int(m.group(1)) if m else None


def detect_dark(env=None) -> bool:
    """Whether the desktop uses a dark colour scheme (best effort; light when unknown)."""
    env = os.environ if env is None else env
    forced = env.get("WORLDBRIDGE_BOOTSTRAP_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    if "dark" in env.get("GTK_THEME", "").lower():
        return True
    conf_home = env.get("WORLDBRIDGE_USER_CONFIG") or env.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    try:
        cp = configparser.RawConfigParser(strict=False)
        cp.optionxform = str
        cp.read(os.path.join(conf_home, "kdeglobals"), encoding="utf-8")
        rgb = [int(x) for x in cp.get("Colors:Window", "BackgroundNormal").split(",")[:3]]
        return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 128
    except (configparser.Error, OSError, ValueError, UnicodeError):
        pass
    try:
        genv = dict(env)
        genv["XDG_CONFIG_HOME"] = conf_home
        if env.get("WORLDBRIDGE_USER_DATA"):
            genv["XDG_DATA_HOME"] = env["WORLDBRIDGE_USER_DATA"]
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], env=genv,
                           capture_output=True, text=True, timeout=2)
        if "dark" in r.stdout.lower():
            return True
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"], env=genv,
                           capture_output=True, text=True, timeout=2)
        return "dark" in r.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


# --------------------------------------------------------------------------------------------------
# shared state between the worker thread and the user interface
# --------------------------------------------------------------------------------------------------
class Cancelled(Exception):
    pass


class JobError(Exception):
    """A failure with a message for the user (``detail`` = the tail of pip's output)."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class Snapshot:
    stage: str = "resolve"            # resolve | download | install | build | prune | check | restore | pip
    index: int = 0
    count: int = 0
    name: str = ""
    done: float = 0.0
    total: float = 0.0
    speed: Optional[float] = None
    eta: Optional[float] = None
    cancellable: bool = True
    version: int = 0
    finished: bool = False
    rc: int = EXIT_OK
    error: str = ""
    detail: str = ""


class Progress:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._s = Snapshot()
        self.meter = SpeedMeter(clock=clock)
        self._files: Dict[int, int] = {}
        self._sizes: Dict[int, int] = {}
        self._fresh = 0                   # bytes received in this run (the speed ignores files already on disk)

    def snapshot(self) -> Snapshot:
        with self._lock:
            s = Snapshot(**self._s.__dict__)
        return s

    def _bump(self) -> None:
        self._s.version += 1

    def stage(self, stage: str, cancellable: bool = True) -> None:
        with self._lock:
            self._s.stage, self._s.cancellable = stage, cancellable
            self._s.speed = self._s.eta = None
            self._bump()

    def plan(self, count: int) -> None:
        with self._lock:
            self._s.count = count
            self._bump()

    def start_file(self, index: int, name: str) -> None:
        with self._lock:
            self._s.index, self._s.name = index, name
            self._bump()

    def set_size(self, index: int, size: int) -> None:
        with self._lock:
            self._sizes[index] = size
            self._s.total = float(sum(self._sizes.values()))
            self._bump()

    def set_bytes(self, index: int, nbytes: int, fresh: int = 0) -> None:
        """Absolute bytes of file ``index`` that are on disk (also lowers it when a bad file is dropped);
        ``fresh``: how many of them were just received (only those count for the speed)."""
        with self._lock:
            self._files[index] = nbytes
            done = float(sum(self._files.values()))
            self._s.done = done
            self._fresh += fresh
            self.meter.add(self._fresh)
            self._s.speed = self.meter.speed()
            self._s.eta = self.meter.eta(self._s.total - done)
            self._bump()

    def finish(self, rc: int, error: str = "", detail: str = "") -> None:
        with self._lock:
            self._s.finished, self._s.rc, self._s.error, self._s.detail = True, rc, error, detail
            self._bump()


# --------------------------------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------------------------------
def make_ssl_context(env=None) -> ssl.SSLContext:
    """The system's CA certificates plus the bundles named by SSL_CERT_FILE / REQUESTS_CA_BUNDLE /
    PIP_CERT / CURL_CA_BUNDLE (a proxy that re-signs HTTPS needs its own CA) and pip's own bundle."""
    env = os.environ if env is None else env
    ctx = ssl.create_default_context()
    files = [env.get(v, "") for v in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "PIP_CERT", "CURL_CA_BUNDLE")]
    try:
        from pip._vendor import certifi  # type: ignore
        files.append(certifi.where())
    except Exception:
        pass
    seen = set()
    for f in files:
        if f and f not in seen and os.path.isfile(f):
            seen.add(f)
            try:
                ctx.load_verify_locations(cafile=f)
            except (ssl.SSLError, OSError):
                pass
    return ctx


def make_opener(ctx: Optional[ssl.SSLContext] = None) -> urllib.request.OpenerDirector:
    """urllib's opener: proxies from the environment (HTTPS_PROXY, NO_PROXY…) and the CA bundles above."""
    return urllib.request.build_opener(urllib.request.ProxyHandler(), urllib.request.HTTPSHandler(context=ctx or make_ssl_context()))


USER_AGENT = "WorldBridge-bootstrap/1"


def head_size(opener, url: str, timeout: float = 20.0) -> Optional[int]:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=timeout) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n and n.isdigit() else None
    except (OSError, http.client.HTTPException, ValueError):
        return None


def download_wheel(opener, w: Wheel, index: int, dest_dir: str, progress: Progress, cancel: threading.Event,
                   retries: int = RETRIES, sleep: Callable[[float], None] = time.sleep) -> str:
    """Downloads ``w`` into ``dest_dir`` (resuming a ``.part`` file) and returns the final path.

    The file only gets its final name once its SHA-256 matches.  ``retries`` consecutive attempts
    without a single new byte end in a JobError; an interrupted transfer that made progress does not
    use up the attempts."""
    final = os.path.join(dest_dir, w.filename)
    part = final + ".part"
    if os.path.isfile(final):
        if verify_file(final, w.sha256):
            size = os.path.getsize(final)
            progress.set_size(index, size)
            progress.set_bytes(index, size)
            return final
        os.remove(final)
    fruitless = 0
    last_error = ""
    while fruitless < retries:
        if cancel.is_set():
            raise Cancelled()
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        progress.set_bytes(index, have)
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if have:
            headers["Range"] = f"bytes={have}-"
        gained = False
        try:
            with opener.open(urllib.request.Request(w.url, headers=headers), timeout=30) as r:
                status = getattr(r, "status", 200)
                if have and status != 206:       # the server ignored the range: start again
                    have = 0
                    progress.set_bytes(index, 0)
                if status == 206:
                    total = parse_content_range(r.headers.get("Content-Range", ""))
                else:
                    n = r.headers.get("Content-Length")
                    total = int(n) if n and n.isdigit() else None
                if total:
                    progress.set_size(index, total)
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        if cancel.is_set():
                            raise Cancelled()
                        block = r.read(CHUNK)
                        if not block:
                            break
                        f.write(block)
                        have += len(block)
                        gained = True
                        progress.set_bytes(index, have, len(block))
                if total and have != total:
                    raise http.client.IncompleteRead(b"", total - have)
        except Cancelled:
            raise
        except urllib.error.HTTPError as ex:
            last_error = f"HTTP {ex.code} {ex.reason}"
            if ex.code == 416:                     # the range is beyond the file: the .part is wrong
                _remove(part)
            elif 400 <= ex.code < 500 and ex.code not in (408, 429):
                raise JobError(t_lang("err_download", name=w.filename, error=last_error))
        except (OSError, http.client.HTTPException, ValueError) as ex:
            last_error = str(getattr(ex, "reason", None) or ex) or ex.__class__.__name__
        else:
            if verify_file(part, w.sha256):
                os.replace(part, final)
                return final
            _remove(part)                          # corrupt: never keep it, start over
            progress.set_bytes(index, 0)
            last_error = "sha256"
            fruitless += 1
            continue
        fruitless = 0 if gained else fruitless + 1
        if fruitless < retries:
            sleep(min(1.0 * 2 ** fruitless, 8.0))
    if last_error == "sha256":
        raise JobError(t_lang("err_hash", name=w.filename))
    raise JobError(t_lang("err_download", name=w.filename, error=last_error))


# the language of the messages raised from worker code (set once in main())
_LANG = "en"


def t_lang(key: str, **values) -> str:
    return t(_LANG, key, **values)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------------------------------
# the job: resolve, download, install, finish
# --------------------------------------------------------------------------------------------------
@dataclass
class Context:
    app: str
    runtime: str
    py: str = field(default_factory=lambda: sys.executable)
    log_path: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    log: Optional[object] = None

    @property
    def lock(self) -> str:
        return os.path.join(self.app, "requirements.lock")

    @property
    def vendor(self) -> str:
        return os.path.join(self.app, "vendor", "wheels")

    @property
    def built(self) -> str:
        return os.path.join(self.runtime, "wheels")

    @property
    def cache(self) -> str:
        return os.path.join(self.runtime, "download", "wheels")


def make_env(app: str, runtime: str) -> Dict[str, str]:
    env = dict(os.environ)
    for k, v in (("PYTHONNOUSERSITE", "1"), ("PIP_NO_CACHE_DIR", "1"), ("PIP_DISABLE_PIP_VERSION_CHECK", "1"),
                 ("PIP_NO_INPUT", "1"), ("WORLDBRIDGE_HOME", runtime), ("PIP_PROGRESS_BAR", "off")):
        env.setdefault(k, v)
    if "PIP_CONFIG_FILE" not in env:
        env["PIP_CONFIG_FILE"] = os.devnull
    env["PYTHONPATH"] = app + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def log(ctx: Context, text: str) -> None:
    if ctx.log:
        ctx.log.write(text.rstrip("\n") + "\n")
        ctx.log.flush()


def run_cmd(ctx: Context, cmd: List[str], cancel: Optional[threading.Event] = None, extra_env=None,
            cwd: Optional[str] = None) -> Tuple[int, str]:
    """Runs a command, appends its output to the log and returns (exit code, last lines of output).
    ``cancel`` set -> the process is terminated and Cancelled raised."""
    log(ctx, "$ " + " ".join(cmd))
    env = dict(ctx.env)
    env.update(extra_env or {})
    tail: Deque[str] = deque(maxlen=60)
    proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")

    def pump():
        for line in proc.stdout:  # type: ignore[union-attr]
            tail.append(line.rstrip("\n"))
            log(ctx, line)

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            th.join(2)
            raise Cancelled()
        time.sleep(0.1)
    th.join(5)
    log(ctx, f"-> exit {proc.returncode}")
    return proc.returncode, "\n".join(tail)


def pip_cmd(ctx: Context, *args: str) -> List[str]:
    return [ctx.py, "-m", "pip", *args]


def pip_version(ctx: Context) -> Tuple[int, ...]:
    try:
        rc, out = run_cmd(ctx, pip_cmd(ctx, "--version"))
        m = re.search(r"pip (\d+)\.(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    except OSError:
        return (0, 0)


def resolve(ctx: Context, cancel: threading.Event) -> Tuple[List[Wheel], str]:
    """The wheels requirements.lock needs here (nothing is installed).  Returns (wheels, '') or ([], pip output)."""
    report = os.path.join(ctx.runtime, "download", "report.json")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    _remove(report)
    cmd = pip_cmd(ctx, "install", "--no-user", "--quiet", "--root-user-action=ignore", "--dry-run",
                  "--ignore-installed", "--report", report, "--only-binary=:all:",
                  "--find-links", ctx.vendor, "--find-links", ctx.built, "-r", ctx.lock)
    rc, out = run_cmd(ctx, cmd, cancel)
    if rc != 0 or not os.path.isfile(report):
        return [], out
    with open(report, encoding="utf-8") as f:
        return parse_report(json.load(f)), ""


def build_missing(ctx: Context, progress: Progress, cancel: threading.Event) -> None:
    progress.stage("build")
    work = os.path.join(ctx.runtime, "build")
    try:
        rc, out = run_cmd(ctx, [ctx.py, os.path.join(ctx.app, "tools", "build_wheels.py"), "--out", ctx.built,
                                "--work", work], cancel)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if rc != 0:
        raise JobError(t_lang("err_build"), out)


def fetch_all(ctx: Context, wheels: List[Wheel], progress: Progress, cancel: threading.Event, opener=None) -> None:
    remote = [w for w in wheels if not w.local]
    progress.plan(len(remote))
    if not remote:
        return
    progress.start_file(1, f"{remote[0].name} {remote[0].version}".strip())
    progress.stage("download")
    os.makedirs(ctx.cache, exist_ok=True)
    opener = opener or make_opener()
    # the sizes first, so that the percentage is of the whole download from the start
    sizes: Dict[int, Optional[int]] = {}
    lock = threading.Lock()

    def head(i: int, w: Wheel) -> None:
        n = head_size(opener, w.url)
        with lock:
            sizes[i] = n

    threads = []
    for i, w in enumerate(remote):
        done_file = os.path.join(ctx.cache, w.filename)
        if os.path.isfile(done_file):
            sizes[i] = os.path.getsize(done_file)
            continue
        th = threading.Thread(target=head, args=(i, w), daemon=True)
        th.start()
        threads.append(th)
        while sum(1 for x in threads if x.is_alive()) >= 6:
            time.sleep(0.02)
    for th in threads:
        while th.is_alive():
            if cancel.is_set():
                raise Cancelled()
            th.join(0.1)
    for i, n in sizes.items():
        if n:
            progress.set_size(i, n)
    for i, w in enumerate(remote):
        if not w.sha256:
            log(ctx, f"warning: {w.filename}: {t_lang('err_nohash')}")
        progress.start_file(i + 1, f"{w.name} {w.version}".strip())
        download_wheel(opener, w, i, ctx.cache, progress, cancel)


def pip_install(ctx: Context, progress: Progress, extra: Tuple[str, ...] = ()) -> Tuple[int, str]:
    return run_cmd(ctx, pip_cmd(ctx, "install", "--no-user", "--quiet", "--root-user-action=ignore", "--no-index",
                                "--only-binary=:all:", "--find-links", ctx.cache, "--find-links", ctx.vendor,
                                "--find-links", ctx.built, *extra))


def pyside_requirement(ctx: Context) -> str:
    with open(ctx.lock, encoding="utf-8") as f:
        for line in f:
            if line.strip().lower().startswith("pyside6-essentials"):
                return line.strip()
    return "PySide6-Essentials"


def reinstall_pyside(ctx: Context, progress: Progress) -> None:
    rc, out = pip_install(ctx, progress, ("--force-reinstall", "--no-deps", pyside_requirement(ctx)))
    if rc != 0:
        raise JobError(t_lang("err_install"), out)


def post_install(ctx: Context, progress: Progress, cancel: threading.Event) -> None:
    """What run.sh always did after the install: prune Qt, check the GUI builds, undo the pruning if not."""
    progress.stage("prune", cancellable=False)
    tools = os.path.join(ctx.app, "tools")
    rc, out = run_cmd(ctx, [ctx.py, os.path.join(tools, "prune_qt.py"), "--missing"])
    if rc == 0 and out.strip():
        reinstall_pyside(ctx, progress)
    run_cmd(ctx, [ctx.py, os.path.join(tools, "prune_qt.py")])
    progress.stage("check", cancellable=False)
    rc, out = run_cmd(ctx, [ctx.py, os.path.join(tools, "gui_selftest.py")], extra_env={"QT_QPA_PLATFORM": "offscreen"})
    if rc != 0:
        progress.stage("restore", cancellable=False)
        reinstall_pyside(ctx, progress)


def run_job(ctx: Context, progress: Progress, cancel: threading.Event, opener=None) -> None:
    """The whole installation; raises Cancelled or JobError."""
    os.makedirs(ctx.built, exist_ok=True)
    progress.stage("resolve")
    if pip_version(ctx) < (22, 3):
        progress.stage("pip")
        rc, out = run_cmd(ctx, pip_cmd(ctx, "install", "--no-user", "--quiet", "--root-user-action=ignore", "--upgrade", "pip"), cancel)
        if rc != 0:
            raise JobError(t_lang("err_network") if classify_pip_error(out) == "network" else t_lang("err_resolve"), out)
        progress.stage("resolve")
    wheels, out = resolve(ctx, cancel)
    built = False
    if not wheels:
        kind = classify_pip_error(out)
        if kind != "no_wheel":
            raise JobError(t_lang("err_network") if kind == "network" else t_lang("err_resolve"), out)
        build_missing(ctx, progress, cancel)             # a package without a prebuilt wheel: compile it here
        built = True
        progress.stage("resolve")
        wheels, out = resolve(ctx, cancel)
        if not wheels:
            raise JobError(t_lang("err_network") if classify_pip_error(out) == "network" else t_lang("err_resolve"), out)
    fetch_all(ctx, wheels, progress, cancel, opener)
    if cancel.is_set():
        raise Cancelled()
    progress.stage("install", cancellable=False)
    rc, out = pip_install(ctx, progress, ("-r", ctx.lock))
    if rc != 0 and not built:
        progress.stage("build", cancellable=False)
        build_missing(ctx, progress, threading.Event())
        progress.stage("install", cancellable=False)
        rc, out = pip_install(ctx, progress, ("-r", ctx.lock))
    if rc != 0:
        raise JobError(t_lang("err_install"), out)
    post_install(ctx, progress, cancel)
    shutil.rmtree(ctx.cache, ignore_errors=True)         # the wheels are installed: keep the runtime lean
    _remove(os.path.join(ctx.runtime, "download", "report.json"))


def run_guarded(ctx: Context, progress: Progress, cancel: threading.Event, opener=None) -> int:
    """run_job() turned into an exit code; the progress object gets the verdict."""
    try:
        run_job(ctx, progress, cancel, opener)
        rc, msg, detail = EXIT_OK, "", ""
    except Cancelled:
        rc, msg, detail = EXIT_CANCEL, t_lang("cancelled"), ""
    except JobError as ex:
        rc, msg, detail = EXIT_FAIL, ex.message, ex.detail
    except Exception as ex:  # a bug: still tell the user and keep the traceback in the log
        log(ctx, traceback.format_exc())
        rc, msg, detail = EXIT_FAIL, f"{ex.__class__.__name__}: {ex}", ""
    if rc != EXIT_OK:
        log(ctx, f"result: {msg}\n{detail}")
    progress.finish(rc, msg, detail)
    return rc


def stage_text(lang: str, s: Snapshot) -> str:
    if s.stage == "download":
        return t(lang, "download", n=max(1, s.index), total=s.count, name=s.name)
    return t(lang, {"install": "install", "build": "build", "prune": "prune", "check": "check",
                    "restore": "restore", "pip": "pip"}.get(s.stage, "resolve"))


# --------------------------------------------------------------------------------------------------
# user interfaces
# --------------------------------------------------------------------------------------------------
class TextUI:
    """Plain lines on stderr (a terminal, a log, or no display)."""

    def __init__(self, lang: str, stream=None):
        self.lang = lang
        self.out = stream or sys.stderr
        self.tty = hasattr(self.out, "isatty") and self.out.isatty()

    def _p(self, text: str, end: str = "\n") -> None:
        try:
            self.out.write(text + end)
            self.out.flush()
        except (OSError, ValueError):
            pass

    def run(self, work: Callable[[threading.Event], int], progress: Progress) -> int:
        cancel = threading.Event()
        result: List[int] = []
        th = threading.Thread(target=lambda: result.append(work(cancel)), daemon=True)
        th.start()
        last_key = None
        last_print = 0.0
        inline = False
        try:
            while th.is_alive():
                s = progress.snapshot()
                text = stage_text(self.lang, s)
                now = time.monotonic()
                if s.stage == "download" and s.total > 0:
                    line = f"{text}  {progress_line(self.lang, s.done, s.total, s.speed, s.eta)}"
                    if self.tty:
                        self._p("\r\033[K" + line, end="")
                        inline = True
                    elif (s.stage, s.index) != last_key or now - last_print > 15:
                        self._p("[WorldBridge] " + line)
                        last_print = now
                    last_key = (s.stage, s.index)
                elif (s.stage, s.index) != last_key:
                    if inline:
                        self._p("")
                        inline = False
                    self._p("[WorldBridge] " + text)
                    last_key = (s.stage, s.index)
                th.join(0.25)
        except KeyboardInterrupt:
            cancel.set()
            th.join()
        if inline:
            self._p("")
        s = progress.snapshot()
        rc = result[0] if result else EXIT_FAIL
        if rc == EXIT_OK:
            self._p("[WorldBridge] " + t(self.lang, "done"))
        else:
            self._p("[WorldBridge] " + (s.error or t(self.lang, "failed")))
            if s.detail and rc == EXIT_FAIL:
                for line in s.detail.splitlines()[-12:]:
                    self._p("    " + line)
        return rc


PALETTES = {
    "light": dict(bg="#f3f3f3", fg="#1f1f1f", muted="#5c5c5c", accent="#2b7bd0", trough="#d6d6d6",
                  err="#b3261e", btn="#e4e4e4", btn_active="#d4d4d4", box="#ffffff"),
    "dark": dict(bg="#232629", fg="#eff0f1", muted="#a3a8ad", accent="#3daee9", trough="#3b4045",
                 err="#ff7b72", btn="#31363b", btn_active="#3d444a", box="#1b1e20"),
}


class TkUI:
    """The progress window.  Construction raises if Tk or the display is unusable."""

    def __init__(self, lang: str, log_path: str, dark: bool, root=None, icon: Optional[str] = None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.lang, self.log_path = tk, ttk, lang, log_path
        self.root = root or tk.Tk()
        self.root.withdraw()
        self.pal = PALETTES["dark" if dark else "light"]
        p = self.pal
        r = self.root
        r.title(t(lang, "title"))
        r.configure(bg=p["bg"])
        r.resizable(False, False)
        try:
            r.tk.call("tk", "appname", "WorldBridge")
            r.wm_iconname("WorldBridge")
        except Exception:
            pass
        if icon and os.path.isfile(icon):
            try:
                self._icon = tk.PhotoImage(file=icon)
                r.iconphoto(True, self._icon)
            except Exception:
                pass
        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("WB.Horizontal.TProgressbar", troughcolor=p["trough"], background=p["accent"],
                        bordercolor=p["trough"], lightcolor=p["accent"], darkcolor=p["accent"], thickness=18)
        style.configure("WB.TButton", background=p["btn"], foreground=p["fg"], bordercolor=p["trough"],
                        focuscolor=p["btn"], lightcolor=p["btn"], darkcolor=p["btn"], padding=(16, 5))
        style.map("WB.TButton", background=[("active", p["btn_active"]), ("disabled", p["btn"])],
                  foreground=[("disabled", p["muted"])])
        import tkinter.font as tkfont
        base = tkfont.nametofont("TkDefaultFont")
        size = abs(int(base.actual("size"))) or 10
        self.f_head = tkfont.Font(family=base.actual("family"), size=size + 4, weight="bold")
        self.f_norm = tkfont.Font(family=base.actual("family"), size=size)
        self.f_small = tkfont.Font(family=base.actual("family"), size=max(8, size - 1))
        frame = tk.Frame(r, bg=p["bg"], padx=26, pady=22)
        frame.pack(fill="both", expand=True)
        self.head = tk.Label(frame, text="WorldBridge", font=self.f_head, bg=p["bg"], fg=p["fg"], anchor="w")
        self.head.pack(fill="x")
        self.intro = tk.Label(frame, text=t(lang, "intro"), font=self.f_small, bg=p["bg"], fg=p["muted"], anchor="w")
        self.intro.pack(fill="x", pady=(0, 14))
        self.status = tk.Label(frame, text=t(lang, "resolve"), font=self.f_norm, bg=p["bg"], fg=p["fg"], anchor="w",
                               justify="left", wraplength=500)
        self.status.pack(fill="x", pady=(0, 8))
        self.bar = ttk.Progressbar(frame, style="WB.Horizontal.TProgressbar", orient="horizontal", length=500,
                                   mode="indeterminate", maximum=100)
        self.bar.pack(fill="x")
        self.bar.start(14)
        self.detail = tk.Label(frame, text=" ", font=self.f_small, bg=p["bg"], fg=p["muted"], anchor="w")
        self.detail.pack(fill="x", pady=(6, 0))
        self.errbox = tk.Text(frame, height=9, width=64, wrap="word", font=self.f_small, bg=p["box"], fg=p["fg"],
                              relief="flat", highlightthickness=1, highlightbackground=p["trough"], padx=6, pady=4)
        self.logline = tk.Label(frame, text="", font=self.f_small, bg=p["bg"], fg=p["muted"], anchor="w", justify="left",
                                wraplength=500)
        buttons = tk.Frame(frame, bg=p["bg"])
        buttons.pack(fill="x", pady=(16, 0))
        self.btn_close = ttk.Button(buttons, style="WB.TButton", text=t(lang, "cancel"), command=self._on_cancel)
        self.btn_close.pack(side="right")
        self.btn_copy = ttk.Button(buttons, style="WB.TButton", text=t(lang, "copy"), command=self._copy_log)
        self.buttons = buttons
        self._mode = "indeterminate"
        self._cancel: Optional[threading.Event] = None
        self._finished = False
        self._last_version = -1
        r.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._center()
        r.deiconify()
        r.update()

    def _center(self) -> None:
        r = self.root
        r.update_idletasks()
        w, h = r.winfo_reqwidth(), r.winfo_reqheight()
        x = max(0, (r.winfo_screenwidth() - w) // 2)
        y = max(0, (r.winfo_screenheight() - h) // 3)
        r.geometry(f"+{x}+{y}")

    def _on_cancel(self) -> None:
        if self._finished:
            self.root.destroy()
            return
        if self._cancel is not None and not self._cancel.is_set() and self._snapshot_cancellable:
            self._cancel.set()
            self.btn_close.state(["disabled"])
            self.status.configure(text=t(self.lang, "cancelling"))

    _snapshot_cancellable = True

    def _copy_log(self) -> None:
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                text = f.read()[-200000:]
        except OSError:
            text = self.errbox.get("1.0", "end")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.logline.configure(text=t(self.lang, "copied") + "  " + t(self.lang, "log_at", path=self.log_path))

    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        if mode == "determinate":
            self.bar.stop()
            self.bar.configure(mode="determinate", value=0)
        else:
            self.bar.configure(mode="indeterminate")
            self.bar.start(14)

    def _poll(self, progress: Progress, th: threading.Thread, result: List[int]) -> None:
        s = progress.snapshot()
        self._snapshot_cancellable = s.cancellable
        if s.version != self._last_version:
            self._last_version = s.version
            if s.stage == "download" and s.total > 0:
                self._set_mode("determinate")
                self.bar.configure(value=percent(s.done, s.total))
                self.detail.configure(text=progress_line(self.lang, s.done, s.total, s.speed, s.eta))
            else:
                if s.stage != "download":
                    self._set_mode("indeterminate")
                    self.detail.configure(text=t(self.lang, "install_detail") if s.stage == "install" else " ")
            if not (self._cancel is not None and self._cancel.is_set()):
                self.status.configure(text=stage_text(self.lang, s))
            if s.stage == "install" or not s.cancellable:
                self.btn_close.state(["disabled"])
        if s.finished and not th.is_alive():
            self._finish(s, result[0] if result else EXIT_FAIL)
            return
        self.root.after(100, self._poll, progress, th, result)

    def _finish(self, s: Snapshot, rc: int) -> None:
        self._rc = rc
        self._finished = True
        self.bar.stop()
        if rc == EXIT_OK:
            self._set_mode("determinate")
            self.bar.configure(value=100)
            self.status.configure(text=t(self.lang, "done"))
            self.root.after(500, self.root.destroy)
        elif rc == EXIT_CANCEL:
            self.root.destroy()
        else:
            self._set_mode("determinate")
            self.bar.configure(value=0)
            self.head.configure(text=t(self.lang, "failed"), fg=self.pal["err"])
            self.status.configure(text=s.error, fg=self.pal["err"])
            self.detail.configure(text=" ")
            self.errbox.insert("1.0", "\n".join(s.detail.splitlines()[-14:]) or s.error)
            self.errbox.see("end")
            self.errbox.configure(state="disabled")
            self.bar.pack_forget()
            self.intro.pack_forget()
            self.errbox.pack(fill="x", pady=(10, 0), before=self.buttons)
            self.logline.configure(text=t(self.lang, "log_at", path=self.log_path))
            self.logline.pack(fill="x", pady=(6, 0), before=self.buttons)
            self.btn_close.configure(text=t(self.lang, "close"))
            self.btn_close.state(["!disabled"])
            self.btn_copy.pack(side="right", padx=(0, 8))
            self._center()

    def run(self, work: Callable[[threading.Event], int], progress: Progress) -> int:
        cancel = threading.Event()
        self._cancel = cancel
        result: List[int] = []
        self._rc = EXIT_FAIL
        th = threading.Thread(target=lambda: result.append(work(cancel)), daemon=True)
        th.start()
        self.root.after(100, self._poll, progress, th, result)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            cancel.set()
        th.join(30)
        return result[0] if result else EXIT_CANCEL


def tk_available(env=None):
    """A hidden Tk root when a window can be shown, else None."""
    env = os.environ if env is None else env
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return None
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        return root
    except Exception:
        return None


def find_icon(app: str) -> Optional[str]:
    for rel in ("worldbridge/icon.png", "worldbridge/assets/icon.png", "worldbridge/assets/worldbridge.png",
                "docs/icon.png", "icon.png"):
        p = os.path.join(app, rel)
        if os.path.isfile(p):
            return p
    return None


def main(argv: Optional[List[str]] = None) -> int:
    global _LANG
    ap = argparse.ArgumentParser(description="Install WorldBridge's packages with a progress window.")
    ap.add_argument("--app", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--runtime", default=os.environ.get("WORLDBRIDGE_HOME") or "")
    ap.add_argument("--ui", choices=("auto", "tk", "text"), default=os.environ.get("WORLDBRIDGE_BOOTSTRAP_UI", "auto"))
    args = ap.parse_args(argv)
    app = os.path.abspath(args.app)
    runtime = os.path.abspath(args.runtime or os.path.join(app, ".runtime"))
    lang = _LANG = pick_language(runtime=runtime)
    os.makedirs(os.path.join(runtime, "logs"), exist_ok=True)
    log_path = os.path.join(runtime, "logs", "bootstrap.log")
    ctx = Context(app=app, runtime=runtime, log_path=log_path, env=make_env(app, runtime))
    progress = Progress()
    root = None if args.ui == "text" else tk_available()
    if args.ui == "tk" and root is None:
        print("[WorldBridge] Tk or a display is not available.", file=sys.stderr)
    ui = None
    if root is not None:
        try:
            ui = TkUI(lang, log_path, detect_dark(), root=root, icon=find_icon(app))
        except Exception:
            ui = None
    if ui is None:
        ui = TextUI(lang)
    with open(log_path, "w", encoding="utf-8") as logf:
        ctx.log = logf
        log(ctx, f"WorldBridge first start {time.strftime('%Y-%m-%d %H:%M:%S')}  python {sys.version.split()[0]}  "
                 f"ui={type(ui).__name__}  lang={lang}")
        opener = make_opener()
        rc = ui.run(lambda cancel: run_guarded(ctx, progress, cancel, opener), progress)
    return rc


if __name__ == "__main__":
    sys.exit(main())

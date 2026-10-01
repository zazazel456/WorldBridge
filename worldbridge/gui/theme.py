"""The desktop's look for the GUI: its widget style, colours, fonts and icons.

WorldBridge follows the user's desktop instead of drawing its own theme:

* Qt reads the desktop settings itself (on KDE Plasma ``kdeglobals``: colour scheme, fonts,
  icon theme; elsewhere GTK or the XDG portal).  ``run.sh`` keeps caches and settings inside
  ``.runtime``; for the GUI the user's real configuration folders are made visible again
  (read only: Qt's own settings, like the file dialog's, still go to ``.runtime/config``).
* The widget style the desktop uses (Breeze, Kvantum, Oxygen…, from ``kdeglobals``,
  ``QT_STYLE_OVERRIDE`` or qt6ct) is a plugin of the system's Qt, which is not the Qt bundled
  with PySide6.  Qt plugins that only use Qt's public API load into a newer Qt of the same
  major version, but one using its private API could crash, so the plugin is first tried in a
  separate process (``python -m worldbridge.gui.theme probe PLUGIN STYLE``, which builds the
  whole main window with it); only if that works is it used, and the answer is remembered
  until the plugin or Qt change.  Otherwise Qt's Fusion style with the desktop's colours.

Colours for states (error, warning, success) come from the KDE colour scheme when there is
one, else Breeze's; secondary text uses the palette's placeholder colour.  Nothing here fixes a
colour of its own on the widgets.
"""

from __future__ import annotations

import ctypes
import glob
import json
import os
import subprocess
import sys
from typing import List, Optional

from .. import RUNTIME_DIR

# where distributions install the Qt 6 plugins
SYSTEM_PLUGIN_DIRS = (
    "/usr/lib/qt6/plugins", "/usr/lib64/qt6/plugins", "/usr/lib/x86_64-linux-gnu/qt6/plugins",
    "/usr/lib/aarch64-linux-gnu/qt6/plugins", "/usr/local/lib/qt6/plugins", "/usr/lib/qt/plugins",
    "/usr/lib64/qt/plugins",
)
_STYLE_IID = "org.qt-project.Qt.QStyleFactoryInterface"
# Breeze's colours for the states, when the desktop has no KDE colour scheme
_BREEZE = {"negative": (218, 68, 83), "neutral": (246, 116, 0), "positive": (39, 174, 96)}


# ============================================================ desktop configuration


def user_config_dir() -> str:
    return os.environ.get("WORLDBRIDGE_USER_CONFIG") or os.environ.get("XDG_CONFIG_HOME") or \
        os.path.join(os.path.expanduser("~"), ".config")


def settings_dir() -> str:
    return os.path.join(RUNTIME_DIR, "config")


def prepare_environment() -> None:
    """Before the QApplication: the desktop's settings are readable, Qt's writes stay in .runtime."""
    real = os.environ.get("WORLDBRIDGE_USER_CONFIG")
    if real and os.path.isdir(real):
        os.environ["XDG_CONFIG_HOME"] = real
    data = os.environ.get("WORLDBRIDGE_USER_DATA")
    if data and os.path.isdir(data):
        dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
        if data not in dirs.split(":"):
            os.environ["XDG_DATA_DIRS"] = data + ":" + dirs     # icon themes, colour schemes (read only)
    from PySide6.QtCore import QSettings

    os.makedirs(settings_dir(), exist_ok=True)
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        QSettings.setPath(fmt, QSettings.UserScope, settings_dir())


def _ini(path: str) -> dict:
    """A KDE-style INI file (kdeglobals, qt6ct.conf) as {group: {key: value}}."""
    out: dict = {}
    group = "General"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line[0] in "#;":
                    continue
                if line.startswith("[") and line.endswith("]"):
                    group = line[1:-1]
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    out.setdefault(group, {})[k.strip().split("[", 1)[0]] = v.strip()
    except OSError:
        pass
    return out


def _config_files(name: str) -> List[str]:
    dirs = [user_config_dir()] + [d for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
    return [os.path.join(d, name) for d in dirs if os.path.isfile(os.path.join(d, name))]


def kdeglobals() -> dict:
    """The KDE settings, the user's over the system's."""
    merged: dict = {}
    for path in reversed(_config_files("kdeglobals")):
        for group, values in _ini(path).items():
            merged.setdefault(group, {}).update(values)
    return merged


def _is_kde() -> bool:
    return "KDE" in (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper().split(":") or \
        bool(os.environ.get("KDE_FULL_SESSION"))


def wanted_styles() -> List[str]:
    """The widget styles the desktop asks for, most wanted first."""
    out = []
    override = os.environ.get("QT_STYLE_OVERRIDE")
    if override:
        out.append(override)
    theme = (os.environ.get("QT_QPA_PLATFORMTHEME") or "").lower()
    if "qt6ct" in theme or "qt5ct" in theme:
        for name in ("qt6ct/qt6ct.conf", "qt5ct/qt5ct.conf"):
            for path in _config_files(name):
                style = _ini(path).get("Appearance", {}).get("style")
                if style:
                    out.append(style)
    if _is_kde():
        g = kdeglobals()
        style = g.get("KDE", {}).get("widgetStyle") or g.get("General", {}).get("widgetStyle")
        out.append(style or "breeze")
    seen, res = set(), []
    for s in out:
        if s.lower() not in seen and s.lower() not in ("fusion", "windows"):
            seen.add(s.lower())
            res.append(s)
    return res


# ============================================================ system style plugins


def _qt_lib_dir() -> str:
    import PySide6

    return os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib")


LIB_DIRS = ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib", "/lib/x86_64-linux-gnu", "/lib64", "/lib",
            "/usr/lib/aarch64-linux-gnu", "/usr/local/lib")


def elf_needed(path: str) -> List[str]:
    """The libraries an ELF file links (its DT_NEEDED entries), read from the file."""
    import struct

    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:         # 64-bit little endian only
        return []
    phoff, = struct.unpack_from("<Q", data, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    loads, dyn = [], None
    for i in range(phnum):
        p_type, _fl, off, vaddr, _pa, filesz = struct.unpack_from("<IIQQQQ", data, phoff + i * phentsize)
        if p_type == 1:
            loads.append((vaddr, off, filesz))
        elif p_type == 2:
            dyn = (off, filesz)
    if dyn is None:
        return []

    def file_off(addr):
        for vaddr, off, size in loads:
            if vaddr <= addr < vaddr + size:
                return addr - vaddr + off
        return None

    needed, strtab = [], None
    for i in range(0, dyn[1], 16):
        tag, val = struct.unpack_from("<qQ", data, dyn[0] + i)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        elif tag == 5:
            strtab = file_off(val)
    if strtab is None:
        return []
    return [data[strtab + n:data.index(b"\0", strtab + n)].decode() for n in needed]


def qt_libs_needed(plugin: str) -> List[str]:
    """PySide6's Qt libraries that ``plugin`` needs, directly or through the system libraries it
    links (KDE Frameworks...), so that they are loaded from PySide6 and never from the system."""
    ours = _qt_lib_dir()
    dirs = [d for d in (os.environ.get("LD_LIBRARY_PATH") or "").split(":") if d] + list(LIB_DIRS)
    out, seen, todo = [], set(), [plugin]
    while todo:
        path = todo.pop()
        for soname in elf_needed(path):
            if soname in seen:
                continue
            seen.add(soname)
            if soname.startswith("libQt6") and os.path.isfile(os.path.join(ours, soname)):
                out.append(soname)
                continue
            # a system library (KDE Frameworks, or a Qt module PySide6 does not have, which the probe
            # judges): what it links matters too
            for d in dirs:
                cand = os.path.join(d, soname)
                if os.path.isfile(cand):
                    todo.append(cand)
                    break
    return out


def preload_qt_libs(plugin: str) -> None:
    """Load PySide6's copy of the Qt libraries the style needs before the style itself."""
    lib = _qt_lib_dir()
    for soname in qt_libs_needed(plugin):
        try:
            ctypes.CDLL(os.path.join(lib, soname), mode=ctypes.RTLD_GLOBAL)
        except OSError:
            pass


def _plugin_dirs() -> List[str]:
    extra = [d for d in (os.environ.get("WORLDBRIDGE_QT_PLUGIN_DIRS") or "").split(":") if d]
    return [d for d in extra + list(SYSTEM_PLUGIN_DIRS) if os.path.isdir(os.path.join(d, "styles"))]


def find_style_plugin(style: str) -> Optional[str]:
    """The system's plugin providing ``style`` that this Qt accepts (same major version, not newer),
    found from its metadata without loading it."""
    from PySide6.QtCore import QLibraryInfo, QPluginLoader

    ours = QLibraryInfo.version()
    for d in _plugin_dirs():
        for path in sorted(glob.glob(os.path.join(d, "styles", "*.so"))):
            meta = QPluginLoader(path).metaData()
            if not meta or meta.get("IID") != _STYLE_IID:
                continue
            keys = [str(k).lower() for k in (meta.get("MetaData") or {}).get("Keys", [])]
            v = int(meta.get("version") or 0)
            major, minor = (v >> 16) & 0xFF, (v >> 8) & 0xFF
            if style.lower() in keys and major == ours.majorVersion() and minor <= ours.minorVersion():
                return path
    return None


def _plugin_home(plugin: str) -> str:
    """A folder with only this style plugin in it: nothing else of the system's Qt is exposed."""
    base = os.path.join(RUNTIME_DIR, "qt-styles", os.path.splitext(os.path.basename(plugin))[0])
    os.makedirs(os.path.join(base, "styles"), exist_ok=True)
    link = os.path.join(base, "styles", os.path.basename(plugin))
    if os.path.realpath(link) != os.path.realpath(plugin):
        try:
            os.remove(link)
        except OSError:
            pass
        os.symlink(plugin, link)
    return base


def _probe_key(plugin: str, style: str) -> str:
    from PySide6.QtCore import qVersion

    st = os.stat(plugin)
    return f"{qVersion()}|{plugin}|{st.st_mtime_ns}|{st.st_size}|{style.lower()}|{os.environ.get('QT_QPA_PLATFORM', '')}"


def _probe_cache() -> str:
    return os.path.join(settings_dir(), "WorldBridge", "styles.json")


def style_works(plugin: str, style: str, timeout: float = 60) -> bool:
    """Tries the plugin in another process (answer cached until the plugin or Qt change)."""
    path = _probe_cache()
    try:
        cache = json.load(open(path))
    except (OSError, ValueError):
        cache = {}
    key = _probe_key(plugin, style)
    if key in cache:
        return bool(cache[key])
    try:
        r = subprocess.run([sys.executable, "-m", "worldbridge.gui.theme", "probe", plugin, style],
                           capture_output=True, timeout=timeout, env=dict(os.environ))
        ok = r.returncode == 0 and b"STYLE OK" in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    cache[key] = ok
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(cache, f, indent=1)
    except OSError:
        pass
    return ok


def desktop_style() -> Optional[str]:
    """Before the QApplication: the desktop's widget style, made available if it can be; None
    means Qt's own choice (Fusion with the desktop's colours)."""
    if os.environ.get("WORLDBRIDGE_NATIVE_STYLE", "1") == "0":
        return None
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QStyleFactory

    have = {k.lower(): k for k in QStyleFactory.keys()}
    for style in wanted_styles():
        if style.lower() in have:
            return have[style.lower()]
        plugin = find_style_plugin(style)
        if plugin and style_works(plugin, style):
            preload_qt_libs(plugin)
            QCoreApplication.addLibraryPath(_plugin_home(plugin))
            return style
    return None


def apply(app, style: Optional[str]) -> None:
    """After the QApplication: the style found by ``desktop_style``."""
    if style:
        app.setStyle(style)


def setup_application(argv) -> "object":
    """The QApplication with the desktop's look (the whole sequence, used by the GUI and the probe)."""
    from PySide6.QtWidgets import QApplication

    from .. import APP_NAME

    prepare_environment()
    style = desktop_style()
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_NAME)
    QApplication.setDesktopFileName("worldbridge")
    app = QApplication(argv)
    apply(app, style)
    return app


# ============================================================ colours


def state_color(kind: str):
    """``negative`` (errors), ``neutral`` (warnings), ``positive`` (success) of the colour scheme."""
    from PySide6.QtGui import QColor

    key = {"negative": "ForegroundNegative", "neutral": "ForegroundNeutral", "positive": "ForegroundPositive"}[kind]
    try:
        cache = state_color.cache
    except AttributeError:
        cache = state_color.cache = kdeglobals() if _is_kde() else {}
    v = cache.get("Colors:Window", {}).get(key) or cache.get("Colors:View", {}).get(key)
    if v:
        try:
            r, g, b = (int(x) for x in v.split(",")[:3])
            return QColor(r, g, b)
        except ValueError:
            pass
    return QColor(*_BREEZE[kind])


def secondary_color(widget=None):
    """Colour of secondary text (hints, details): the palette's inactive text."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from PySide6.QtGui import QColor

    pal = widget.palette() if widget is not None else QApplication.palette()
    c = pal.color(QPalette.PlaceholderText)
    if c.alpha() < 255:                  # Qt's default is the text colour half transparent: made opaque
        bg, a = pal.color(QPalette.Window), c.alphaF()
        c = QColor(round(c.red() * a + bg.red() * (1 - a)), round(c.green() * a + bg.green() * (1 - a)),
                   round(c.blue() * a + bg.blue() * (1 - a)))
    return c


def span(text: str, kind: str) -> str:
    """Rich text in a state's colour (``secondary`` too)."""
    col = secondary_color() if kind == "secondary" else state_color(kind)
    return f"<span style='color:{col.name()}'>{text}</span>"


def icon(*names: str, fallback=None):
    """An icon of the desktop's icon theme (first of ``names`` it has), else one of the style's."""
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    for n in names:
        if QIcon.hasThemeIcon(n):
            return QIcon.fromTheme(n)
    if fallback is not None:
        return QApplication.style().standardIcon(fallback)
    return QIcon()


# ============================================================ probe


def _probe(plugin: str, style: str) -> int:
    """Child process: the real main window with the style, drawn once."""
    os.environ.setdefault("WORLDBRIDGE_WORKERS", "1")
    prepare_environment()
    preload_qt_libs(plugin)
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.addLibraryPath(_plugin_home(plugin))
    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    app.setStyle(style)
    if app.style().name().lower() != style.lower():
        print("style not loaded", app.style().name())
        return 1
    from .app import MainWindow

    w = MainWindow(remember=False)
    w.resize(1100, 800)
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        app.processEvents()
        w.grab()
    w.deleteLater()
    app.processEvents()
    print("STYLE OK", app.style().name())
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "probe":
        sys.exit(_probe(sys.argv[2], sys.argv[3]))
    print(__doc__)

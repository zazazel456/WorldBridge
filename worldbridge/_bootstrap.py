"""Self-installation of the Python dependencies inside the program folder.

When WorldBridge is started with a Python that lacks its dependencies (e.g. the system
``python3 -m worldbridge``) they are installed with ``pip --target`` into
``.runtime/site-packages`` next to the program - never into the system or the user's
home - and that folder is put in front of ``sys.path``.  Only prebuilt wheels are used
(``vendor/wheels`` provides the Amulet ones that PyPI ships as source only), so no compiler
is needed.  If that is not possible (a Python version without wheels, no pip...) the program
restarts itself through ``run.sh``, which uses a portable Python in ``.runtime/python``.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

from . import RUNTIME_DIR
from .i18n import tr

CORE = ("numpy", "amulet", "amulet_nbt", "PyMCTranslate", "leveldb")
GUI = ("PySide6",)


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# versions with wheels for every pinned package (numpy 1.26 and the vendored Amulet wheels)
SUPPORTED_PYTHONS = ((3, 11), (3, 12))


def _lock_file() -> str:
    return os.path.join(APP_DIR, "requirements.lock")


def site_dir() -> str:
    return os.path.join(RUNTIME_DIR, "site-packages", f"py{sys.version_info[0]}{sys.version_info[1]}")


def _missing(mods) -> list:
    return [m for m in mods if importlib.util.find_spec(m) is None]


def ensure(gui: bool) -> None:
    target = site_dir()
    if os.path.isdir(target) and target not in sys.path:
        sys.path.insert(0, target)
        importlib.invalidate_caches()
    need = _missing(CORE + (GUI if gui else ()))
    if not need:
        return
    if sys.version_info[:2] not in SUPPORTED_PYTHONS:
        _use_launcher(tr("Python {version} has no prebuilt packages for every dependency",
                         version=f"{sys.version_info[0]}.{sys.version_info[1]}"))
    print("[WorldBridge] " + tr("Missing dependencies ({names}): installing them in {path} …", names=", ".join(need), path=target),
          file=sys.stderr)
    env = dict(os.environ)
    env.update({"PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1",
                "PIP_CONFIG_FILE": os.devnull})
    cmd = [sys.executable, "-m", "pip", "install", "--no-user", "--upgrade", "--target", target,
           "--only-binary=:all:", "--find-links", os.path.join(APP_DIR, "vendor", "wheels"), "-r", _lock_file()]
    try:
        subprocess.run(cmd, check=True, env=env)
    except (subprocess.CalledProcessError, OSError) as ex:
        _use_launcher(tr("installation with pip failed ({error})", error=ex))
    if target not in sys.path:
        sys.path.insert(0, target)
    importlib.invalidate_caches()
    still = _missing(CORE + (GUI if gui else ()))
    if still:
        raise SystemExit("[WorldBridge] " + tr("Dependencies still missing: {names}", names=", ".join(still)))


def _use_launcher(reason: str) -> None:
    """Restart through run.sh (portable Python + local runtime), unless we already come from it."""
    launcher = os.path.join(APP_DIR, "run.sh")
    if os.environ.get("WORLDBRIDGE_LAUNCHER") or not os.path.isfile(launcher) or not sys.platform.startswith("linux"):
        raise SystemExit("[WorldBridge] " + tr("Cannot install the dependencies: {reason}.", reason=reason))
    print("[WorldBridge] " + tr("{reason}: using ./run.sh (portable Python in the .runtime folder).", reason=reason), file=sys.stderr)
    sys.stderr.flush()
    os.execvp("bash", ["bash", launcher] + sys.argv[1:])

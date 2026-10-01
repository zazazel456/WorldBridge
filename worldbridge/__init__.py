"""WorldBridge - universal Minecraft world converter.

Converts worlds between Java Edition (Classic -> latest), Bedrock Edition
(Pocket Edition 0.x -> latest) and Legacy Console Edition (Xbox 360, PS3,
Wii U, PS Vita, PS4, Xbox One, Switch and the Windows64 PC ports built from
the LCE source such as MinecraftConsoles / LCEMP / neoLegacy).
"""

import os as _os
import tempfile as _tempfile

__version__ = "0.2.0"
APP_NAME = "WorldBridge"


def _runtime_dir() -> str:
    """Folder for caches/logs: ``$WORLDBRIDGE_HOME`` (set by run.sh), else ``.runtime``
    next to the program, else a temporary folder.  Never the user's home."""
    for cand in (_os.environ.get("WORLDBRIDGE_HOME"),
                 _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".runtime")):
        if not cand:
            continue
        try:
            _os.makedirs(cand, exist_ok=True)
            if _os.access(cand, _os.W_OK):
                return cand
        except OSError:
            pass
    return _os.path.join(_tempfile.gettempdir(), "worldbridge-runtime")


RUNTIME_DIR = _runtime_dir()
# Amulet Core keeps temporary chunk databases and logs in the user's cache/log folders
# (~/.cache/AmuletTeam ...): keep them inside the program's own runtime folder instead.
_os.environ.setdefault("CACHE_DIR", _os.path.join(RUNTIME_DIR, "cache", "amulet"))
_os.environ.setdefault("LOG_DIR", _os.path.join(RUNTIME_DIR, "logs", "amulet"))

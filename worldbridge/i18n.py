"""The language of WorldBridge's messages: English (the source) or Italian.

Every message a user can see is written in English and passed through :func:`tr`, which returns the
Italian text from :mod:`worldbridge.i18n_it` when Italian is the current language.  Placeholders are
named, ``tr("{n} chunks converted", n=n)``, so a translation can move them.  Texts defined before the
language is known (module constants) are marked with :func:`N_` and translated where they are shown.

The language is, in order: the one set with :func:`set_language` (the interface's EN / IT switch, the
``--lang`` option), ``WORLDBRIDGE_LANG``, the system locale (Italian locales give Italian), English.
"""
from __future__ import annotations

import locale
import os
from typing import Dict, Optional

LANGUAGES = {"en": "English", "it": "Italiano"}
_current: Optional[str] = None
_catalogs: Dict[str, Dict[str, str]] = {}


def system_language() -> str:
    env = os.environ.get("WORLDBRIDGE_LANG", "").strip().lower()[:2]
    if env in LANGUAGES:
        return env
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return "it" if value.lower().startswith("it") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except ValueError:
        loc = ""
    return "it" if loc.lower().startswith("it") else "en"


def language() -> str:
    global _current
    if _current is None:
        _current = system_language()
    return _current


def set_language(code: Optional[str]) -> str:
    """Set the language (``None`` or an unknown code: the system's) and return it."""
    global _current
    code = (code or "").strip().lower()[:2]
    _current = code if code in LANGUAGES else system_language()
    os.environ["WORLDBRIDGE_LANG"] = _current     # worker processes and restarts follow it
    return _current


def _catalog(code: str) -> Dict[str, str]:
    if code not in _catalogs:
        if code == "it":
            from .i18n_it import IT
            _catalogs[code] = IT
        else:
            _catalogs[code] = {}
    return _catalogs[code]


def tr(text: str, /, **values) -> str:
    """``text`` in the current language, with its ``{placeholders}`` filled from ``values``."""
    lang = language()
    out = text if lang == "en" else _catalog(lang).get(text, text)
    return out.format(**values) if values else out


def N_(text: str) -> str:
    """Marks a text for translation without translating it (it is translated with tr() when shown)."""
    return text

"""Every message has its Italian text, with the same placeholders."""
import ast
import os
import string

from worldbridge import i18n
from worldbridge.i18n_it import IT

ROOT = os.path.join(os.path.dirname(__file__), "..", "worldbridge")


def _texts():
    """The literal texts given to tr() and N_() in the program."""
    out = {}
    for dp, _, files in os.walk(ROOT):
        for f in files:
            if not f.endswith(".py") or f in ("i18n.py", "i18n_it.py"):
                continue
            p = os.path.join(dp, f)
            for node in ast.walk(ast.parse(open(p, encoding="utf-8").read())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_")
                        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    out.setdefault(node.args[0].value, f"{os.path.relpath(p, ROOT)}:{node.lineno}")
    return out


def _fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_text_has_an_italian_translation():
    missing = {t: where for t, where in _texts().items() if t not in IT}
    assert not missing, "\n".join(f"{w}: {t!r}" for t, w in list(missing.items())[:20])


def test_translations_keep_the_placeholders():
    wrong = [en for en, it in IT.items() if _fields(en) != _fields(it)]
    assert not wrong, wrong[:10]


def test_no_unused_translations():
    used = set(_texts())
    unused = [en for en in IT if en not in used]
    assert not unused, unused[:10]


def test_tr_follows_the_language():
    i18n.set_language("it")
    assert i18n.tr("Completed") == "Completato"
    assert i18n.tr("Selection: {n} chunks", n=3) == "Selezione: 3 chunk"
    assert i18n.tr("a text without translation") == "a text without translation"
    i18n.set_language("en")
    assert i18n.tr("Selection: {n} chunks", n=3) == "Selection: 3 chunks"


def test_system_language(monkeypatch):
    monkeypatch.delenv("WORLDBRIDGE_LANG", raising=False)
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "it_IT.UTF-8")
    assert i18n.system_language() == "it"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.system_language() == "en"
    monkeypatch.setenv("WORLDBRIDGE_LANG", "it")
    assert i18n.system_language() == "it"


def test_cli_speaks_both_languages(capsys):
    from worldbridge.cli import main

    assert main(["--lang", "it", "info", "/nonexistent/world"]) == 1
    assert "Formato non riconosciuto" in capsys.readouterr().out
    assert main(["--lang", "en", "info", "/nonexistent/world"]) == 1
    assert "Format not recognised" in capsys.readouterr().out


def test_every_call_fills_its_placeholders():
    """tr("… {n} …", n=…): the values given are the placeholders of the text, no more, no less."""
    wrong = []
    for dp, _, files in os.walk(ROOT):
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            for node in ast.walk(ast.parse(open(p, encoding="utf-8").read())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and not any(k.arg is None for k in node.keywords)):
                    given = {k.arg for k in node.keywords}
                    if given != _fields(node.args[0].value):
                        wrong.append(f"{os.path.relpath(p, ROOT)}:{node.lineno} {node.args[0].value[:60]!r}")
    assert not wrong, "\n".join(wrong)

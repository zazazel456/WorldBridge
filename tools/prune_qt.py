"""Remove the parts of PySide6-Essentials WorldBridge never uses (QML/Quick, Designer,
developer tools, headers, most translations) from the local runtime.

Kept: the few Qt Quick / QML libraries that KDE's Breeze widget style links (about 20 MB), so that
the desktop's Breeze can be loaded against this Qt instead of the system's (see gui/theme.py).
``prune_qt.py --missing`` prints those that a previous, stricter pruning removed (run.sh then
reinstalls PySide6 before pruning again).

Run by run.sh right after installing the dependencies; run.sh then verifies that the GUI
still starts and reinstalls PySide6 untouched if anything went wrong."""

import glob
import os
import shutil
import sys

import PySide6

root = os.path.dirname(PySide6.__file__)
qt = os.path.join(root, "Qt")
removed = 0
# linked by the Breeze style and the KDE Frameworks it uses (Kirigami platform, KIconThemes)
KEEP = {f"libQt6{m}.so.6" for m in ("Qml", "QmlMeta", "QmlModels", "QmlWorkerScript", "Quick", "QuickControls2",
                                     "QuickTemplates2")}

if sys.argv[1:] == ["--missing"]:
    print(" ".join(sorted(k for k in KEEP if not os.path.exists(os.path.join(qt, "lib", k)))))
    sys.exit(0)


def rm(path):
    global removed
    for p in glob.glob(path):
        if os.path.isdir(p) and not os.path.islink(p):
            removed += sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.exists(p) or os.path.islink(p):
            removed += os.path.getsize(p) if os.path.isfile(p) else 0
            os.remove(p)


# QML / Quick runtime and modules
rm(os.path.join(qt, "qml"))
for pat in ("libQt6Quick*", "libQt6Qml*", "libQt6LabsStyleKit*", "libQt6Designer*", "libQt6WaylandCompositor*",
            "libQt6ShaderTools*", "libQt6UiTools*", "libQt6Help*", "libQt6Test*"):
    for f in glob.glob(os.path.join(qt, "lib", pat)):
        if os.path.basename(f) not in KEEP:
            rm(f)
for pat in ("QtQuick*", "QtQml*", "QtDesigner*", "QtUiTools*", "QtHelp*", "QtTest*"):
    rm(os.path.join(root, pat))
# developer tools, headers, type stubs
for tool in ("designer", "linguist", "assistant", "lupdate", "lrelease", "qmlls", "qmlformat", "qmllint",
             "qmlcachegen", "qmlimportscanner", "qmltyperegistrar", "qsb", "balsam", "balsamui", "uic", "rcc",
             "svgtoqml", "androiddeployqt", "qtpaths"):
    rm(os.path.join(root, tool))
for d in ("include", "typesystems", "glue", "scripts", "support"):
    if d != "support":
        rm(os.path.join(root, d))
rm(os.path.join(qt, "metatypes"))
rm(os.path.join(qt, "libexec"))
rm(os.path.join(root, "*.pyi"))
# translations: keep Italian and English Qt base strings (standard dialogs)
for f in glob.glob(os.path.join(qt, "translations", "*")):
    base = os.path.basename(f)
    if not (base.startswith("qtbase_it") or base.startswith("qtbase_en") or base.startswith("qt_it") or base.startswith("qt_en")):
        rm(f)
# plugins only needed by QML
for d in ("qmltooling", "qmllint", "scenegraph"):
    rm(os.path.join(qt, "plugins", d))

print(f"PySide6: liberati {removed / 1e6:.0f} MB")
sys.exit(0)

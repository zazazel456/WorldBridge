#!/usr/bin/env bash
# WorldBridge launcher for Linux.
#
# Everything the program needs lives in ./.runtime next to this script:
#   * a portable CPython (python-build-standalone, SHA-256 verified) - no system Python needed
#   * the Python packages from requirements.lock
#   * pip / Amulet / Qt / fontconfig caches and logs
# Nothing is written to the system or to ~/.cache, ~/.config, ~/.local.
# Remove everything with:  ./run.sh --clean   (or just delete the .runtime folder)
set -euo pipefail

APP="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RT="$APP/.runtime"

PY_TAG="20260901"
PY_VER="3.11.16"
case "$(uname -m)" in
    x86_64|amd64)  ARCH="x86_64";  PY_SHA="faa0758583a63f14c5eee516af82738403b59c13edda6fc0a21d953febd89eed" ;;
    *) echo "Architettura non supportata: $(uname -m). Amulet Core (amulet-rocksdb) è distribuito" \
            "per Linux solo su x86_64." >&2; exit 1 ;;
esac
PY_FILE="cpython-${PY_VER}+${PY_TAG}-${ARCH}-unknown-linux-gnu-install_only.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/${PY_FILE}"
PY="$RT/python/bin/python3"

say() { printf '\033[1;36m[WorldBridge]\033[0m %s\n' "$*" >&2; }

if [ "${1:-}" = "--clean" ]; then
    rm -rf "${RT:?}"
    say "Runtime locale rimosso ($RT)."
    exit 0
fi

download() {  # url dest
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --progress-bar -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$2" "$1"
    else
        say "Serve curl o wget per scaricare il runtime."; exit 1
    fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# ---- isolate every cache / config write inside .runtime
mkdir -p "$RT/cache" "$RT/config" "$RT/data" "$RT/state"
export PYTHONNOUSERSITE=1
export PIP_NO_CACHE_DIR=1
export PIP_CONFIG_FILE=/dev/null
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
export PYTHONPYCACHEPREFIX="$RT/cache/pycache"
export WORLDBRIDGE_HOME="$RT" WORLDBRIDGE_LAUNCHER=1
# the desktop's own settings (KDE colour scheme, Kvantum, GTK theme, icons) stay readable for the GUI,
# which reads them from here; everything WorldBridge and Qt write goes to .runtime
export WORLDBRIDGE_USER_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}" WORLDBRIDGE_USER_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
if [ -z "${WORLDBRIDGE_KEEP_XDG:-}" ]; then
    export XDG_CACHE_HOME="$RT/cache" XDG_CONFIG_HOME="$RT/config" XDG_DATA_HOME="$RT/data" XDG_STATE_HOME="$RT/state"
fi
export PYTHONPATH="$APP${PYTHONPATH:+:$PYTHONPATH}"

# ---- 1. portable Python
if [ ! -x "$PY" ] || [ "$(cat "$RT/python.version" 2>/dev/null)" != "$PY_VER+$PY_TAG" ]; then
    say "Scarico Python $PY_VER portatile (una sola volta)…"
    mkdir -p "$RT/download"
    tmp="$RT/download/$PY_FILE"
    download "$PY_URL" "$tmp"
    got="$(sha256 "$tmp")"
    if [ "$got" != "$PY_SHA" ]; then
        rm -f "$tmp"; say "Checksum non valido per $PY_FILE (atteso $PY_SHA, ottenuto $got)."; exit 1
    fi
    rm -rf "$RT/python"
    tar -xzf "$tmp" -C "$RT"
    rm -f "$tmp"
    echo "$PY_VER+$PY_TAG" > "$RT/python.version"
    rm -f "$RT/deps.stamp"
fi

# ---- 2. Python packages (reinstalled only when requirements.lock changes)
#         Only prebuilt wheels are used: PyPI's for most packages, ./vendor/wheels for the Amulet
#         ones that PyPI ships as source only.  If one is still missing it is compiled here with a
#         portable Zig toolchain (tools/build_wheels.py) - no gcc, headers or -dev packages needed.
want="$(sha256 "$APP/requirements.lock")-$(sha256 "$APP/vendor/wheels/SHA256SUMS")-$(sha256 "$APP/tools/prune_qt.py")-$PY_VER"
PIPI=("$PY" -m pip install --no-user --quiet --root-user-action=ignore)
DEPS=(--only-binary=:all: --find-links "$APP/vendor/wheels" --find-links "$RT/wheels" -r "$APP/requirements.lock")
if [ "$(cat "$RT/deps.stamp" 2>/dev/null)" != "$want" ]; then
    say "Installo le dipendenze (Amulet, PyMCTranslate, amulet-nbt, numpy, PySide6) nel runtime locale…"
    mkdir -p "$RT/wheels"
    "${PIPI[@]}" --upgrade pip
    if ! "${PIPI[@]}" "${DEPS[@]}"; then
        say "Alcune dipendenze non hanno pacchetti precompilati per questo sistema: le compilo in locale…"
        "$PY" "$APP/tools/build_wheels.py" --out "$RT/wheels" --work "$RT/build"
        rm -rf "${RT:?}/build"
        "${PIPI[@]}" "${DEPS[@]}"
    fi
    # drop the parts of Qt the program never uses (QML, Designer, tools…), then make sure the
    # GUI still builds; if not, reinstall PySide6 untouched.  Libraries an older pruning removed
    # and that are kept now (for the desktop's Breeze style) come back with a reinstall first.
    if [ -n "$("$PY" "$APP/tools/prune_qt.py" --missing 2>/dev/null)" ]; then
        "${PIPI[@]}" --force-reinstall --no-deps "$(grep -i '^PySide6-Essentials' "$APP/requirements.lock")"
    fi
    "$PY" "$APP/tools/prune_qt.py" >&2 || true
    if ! QT_QPA_PLATFORM=offscreen "$PY" "$APP/tools/gui_selftest.py" >/dev/null 2>&1; then
        say "Ripristino PySide6 completo…"
        "${PIPI[@]}" --force-reinstall --no-deps "$(grep -i '^PySide6-Essentials' "$APP/requirements.lock")"
    fi
    echo "$want" > "$RT/deps.stamp"
fi

# ---- 3. graphical interface: Qt's X11 plugin needs a few xcb helper libraries that many
#         distributions do not install; fetch the missing ones into .runtime/syslibs
is_cli=0
case "${1:-}" in info|convert|versions|players|trim|-h|--help) is_cli=1 ;; esac
if [ $is_cli -eq 0 ]; then
    if [ ! -f "$RT/syslibs.checked" ] && command -v ldd >/dev/null 2>&1; then
        left="$("$PY" "$APP/tools/fetch_syslibs.py" "$RT/syslibs" || true)"
        touch "$RT/syslibs.checked"
        if [ -n "$left" ]; then
            say "Librerie grafiche non disponibili: $left"
        fi
    fi
    export LD_LIBRARY_PATH="$RT/syslibs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    if ! "$PY" -c "from PySide6 import QtWidgets" 2>/dev/null; then
        say "L'interfaccia grafica non si avvia: mancano librerie OpenGL/EGL o fontconfig del sistema."
        say "Su Debian/Ubuntu:  sudo apt install libegl1 libgl1 libfontconfig1"
        say "Intanto puoi usare la riga di comando:  ./run.sh convert <sorgente> <output> --to java"
        exit 1
    fi
fi

exec "$PY" -m worldbridge "$@"

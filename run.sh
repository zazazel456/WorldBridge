#!/usr/bin/env bash
# WorldBridge launcher for Linux.
#
# Everything the program needs lives in ./.runtime next to this script (or in $WORLDBRIDGE_RUNTIME):
#   * a portable CPython (python-build-standalone, SHA-256 verified) - no system Python needed
#   * the Python packages from requirements.lock
#   * pip / Amulet / Qt / fontconfig caches and logs
# Nothing is written to the system or to ~/.cache, ~/.config, ~/.local.
# Remove everything with:  ./run.sh --clean   (or just delete the .runtime folder)
#
# First start: the portable Python (~30 MB) is downloaded here; from a launcher without a terminal a
# small progress dialog (kdialog or zenity, when installed) shows the download.  The packages are
# then installed by tools/bootstrap_ui.py, which shows its own progress window (or plain lines).
set -euo pipefail

APP="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RT="${WORLDBRIDGE_RUNTIME:-$APP/.runtime}"      # WORLDBRIDGE_RUNTIME: another place for the runtime (tests)
case "$RT" in /*) ;; *) RT="$PWD/$RT" ;; esac
RT="${RT%/}"

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
    if [ -z "$RT" ] || [ "$RT" = "$HOME" ] || [ "$RT" = "$APP" ]; then
        say "Rifiuto di rimuovere $RT."; exit 1
    fi
    rm -rf "${RT:?}"
    say "Runtime locale rimosso ($RT)."
    exit 0
fi

# ---- language of the dialogs (the same choice the program makes: WORLDBRIDGE_LANG, else the locale)
lang_it() {
    case "${WORLDBRIDGE_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANGUAGE:-${LANG:-}}}}}" in it*|IT*) return 0 ;; *) return 1 ;; esac
}
msg() { if lang_it; then printf '%s' "$1"; else printf '%s' "$2"; fi; }   # msg "italiano" "english"

# ---- desktop dialogs, only when there is no terminal (a launcher / double click).
#      Their texts are plain ASCII: zenity / kdialog reject non-ASCII arguments in a C locale.
have_terminal() { [ -t 1 ] || [ -t 2 ]; }
QDBUS="" TOOL=""
dialog_tool() {  # sets TOOL to kdialog or zenity when a dialog can be shown; fails otherwise
    TOOL=""
    have_terminal && return 1
    [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || return 1
    if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v kdialog >/dev/null 2>&1; then
        for q in qdbus qdbus6 qdbus-qt6 qdbus-qt5; do   # kdialog's progress bar is driven through D-Bus
            if command -v "$q" >/dev/null 2>&1; then QDBUS="$q"; TOOL=kdialog; return 0; fi
        done
    fi
    if command -v zenity >/dev/null 2>&1; then TOOL=zenity; return 0; fi
    return 1
}

fail() {  # message: to the terminal and, without one, to a dialog
    say "$*"
    if dialog_tool; then
        case "$TOOL" in
            kdialog) kdialog --title "WorldBridge" --error "$*" >/dev/null 2>&1 || true ;;
            zenity)  m="$*"; m="${m//&/&amp;}"; m="${m//</&lt;}"; m="${m//>/&gt;}"      # zenity reads Pango markup
                     zenity --error --title="WorldBridge" --text="$m" >/dev/null 2>&1 || true ;;
        esac
    fi
    exit 1
}

fmt_mb() {  # bytes -> 12.3 (comma in Italian)
    local v; v="$(printf '%d.%d' $(($1 / 1048576)) $(($1 * 10 / 1048576 % 10)))"
    if lang_it; then v="${v/./,}"; fi
    printf '%s' "$v"
}
fmt_eta() { local s="$1"; if [ "$s" -ge 3600 ]; then printf '%d:%02d:%02d' $((s / 3600)) $((s % 3600 / 60)) $((s % 60)); else printf '%d:%02d' $((s / 60)) $((s % 60)); fi; }

DLG_PID="" DLG_FIFO="" DLG_REF=""
dlg_open() {  # tool title text pulsate(0|1)
    case "$1" in
        zenity)
            DLG_FIFO="$(mktemp -u "${TMPDIR:-/tmp}/wb-dlg.XXXXXX")"; mkfifo "$DLG_FIFO"
            local opt=(--percentage=0); [ "$4" = 1 ] && opt=(--pulsate)
            zenity --progress --title="$2" --text="$3" --width=440 "${opt[@]}" --auto-close \
                <"$DLG_FIFO" >/dev/null 2>&1 &
            DLG_PID=$!
            exec 8<>"$DLG_FIFO"
            sleep 0.5
            kill -0 "$DLG_PID" 2>/dev/null || { dlg_close zenity; return 1; } ;;
        kdialog)
            DLG_REF="$(timeout 15 kdialog --title "$2" --progressbar "$3" 100 2>/dev/null)" || return 1
            "$QDBUS" $DLG_REF showCancelButton true >/dev/null 2>&1 || true ;;
    esac
}
dlg_update() {  # tool percent text
    case "$1" in
        zenity) printf '%s\n# %s\n' "$2" "$3" >&8 2>/dev/null || true ;;
        kdialog) "$QDBUS" $DLG_REF Set "" value "$2" >/dev/null 2>&1 || true
                 "$QDBUS" $DLG_REF setLabelText "$3" >/dev/null 2>&1 || true ;;
    esac
}
dlg_alive() {  # false once the user pressed Cancel (or the dialog died)
    case "$1" in
        zenity) kill -0 "$DLG_PID" 2>/dev/null ;;
        kdialog) [ "$("$QDBUS" $DLG_REF wasCancelled 2>/dev/null)" = "false" ] ;;
    esac
}
dlg_close() {
    case "$1" in
        zenity) exec 8>&-
                kill "$DLG_PID" 2>/dev/null || true; wait "$DLG_PID" 2>/dev/null || true
                rm -f "$DLG_FIFO" ;;
        kdialog) "$QDBUS" $DLG_REF close >/dev/null 2>&1 || true ;;
    esac
}

fetch_quiet() {  # url dest   (no progress output; used behind a dialog)
    if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -o "$2" "$1"
    else wget -q -O "$2" "$1"; fi
}
content_length() {  # url -> bytes (0 when unknown)
    local n=0
    if command -v curl >/dev/null 2>&1; then
        n="$(curl -fsSIL --max-time 20 "$1" 2>/dev/null | tr -d '\r' | awk 'tolower($1)=="content-length:"{n=$2} END{print n+0}')" || n=0
    fi
    printf '%s' "${n:-0}"
}

download_dialog() {  # tool url dest : returns 0 ok, 1 failed, 2 cancelled, 3 no dialog
    local tool="$1" url="$2" dest="$3" total size=0 prev=0 speed=0 inst pid rc=0 pct text eta
    local title text0
    title="$(msg 'WorldBridge - primo avvio' 'WorldBridge - first start')"
    text0="$(msg 'Download di Python (una sola volta)...' 'Downloading Python (only once)...')"
    total="$(content_length "$url")"
    rm -f "$dest"
    dlg_open "$tool" "$title" "$text0" "$([ "$total" -gt 0 ] && echo 0 || echo 1)" || return 3   # no dialog after all
    fetch_quiet "$url" "$dest" & pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        if ! dlg_alive "$tool"; then
            kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true
            rm -f "$dest"; dlg_close "$tool"; return 2
        fi
        size="$(stat -c %s "$dest" 2>/dev/null || echo 0)"
        inst=$((size - prev)); prev=$size
        if [ "$speed" -eq 0 ]; then speed=$inst; else speed=$(((speed * 3 + inst) / 4)); fi
        if [ "$total" -gt 0 ]; then
            pct=$((size * 100 / total)); [ "$pct" -gt 99 ] && pct=99
            eta="--:--"; [ "$speed" -gt 0 ] && eta="$(fmt_eta $(((total - size) / speed)))"
            text="$text0  $(fmt_mb "$size") MB $(msg 'di' 'of') $(fmt_mb "$total") MB  -  $(fmt_mb "$speed") MB/s  -  $(msg 'mancano' 'ETA') $eta"
        else
            pct=0; text="$text0  $(fmt_mb "$size") MB  -  $(fmt_mb "$speed") MB/s"
        fi
        dlg_update "$tool" "$pct" "$text"
    done
    wait "$pid" || rc=$?
    dlg_update "$tool" 100 "$text0"
    dlg_close "$tool"
    [ "$rc" -eq 0 ] || return 1
    return 0
}

download() {  # url dest
    local rc=0
    if dialog_tool; then
        download_dialog "$TOOL" "$1" "$2" || rc=$?
        case "$rc" in
            0) return 0 ;;
            2) say "Download annullato."; exit 130 ;;
            3) ;;                       # the dialog tool does not work here: download without it
            *) return 1 ;;
        esac
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --progress-bar -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "$2" "$1"
    else
        fail "Serve curl o wget per scaricare il runtime."
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
    download "$PY_URL" "$tmp" || { rm -f "$tmp"; fail "$(msg "Download di Python non riuscito ($PY_URL)." "Could not download Python ($PY_URL).")"; }
    got="$(sha256 "$tmp")"
    if [ "$got" != "$PY_SHA" ]; then
        rm -f "$tmp"
        fail "$(msg "Checksum non valido per $PY_FILE (atteso $PY_SHA, ottenuto $got)." "Invalid checksum for $PY_FILE (expected $PY_SHA, got $got).")"
    fi
    rm -rf "$RT/python"
    tar -xzf "$tmp" -C "$RT"
    rm -f "$tmp"
    echo "$PY_VER+$PY_TAG" > "$RT/python.version"
    rm -f "$RT/deps.stamp"
fi

# ---- 2. Python packages (reinstalled only when requirements.lock changes)
#         tools/bootstrap_ui.py (run with the portable Python) asks pip which wheels requirements.lock
#         needs, downloads them with a progress window (plain lines on a terminal / without a display),
#         installs them offline, then prunes Qt and checks the GUI builds.  Only prebuilt wheels are used:
#         PyPI's for most packages, ./vendor/wheels for the Amulet ones that PyPI ships as source only.
#         If one is still missing it is compiled here with a portable Zig toolchain
#         (tools/build_wheels.py) - no gcc, headers or -dev packages needed.
want="$(sha256 "$APP/requirements.lock")-$(sha256 "$APP/vendor/wheels/SHA256SUMS")-$(sha256 "$APP/tools/prune_qt.py")-$PY_VER"
is_cli=0
cmd_arg="${1:-}"
case "$cmd_arg" in   # an optional "--lang it" before the command
    --lang)   [ -n "${2:-}" ] && export WORLDBRIDGE_LANG="$2"; cmd_arg="${3:-}" ;;
    --lang=*) export WORLDBRIDGE_LANG="${cmd_arg#--lang=}"; cmd_arg="${2:-}" ;;
esac
case "$cmd_arg" in info|convert|versions|players|trim|-h|--help) is_cli=1 ;; esac
if [ "$(cat "$RT/deps.stamp" 2>/dev/null)" != "$want" ]; then
    say "Installo le dipendenze (Amulet, PyMCTranslate, amulet-nbt, numpy, PySide6) nel runtime locale…"
    ui="${WORLDBRIDGE_BOOTSTRAP_UI:-auto}"
    [ $is_cli -eq 1 ] && ui=text          # the command line: plain progress lines, no window
    rc=0
    "$PY" "$APP/tools/bootstrap_ui.py" --app "$APP" --runtime "$RT" --ui "$ui" || rc=$?
    case "$rc" in
        0) ;;
        3) say "Installazione annullata: alla prossima partenza riprende da dove si era fermata."; exit 130 ;;
        *) say "Installazione delle dipendenze non riuscita. Log: $RT/logs/bootstrap.log"; exit 1 ;;
    esac
    echo "$want" > "$RT/deps.stamp"
fi

# ---- 3. graphical interface: Qt's X11 plugin needs a few xcb helper libraries that many
#         distributions do not install; fetch the missing ones into .runtime/syslibs
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
        say "Intanto puoi usare la riga di comando:  ./run.sh convert <sorgente> <output> --to java"
        fail "L'interfaccia grafica non si avvia: mancano librerie OpenGL/EGL o fontconfig del sistema." \
             "Su Debian/Ubuntu:  sudo apt install libegl1 libgl1 libfontconfig1"
    fi
fi

exec "$PY" -m worldbridge "$@"

#!/usr/bin/env bash
set -euo pipefail

DEFAULT_APP_DIR="/opt/erfassung"
APP_DIR="$DEFAULT_APP_DIR"

print_help() {
    cat <<USAGE
$0 [--app-dir <path>]

Optionen:
  --app-dir     Installationverzeichnis der Anwendung (Standard: ${DEFAULT_APP_DIR}).
  -h, --help    Diese Hilfe anzeigen.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-dir)
            APP_DIR="$2"
            shift 2
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo "Unbekannte Option: $1" >&2
            print_help
            exit 1
            ;;
    esac
done

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Fehler: Benötigtes Programm '$1' wurde nicht gefunden." >&2
        exit 1
    fi
}

run_as_root() {
    if [[ $EUID -ne 0 ]]; then
        if command -v sudo >/dev/null 2>&1; then
            sudo "$@"
        else
            echo "Fehler: Für '$*' sind erhöhte Rechte erforderlich (sudo)." >&2
            exit 1
        fi
    else
        "$@"
    fi
}

echo "🔄 Aktualisiere Installation in ${APP_DIR}..."

if [[ ! -d "$APP_DIR" ]]; then
    echo "Fehler: Installationsverzeichnis '$APP_DIR' wurde nicht gefunden." >&2
    exit 1
fi

if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
    echo "Fehler: requirements.txt wurde im Installationsverzeichnis nicht gefunden." >&2
    exit 1
fi

BUILD_DEPS=()
PKG_MANAGER=""
INSTALL_CMD=()
UPDATE_CMD=()

if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt-get"
    INSTALL_CMD=(apt-get install -y)
    UPDATE_CMD=(apt-get update)
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
    INSTALL_CMD=(dnf install -y)
    UPDATE_CMD=(dnf makecache)
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
    INSTALL_CMD=(yum install -y)
    UPDATE_CMD=(yum makecache)
else
    echo "Warnung: Kein unterstützter Paketmanager gefunden. Bitte installieren Sie Systemabhängigkeiten manuell." >&2
fi

if [[ -n "$PKG_MANAGER" ]]; then
    echo "🔧 Aktualisiere Paketquellen über $PKG_MANAGER..."
    run_as_root "${UPDATE_CMD[@]}"
    COMMON_PKGS=(python3 python3-venv python3-pip sqlite3 wget ca-certificates unzip)
    SLIDESHOW_PKGS=(mpv x11-xserver-utils)
    ALL_PKGS=("${COMMON_PKGS[@]}" "${SLIDESHOW_PKGS[@]}")
    echo "🔧 Stelle Systempakete sicher..."
    run_as_root "${INSTALL_CMD[@]}" "${ALL_PKGS[@]}"
fi

require_command python3
require_command wget

if ! command -v mpv >/dev/null 2>&1; then
    if [[ -n "$PKG_MANAGER" ]]; then
        echo "Fehler: 'mpv' wurde trotz Paketinstallation nicht gefunden." >&2
        exit 1
    else
        echo "Warnung: 'mpv' wurde nicht gefunden. Bitte installieren Sie es manuell." >&2
    fi
fi

VENV_DIR="$APP_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "🌱 Virtuelle Umgebung wird erstellt..."
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

pip install --upgrade pip setuptools wheel
pip install --no-cache-dir -r "$APP_DIR/requirements.txt"

deactivate

echo "✅ Update abgeschlossen."

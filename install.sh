#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Erfassung"
APP_SLUG=$(printf '%s' "$APP_NAME" | tr '[:upper:]' '[:lower:]')
DEFAULT_INSTALL_DIR="/opt/erfassung"
SOURCE_URL=""
INSTALL_DIR=""
MARKER_FILE=".${APP_SLUG}_installed"
SERVICE_NAME="${APP_SLUG}.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"

print_help() {
    cat <<USAGE
$0 [--source-url <url>] [--install-dir <path>]

Optionen:
  --source-url    Archiv (tar.gz/zip), das den Anwendungscode enthält. Wenn angegeben,
                  wird der Quellcode automatisch heruntergeladen und entpackt.
  --install-dir   Zielverzeichnis für die Installation. Standard: ${DEFAULT_INSTALL_DIR}
                  (nur relevant, wenn --source-url verwendet wird).
  -h, --help      Diese Hilfe anzeigen.

Beispiel:
  wget https://example.com/install.sh -O install.sh && \
  bash install.sh --source-url https://example.com/erfassung.tar.gz
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source-url)
            SOURCE_URL="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
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

echo "📦 Prüfe Systemvoraussetzungen..."

BUILD_DEPS=()

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
    echo "Warnung: Kein unterstützter Paketmanager gefunden. Bitte installieren Sie Python 3.11+, pip und venv manuell." >&2
    PKG_MANAGER=""
fi

if [[ -n "$PKG_MANAGER" ]]; then
    echo "🔧 Aktualisiere Paketquellen über $PKG_MANAGER..."
    run_as_root "${UPDATE_CMD[@]}"
    echo "🔧 Installiere Systempakete..."
    COMMON_PKGS=(python3 python3-venv python3-pip sqlite3 wget ca-certificates unzip)
    SLIDESHOW_PKGS=(mpv x11-xserver-utils)
    ALL_PKGS=("${COMMON_PKGS[@]}" "${SLIDESHOW_PKGS[@]}")
    if [[ ${#BUILD_DEPS[@]} -gt 0 ]]; then
        ALL_PKGS+=("${BUILD_DEPS[@]}")
    fi
    run_as_root "${INSTALL_CMD[@]}" "${ALL_PKGS[@]}"
fi

require_command python3
require_command wget

if ! command -v mpv >/dev/null 2>&1; then
    if [[ -n "${PKG_MANAGER:-}" ]]; then
        echo "Fehler: 'mpv' wurde trotz Paketinstallation nicht gefunden." >&2
        exit 1
    else
        echo "Warnung: 'mpv' wurde nicht gefunden. Bitte installieren Sie es manuell." >&2
    fi
fi

abspath() {
    python3 - <<'PY' "$1"
import os
import sys
print(os.path.abspath(sys.argv[1]))
PY
}

if [[ -n "$SOURCE_URL" ]]; then
    TEMP_ROOT=$(mktemp -d)
    echo "⬇️  Lade Anwendung aus $SOURCE_URL herunter..."
    TMP_ARCHIVE="$TEMP_ROOT/source"
    wget -O "$TMP_ARCHIVE" "$SOURCE_URL"
    echo "📁 Entpacke Archiv..."
    case "$SOURCE_URL" in
        *.zip)
            require_command unzip
            unzip -q "$TMP_ARCHIVE" -d "$TEMP_ROOT"
            ;;
        *.tar.gz|*.tgz)
            tar -xzf "$TMP_ARCHIVE" -C "$TEMP_ROOT"
            ;;
        *)
            echo "Fehler: Unbekanntes Archivformat. Unterstützt werden .zip und .tar.gz." >&2
            rm -rf "$TEMP_ROOT"
            exit 1
            ;;
    esac
    SOURCE_PROJECT_DIR=$(find "$TEMP_ROOT" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    if [[ -z "$SOURCE_PROJECT_DIR" ]]; then
        SOURCE_PROJECT_DIR="$TEMP_ROOT"
    fi
else
    SOURCE_PROJECT_DIR=$(pwd)
fi

TARGET_DIR=${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}
TARGET_DIR=$(abspath "$TARGET_DIR")

if [[ ! -f "$SOURCE_PROJECT_DIR/requirements.txt" ]]; then
    echo "Fehler: requirements.txt wurde im Projektverzeichnis nicht gefunden." >&2
    [[ -n "${TEMP_ROOT:-}" ]] && rm -rf "$TEMP_ROOT"
    exit 1
fi

echo "📂 Zielverzeichnis: $TARGET_DIR"

if [[ -d "$TARGET_DIR" ]]; then
    echo "♻️  Entferne bestehende Installation in $TARGET_DIR..."
    run_as_root rm -rf "$TARGET_DIR"
fi

run_as_root mkdir -p "$TARGET_DIR"
OWNER_USER=${SUDO_USER:-$(id -un)}
OWNER_GROUP=$(id -gn "$OWNER_USER")

echo "📦 Kopiere Anwendung nach $TARGET_DIR..."
tar -C "$SOURCE_PROJECT_DIR" -cf - . | run_as_root tar -C "$TARGET_DIR" -xf -
run_as_root chown -R "$OWNER_USER":"$OWNER_GROUP" "$TARGET_DIR"

[[ -n "${TEMP_ROOT:-}" ]] && rm -rf "$TEMP_ROOT"

PROJECT_DIR="$TARGET_DIR"
VENV_DIR="$PROJECT_DIR/.venv"

if [[ -d "$VENV_DIR" ]]; then
    echo "♻️  Entferne alte virtuelle Umgebung..."
    rm -rf "$VENV_DIR"
fi

echo "🌱 Erstelle Python-Umgebung..."
python3 -m venv "$VENV_DIR"

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

pip install --upgrade pip setuptools wheel
pip install --no-cache-dir -r "$PROJECT_DIR/requirements.txt"

deactivate

SERVICE_STATUS_MSG="Systemd wurde nicht gefunden. Starten Sie den Dienst manuell mit 'cd $PROJECT_DIR && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000'."
if command -v systemctl >/dev/null 2>&1; then
    echo "🛠️  Richte systemd-Dienst ${SERVICE_NAME} ein..."
    UNIT_CONTENT="[Unit]\\nDescription=${APP_NAME} API\\nAfter=network.target\\n\\n[Service]\\nType=simple\\nWorkingDirectory=${PROJECT_DIR}\\nUser=${OWNER_USER}\\nGroup=${OWNER_GROUP}\\nEnvironment=PATH=${PROJECT_DIR}/.venv/bin\\nExecStart=${PROJECT_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000\\nRestart=on-failure\\n\\n[Install]\\nWantedBy=multi-user.target"
    printf '%b' "$UNIT_CONTENT" | run_as_root tee "$SERVICE_FILE" >/dev/null
    run_as_root systemctl daemon-reload
    run_as_root systemctl enable --now "$SERVICE_NAME"
    SERVICE_STATUS_MSG="Dienst ${SERVICE_NAME} wurde installiert und gestartet."
fi

touch "$PROJECT_DIR/$MARKER_FILE"

echo "✅ Installation abgeschlossen."
cat <<INFO

Nächste Schritte:
  1. cd "$PROJECT_DIR"
  2. source .venv/bin/activate
  3. uvicorn app.main:app --reload

Die Anwendung liegt unter $PROJECT_DIR (Standard: /opt/erfassung).
${SERVICE_STATUS_MSG}
Standardzugang: Benutzer "admin" mit PIN 0000.
INFO

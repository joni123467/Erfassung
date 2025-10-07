#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Erfassung"
DEFAULT_INSTALL_DIR="erfassung-app"
SOURCE_URL=""
INSTALL_DIR=""

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
    run_as_root "${INSTALL_CMD[@]}" python3 python3-venv python3-pip sqlite3 wget ca-certificates unzip
fi

require_command python3
require_command wget

if [[ -n "$SOURCE_URL" ]]; then
    INSTALL_DIR=${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}
    mkdir -p "$INSTALL_DIR"
    WORK_DIR=$(cd "$INSTALL_DIR" && pwd)
    echo "⬇️  Lade Anwendung aus $SOURCE_URL herunter..."
    TMP_ARCHIVE=$(mktemp)
    wget -O "$TMP_ARCHIVE" "$SOURCE_URL"
    echo "📁 Entpacke Archiv..."
    case "$SOURCE_URL" in
        *.zip)
            require_command unzip
            unzip -q "$TMP_ARCHIVE" -d "$WORK_DIR"
            ;;
        *.tar.gz|*.tgz)
            tar -xzf "$TMP_ARCHIVE" -C "$WORK_DIR"
            ;;
        *)
            echo "Fehler: Unbekanntes Archivformat. Unterstützt werden .zip und .tar.gz." >&2
            rm -f "$TMP_ARCHIVE"
            exit 1
            ;;
    esac
    rm -f "$TMP_ARCHIVE"
    # Falls Archiv einen Unterordner enthält, in diesen wechseln
    SUBDIR=$(find "$WORK_DIR" -maxdepth 1 -type d ! -path "$WORK_DIR" | head -n 1)
    if [[ -n "$SUBDIR" ]]; then
        PROJECT_DIR="$SUBDIR"
    else
        PROJECT_DIR="$WORK_DIR"
    fi
else
    PROJECT_DIR=$(pwd)
fi

echo "📂 Projektverzeichnis: $PROJECT_DIR"

if [[ ! -f "$PROJECT_DIR/requirements.txt" ]]; then
    echo "Fehler: requirements.txt wurde im Projektverzeichnis nicht gefunden." >&2
    exit 1
fi

PYTHON_BIN=$(command -v python3)
VENV_DIR="$PROJECT_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "🌱 Erstelle Python-Umgebung..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

deactivate

echo "✅ Installation abgeschlossen."
cat <<INFO

Nächste Schritte:
  1. cd "$PROJECT_DIR"
  2. source .venv/bin/activate
  3. uvicorn app.main:app --reload

Standardzugang: Benutzer "admin" mit PIN 0000.
INFO

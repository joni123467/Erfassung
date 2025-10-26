#!/usr/bin/env bash
set -euo pipefail

DEFAULT_APP_DIR="/opt/erfassung"
DEFAULT_REPO_URL="https://github.com/joni123467/Erfassung"
DEFAULT_REPO_REF="main"

APP_DIR="$DEFAULT_APP_DIR"
REPO_URL="$DEFAULT_REPO_URL"
REPO_REF="$DEFAULT_REPO_REF"

print_help() {
    cat <<USAGE
$0 [--app-dir <path>] [--repo-url <url>] [--ref <branch-or-tag>]

Optionen:
  --app-dir     Installationsverzeichnis der Anwendung (Standard: ${DEFAULT_APP_DIR}).
  --repo-url    Git-Repository-URL, aus der Updates geladen werden (Standard: ${DEFAULT_REPO_URL}).
  --ref         Branch oder Tag, der für Updates verwendet wird (Standard: ${DEFAULT_REPO_REF}).
  -h, --help    Diese Hilfe anzeigen.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-dir)
            APP_DIR="$2"
            shift 2
            ;;
        --repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        --ref)
            REPO_REF="$2"
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

download_file() {
    local url="$1"
    local destination="$2"

    if command -v curl >/dev/null 2>&1; then
        if curl -fsSL "$url" -o "$destination"; then
            return 0
        fi
    elif command -v wget >/dev/null 2>&1; then
        if wget -q "$url" -O "$destination"; then
            return 0
        fi
    else
        echo "Fehler: Für Downloads wird curl oder wget benötigt." >&2
        exit 1
    fi

    return 1
}

if [[ "${ERFASSUNG_NO_BOOTSTRAP:-0}" != "1" ]]; then
    TMP_DIR="$(mktemp -d)"
    cleanup_bootstrap() {
        rm -rf "$TMP_DIR"
    }
    trap cleanup_bootstrap EXIT
    ARCHIVE_PATH="$TMP_DIR/source.tar.gz"

    # Entfernt ggf. abschließende Slashes.
    REPO_URL="${REPO_URL%/}"
    ARCHIVE_URL="${REPO_URL}/archive/refs/heads/${REPO_REF}.tar.gz"

    echo "⬇️  Lade aktuelle Update-Routine von ${ARCHIVE_URL}..."
    if ! download_file "$ARCHIVE_URL" "$ARCHIVE_PATH"; then
        ALT_ARCHIVE_URL="${REPO_URL}/archive/refs/tags/${REPO_REF}.tar.gz"
        echo "⚠️  Branch-Download fehlgeschlagen, versuche Tag ${ALT_ARCHIVE_URL}..."
        if ! download_file "$ALT_ARCHIVE_URL" "$ARCHIVE_PATH"; then
            echo "Fehler: Update-Paket konnte nicht geladen werden." >&2
            exit 1
        fi
    fi

    echo "📦 Entpacke Update-Paket..."
    tar -xzf "$ARCHIVE_PATH" -C "$TMP_DIR"
    NEW_SOURCE_DIR="$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

    if [[ -z "$NEW_SOURCE_DIR" ]]; then
        echo "Fehler: Entpackte Update-Routine konnte nicht gefunden werden." >&2
        exit 1
    fi

    if [[ ! -f "$NEW_SOURCE_DIR/update.sh" ]]; then
        echo "Fehler: Die aktualisierte Update-Routine enthält kein update.sh." >&2
        exit 1
    fi

    echo "▶️  Starte aktualisierte Update-Routine..."
    ERFASSUNG_NO_BOOTSTRAP=1 ERFASSUNG_SOURCE_DIR="$NEW_SOURCE_DIR" bash "$NEW_SOURCE_DIR/update.sh" "$@"
    EXIT_CODE=$?
    cleanup_bootstrap
    trap - EXIT
    exit $EXIT_CODE
fi

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

SOURCE_DIR="${ERFASSUNG_SOURCE_DIR:-}"
if [[ -n "$SOURCE_DIR" ]]; then
    if [[ ! -d "$SOURCE_DIR" ]]; then
        echo "Fehler: Quelldateien unter '$SOURCE_DIR' wurden nicht gefunden." >&2
        exit 1
    fi

    echo "📁 Synchronisiere Programmdateien in ${APP_DIR}..."
    PRESERVE_ITEMS=(".venv" ".env" "config" "config.yml" "config.yaml" "data" "logs")
    shopt -s dotglob
    for item in "$APP_DIR"/* "$APP_DIR"/.*; do
        name="$(basename "$item")"
        if [[ "$name" == "." || "$name" == ".." ]]; then
            continue
        fi

        skip=false
        for keep in "${PRESERVE_ITEMS[@]}"; do
            if [[ "$name" == "$keep" ]]; then
                skip=true
                break
            fi
        done

        if [[ $skip == false ]]; then
            rm -rf "$item"
        fi
    done
    shopt -u dotglob

    tar -C "$SOURCE_DIR" -cf - --exclude=.git --exclude=.github --exclude='*.pyc' --exclude='__pycache__' . | \
        tar -C "$APP_DIR" -xf -
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

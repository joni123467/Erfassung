#!/usr/bin/env sh
set -eu
if (set -o 2>/dev/null | grep -q 'pipefail'); then
    set -o pipefail 2>/dev/null || true
fi

DEFAULT_APP_DIR="/opt/erfassung"
DEFAULT_REPO_URL="https://github.com/joni123467/Erfassung"
DEFAULT_REPO_REF="main"

SCRIPT_VERSION=""
if [ -n "${ERFASSUNG_SOURCE_DIR:-}" ] && [ -f "${ERFASSUNG_SOURCE_DIR}/VERSION" ]; then
    SCRIPT_VERSION=$(tr -d '\r\n' < "${ERFASSUNG_SOURCE_DIR}/VERSION")
else
    SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
    if [ -f "$SCRIPT_DIR/VERSION" ]; then
        SCRIPT_VERSION=$(tr -d '\r\n' < "$SCRIPT_DIR/VERSION")
    fi
fi

ARCHIVE_REF='$Format:%(describe:tags=true)$'
ARCHIVE_REF_RESOLVED=""
if [ "$ARCHIVE_REF" != '$Format:%(describe:tags=true)$' ]; then
    ARCHIVE_REF_RESOLVED=${ARCHIVE_REF%%-g*}
    case "$ARCHIVE_REF_RESOLVED" in
        refs/tags/*)
            ARCHIVE_REF_RESOLVED=${ARCHIVE_REF_RESOLVED#refs/tags/}
            ;;
        refs/heads/*)
            ARCHIVE_REF_RESOLVED=${ARCHIVE_REF_RESOLVED#refs/heads/}
            ;;
    esac
    if [ -z "$SCRIPT_VERSION" ]; then
        case "$ARCHIVE_REF_RESOLVED" in
            version-*)
                SCRIPT_VERSION=${ARCHIVE_REF_RESOLVED#version-}
                ;;
        esac
    fi
fi

if [ -n "$SCRIPT_VERSION" ]; then
    DEFAULT_REPO_REF="version-$SCRIPT_VERSION"
elif [ -n "$ARCHIVE_REF_RESOLVED" ]; then
    DEFAULT_REPO_REF="$ARCHIVE_REF_RESOLVED"
elif [ "${ERFASSUNG_NO_BOOTSTRAP:-0}" = "1" ]; then
    VERSION_FILE="$DEFAULT_APP_DIR/VERSION"
    if [ -f "$VERSION_FILE" ]; then
        CURRENT_VERSION=$(tr -d '\r\n' < "$VERSION_FILE")
        if [ -n "$CURRENT_VERSION" ]; then
            DEFAULT_REPO_REF="version-$CURRENT_VERSION"
        fi
    fi
fi

APP_DIR="$DEFAULT_APP_DIR"
REPO_URL="$DEFAULT_REPO_URL"
REPO_REF="$DEFAULT_REPO_REF"
REPO_REF_WAS_EXPLICIT=0

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

while [ "$#" -gt 0 ]; do
    case "$1" in
        --app-dir)
            if [ "$#" -lt 2 ]; then
                echo "Option --app-dir benötigt einen Wert." >&2
                exit 1
            fi
            APP_DIR="$2"
            shift 2
            ;;
        --repo-url)
            if [ "$#" -lt 2 ]; then
                echo "Option --repo-url benötigt einen Wert." >&2
                exit 1
            fi
            REPO_URL="$2"
            shift 2
            ;;
        --ref)
            if [ "$#" -lt 2 ]; then
                echo "Option --ref benötigt einen Wert." >&2
                exit 1
            fi
            REPO_REF="$2"
            REPO_REF_WAS_EXPLICIT=1
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
    url="$1"
    destination="$2"

    if command -v curl >/dev/null 2>&1; then
        if curl -fsSL "$url" -o "$destination"; then
            return 0
        fi
    fi
    if command -v wget >/dev/null 2>&1; then
        if wget -q "$url" -O "$destination"; then
            return 0
        fi
    fi
    return 1
}

fetch_latest_release_ref() {
    repo_url="$1"

    case "$repo_url" in
        https://github.com/*/*)
            api_url="https://api.github.com/repos/${repo_url#https://github.com/}/releases/latest"
            ;;
        https://api.github.com/repos/*)
            api_url="${repo_url%/}/releases/latest"
            ;;
        *)
            return 1
            ;;
    esac

    if command -v curl >/dev/null 2>&1; then
        response=$(curl -fsSL "$api_url" 2>/dev/null || true)
    elif command -v wget >/dev/null 2>&1; then
        response=$(wget -q -O - "$api_url" 2>/dev/null || true)
    else
        return 1
    fi

    if [ -z "$response" ]; then
        return 1
    fi

    latest_tag=$(printf '%s' "$response" |
        sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"[:cntrl:]]*\)".*/\1/p' |
        head -n 1)

    if [ -n "$latest_tag" ]; then
        printf '%s\n' "$latest_tag"
        return 0
    fi

    return 1
}

if [ "${ERFASSUNG_NO_BOOTSTRAP:-0}" != "1" ]; then
    if [ "$REPO_REF_WAS_EXPLICIT" -eq 0 ]; then
        if LATEST_REF=$(fetch_latest_release_ref "$REPO_URL") && [ -n "$LATEST_REF" ]; then
            if [ "$REPO_REF" != "$LATEST_REF" ]; then
                echo "ℹ️  Verwende neueste Release-Version ${LATEST_REF}."
            fi
            REPO_REF="$LATEST_REF"
        else
            echo "⚠️  Neueste Release-Version konnte nicht ermittelt werden, verwende ${REPO_REF}." >&2
        fi
    fi

    TMP_DIR=$(mktemp -d)
    cleanup_bootstrap() {
        rm -rf "$TMP_DIR"
    }
    trap cleanup_bootstrap EXIT
    ARCHIVE_PATH="$TMP_DIR/source.tar.gz"

    REPO_URL=${REPO_URL%/}

    CANDIDATE_URLS="${REPO_URL}/archive/refs/tags/${REPO_REF}.tar.gz"
    case "$REPO_REF" in
        */*)
            CANDIDATE_URLS="${REPO_URL}/archive/refs/heads/${REPO_REF}.tar.gz $CANDIDATE_URLS"
            ;;
        version-*|v*)
            CANDIDATE_URLS="${REPO_URL}/archive/refs/tags/${REPO_REF}.tar.gz ${REPO_URL}/archive/refs/heads/${REPO_REF}.tar.gz"
            ;;
        *)
            CANDIDATE_URLS="${REPO_URL}/archive/refs/heads/${REPO_REF}.tar.gz ${REPO_URL}/archive/refs/tags/${REPO_REF}.tar.gz"
            ;;
    esac

    DOWNLOAD_SUCCESS=0
    for ARCHIVE_URL in $CANDIDATE_URLS; do
        echo "⬇️  Lade aktuelle Update-Routine von ${ARCHIVE_URL}..."
        if download_file "$ARCHIVE_URL" "$ARCHIVE_PATH"; then
            DOWNLOAD_SUCCESS=1
            break
        fi
        echo "⚠️  Konnte ${ARCHIVE_URL} nicht laden, versuche alternative Quelle..."
    done

    if [ "$DOWNLOAD_SUCCESS" -ne 1 ]; then
        echo "Fehler: Update-Paket konnte nicht geladen werden." >&2
        exit 1
    fi

    echo "📦 Entpacke Update-Paket..."
    tar -xzf "$ARCHIVE_PATH" -C "$TMP_DIR"
    NEW_SOURCE_DIR=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)

    if [ -z "$NEW_SOURCE_DIR" ]; then
        echo "Fehler: Entpackte Update-Routine konnte nicht gefunden werden." >&2
        exit 1
    fi

    if [ ! -f "$NEW_SOURCE_DIR/update.sh" ]; then
        echo "Fehler: Die aktualisierte Update-Routine enthält kein update.sh." >&2
        exit 1
    fi

    echo "▶️  Starte aktualisierte Update-Routine..."
    ERFASSUNG_NO_BOOTSTRAP=1 ERFASSUNG_SOURCE_DIR="$NEW_SOURCE_DIR" sh "$NEW_SOURCE_DIR/update.sh" "$@"
    EXIT_CODE=$?
    cleanup_bootstrap
    trap - EXIT
    exit "$EXIT_CODE"
fi

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Fehler: Benötigtes Programm '$1' wurde nicht gefunden." >&2
        exit 1
    fi
}

run_as_root() {
    if [ "$(id -u)" -ne 0 ]; then
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

if [ ! -d "$APP_DIR" ]; then
    echo "Fehler: Installationsverzeichnis '$APP_DIR' wurde nicht gefunden." >&2
    exit 1
fi

SOURCE_DIR=${ERFASSUNG_SOURCE_DIR:-}
if [ -n "$SOURCE_DIR" ]; then
    if [ ! -d "$SOURCE_DIR" ]; then
        echo "Fehler: Quelldateien unter '$SOURCE_DIR' wurden nicht gefunden." >&2
        exit 1
    fi

    echo "📁 Synchronisiere Programmdateien in ${APP_DIR}..."
    PRESERVE_ITEMS=".venv .env config config.yml config.yaml data logs erfassung.db"
    for item in "$APP_DIR"/* "$APP_DIR"/.[!.]* "$APP_DIR"/..?*; do
        [ -e "$item" ] || continue
        name=$(basename "$item")
        case "$name" in
            .|..)
                continue
                ;;
        esac
        skip=0
        for keep in $PRESERVE_ITEMS; do
            if [ "$name" = "$keep" ]; then
                skip=1
                break
            fi
        done
        if [ "$skip" -eq 0 ]; then
            rm -rf "$item"
        fi
    done

    tar -C "$SOURCE_DIR" -cf - --exclude=.git --exclude=.github --exclude='*.pyc' --exclude='__pycache__' . |
        tar -C "$APP_DIR" -xf -
fi

if [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo "Fehler: requirements.txt wurde im Installationsverzeichnis nicht gefunden." >&2
    exit 1
fi

PKG_MANAGER=""
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt-get"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
else
    echo "Warnung: Kein unterstützter Paketmanager gefunden. Bitte installieren Sie Systemabhängigkeiten manuell." >&2
fi

COMMON_PKGS="python3 python3-venv python3-pip sqlite3 wget ca-certificates unzip"
SLIDESHOW_PKGS="mpv x11-xserver-utils"
ALL_PKGS="$COMMON_PKGS $SLIDESHOW_PKGS"

if [ -n "$PKG_MANAGER" ]; then
    echo "🔧 Aktualisiere Paketquellen über $PKG_MANAGER..."
    case "$PKG_MANAGER" in
        apt-get)
            run_as_root apt-get update
            run_as_root apt-get install -y $ALL_PKGS
            ;;
        dnf)
            run_as_root dnf makecache
            run_as_root dnf install -y $ALL_PKGS
            ;;
        yum)
            run_as_root yum makecache
            run_as_root yum install -y $ALL_PKGS
            ;;
    esac
fi

require_command python3
require_command wget

if ! command -v mpv >/dev/null 2>&1; then
    if [ -n "$PKG_MANAGER" ]; then
        echo "Fehler: 'mpv' wurde trotz Paketinstallation nicht gefunden." >&2
        exit 1
    else
        echo "Warnung: 'mpv' wurde nicht gefunden. Bitte installieren Sie es manuell." >&2
    fi
fi

VENV_DIR="$APP_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "🌱 Virtuelle Umgebung wird erstellt..."
    python3 -m venv "$VENV_DIR"
fi

. "$VENV_DIR/bin/activate"

pip install --upgrade pip setuptools wheel
pip install --no-cache-dir -r "$APP_DIR/requirements.txt"

if ! pip check; then
    echo "Fehler: Python-Abhängigkeiten konnten nicht vollständig installiert werden." >&2
    exit 1
fi

CURRENT_DIR=$(pwd)
cd "$APP_DIR"
python - <<'PY'
from app import database, models

models.Base.metadata.create_all(bind=database.engine)
PY
python -m app.db_migrations --database "$APP_DIR/erfassung.db"
cd "$CURRENT_DIR"

deactivate

if [ "${ERFASSUNG_SKIP_SERVICE_RESTART:-0}" = "1" ]; then
    echo "ℹ️  Neustart des Dienstes wurde übersprungen (ERFASSUNG_SKIP_SERVICE_RESTART=1)."
else
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl list-unit-files | grep -q '^erfassung\.service'; then
            echo "🔁 Starte Dienst erfassung.service neu..."
            if ! run_as_root systemctl restart erfassung.service; then
                echo "⚠️  Der Dienst konnte nicht neu gestartet werden." >&2
            fi
        fi
    fi
fi

echo "✅ Update abgeschlossen."

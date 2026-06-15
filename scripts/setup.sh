#!/usr/bin/env bash
# Bootstrap script: install uv + cursaves from this repo, then run interactive setup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "cursaves setup (bootstrap)"
echo "================================"

find_python() {
    for cmd in python3 python py; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

if ! PYTHON=$(find_python); then
    echo "Error: Python 3.10+ is required but was not found." >&2
    echo "Install Python from https://www.python.org/downloads/" >&2
    exit 1
fi
echo "Python: $($PYTHON --version)"

if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required but not found." >&2
    echo "Install git from https://git-scm.com/downloads" >&2
    exit 1
fi
echo "Git: $(git --version)"

install_uv() {
    echo ""
    echo "uv is not installed."
    echo "Install with:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    read -r -p "Install uv now? [y/N] " reply
    case "$reply" in
        [yY]|[yY][eE][sS])
            curl -LsSf https://astral.sh/uv/install.sh | sh
            # shellcheck disable=SC1091
            if [ -f "$HOME/.local/bin/env" ]; then
                source "$HOME/.local/bin/env"
            elif [ -f "$HOME/.cargo/env" ]; then
                source "$HOME/.cargo/env"
            fi
            ;;
        *)
            echo "Cannot continue without uv." >&2
            exit 1
            ;;
    esac
}

if ! command -v uv >/dev/null 2>&1; then
    install_uv
fi
echo "uv: $(uv --version)"

echo ""
echo "Installing cursaves from $ROOT ..."
uv tool install --force "$ROOT"

CURSAVES=""
if command -v cursaves >/dev/null 2>&1; then
    CURSAVES="cursaves"
elif [ -x "$HOME/.local/bin/cursaves" ]; then
    CURSAVES="$HOME/.local/bin/cursaves"
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "Warning: cursaves not found on PATH." >&2
    echo "Run: uv tool update-shell" >&2
    echo "Then restart your terminal and run: cursaves setup" >&2
    exit 1
fi

echo ""
echo "Running: $CURSAVES setup $*"
exec "$CURSAVES" setup "$@"

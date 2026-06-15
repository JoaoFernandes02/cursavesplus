#!/usr/bin/env bash
# One-click install: uv + cursaves + desktop shortcut + launch GUI
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GITHUB_URL="git+https://github.com/Callum-Ward/cursaves.git"

echo "cursaves installer"
echo "=================="

find_python() {
  for cmd in python3 python "py -3"; do
    if command -v ${cmd%% *} >/dev/null 2>&1; then
      if $cmd -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

find_python || { echo "Python 3.10+ required." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git required." >&2; exit 1; }

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

INSTALL_TARGET="$ROOT"
if [[ ! -f "$ROOT/pyproject.toml" ]]; then
  INSTALL_TARGET="$GITHUB_URL"
  echo "Installing from GitHub..."
else
  echo "Installing from local repo: $ROOT"
fi

uv tool install --force "$INSTALL_TARGET"

export PATH="$HOME/.local/bin:$PATH"
command -v cursaves >/dev/null 2>&1 || { echo "cursaves not on PATH. Run: uv tool update-shell" >&2; exit 1; }

echo ""
echo "Creating desktop shortcut..."
CURSAVES_PATH="$(command -v cursaves)"
if [[ "$(uname)" == "Darwin" ]]; then
  DESKTOP="$HOME/Desktop/Cursaves.command"
  cat > "$DESKTOP" <<EOF
#!/bin/bash
exec "$CURSAVES_PATH"
EOF
  chmod +x "$DESKTOP"
elif [[ -d "$HOME/Desktop" ]]; then
  cat > "$HOME/Desktop/cursaves.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cursaves
Exec=$CURSAVES_PATH
Terminal=false
EOF
  chmod +x "$HOME/Desktop/cursaves.desktop"
fi

echo ""
echo "Launching cursaves..."
if [[ "$(uname)" == "Darwin" ]]; then
  open -a cursaves 2>/dev/null || cursaves &
else
  cursaves &
fi

echo "Done. cursaves GUI should be opening."

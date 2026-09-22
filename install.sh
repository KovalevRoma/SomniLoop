#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/somniloop.desktop"
ICON_FILE="$PROJECT_DIR/src/somniloop/assets/somniloop.svg"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required."
  exit 1
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip

echo "Installing SomniLoop and local LLM support..."
if ! "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR[llm]"; then
  echo "LLM support could not be installed; installing the tracker without it."
  "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR"
fi

mkdir -p "$APPLICATIONS_DIR"
sed \
  -e "s|@EXEC@|\"$VENV_DIR/bin/python\" -m somniloop|g" \
  -e "s|@ICON@|$ICON_FILE|g" \
  "$PROJECT_DIR/assets/somniloop.desktop.in" > "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"

if command -v systemctl >/dev/null 2>&1; then
  mkdir -p "$SYSTEMD_USER_DIR"
  sed -e "s|@PYTHON@|$VENV_DIR/bin/python|g" \
    "$PROJECT_DIR/assets/somniloop-reminders.service.in" \
    > "$SYSTEMD_USER_DIR/somniloop-reminders.service"
  cp "$PROJECT_DIR/assets/somniloop-reminders.timer" "$SYSTEMD_USER_DIR/"
  systemctl --user daemon-reload || true
  systemctl --user enable --now somniloop-reminders.timer || true
fi

DESKTOP_DIR="$HOME/Desktop"
if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
fi
if [ -d "$DESKTOP_DIR" ] && [ "$DESKTOP_DIR" != "$HOME" ]; then
  cp "$DESKTOP_FILE" "$DESKTOP_DIR/SomniLoop.desktop"
  chmod +x "$DESKTOP_DIR/SomniLoop.desktop"
  gio set "$DESKTOP_DIR/SomniLoop.desktop" metadata::trusted true >/dev/null 2>&1 || true
fi

echo
echo "SomniLoop is installed. Open it from the Ubuntu applications menu."
echo "Project source: $PROJECT_DIR"
echo "To download the optional model, open Settings inside SomniLoop."

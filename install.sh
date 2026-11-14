#!/usr/bin/env bash
# ============================================================================
#  Nocthify - erzak | Linux installer (Ubuntu/Debian/Mint/Pop, Fedora, Arch/
#  Manjaro, openSUSE, ... GNOME, KDE, XFCE, Cinnamon, MATE, LXQt)
#
#  One-line install:
#    curl -fsSL https://raw.githubusercontent.com/AkbarLingga/Nocthify-by-erzak/main/install.sh | bash
# ============================================================================
set -e

# >>> Change this to your GitHub "user/repo" after you create the repository <<<
REPO="AkbarLingga/Nocthify-by-erzak"
BRANCH="main"

ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nocthify"
APP="$ROOT/app"
VENV="$ROOT/venv"
BIN="$HOME/.local/bin"

say()  { printf "  \033[36m>\033[0m  %s\n" "$*"; }
ok()   { printf "  \033[32mOK\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m  %s\n" "$*"; }

echo
echo "   Nocthify - erzak"
echo "   Dynamic Island + Control Center + Dock"
echo

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

# ------------------------------------------------------- system packages ---
# Distro PyQt5 shares the system Qt libraries -> smaller install, less RAM.
install_pkgs() {
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -qq || true
    $SUDO apt-get install -y -qq python3 python3-venv python3-pyqt5 python3-pyqt5.qtsvg \
      python3-psutil wmctrl x11-utils xdotool playerctl brightnessctl git >/dev/null || return 1
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y -q python3 python3-qt5 python3-psutil wmctrl xprop xdotool playerctl \
      brightnessctl git || return 1
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -S --needed --noconfirm python python-pyqt5 python-psutil wmctrl xorg-xprop \
      xdotool playerctl brightnessctl git >/dev/null || return 1
  elif command -v zypper >/dev/null 2>&1; then
    $SUDO zypper -n -q install python3 python3-qt5 python3-psutil wmctrl xprop xdotool playerctl \
      brightnessctl git || return 1
  else
    return 1
  fi
}

if [ -n "$SUDO" ] || [ "$(id -u)" -eq 0 ]; then
  say "Installing system packages (PyQt5, wmctrl, playerctl, brightnessctl)..."
  install_pkgs || warn "Could not install system packages automatically - falling back to pip."
else
  warn "No sudo: skipping system packages (window list / media / brightness may be limited)."
fi

PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "Python 3.8+ is required. Install python3 and run again."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || {
  echo "Python 3.8+ is required (found $("$PY" --version))."; exit 1; }
ok "Python: $PY"

# ------------------------------------------------------------- app files ---
mkdir -p "$ROOT" "$BIN"
if [ -x "$VENV/bin/python" ] && [ -f "$APP/run.pyw" ]; then
  "$VENV/bin/python" "$APP/run.pyw" --quit >/dev/null 2>&1 || true
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [ -n "$HERE" ] && [ -f "$HERE/nocthify/app.py" ]; then
  say "Installing from local folder $HERE"
  rm -rf "$APP"; mkdir -p "$APP"
  cp -r "$HERE/nocthify" "$HERE/run.pyw" "$HERE/requirements.txt" "$APP/"
  cp "$HERE/README.md" "$HERE/LICENSE" "$HERE/uninstall.sh" "$APP/" 2>/dev/null || true
elif command -v git >/dev/null 2>&1; then
  if [ -d "$APP/.git" ]; then
    say "Updating Nocthify..."; git -C "$APP" pull --ff-only -q
  else
    say "Downloading Nocthify..."; rm -rf "$APP"
    git clone -q --depth 1 -b "$BRANCH" "https://github.com/$REPO.git" "$APP"
  fi
else
  say "Downloading Nocthify..."
  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" | tar -xz -C "$tmp"
  rm -rf "$APP"; mv "$tmp"/* "$APP"; rm -rf "$tmp"
fi
ok "Files: $APP"

# --------------------------------------------------------- environment ---
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating environment..."
  "$PY" -m venv --system-site-packages "$VENV"
fi
if ! "$VENV/bin/python" -c "import PyQt5.QtSvg, PyQt5.QtWidgets, psutil" 2>/dev/null; then
  say "Installing PyQt5 + psutil with pip..."
  "$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
  "$VENV/bin/python" -m pip install -q -r "$APP/requirements.txt"
fi
ok "Dependencies ready"

# ------------------------------------------------------------ launchers ---
cat > "$BIN/nocthify" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$APP/run.pyw" "\$@"
EOF
chmod +x "$BIN/nocthify"

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/nocthify.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Nocthify
Comment=Dynamic Island, Control Center and Dock
Exec=$BIN/nocthify
Icon=preferences-desktop
Terminal=false
Categories=Utility;
EOF
cat > "$APPS/nocthify-settings.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Nocthify Settings
Exec=$BIN/nocthify --settings
Icon=preferences-desktop
Terminal=false
Categories=Settings;
EOF
ok "Menu entries created  (command: nocthify)"

say "Starting Nocthify..."
nohup "$BIN/nocthify" >/dev/null 2>&1 &
echo
echo "   Done! Hover the island at the top of the screen, right-click the Dock for options."
echo "   Tip: bind 'nocthify --launcher' and 'nocthify --control-center' to keys in your"
echo "        desktop's keyboard settings for Spotlight / Control Center shortcuts."
echo

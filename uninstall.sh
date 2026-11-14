#!/usr/bin/env bash
# Nocthify - erzak | Linux uninstaller
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nocthify"
[ -x "$ROOT/venv/bin/python" ] && "$ROOT/venv/bin/python" "$ROOT/app/run.pyw" --quit >/dev/null 2>&1
rm -rf "$ROOT" "$HOME/.local/bin/nocthify" \
  "${XDG_DATA_HOME:-$HOME/.local/share}/applications/nocthify.desktop" \
  "${XDG_DATA_HOME:-$HOME/.local/share}/applications/nocthify-settings.desktop" \
  "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/nocthify.desktop"
echo "Nocthify removed. Settings are kept in ~/.config/nocthify (delete it to remove them too)."

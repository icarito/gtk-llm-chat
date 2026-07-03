#!/bin/bash
# install-dev.sh - integra gtk-llm-chat al escritorio desde un checkout
# en desarrollo (venv local, sin empaquetar).
#
# Instala:
#   - symlink en ~/.local/bin/gtk-llm-chat -> .venv/bin/gtk-llm-chat
#   - el .desktop (Exec apunta al symlink, así sobrevive a recrear el venv)
#   - los íconos de la app en ~/.local/share/icons/hicolor/
#
# Uso: desktop/install-dev.sh [--uninstall]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_BIN="$PROJECT_ROOT/.venv/bin/gtk-llm-chat"
BIN_DIR="$HOME/.local/bin"
BIN_LINK="$BIN_DIR/gtk-llm-chat"
APPS_DIR="$HOME/.local/share/applications"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
DESKTOP_SRC="$PROJECT_ROOT/desktop/org.fuentelibre.gtk_llm_Chat.desktop"
DESKTOP_DST="$APPS_DIR/org.fuentelibre.gtk_llm_Chat.desktop"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$BIN_LINK" "$DESKTOP_DST"
    rm -f "$ICON_THEME_DIR/256x256/apps/org.fuentelibre.gtk_llm_Chat.png"
    rm -f "$ICON_THEME_DIR/symbolic/apps/org.fuentelibre.gtk_llm_Chat-symbolic.svg"
    gtk-update-icon-cache -f -t "$ICON_THEME_DIR" 2>/dev/null || true
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
    echo "Desinstalado."
    exit 0
fi

if [ ! -x "$VENV_BIN" ]; then
    echo "No se encontró $VENV_BIN — crea el venv primero (ver docs/development-guide.md)." >&2
    exit 1
fi

mkdir -p "$BIN_DIR" "$APPS_DIR" \
    "$ICON_THEME_DIR/256x256/apps" "$ICON_THEME_DIR/symbolic/apps"

ln -sf "$VENV_BIN" "$BIN_LINK"

cp "$PROJECT_ROOT/gtk_llm_chat/hicolor/256x256/apps/org.fuentelibre.gtk_llm_Chat.png" \
    "$ICON_THEME_DIR/256x256/apps/"
cp "$PROJECT_ROOT/gtk_llm_chat/hicolor/symbolic/apps/org.fuentelibre.gtk_llm_Chat-symbolic.svg" \
    "$ICON_THEME_DIR/symbolic/apps/"

# Exec apunta al symlink (estable), no al binario del venv directamente
sed "s|^Exec=gtk-llm-chat|Exec=$BIN_LINK|" "$DESKTOP_SRC" > "$DESKTOP_DST"

gtk-update-icon-cache -f -t "$ICON_THEME_DIR" 2>/dev/null || true
update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo "Instalado:"
echo "  comando:  $BIN_LINK -> $VENV_BIN"
echo "  launcher: $DESKTOP_DST"
echo "  ícono:    $ICON_THEME_DIR/{256x256,symbolic}/apps/"
echo ""
echo "Puede que necesites cerrar sesión o reiniciar el shell para que"
echo "el launcher de GNOME lo muestre inmediatamente."

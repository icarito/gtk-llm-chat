#!/bin/bash
# macos/bootstrap.sh for gtk-llm-chat
# Add any macOS-specific dependency installation here

set -e

# Instala Homebrew si no está instalado
if ! command -v brew >/dev/null 2>&1; then
    echo "Instalando Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

echo "Instalando dependencias de sistema..."
brew update
brew install gtk+4 adwaita-icon-theme cairo pango gobject-introspection glib pkg-config

echo "Instalando dependencias Python..."
python3 -m pip install pycairo PyGObject Pillow

echo "Dependencias instaladas."

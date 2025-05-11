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
brew install gtk+3 adwaita-icon-theme

echo "Instalando dependencias Python..."
python3 -m pip install --upgrade pip
python3 -m pip install pycairo PyGObject Pillow

echo "Dependencias instaladas."

# Ad-hoc signing (opcional, para apps tipo bundle)
# if [ -d "dist" ]; then
#    for app in dist/*.app; do
#        if [ -d "$app" ]; then
#            echo "Firmando $app con ad-hoc..."
#            codesign --sign - --force --deep "$app"
#        fi
#    done
#fi

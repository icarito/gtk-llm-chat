#!/bin/bash
# Script para depurar problemas de iconos en el Flatpak

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Herramienta de diagnóstico de iconos para GTK LLM Chat ===${NC}"

# Verificar si estamos dentro de un Flatpak
if [[ -f "/.flatpak-info" ]]; then
    echo -e "${GREEN}✓ Ejecutando dentro de un Flatpak${NC}"
    FLATPAK_ID=$(grep "app-id=" "/.flatpak-info" | cut -d= -f2)
    echo -e "${GREEN}  ID de aplicación: $FLATPAK_ID${NC}"
else
    echo -e "${YELLOW}⚠ No está ejecutando dentro de un Flatpak${NC}"
fi

# Verificar variables de entorno GTK
echo -e "\n${BLUE}Variables de entorno GTK:${NC}"
echo -e "${GREEN}GTK_THEME=${GTK_THEME}${NC}"
echo -e "${GREEN}GTK_THEME_VARIANT=${GTK_THEME_VARIANT}${NC}"
echo -e "${GREEN}ICON_THEME=${ICON_THEME}${NC}"
echo -e "${GREEN}LLM_USER_PATH=${LLM_USER_PATH}${NC}"

# Verificar directorios de iconos
echo -e "\n${BLUE}Verificando directorios de iconos:${NC}"
icon_dirs=(
    "/app/share/icons/hicolor/symbolic/apps"
    "/app/share/icons/hicolor/scalable/apps"
    "/app/share/icons/hicolor/48x48/apps"
    "/app/gtk_llm_chat/hicolor/symbolic/apps"
    "/app/gtk_llm_chat/hicolor/scalable/apps" 
    "/app/gtk_llm_chat/hicolor/48x48/apps"
)

for dir in "${icon_dirs[@]}"; do
    if [[ -d "$dir" ]]; then
        echo -e "${GREEN}✓ $dir${NC}"
        ls -l "$dir" | grep "org.fuentelibre" | while read -r line; do
            echo "    $line"
        done
    else
        echo -e "${RED}✗ $dir (no existe)${NC}"
    fi
done

# Verificar si el icono simbólico es válido
echo -e "\n${BLUE}Verificando validez del icono simbólico:${NC}"
icon_symbolic="/app/share/icons/hicolor/symbolic/apps/org.fuentelibre.gtk_llm_Chat-symbolic.svg"
if [[ -f "$icon_symbolic" ]]; then
    echo -e "${GREEN}✓ El icono simbólico existe${NC}"
    if grep -q "currentColor" "$icon_symbolic"; then
        echo -e "${GREEN}✓ El icono contiene 'currentColor' (SVG simbólico correcto)${NC}"
    else
        echo -e "${YELLOW}⚠ El icono NO contiene 'currentColor' (podría no ser un SVG simbólico adecuado)${NC}"
    fi
else
    echo -e "${RED}✗ No se encontró icono simbólico en $icon_symbolic${NC}"
fi

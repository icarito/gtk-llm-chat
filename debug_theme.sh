#!/bin/bash
# Script para diagnosticar problemas de tema en Flatpak

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Diagnóstico de Temas para GTK LLM Chat (Flatpak) ===${NC}"

# Verificar si estamos dentro de un Flatpak
if [[ -f "/.flatpak-info" ]]; then
    echo -e "${GREEN}✓ Ejecutando dentro de un Flatpak${NC}"
    FLATPAK_ID=$(grep "app-id=" "/.flatpak-info" | cut -d= -f2)
    echo -e "${GREEN}  ID de aplicación: $FLATPAK_ID${NC}"
else
    echo -e "${YELLOW}⚠ No está ejecutando dentro de un Flatpak${NC}"
    echo -e "Execute este script con:"
    echo -e "  flatpak run --command=sh org.fuentelibre.gtk_llm_Chat -c \"/app/bin/debug_theme.sh\""
    exit 1
fi

# Verificar variables de entorno GTK
echo -e "\n${BLUE}Variables de entorno GTK:${NC}"
echo -e "${GREEN}GTK_THEME=${GTK_THEME}${NC}"
echo -e "${GREEN}GTK_USE_PORTAL=${GTK_USE_PORTAL}${NC}"
echo -e "${GREEN}ADW_DISABLE_PORTAL=${ADW_DISABLE_PORTAL}${NC}"
echo -e "${GREEN}ICON_THEME=${ICON_THEME}${NC}"
echo -e "${GREEN}LLM_USER_PATH=${LLM_USER_PATH}${NC}"

# Verificar si libadwaita está instalada
echo -e "\n${BLUE}Verificando libadwaita:${NC}"
if ldconfig -p 2>/dev/null | grep -q "libadwaita"; then
    echo -e "${GREEN}✓ libadwaita instalada${NC}"
    ldconfig -p | grep "libadwaita" | while read -r line; do
        echo "    $line"
    done
elif [ -f "/app/lib/libadwaita-1.so" ]; then
    echo -e "${GREEN}✓ libadwaita encontrada en /app/lib${NC}"
else
    echo -e "${RED}✗ No se encontró libadwaita${NC}"
fi

# Verificar archivos de configuración GTK
echo -e "\n${BLUE}Archivos de configuración GTK:${NC}"
gtk_config_files=(
    "/app/etc/gtk-3.0/settings.ini"
    "/app/etc/gtk-4.0/settings.ini"
    "/app/share/gtk-3.0/settings.ini"
    "/app/share/gtk-4.0/settings.ini"
    "$HOME/.config/gtk-3.0/settings.ini"
    "$HOME/.config/gtk-4.0/settings.ini"
)

for file in "${gtk_config_files[@]}"; do
    if [[ -f "$file" ]]; then
        echo -e "${GREEN}✓ $file${NC}"
        echo "    Contenido:"
        cat "$file" | while read -r line; do
            echo "    $line"
        done
    else
        echo -e "${YELLOW}⚠ $file (no existe)${NC}"
    fi
done

# Verificar temas instalados
echo -e "\n${BLUE}Temas GTK instalados:${NC}"
theme_dirs=(
    "/app/share/themes"
    "/usr/share/themes"
    "$HOME/.themes"
)

for dir in "${theme_dirs[@]}"; do
    if [[ -d "$dir" ]]; then
        echo -e "${GREEN}✓ $dir${NC}"
        ls -la "$dir" | grep -v "^total" | while read -r line; do
            echo "    $line"
        done
    else
        echo -e "${YELLOW}⚠ $dir (no accesible)${NC}"
    fi
done

echo -e "\n${BLUE}Consejos para solucionar problemas de tema:${NC}"
echo "1. Instale el tema Adwaita con: flatpak install org.gtk.Gtk3theme.Adwaita"
echo "2. Instale el tema Adwaita-dark con: flatpak install org.gtk.Gtk3theme.Adwaita-dark"
echo "3. Use --env=GTK_THEME=Adwaita:dark al ejecutar la aplicación"
echo "4. Asegúrese de tener acceso a los directorios de temas"
echo "5. Para libadwaita, asegúrese de que GTK_USE_PORTAL=1 y ADW_DISABLE_PORTAL=0"

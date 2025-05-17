#!/usr/bin/env bash
#
# appimagetool-wrap.sh
# Envuelto para limpiar libssl interno y generar AppRun antes de invocar al real appimagetool

# 1) rutas
APPDIR="/home/runner/work/gtk-llm-chat/gtk-llm-chat/dist"
REAL_TOOL="/home/runner/work/gtk-llm-chat/gtk-llm-chat/venv/lib/python3.10/site-packages/pydeployment/linux/appimagetool/appimagetool-x86_64.AppImage"   # o donde esté instalado tu appimagetool

# 2) eliminar OpenSSL interno de PyInstaller
rm -f "$APPDIR"/_internal/libssl.so*  "$APPDIR"/_internal/libcrypto.so*

# 3) escribir AppRun que prioriza libs del sistema
cat > "$APPDIR"/AppRun << 'EOF'
#!/bin/bash

# Obtener la ruta absoluta al directorio donde se está ejecutando AppRun
# Esto es crucial para que las rutas internas funcionen correctamente
APPDIR=$(dirname "$(readlink -f "$0")")

# Configurar LD_LIBRARY_PATH para que encuentre las bibliotecas .so empaquetadas
# (Es probable que ya tengas una línea similar, PyInstaller a menudo la gestiona)
export LD_LIBRARY_PATH="${APPDIR}/_internal:${LD_LIBRARY_PATH}" # Ajusta si tus .so están en otro subdirectorio de _internal

# >>> AÑADE O MODIFICA ESTA LÍNEA CRUCIAL <<<
# Configurar GI_TYPELIB_PATH para apuntar a los archivos .typelib empaquetados
export GI_TYPELIB_PATH="${APPDIR}/_internal/gi_typelibs:${GI_TYPELIB_PATH}"

# Otras variables de entorno importantes que podrías necesitar:
# Para que encuentre esquemas GSettings, .desktop files, iconos, etc.
# Tu .desktop está en APPDIR/usr/share/applications/
# Tus iconos de app están en APPDIR/_internal/gtk_llm_chat/hicolor/
export XDG_DATA_DIRS="${APPDIR}/usr/share:${APPDIR}/_internal/share:${APPDIR}/_internal/gtk_llm_chat:${XDG_DATA_DIRS}"

# Si empaquetas esquemas GSettings (recomendado, como en la versión de Ubuntu 24):
# export GSETTINGS_SCHEMA_DIR="${APPDIR}/_internal/share/glib-2.0/schemas"

# Para traducciones (si están en APPDIR/_internal/po y tu dominio es "gtk-llm-chat")
export TEXTDOMAINDIR="${APPDIR}/_internal/po"
export TEXTDOMAIN="gtk-llm-chat" # Reemplaza con tu text domain real

# Ejecutar el binario principal de tu aplicación (el que creó PyInstaller)
# Asegúrate de que el nombre y la ruta del ejecutable sean correctos.
# Si PyInstaller creó "chat_application" y está en _internal:
# ... (definición de APPDIR y exportaciones de LD_LIBRARY_PATH) ...

export GI_TYPELIB_PATH="${APPDIR}/_internal/gi_typelibs:${GI_TYPELIB_PATH}"
export XDG_DATA_DIRS="${APPDIR}/usr/share:${APPDIR}/_internal/share:${APPDIR}/_internal/gtk_llm_chat:${XDG_DATA_DIRS}"
# ... (otras exportaciones) ...

# --- Debugging lines ---
echo "--- AppRun Debug ---" >&2
echo "APPDIR is: ${APPDIR}" >&2
echo "GI_TYPELIB_PATH is: ${GI_TYPELIB_PATH}" >&2
echo "Contents of GI_TYPELIB_PATH target:" >&2
ls -l "${APPDIR}/_internal/gi_typelibs/" >&2
echo "Python path:" >&2
"${APPDIR}/gtk-llm-chat" -c "import sys; print(sys.path)" >&2 # Asumiendo que gtk-llm-chat es el ejecutable de Python
echo "--- End AppRun Debug ---" >&2
# --- End Debugging lines ---

exec "${APPDIR}/gtk-llm-chat" "$@"
EOF
chmod +x "$APPDIR"/AppRun

# 4) invoca al appimagetool “real”
exec "$REAL_TOOL" "$@"


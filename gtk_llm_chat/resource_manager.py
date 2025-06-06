"""
resource_manager.py - Gestor centralizado de recursos para GTK LLM Chat

Maneja rutas de imágenes, iconos y otros recursos de forma consistente
tanto en entornos de desarrollo como congelados (PyInstaller).
"""

import os
import sys
from typing import Optional
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, GdkPixbuf, Gio, Gdk
from .debug_utils import debug_print


class ResourceManager:
    """Gestor centralizado de recursos para la aplicación."""
    
    def __init__(self):
        self._is_frozen = getattr(sys, 'frozen', False)
        # self._base_path se usa para desarrollo y PyInstaller.
        # Para Flatpak, la base de recursos principal es /app.
        if self._is_frozen and hasattr(sys, '_MEIPASS'): # PyInstaller
            self._base_path = sys._MEIPASS
        elif not self._is_frozen: # Desarrollo
            self._base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else: # Frozen, pero no PyInstaller (podría ser Flatpak si no se maneja explícitamente o Nuitka, etc.)
            self._base_path = os.path.dirname(sys.executable)
            
        self._icon_theme_configured = False
        
    def _get_base_path(self) -> str:
        """Obtiene la ruta base de la aplicación según el entorno."""
        # Esta función ahora es más simple, ya que la lógica principal está en __init__
        # y la detección de Flatpak se hace donde se necesita.
        is_flatpak_env = os.environ.get('FLATPAK_ID') or os.path.exists('/.flatpak-info')
        if is_flatpak_env:
            return '/app'
        return self._base_path
    
    def get_image_path(self, relative_path: str) -> Optional[str]:
        """
        Obtiene la ruta completa de una imagen.
        
        Args:
            relative_path: Ruta relativa desde la base del proyecto
            
        Returns:
            Ruta completa al archivo de imagen o None si no existe
        """
        current_search_base = self._get_base_path() # Usa la ruta base correcta (ej. /app para flatpak)

        # Si la ruta relativa ya es absoluta (ej. /app/share/...), úsala directamente.
        if os.path.isabs(relative_path) and os.path.exists(relative_path):
            return relative_path

        possible_paths = []
        
        # Ruta directa desde la base actual
        possible_paths.append(os.path.join(current_search_base, relative_path))

        if self._is_frozen and not (os.environ.get('FLATPAK_ID') or os.path.exists('/.flatpak-info')): # PyInstaller
            # Lógica específica de PyInstaller si es necesario, por ejemplo, si los recursos están anidados
            if not os.path.isabs(relative_path) and not relative_path.startswith("gtk_llm_chat/"):
                 possible_paths.append(os.path.join(current_search_base, "gtk_llm_chat", "hicolor", "48x48", "apps", relative_path))
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
                
        debug_print(f"Warning: Resource not found: {relative_path}")
        debug_print(f"Searched in: {possible_paths} (current_search_base: {current_search_base})")
        return None
    
    def get_icon_pixbuf(self, icon_path: str, size: int = 64) -> Optional[GdkPixbuf.Pixbuf]:
        """
        Carga un icono como GdkPixbuf con el tamaño especificado.
        
        Args:
            icon_path: Ruta relativa al icono
            size: Tamaño del icono en pixels
            
        Returns:
            GdkPixbuf.Pixbuf o None si no se puede cargar
        """
        full_path = self.get_image_path(icon_path)
        if not full_path:
            return None
            
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(
                full_path, size, size, True
            )
        except Exception as e:
            debug_print(f"Error loading icon {full_path}: {e}")
            return None
    
    def setup_icon_theme(self):
        """Configura el tema de iconos para incluir los iconos personalizados."""
        if self._icon_theme_configured:
            return

        if not Gtk.is_initialized():
            debug_print("[FAIL] GTK not initialized, skipping icon theme setup")
            return

        try:
            display = Gdk.Display.get_default()
            if not display:
                debug_print("[FAIL] No default display available")
                return

            icon_theme = Gtk.IconTheme.get_for_display(display)
            
            is_flatpak_env = os.environ.get('FLATPAK_ID') or os.path.exists('/.flatpak-info')

            if is_flatpak_env:
                # En Flatpak, los iconos están en /app/share/icons/.
                # Gtk.IconTheme debería encontrarlos automáticamente debido a XDG_DATA_DIRS
                # y la caché de iconos actualizada.
                # Añadir /app/share/icons explícitamente es una medida de seguridad.
                flatpak_icon_share_dir = "/app/share/icons"
                if os.path.exists(flatpak_icon_share_dir):
                    icon_theme.add_search_path(flatpak_icon_share_dir)
                    debug_print(f"[OK] Added Flatpak icon search path: {flatpak_icon_share_dir}")
                else:
                    debug_print(f"[WARN] Flatpak icon share dir not found: {flatpak_icon_share_dir}")
            
            elif self._is_frozen: # PyInstaller (no Flatpak)
                # self._base_path es sys._MEIPASS para PyInstaller
                # Asumimos que los iconos están en una carpeta 'hicolor' relativa a 'gtk_llm_chat' dentro de MEIPASS
                pyinstaller_icon_hicolor_path = os.path.join(self._base_path, "gtk_llm_chat", "hicolor")
                if os.path.exists(pyinstaller_icon_hicolor_path):
                    icon_theme.add_search_path(pyinstaller_icon_hicolor_path) # Añadir el directorio hicolor
                    debug_print(f"[OK] Added PyInstaller hicolor search path: {pyinstaller_icon_hicolor_path}")
                else:
                    debug_print(f"[WARN] PyInstaller hicolor path not found: {pyinstaller_icon_hicolor_path}")
                # Considerar también una estructura de tema completo si existe
                custom_theme_dir = os.path.join(self._base_path, "gtk_llm_chat", "my_custom_theme")
                if os.path.exists(os.path.join(custom_theme_dir, "index.theme")):
                    icon_theme.add_search_path(custom_theme_dir)
                    debug_print(f"[OK] Added custom theme path for PyInstaller: {custom_theme_dir}")

            else: # Desarrollo
                # self._base_path es la raíz del proyecto
                dev_icon_hicolor_path = os.path.join(self._base_path, "gtk_llm_chat", "hicolor")
                if os.path.exists(dev_icon_hicolor_path):
                    icon_theme.add_search_path(dev_icon_hicolor_path) # Añadir el directorio hicolor
                    debug_print(f"[OK] Added development hicolor search path: {dev_icon_hicolor_path}")
                else:
                    debug_print(f"[WARN] Development hicolor path not found: {dev_icon_hicolor_path}")
            
            self._icon_theme_configured = True
            debug_print("[OK] Icon theme configured successfully")

        except Exception as e:
            debug_print(f"[FAIL] Error configuring icon theme: {e}")
    
    def create_image_widget(self, image_path: str, size: int = -1) -> Gtk.Image:
        """
        Crea un widget Gtk.Image desde una ruta de imagen.
        
        Args:
            image_path: Ruta relativa a la imagen
            size: Tamaño del icono (-1 para tamaño original)
            
        Returns:
            Widget Gtk.Image
        """
        full_path = self.get_image_path(image_path)
        
        if full_path and os.path.exists(full_path):
            if size > 0:
                pixbuf = self.get_icon_pixbuf(image_path, size)
                if pixbuf:
                    image = Gtk.Image.new_from_pixbuf(pixbuf)
                else:
                    image = Gtk.Image.new_from_icon_name("image-missing")
            else:
                image = Gtk.Image.new_from_file(full_path)
        else:
            # Fallback a icono del sistema
            image = Gtk.Image.new_from_icon_name("image-missing")
            print(f"Using fallback icon for: {image_path}")
        
        return image
    
    def create_icon_widget(self, icon_name: str, size: int = 48) -> Gtk.Image:
        """
        Crea un widget Gtk.Image desde un nombre de icono.
        
        Args:
            icon_name: Nombre del icono (ej: "org.fuentelibre.gtk_llm_Chat")
            size: Tamaño del icono
            
        Returns:
            Widget Gtk.Image
        """
        self.setup_icon_theme()
        
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(size)
        
        # Verificar si el icono se cargó correctamente por el tema
        try:
            display = Gdk.Display.get_default()
            if display:
                icon_theme = Gtk.IconTheme.get_for_display(display)
                if icon_theme.has_icon(icon_name):
                    debug_print(f"Icon '{icon_name}' (size {size}) found by Gtk.IconTheme.")
                    # Opcional: obtener más información sobre el icono encontrado
                    # icon_info = icon_theme.lookup_icon(icon_name, [], size, 1, Gtk.TextDirection.NONE, None)
                    # if icon_info and icon_info.get_filename():
                    #     debug_print(f"  -> Path: {icon_info.get_filename()}")
                    # else:
                    #     debug_print(f"  -> Gtk.IconTheme found it, but no direct path from lookup_icon (normal for themed icons).")

                else:
                    debug_print(f"Icon '{icon_name}' (size {size}) NOT found by Gtk.IconTheme. Attempting fallbacks.")
                    # La lógica de fallback es compleja y puede no funcionar bien en Flatpak
                    # si las rutas no están alineadas con cómo get_image_path las resuelve.
                    # Para Flatpak, el icono debería estar en /app/share/icons/...
                    
                    current_search_base = self._get_base_path() # /app para flatpak
                    is_flatpak_env = os.environ.get('FLATPAK_ID') or os.path.exists('/.flatpak-info')

                    fallback_paths_to_try = []
                    if icon_name.endswith('-symbolic'):
                        if is_flatpak_env:
                            fallback_paths_to_try.append(f"share/icons/hicolor/symbolic/apps/{icon_name}.svg")
                        else: # Desarrollo o PyInstaller
                            fallback_paths_to_try.append(f"gtk_llm_chat/hicolor/symbolic/apps/{icon_name}.svg")
                    else: # Iconos normales
                        if is_flatpak_env:
                            # Estas rutas son relativas a /app si get_image_path usa current_search_base = /app
                            fallback_paths_to_try.extend([
                                f"share/icons/hicolor/256x256/apps/{icon_name}.png",
                                f"share/icons/hicolor/scalable/apps/{icon_name}.svg",
                                f"share/icons/hicolor/48x48/apps/{icon_name}.png",
                            ])
                        else: # Desarrollo o PyInstaller
                             # Estas rutas son relativas a la raíz del proyecto o MEIPASS
                            fallback_paths_to_try.extend([
                                f"gtk_llm_chat/hicolor/256x256/apps/{icon_name}.png",
                                f"gtk_llm_chat/hicolor/scalable/apps/{icon_name}.svg",
                                f"gtk_llm_chat/hicolor/48x48/apps/{icon_name}.png",
                            ])

                    for fallback_path_str in fallback_paths_to_try:
                        # get_image_path construirá la ruta completa usando current_search_base
                        resolved_path = self.get_image_path(fallback_path_str)
                        if resolved_path:
                            debug_print(f"Attempting fallback for '{icon_name}' with resolved path: {resolved_path}")
                            # Usamos create_image_widget que carga desde archivo directamente
                            return self.create_image_widget(resolved_path, size) 

                    debug_print(f"Icon '{icon_name}' not found via Gtk.IconTheme or fallbacks. Using 'image-missing'.")
                    image = Gtk.Image.new_from_icon_name("image-missing") # Fallback final
                    image.set_pixel_size(size)
            else:
                debug_print(f"Icon '{icon_name}': No Gdk.Display for Gtk.IconTheme check.")
        except Exception as e:
            debug_print(f"Error during icon fallback check for '{icon_name}': {e}")
            # Si hay un error aquí, la imagen ya creada con new_from_icon_name se devuelve.
        
        return image
    
    def debug_resources(self):
        """Imprime información de debug sobre la ubicación de recursos."""
        print("=== RESOURCE MANAGER DEBUG ===")
        print(f"Frozen: {self._is_frozen}")
        print(f"Base path: {self._base_path}")
        
        if hasattr(sys, '_MEIPASS'):
            print(f"_MEIPASS: {sys._MEIPASS}")
            
        # Verificar recursos comunes
        test_resources = [
            "gtk_llm_chat/hicolor/48x48/apps/org.fuentelibre.gtk_llm_Chat.png",
            "gtk_llm_chat/hicolor",
        ]
        
        for resource in test_resources:
            path = self.get_image_path(resource)
            exists = path and os.path.exists(path)
            debug_print(f"Resource {resource}: {'[OK]' if exists else '[FAIL]'} ({path})")
        
        debug_print("=== END RESOURCE DEBUG ===")


# Instancia global del gestor de recursos
resource_manager = ResourceManager()

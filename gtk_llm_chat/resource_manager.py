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
from platform_utils import debug_print


class ResourceManager:
    """Gestor centralizado de recursos para la aplicación."""
    
    def __init__(self):
        self._is_frozen = getattr(sys, 'frozen', False)
        self._base_path = self._get_base_path()
        self._icon_theme_configured = False
        
    def _get_base_path(self) -> str:
        """Obtiene la ruta base de la aplicación según el entorno."""
        if self._is_frozen:
            # En entorno congelado, usar la ruta del ejecutable
            if hasattr(sys, '_MEIPASS'):
                return sys._MEIPASS
            else:
                return os.path.dirname(sys.executable)
        else:
            # En desarrollo, usar la ruta del módulo
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def get_image_path(self, relative_path: str) -> Optional[str]:
        """
        Obtiene la ruta completa de una imagen.
        
        Args:
            relative_path: Ruta relativa desde la base del proyecto
            
        Returns:
            Ruta completa al archivo de imagen o None si no existe
        """
        # Intentar diferentes ubicaciones posibles
        possible_paths = []
        
        if self._is_frozen:
            # En entorno congelado, los recursos pueden estar en diferentes ubicaciones
            possible_paths.extend([
                os.path.join(self._base_path, relative_path),
                os.path.join(self._base_path, "_internal", relative_path),
                os.path.join(self._base_path, "gtk_llm_chat", relative_path.replace("../", "")),
            ])
        else:
            # En desarrollo
            possible_paths.append(os.path.join(self._base_path, relative_path))
        
        # Buscar el archivo en las ubicaciones posibles
        for path in possible_paths:
            if os.path.exists(path):
                return path
                
        debug_print(f"Warning: Resource not found: {relative_path}")
        debug_print(f"Searched in: {possible_paths}")
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
            # Obtener el display por defecto
            display = Gdk.Display.get_default()
            if not display:
                debug_print("[FAIL] No default display available")
                return
                
            icon_theme = Gtk.IconTheme.get_for_display(display)
            
            # Añadir directorios de iconos personalizados
            icon_dirs = []
            
            if self._is_frozen:
                # En entorno congelado
                icon_dirs.extend([
                    os.path.join(self._base_path, "gtk_llm_chat", "hicolor"),
                    os.path.join(self._base_path, "_internal", "gtk_llm_chat", "hicolor"),
                    os.path.join(self._base_path, "hicolor"),
                ])
            else:
                # En desarrollo
                icon_dirs.append(os.path.join(self._base_path, "gtk_llm_chat", "hicolor"))
            
            # Añadir directorios que existan
            for icon_dir in icon_dirs:
                if os.path.exists(icon_dir):
                    icon_theme.add_search_path(icon_dir)
                    debug_print(f"[OK] Added icon search path: {icon_dir}")
            
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
        # Asegurar que el tema de iconos esté configurado
        self.setup_icon_theme()
        
        # Intentar cargar el icono personalizado primero
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(size)
        
        # Verificar si el icono se cargó correctamente
        try:
            display = Gdk.Display.get_default()
            if display:
                icon_theme = Gtk.IconTheme.get_for_display(display)
                
                if not icon_theme.has_icon(icon_name):
                    # Fallback: intentar cargar desde archivo
                    fallback_paths = [
                        f"windows/{icon_name}.png",
                        f"linux/{icon_name}.png", 
                        f"macos/{icon_name}.icns",
                        f"gtk_llm_chat/hicolor/scalable/apps/{icon_name}.svg",
                        f"gtk_llm_chat/hicolor/48x48/apps/{icon_name}.png",
                    ]
                    
                    for fallback_path in fallback_paths:
                        if self.get_image_path(fallback_path):
                            return self.create_image_widget(fallback_path, size)
                    
                    # Último fallback: icono genérico
                    print(f"Icon not found: {icon_name}, using application-x-executable")
                    image = Gtk.Image.new_from_icon_name("application-x-executable")
                    image.set_pixel_size(size)
        except Exception as e:
            print(f"Error checking icon availability: {e}")
        
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
            "windows/org.fuentelibre.gtk_llm_Chat.png",
            "linux/org.fuentelibre.gtk_llm_Chat.png",
            "gtk_llm_chat/hicolor",
        ]
        
        for resource in test_resources:
            path = self.get_image_path(resource)
            exists = path and os.path.exists(path)
            debug_print(f"Resource {resource}: {'[OK]' if exists else '[FAIL]'} ({path})")
        
        debug_print("=== END RESOURCE DEBUG ===")


# Instancia global del gestor de recursos
resource_manager = ResourceManager()

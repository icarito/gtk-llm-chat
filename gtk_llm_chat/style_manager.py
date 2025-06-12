"""
style_manager.py - Gestor centralizado de estilos CSS para GTK LLM Chat

Proporciona estilos consistentes y específicos por plataforma para toda la aplicación.
Carga archivos CSS externos organizados por plataforma.
"""


import os
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
from .debug_utils import debug_print


class StyleManager:
    """Gestor centralizado de estilos CSS para la aplicación."""
    
    def __init__(self):
        self._css_provider = None
        self._styles_loaded = False
        self._platform = self._detect_platform()
        self._styles_dir = os.path.join(os.path.dirname(__file__), 'styles')
        self._apply_platform_workarounds()
    
    def apply_macos_native_window_controls(self, headerbar):
        """
        Busca y activa Gtk.WindowControls existentes en la headerbar (solo macOS, sin crear nuevos).
        Llama a este método después de crear la headerbar y tras mostrar la ventana.
        """
        import sys
        if sys.platform != 'darwin':
            return False
        headerbar.set_decoration_layout('close,minimize,maximize:')
        if not hasattr(Gtk, 'WindowControls'):
            return False
        def find_window_controls(parent):
            if not parent:
                return None
            child = parent.get_first_child()
            while child:
                if hasattr(Gtk, 'WindowControls') and isinstance(child, Gtk.WindowControls):
                    return child
                found_in_child = find_window_controls(child)
                if found_in_child:
                    return found_in_child
                child = child.get_next_sibling()
            return None
        controls = find_window_controls(headerbar)
        if controls:
            controls.set_use_native_controls(True)
        return False

    def _apply_platform_workarounds(self):
        """
        Aplica workarounds de plataforma que no pueden resolverse solo con CSS.
        - Tipografía Segoe UI en Windows
        - Controles nativos en MacOS (si aplica)
        """
        try:
            if self._platform == 'windows':
                settings = Gtk.Settings.get_default()
                if settings:
                    settings.set_property('gtk-font-name', 'Segoe UI')
            elif self._platform == 'macos':
                # Workaround: usar controles nativos en headerbar si es posible
                # Esto requiere que la ventana tenga un headerbar con set_decoration_layout
                # y que los controles sean instanciados como Gtk.WindowControls
                # No se puede hacer globalmente aquí, pero se documenta para aplicar en cada ventana
                pass
        except Exception as e:
            debug_print(f"[StyleManager] Error aplicando workaround de plataforma: {e}")
        
    def _detect_platform(self) -> str:
        """Detecta la plataforma actual."""
        if sys.platform.startswith('win'):
            return 'windows'
        elif sys.platform == 'darwin':
            return 'macos'
        elif sys.platform.startswith('haiku'):
            return 'haiku'
        else:
            return 'linux'
    
    def _load_css_file(self, filename: str) -> str:
        """
        Carga el contenido de un archivo CSS.
        
        Args:
            filename: Nombre del archivo CSS a cargar
            
        Returns:
            Contenido del archivo CSS como string, vacío si hay error
        """
        try:
            css_path = os.path.join(self._styles_dir, filename)
            if os.path.exists(css_path):
                with open(css_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                debug_print(f"[StyleManager] Archivo CSS no encontrado: {css_path}")
                return ""
        except Exception as e:
            debug_print(f"[StyleManager] Error cargando CSS {filename}: {e}")
            return ""
    
    def get_base_styles(self) -> str:
        """Obtiene los estilos CSS base para toda la aplicación."""
        return self._load_css_file('base.css')
    
    def get_platform_styles(self) -> str:
        """Obtiene estilos específicos de la plataforma actual."""
        return self._load_css_file(f'{self._platform}.css')
    
    def load_styles(self):
        """Carga y aplica los estilos CSS a la aplicación."""
        if self._styles_loaded:
            return
            
        try:
            # Crear el proveedor CSS
            self._css_provider = Gtk.CssProvider()
            
            # Combinar estilos base y específicos de plataforma
            base_css = self.get_base_styles()
            platform_css = self.get_platform_styles()
            
            if not base_css and not platform_css:
                debug_print("[StyleManager] No se encontraron archivos CSS válidos")
                return
            
            css_content = base_css + "\n" + platform_css
            
            # Cargar CSS
            self._css_provider.load_from_string(css_content)
            
            # Aplicar al display por defecto
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    self._css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                debug_print(f"[OK] CSS styles loaded for platform: {self._platform}")
                debug_print(f"[StyleManager] Base CSS: {len(base_css)} chars")
                debug_print(f"[StyleManager] Platform CSS: {len(platform_css)} chars")
                self._styles_loaded = True
            else:
                debug_print("[FAIL] No default display found for CSS loading")
                
        except Exception as e:
            debug_print(f"[FAIL] Error loading CSS styles: {e}")
    
    def apply_to_widget(self, widget: Gtk.Widget, css_class: str):
        """
        Aplica una clase CSS específica a un widget.
        
        Args:
            widget: Widget GTK al que aplicar la clase
            css_class: Nombre de la clase CSS
        """
        style_context = widget.get_style_context()
        style_context.add_class(css_class)
    
    def remove_from_widget(self, widget: Gtk.Widget, css_class: str):
        """
        Remueve una clase CSS de un widget.
        
        Args:
            widget: Widget GTK del que remover la clase
            css_class: Nombre de la clase CSS
        """
        style_context = widget.get_style_context()
        style_context.remove_class(css_class)
    
    def get_platform(self) -> str:
        """Retorna la plataforma actual."""
        return self._platform
    
    def get_styles_directory(self) -> str:
        """Retorna el directorio donde se encuentran los archivos CSS."""
        return self._styles_dir
    
    def debug_styles(self):
        """Imprime información de debug sobre los estilos."""
        debug_print("=== STYLE MANAGER DEBUG ===")
        debug_print(f"Platform: {self._platform}")
        debug_print(f"Styles directory: {self._styles_dir}")
        debug_print(f"Styles loaded: {self._styles_loaded}")
        debug_print(f"CSS Provider: {self._css_provider is not None}")
        
        # Verificar archivos CSS disponibles
        debug_print("Available CSS files:")
        if os.path.exists(self._styles_dir):
            for file in os.listdir(self._styles_dir):
                if file.endswith('.css'):
                    file_path = os.path.join(self._styles_dir, file)
                    size = os.path.getsize(file_path)
                    debug_print(f"  - {file} ({size} bytes)")
        else:
            debug_print(f"  Styles directory does not exist: {self._styles_dir}")
        
        if self._css_provider:
            try:
                # Intentar obtener información del proveedor
                debug_print("CSS Provider is active")
            except Exception as e:
                debug_print(f"CSS Provider error: {e}")
        
        debug_print("=== END STYLE DEBUG ===")


# Instancia global del gestor de estilos
style_manager = StyleManager()
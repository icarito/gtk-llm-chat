"""
style_manager.py - Gestor centralizado de estilos CSS para GTK LLM Chat

Proporciona estilos consistentes y específicos por plataforma para toda la aplicación.
"""


import os
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
from .debug_utils import debug_print


class StyleManager:
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
    """Gestor centralizado de estilos CSS para la aplicación."""
    
    def __init__(self):
        self._css_provider = None
        self._styles_loaded = False
        self._platform = self._detect_platform()
        self._apply_platform_workarounds()

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
    
    def get_base_styles(self) -> str:
        """Obtiene los estilos CSS base para toda la aplicación."""
        return """
        /* === ESTILOS BASE PARA TODA LA APLICACIÓN === */
        
        /* Contenedores principales */
        .main-container {
            background-color: @theme_bg_color;
            color: @theme_fg_color;
        }
        
        /* Encabezados */
        .app-header {
            background: linear-gradient(to bottom, 
                        alpha(@theme_bg_color, 0.98), 
                        alpha(@theme_bg_color, 0.95));
            border-bottom: 1px solid alpha(@theme_fg_color, 0.1);
            padding: 12px;
        }
        
        .app-title {
            font-weight: bold;
            font-size: 1.1em;
            color: @theme_fg_color;
        }
        
        .app-subtitle {
            color: alpha(@theme_fg_color, 0.7);
            font-size: 0.9em;
        }
        
        /* Botones principales */
        .primary-button {
            background: linear-gradient(to bottom, @theme_selected_bg_color, 
                                       shade(@theme_selected_bg_color, 0.9));
            color: @theme_selected_fg_color;
            border: 1px solid shade(@theme_selected_bg_color, 0.8);
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 500;
        }
        
        .primary-button:hover {
            background: linear-gradient(to bottom, 
                                       shade(@theme_selected_bg_color, 1.1), 
                                       @theme_selected_bg_color);
        }
        
        .primary-button:active {
            background: shade(@theme_selected_bg_color, 0.9);
            border-color: shade(@theme_selected_bg_color, 0.7);
        }
        
        /* Botones secundarios */
        .secondary-button {
            background: @theme_bg_color;
            color: @theme_fg_color;
            border: 1px solid alpha(@theme_fg_color, 0.2);
            border-radius: 6px;
            padding: 8px 16px;
        }
        
        .secondary-button:hover {
            background: alpha(@theme_fg_color, 0.05);
            border-color: alpha(@theme_fg_color, 0.3);
        }
        
        /* Grupos de botones */
        .button-group {
            margin: 6px;
        }
        
        .button-group button {
            margin: 2px;
        }
        
        /* Paneles de contenido */
        .content-panel {
            background-color: @theme_base_color;
            border: 1px solid alpha(@theme_fg_color, 0.1);
            border-radius: 8px;
            padding: 16px;
            margin: 8px;
        }
        
        /* Lista de elementos */
        .item-list {
            background-color: @theme_base_color;
            border-radius: 6px;
        }
        
        .item-list row {
            padding: 8px 12px;
            border-bottom: 1px solid alpha(@theme_fg_color, 0.05);
        }
        
        .item-list row:last-child {
            border-bottom: none;
        }
        
        .item-list row:hover {
            background-color: alpha(@theme_selected_bg_color, 0.1);
        }
        
        /* Entrada de texto */
        .text-input {
            background-color: @theme_base_color;
            color: @theme_text_color;
            border: 1px solid alpha(@theme_fg_color, 0.2);
            border-radius: 6px;
            padding: 8px 12px;
        }
        
        .text-input:focus {
            border-color: @theme_selected_bg_color;
            box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.2);
        }
        
        /* Área de mensaje de chat */
        .message-container {
            margin: 8px;
            padding: 12px;
            border-radius: 8px;
        }
        
        /* Estilos de mensajes específicos */
        .message {
            padding: 8px;
        }

        .message-content {
            padding: 6px;
            min-width: 400px;
        }

        .user-message .message-content {
            background-color: @blue_3;
            border-radius: 12px 12px 0 12px;
        }

        .assistant-message .message-content {
            background-color: @card_bg_color;
            border-radius: 12px 12px 12px 0;
        }

        .timestamp {
            font-size: 0.8em;
            opacity: 0.7;
        }

        .error-message {
            background-color: alpha(@error_color, 0.1);
            border-radius: 6px;
            padding: 8px;
        }

        .error-icon {
            color: @error_color;
        }

        .error-content {
            padding: 3px;
        }

        textview {
            background: none;
            color: inherit;
            padding: 3px;
        }

        textview text {
            background: none;
        }

        .user-message textview text {
            color: white;
        }

        .user-message textview text selection {
            background-color: rgba(255,255,255,0.3);
            color: white;
        }
        
        /* Área de entrada de chat */
        .chat-input-container {
            background-color: @theme_bg_color;
            border-top: 1px solid alpha(@theme_fg_color, 0.1);
            padding: 12px;
        }
        
        .chat-input {
            background-color: @theme_base_color;
            border: 1px solid alpha(@theme_fg_color, 0.2);
            border-radius: 20px;
            padding: 12px 16px;
            font-size: 1em;
        }
        
        .chat-input:focus {
            border-color: @theme_selected_bg_color;
            box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.2);
        }
        
        /* Botón de envío */
        .send-button {
            background: @theme_selected_bg_color;
            color: @theme_selected_fg_color;
            border: none;
            border-radius: 50%;
            padding: 8px;
            margin-left: 8px;
        }
        
        .send-button:hover {
            background: shade(@theme_selected_bg_color, 1.1);
        }
        
        /* Sidebar */
        .sidebar {
            background-color: alpha(@theme_bg_color, 0.95);
            border-right: 1px solid alpha(@theme_fg_color, 0.1);
            min-width: 250px;
        }
        
        .sidebar-header {
            background-color: alpha(@theme_bg_color, 0.98);
            border-bottom: 1px solid alpha(@theme_fg_color, 0.1);
            padding: 16px;
        }
        
        /* Elementos de estado */
        .status-indicator {
            border-radius: 50%;
            min-width: 8px;
            min-height: 8px;
            margin-right: 8px;
        }
        
        .status-connected {
            background-color: #4CAF50;
        }
        
        .status-connecting {
            background-color: #FF9800;
        }
        
        .status-error {
            background-color: #F44336;
        }
        
        """
    
    def get_platform_styles(self) -> str:
        """Obtiene estilos específicos de la plataforma actual."""
        if self._platform == 'windows':
            return """
            /* === ESTILOS ESPECÍFICOS PARA WINDOWS === */
            
            /* Remover sombras y bordes redondeados que no se ven bien en Windows */
            window {
                box-shadow: none;
                margin: -12px;
                border-radius: 0px;
                padding: 6px;
            }
            .menu {
                margin: -30px;
                border-radius: 0px;
            }
            .menu > * {
                padding: 10px;
            }

            
            /* Botones más planos para Windows */
            button {
                box-shadow: none;
                border-radius: 0px;
            }

            /* Usar tipografía Segoe UI (también aplicado vía workaround en Python) */
            .main-container, body, window, * {
                font-family: 'Segoe UI', 'Trebuchet MS', Tahoma, sans-serif;
            }
            
            /* Scrollbars estilo Windows */
            scrollbar {
                background-color: alpha(@theme_fg_color, 0.1);
                border-radius: 0;
            }
            
            scrollbar slider {
                background-color: alpha(@theme_fg_color, 0.3);
                border-radius: 0;
            }
            scrollbar slider:hover {
                background-color: alpha(@theme_fg_color, 0.5);
            }
            """
        elif self._platform == 'macos':
            return """
            /* === ESTILOS ESPECÍFICOS PARA macOS === */
            
            /* Ventanas con esquinas redondeadas y ajuste de ángulo */
            window {
                border-radius: 10px;
            }
            
            /* Scrollbars estilo macOS */
            scrollbar {
                background-color: transparent;
                border-radius: 4px;
            }
            
            scrollbar slider {
                background-color: alpha(@theme_fg_color, 0.4);
                border-radius: 4px;
                min-width: 8px;
                min-height: 8px;
            }
            
            scrollbar slider:hover {
                background-color: alpha(@theme_fg_color, 0.6);
            }
            """
        elif self._platform == 'haiku':
            return """
            /* === ESTILOS ESPECÍFICOS PARA Haiku === */
            window {
                box-shadow: none;
                margin: -12px;
                border-radius: 0px;
                padding: 6px;
            }
            .menu {
                margin: -30px;
                border-radius: 0px;
            }
            .menu > * {
                padding: 10px;
            }

headerbar windowcontrols {
    border-spacing: 6px; }
    headerbar windowcontrols.start:not(.empty):dir(ltr), headerbar windowcontrols.end:not(.empty):dir(rtl) {
      margin-right: 7px; }
    headerbar windowcontrols.start:not(.empty):dir(rtl), headerbar windowcontrols.end:not(.empty):dir(ltr) {
      margin-left: 7px; }
    headerbar windowcontrols button.close {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none;
      background-image: url("assets/close-focused.png"); }
      headerbar windowcontrols button.close:backdrop {
        background-image: url("assets/close-unfocused.png"); }
    headerbar windowcontrols button.maximize {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none;
      background-image: url("assets/maximize-focused.png"); }
      headerbar windowcontrols button.maximize:backdrop {
        background-image: url("assets/maximize-unfocused.png"); }
    headerbar windowcontrols button.minimize {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none;
      background-image: url("assets/minimize-focused.png"); }
      headerbar windowcontrols button.minimize:backdrop {
        background-image: url("assets/minimize-unfocused.png"); }
    .maximized headerbar windowcontrols button.maximize {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none; }


headerbar {
  min-height: 30px;
  padding: 4px 8px;
  color: #000000;
  background-color: #FFC000;
  background-image: linear-gradient(to bottom, #ffe699, #FFC000);
  box-shadow: inset 1px 1px #ffd966, inset -1px -1px #FFC000; }
  headerbar .title {
    padding-left: 12px;
    padding-right: 12px;
    font-weight: bold; }
  headerbar .subtitle {
    font-size: smaller;
    padding-left: 12px;
    padding-right: 12px;
    color: alpha(currentColor, 0.7); }
  headerbar:backdrop {
    color: #000000;
    background-color: #D7D7D7;
    background-image: linear-gradient(to bottom, #e2e2e2, #D7D7D7);
    box-shadow: inset 1px 1px #f2f2f2, inset -1px -1px #b7b7b7; }
  .tiled headerbar, .tiled headerbar:backdrop, .maximized headerbar, .maximized headerbar:backdrop {
    border-radius: 0; }
  headerbar.titlebar, .titlebar headerbar {
    border-radius: 0px 0px 0px 0px; }
  separator:first-child + headerbar, separator:first-child + headerbar:backdrop, headerbar:first-child, headerbar:first-child:backdrop {
    border-top-left-radius: 0px; }
    .maximized separator:first-child + headerbar, .tiled separator:first-child + headerbar, .maximized separator:first-child + headerbar:backdrop, .tiled separator:first-child + headerbar:backdrop, .maximized headerbar:first-child, .tiled headerbar:first-child, .maximized headerbar:first-child:backdrop, .tiled headerbar:first-child:backdrop {
      border-radius: 0; }
  headerbar:last-child, headerbar:last-child:backdrop {
    border-top-right-radius: 0px; }
    .maximized headerbar:last-child, .tiled headerbar:last-child, .maximized headerbar:last-child:backdrop, .tiled headerbar:last-child:backdrop {
      border-radius: 0; }
  headerbar windowcontrols {
    border-spacing: 6px; }
    headerbar windowcontrols.start:not(.empty):dir(ltr), headerbar windowcontrols.end:not(.empty):dir(rtl) {
      margin-right: 7px; }
    headerbar windowcontrols.start:not(.empty):dir(rtl), headerbar windowcontrols.end:not(.empty):dir(ltr) {
      margin-left: 7px; }
    headerbar windowcontrols button.close {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none;
      background-image: url("assets/close-focused.png"); }
      headerbar windowcontrols button.close:backdrop {
        background-image: url("assets/close-unfocused.png"); }
    headerbar windowcontrols button.maximize {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none;
      background-image: url("assets/maximize-focused.png"); }
      headerbar windowcontrols button.maximize:backdrop {
        background-image: url("assets/maximize-unfocused.png"); }
    headerbar windowcontrols button.minimize {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none;
      background-image: url("assets/minimize-focused.png"); }
      headerbar windowcontrols button.minimize:backdrop {
        background-image: url("assets/minimize-unfocused.png"); }
    .maximized headerbar windowcontrols button.maximize {
      padding: 0px;
      min-width: 14px;
      min-height: 14px;
      border: none;
      border-radius: 0;
      color: transparent;
      background-color: transparent;
      background-size: 14px 14px;
      background-repeat: no-repeat;
      background-position: center center;
      box-shadow: none;
      -gtk-icon-shadow: none; }

            """
        else:  # Linux
            return """
            /* === ESTILOS ESPECÍFICOS PARA LINUX === */
            
            /* Usar estilos nativos de GTK en su mayoría */
            
            /* Scrollbars estilo Adwaita mejorado */
            scrollbar {
                background-color: alpha(@theme_base_color, 0.5);
                border-radius: 3px;
            }
            
            scrollbar slider {
                background-color: alpha(@theme_fg_color, 0.4);
                border-radius: 3px;
                min-width: 10px;
                min-height: 10px;
            }
            
            scrollbar slider:hover {
                background-color: alpha(@theme_fg_color, 0.6);
            }
            
            /* Botones con mejor feedback visual */
            button:hover {
                box-shadow: 0 1px 3px alpha(@theme_fg_color, 0.2);
            }
            """
    
    def load_styles(self):
        """Carga y aplica los estilos CSS a la aplicación."""
        if self._styles_loaded:
            return
            
        try:
            # Crear el proveedor CSS
            self._css_provider = Gtk.CssProvider()
            
            # Combinar estilos base y específicos de plataforma
            css_content = self.get_base_styles() + "\n" + self.get_platform_styles()
            
            # Cargar CSS
            self._css_provider.load_from_data(css_content, -1)
            
            # Aplicar al display por defecto
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    self._css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                debug_print(f"[OK] CSS styles loaded for platform: {self._platform}")
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
    
    def debug_styles(self):
        """Imprime información de debug sobre los estilos."""
        debug_print("=== STYLE MANAGER DEBUG ===")
        debug_print(f"Platform: {self._platform}")
        debug_print(f"Styles loaded: {self._styles_loaded}")
        debug_print(f"CSS Provider: {self._css_provider is not None}")
        
        if self._css_provider:
            try:
                # Intentar obtener información del proveedor
                debug_print("CSS Provider is active")
            except Exception as e:
                debug_print(f"CSS Provider error: {e}")
        
        debug_print("=== END STYLE DEBUG ===")


# Instancia global del gestor de estilos
style_manager = StyleManager()

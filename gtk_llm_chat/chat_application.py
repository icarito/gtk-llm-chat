import json
import os
import re
import signal
import sys
import subprocess
import threading

from gi import require_versions
require_versions({"Gtk": "4.0", "Adw": "1"})

from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory

_ = gettext.gettext

DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


# Reemplazar la definición de la interfaz D-Bus con XML
DBUS_INTERFACE_XML = """
<node>
  <interface name='org.fuentelibre.gtk_llm_Chat'>
    <method name='OpenConversation'>
      <arg type='s' name='cid' direction='in'/>
    </method>
  </interface>
</node>
"""

class LLMChatApplication(Adw.Application):
    """Class for a chat instance"""

    def __init__(self, config=None):
        super().__init__(
            application_id="org.fuentelibre.gtk_llm_Chat",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )

        self._shutting_down = False  # Bandera para controlar proceso de cierre
        self._window_by_cid = {}  # Mapa de CID -> ventana

        # Add signal handler
        signal.signal(signal.SIGINT, self._handle_sigint)
        self.connect('shutdown', self.on_shutdown)  # Conectar señal shutdown

        # Windows-specific adjustments
        if sys.platform == "win32":
            settings = Gtk.Settings.get_default()
            if settings:
                settings.set_property('gtk-font-name', 'Segoe UI')

        # Force dark mode until we've tested / liked light mode (issue #25)
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

    def _handle_sigint(self, signum, frame):
        """Handles SIGINT signal to close the application"""
        debug_print(_("\nClosing application..."))
        self.quit()

    def _register_dbus_interface(self):
        # Solo ejecutar en Linux
        if sys.platform != 'linux':
            return
        try:
            from gi.repository import Gio
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node_info = Gio.DBusNodeInfo.new_for_xml(DBUS_INTERFACE_XML)
            interface_info = node_info.interfaces[0]
            def method_call_handler(connection, sender, object_path, interface_name, method_name, parameters, invocation):
                if method_name == "OpenConversation":
                    try:
                        cid = parameters.unpack()[0]
                        debug_print(f"D-Bus: Recibida solicitud para abrir conversación CID: '{cid}'")
                        # Usar GLib.idle_add para manejar la llamada en el hilo principal de GTK
                        GLib.idle_add(lambda: self.OpenConversation(cid))
                        invocation.return_value(None)
                    except Exception as e:
                        debug_print(f"D-Bus: Error al procesar OpenConversation: {e}")
                        invocation.return_dbus_error("org.fuentelibre.Error.Failed", str(e))
                else:
                    invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Método desconocido")
            reg_id = connection.register_object(
                '/org/fuentelibre/gtk_llm_Chat',
                interface_info,
                method_call_handler,
                None,  # get_property_handler
                None   # set_property_handler
            )
            if reg_id > 0:
                self.dbus_registration_id = reg_id
                debug_print("Interfaz D-Bus registrada correctamente")
            else:
                debug_print("Error al registrar la interfaz D-Bus")
        except Exception as e:
            debug_print(f"Error al registrar D-Bus (solo debe ocurrir en Linux): {e}")

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Solo registrar D-Bus en Linux
        if sys.platform=='linux':
            self._register_dbus_interface()

        self.hold()  # Asegura que la aplicación no termine prematuramente

        APP_NAME = "gtk-llm-chat"
        if getattr(sys, 'frozen', False):
            base_path = os.path.join(
                    sys._MEIPASS)
        else:
            base_path = os.path.join(os.path.dirname(__file__), "..")

        LOCALE_DIR = os.path.abspath(os.path.join(base_path, 'po'))

        lang = locale.getdefaultlocale()[0]  # Ej: 'es_ES'
        if lang:
            gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
            gettext.textdomain(APP_NAME)
            lang_trans = gettext.translation(APP_NAME, LOCALE_DIR, languages=[lang], fallback=True)
            lang_trans.install()
            global _
            _ = lang_trans.gettext

        self._setup_icon()

        # Configure actions
        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self.on_rename_activate)
        self.add_action(rename_action)

        delete_action = Gio.SimpleAction.new("delete", None)
        delete_action.connect("activate", self.on_delete_activate)
        self.add_action(delete_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

    def OpenConversation(self, cid):
        """Abrir una nueva conversación dado un CID"""
        debug_print(f"D-Bus: OpenConversation recibido con CID: {cid}")
        if not cid:
            debug_print("D-Bus: CID vacío, creando nueva conversación")
            # Siempre crear una nueva ventana cuando el CID está vacío
            self.open_conversation_window({})
            return

        window = self._window_by_cid.get(cid)
        if window is None:
            # Crear y registrar una nueva ventana
            debug_print(f"D-Bus: Creando nueva ventana para CID: {cid}")
            self.open_conversation_window({'cid': cid})
        else:
            # Verificamos si la ventana es válida antes de llamar a present()
            if hasattr(window, 'present') and callable(window.present):
                debug_print(f"D-Bus: Enfocando ventana existente para CID: {cid}")
                window.present()
            else:
                debug_print(f"D-Bus: Error - ventana para CID {cid} no es válida, creando nueva")
                del self._window_by_cid[cid]
                self.open_conversation_window({'cid': cid})

    def create_chat_window(self, cid):
        """Crear una nueva ventana de chat"""
        # Implementación para crear una ventana de chat
        pass

    def on_shutdown(self, app):
        """Handles application shutdown and unregisters D-Bus."""
        self._shutting_down = True
        if hasattr(self, 'dbus_registration_id'):
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.unregister_object(self.dbus_registration_id)

    def get_application_version(self):
        """
        Gets the application version from _version.py.
        """
        try:
            from gtk_llm_chat import _version
            return _version.__version__
        except ImportError:
            debug_print(_("Error: _version.py not found"))
            return "Unknown"
        return "Unknown"

    def _setup_icon(self):
        """Configures the application icon"""
        # Set search directory
        if getattr(sys, 'frozen', False):
            base_path = os.path.join(sys._MEIPASS, 'gtk_llm_chat')
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(base_path)

    def do_command_line(self, command_line):
        """Procesa los argumentos de la línea de comandos."""
        debug_print("do_command_line invocado")

        # Extraer configuración de los argumentos
        args = command_line.get_arguments()
        debug_print(f"Argumentos recibidos: {args}")

        config = {}
        only_applet = False
        legacy_applet = False
        has_args = False  # Flag para saber si se recibieron argumentos relevantes
        
        for arg in args:
            # Skip the executable path (first argument)
            if arg == args[0] and arg.endswith(("gtk-llm-chat", "gtk-llm-chat.exe", "python", "python.exe")):
                continue
                
            has_args = True  # Se recibió al menos un argumento válido
                
            if arg.startswith("--cid="):
                config['cid'] = arg.split("=", 1)[1]
                debug_print(f"CID encontrado en argumentos: {config['cid']}")
            elif arg.startswith("--model="):
                config['model'] = arg.split("=", 1)[1]
            elif arg.startswith("--template="):
                config['template'] = arg.split("=", 1)[1]
            elif arg.startswith("--applet"):
                only_applet = True
            elif arg.startswith("--legacy-applet"):
                legacy_applet = True
            # Puedes añadir más parámetros según sea necesario

        # Guardar esta configuración para usarla
        debug_print(f"Configuración preparada: {config}")

        # Abrir ventana de conversación con la configuración extraída
        if not only_applet:
            # Si no hay argumentos relevantes y la app ya está corriendo, 
            # crear una nueva ventana vacía. Esto asegura que al invocar la app 
            # sin argumentos siempre se cree una nueva ventana.
            if not has_args and self.get_active_window():
                debug_print("Aplicación ya en ejecución sin argumentos, creando nueva ventana")
                self.open_conversation_window({})
            else:
                self.open_conversation_window(config)
                
        if legacy_applet:
            self._applet_loaded = True

        return 0

    def do_activate(self):
        """Activa la aplicación y crea una nueva ventana utilizando la configuración actual."""
        Adw.Application.do_activate(self)
        debug_print("do_activate invocado")

        self.open_conversation_window()

    def _create_new_window_with_config(self, config):
        """Crea una nueva ventana con la configuración dada."""
        debug_print(f"Creando nueva ventana con configuración: {config}")

        from chat_window import LLMChatWindow
        chat_history = ChatHistory()

        # Crear la nueva ventana con la configuración
        window = LLMChatWindow(application=self, config=config, chat_history=chat_history)
        window.set_icon_name("org.fuentelibre.gtk_llm_Chat")

        # Configurar el manejador de eventos de teclado
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        window.add_controller(key_controller)

        # Registrar la ventana por CID si existe
        if 'cid' in config and config['cid']:
            cid = config['cid']
            self._window_by_cid[cid] = window
            debug_print(f"Ventana registrada para CID: {cid}")

        # Presentar la ventana
        window.present()

        return window

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Maneja eventos de teclado a nivel de aplicación."""
        window = self.get_active_window()

        # F10: Toggle del sidebar
        if keyval == Gdk.KEY_F10:
            if window and hasattr(window, 'split_view'):
                is_visible = window.split_view.get_show_sidebar()
                window.split_view.set_show_sidebar(not is_visible)
                return True

        # F2: Renombrar conversación
        if keyval == Gdk.KEY_F2:
            if window:
                self.on_rename_activate(None, None)
                return True

        # Escape: Cerrar ventana solo si el input tiene el foco
        if keyval == Gdk.KEY_Escape:
            if window:
                # Verificar si el foco está en el input_text
                if hasattr(window, 'input_text') and window.input_text.has_focus():
                    window.close()
                    return True

        # Permitir que otros controles procesen otros eventos de teclado
        return False

    def on_rename_activate(self, action, param):
        """Renames the current conversation"""
        window = self.get_active_window()
        window.header.set_title_widget(window.title_entry)
        window.title_entry.grab_focus()

    def on_delete_activate(self, action, param):
        """Deletes the current conversation"""
        window = self.get_active_window()

        # Verificar que tenemos una ventana y acceder a su configuración
        if not window or not hasattr(window, 'config'):
            debug_print("No se puede eliminar: ventana inválida o sin configuración")
            return

        dialog = Gtk.MessageDialog(
            transient_for=window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Are you sure you want to delete the conversation?")
        )

        def on_delete_response(dialog, response):
            if response == Gtk.ResponseType.YES and hasattr(window, 'chat_history'):
                cid = window.config.get('cid')
                debug_print(f"Eliminando conversación con CID: {cid}")
                if cid:
                    window.chat_history.delete_conversation(cid)

                    # Verificar si hay más ventanas abiertas
                    other_windows = [w for w in self.get_windows() if w != window]

                    # Cerrar solo la ventana actual en lugar de toda la aplicación
                    window.close()

            dialog.destroy()

        dialog.connect("response", on_delete_response)
        dialog.present()

    def on_about_activate(self, action, param):
        """Shows the 'About' dialog"""
        about_dialog = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            # Keep "Gtk LLM Chat" as the application name
            application_name=_("Gtk LLM Chat"),
            application_icon="org.fuentelibre.gtk_llm_Chat",
            website="https://github.com/icarito/gtk_llm_chat",
            comments=_("A frontend for LLM"),
            license_type=Gtk.License.GPL_3_0,
            developer_name="Sebastian Silva",
            version=self.get_application_version(),
            developers=["Sebastian Silva <sebastian@fuentelibre.org>"],
            copyright="© 2024 Sebastian Silva"
        )
        about_dialog.present()

    def open_conversation_window(self, config=None):
        """
        Abre una ventana de conversación con la configuración dada.

        Args:
            config (dict, optional): Configuración para la ventana de conversación. 
                                    Puede incluir 'cid', 'model', etc.

        Returns:
            LLMChatWindow: La ventana creada o enfocada
        """
        # Asegurar que tenemos una configuración
        config = config or {}

        # Evitar que se abra una ventana de applet
        conversation_config = dict(config)
        if 'applet' in conversation_config:
            conversation_config.pop('applet')

        # Si hay un CID específico en la configuración
        if 'cid' in conversation_config:
            cid = conversation_config['cid']
            debug_print(f"Abriendo ventana con CID específico: {cid}")

            # Verificar si ya existe una ventana registrada para este CID
            if cid in self._window_by_cid:
                window = self._window_by_cid[cid]
                if window.is_visible():
                    debug_print(f"Se encontró ventana registrada para CID {cid}, activándola")
                    window.present()
                    return window
                else:
                    # Si la ventana existe pero no es visible, eliminarla del registro
                    debug_print(f"La ventana para CID {cid} no es visible, eliminando del registro")
                    del self._window_by_cid[cid]

            # Si no existe una ventana para este CID o no es visible, crear una nueva
            debug_print(f"Creando nueva ventana para CID: {cid}")
            return self._create_new_window_with_config(conversation_config)

        else:
            # Si no hay CID específico, crear siempre una nueva ventana de conversación
            debug_print("Creando nueva ventana sin CID específico")
            return self._create_new_window_with_config(conversation_config)


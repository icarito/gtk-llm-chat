import json
import os
import re
import signal
import sys
import subprocess
import threading
import gettext
import locale

from gi import require_versions
require_versions({"Gtk": "4.0", "Adw": "1"})

from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext
import llm

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from .db_operations import ChatHistory

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
        
        debug_print("LLMChatApplication.__init__: Verificando si se necesita configuración inicial...")
        self._needs_initial_setup = self._check_initial_setup_needed()
        debug_print(f"LLMChatApplication.__init__: _needs_initial_setup = {self._needs_initial_setup}")

        # Add signal handler
        signal.signal(signal.SIGINT, self._handle_sigint)
        self.connect('shutdown', self.on_shutdown)  # Conectar señal shutdown

        # Force dark mode
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
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node_info = Gio.DBusNodeInfo.new_for_xml(DBUS_INTERFACE_XML)
            interface_info = node_info.interfaces[0]
            
            def method_call_handler(connection, sender, object_path, interface_name, method_name, parameters, invocation):
                if method_name == "OpenConversation":
                    try:
                        cid = parameters.unpack()[0]
                        debug_print(f"D-Bus: Recibida solicitud para abrir conversación CID: '{cid}'")
                        GLib.idle_add(lambda: self.OpenConversation(cid))
                        invocation.return_value(None)
                    except Exception as e:
                        debug_print(f"D-Bus: Error al procesar OpenConversation: {e}")
                        invocation.return_dbus_error("org.fuentelibre.Error.Failed", str(e))
                else:
                    invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Método desconocido")

            self.dbus_registration_id = connection.register_object(
                "/" + self.get_application_id().replace('.', '/'),
                interface_info,
                method_call_handler,
                None, None
            )
        except Exception as e:
            debug_print(f"D-Bus: Error al registrar interfaz: {e}")

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._register_dbus_interface()

    def do_activate(self):
        # Adw.Application.do_activate(self)
        pass

    def OpenConversation(self, cid):
        """Abrir una nueva conversación dado un CID"""
        debug_print(f"D-Bus: OpenConversation recibido con CID: {cid}")
        if not cid:
            self.open_conversation_window({})
            return

        window = self._window_by_cid.get(cid)
        if window is None:
            self.open_conversation_window({'cid': cid})
        else:
            window.present()

    def on_shutdown(self, app):
        """Handles application shutdown."""
        self._shutting_down = True
        if hasattr(self, 'dbus_registration_id'):
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.unregister_object(self.dbus_registration_id)

    def do_command_line(self, command_line):
        """Procesa los argumentos de la línea de comandos."""
        args = command_line.get_arguments()
        config = {}
        has_args = False
        
        for arg in args[1:]:
            has_args = True
            if arg.startswith("--cid="):
                config['cid'] = arg.split("=", 1)[1]
            elif arg.startswith("--model="):
                config['model'] = arg.split("=", 1)[1]
            elif arg.startswith("--template="):
                config['template'] = arg.split("=", 1)[1]

        if self._needs_initial_setup:
            self._show_welcome_window()
        else:
            if not has_args and self.get_active_window():
                self.open_conversation_window({})
            else:
                self.open_conversation_window(config)

        return 0

    def _check_initial_setup_needed(self):
        try:
            import llm
            user_dir = llm.user_dir()
            db_path = os.path.join(user_dir, "logs.db")
            return not os.path.exists(db_path)
        except:
            return True

    def _show_welcome_window(self):
        from .welcome import WelcomeWindow
        def on_welcome_finished(config):
            self.open_conversation_window(config)

        win = WelcomeWindow(self, on_welcome_finished=on_welcome_finished)
        win.present()

    def open_conversation_window(self, config=None):
        config = config or {}
        cid = config.get('cid')

        if cid and cid in self._window_by_cid:
            window = self._window_by_cid[cid]
            window.present()
            return window

        window = self._create_new_window_with_config(config)
        if cid:
            self._window_by_cid[cid] = window
        return window

    def _create_new_window_with_config(self, config, backend=None):
        from .chat_window import LLMChatWindow
        window = LLMChatWindow(application=self, config=config, backend=backend)
        window.present()
        return window

    def get_application_version(self):
        return "0.1.0" # Placeholder

    def on_new_conversation_activate(self, action, param):
        self.open_conversation_window({})

    def on_about_activate(self, action, param):
        about_dialog = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            application_name=_("Gtk LLM Chat"),
            application_icon="org.fuentelibre.gtk_llm_Chat",
            version=self.get_application_version(),
            copyright="© 2024 Sebastian Silva"
        )
        about_dialog.present()

    def _ensure_xmpp_session(self, jid, password):
        session = getattr(self, '_xmpp_session', None)
        if session is None or not session.is_connected:
            from .xmpp_client import XmppSession
            session = XmppSession(jid, password)
            self._xmpp_session = session
            session.connect_to_server()
            # Conditional hold: keep app running while XMPP is connected
            self.hold()
        return session

    def open_xmpp_conversation(self, session, bare_jid):
        key = f"xmpp:{session.bare_jid}:{bare_jid}"
        existing = self._window_by_cid.get(key)
        if existing is not None:
            existing.present()
            return existing
        conversation = session.get_conversation(bare_jid)
        window = self._create_new_window_with_config({}, backend=conversation)
        self._window_by_cid[key] = window
        return window

    def _on_window_closed(self, window):
        # Remove from registration
        for key, win in list(self._window_by_cid.items()):
            if win == window:
                del self._window_by_cid[key]

        # If last window and no XMPP session connected, quit
        if len(self.get_windows()) == 0:
            session = getattr(self, '_xmpp_session', None)
            if session is None or not session.is_connected:
                self.quit()
            else:
                debug_print("Last window closed, but XMPP session is active. Staying alive.")

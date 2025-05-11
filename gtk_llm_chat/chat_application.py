import json
import os
import re
import signal
import sys
import subprocess

from gi import require_versions
require_versions({"Gtk": "4.0", "Adw": "1"})

from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory

_ = gettext.gettext

DEBUG = os.environ.get('DEBUG') or False

TRAY_PROCESS = None

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


class LLMChatApplication(Adw.Application):
    """Class for a chat instance"""

    def __init__(self):
        super().__init__(
            application_id="org.fuentelibre.gtk_llm_Chat",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )

        self.config = {}
        self.tray_process = None  # Subproceso del tray applet

        # Add signal handler
        signal.signal(signal.SIGINT, self._handle_sigint)
        self.connect('shutdown', self.on_shutdown)  # Conectar señal shutdown

        # Windows-specific adjustments
        if sys.platform == "win32":
            settings = Gtk.Settings.get_default()
            if settings:
                settings.set_property('gtk-font-name', 'Segoe UI')


    def _handle_sigint(self, signum, frame):
        """Handles SIGINT signal to close the application"""
        debug_print(_("\nClosing application..."))
        self.quit()

    def do_startup(self):
        # Llamar correctamente al método de la clase base
        Adw.Application.do_startup(self)

        # Iniciar el tray applet
        self._start_tray_applet()

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

        # Configure the application icon
        self._setup_icon()

        # Configure actions
        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self.on_rename_activate)
        self.add_action(rename_action)

        delete_action = Gio.SimpleAction.new("delete", None)  # Corrected: parameter_type should be None
        delete_action.connect("activate", self.on_delete_activate)
        self.add_action(delete_action)

        about_action = Gio.SimpleAction.new("about", None)  # Corrected: parameter_type should be None
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

    def _start_tray_applet(self):
        """Inicia el tray applet en un subproceso."""
        if self.tray_process is None:
            self.tray_process = subprocess.Popen([sys.executable, "gtk_llm_chat/tk_llm_applet.py"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _handle_tray_exit(self):
        """Maneja el cierre inesperado del tray applet."""
        if self.tray_process and self.tray_process.poll() is not None:
            print("El tray applet se cerró inesperadamente. Cerrando la aplicación principal.")
            self.quit()

    def on_shutdown(self, app):
        """Handles application shutdown and terminates the tray process."""
        if self.tray_process:
            print("Terminando proceso del applet...")
            self.tray_process.terminate()
            try:
                self.tray_process.wait(timeout=5)
                print("Proceso terminado correctamente.")
            except subprocess.TimeoutExpired:
                print("Proceso no terminó a tiempo, matando a la fuerza.")
                self.tray_process.kill()
                self.tray_process.wait()

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

    def do_activate(self):
        # Llamar correctamente al método de la clase base
        Adw.Application.do_activate(self)

        # Supervisar el tray applet
        GLib.timeout_add_seconds(1, self._handle_tray_exit)

        # Crear y mostrar la ventana principal
        from chat_window import LLMChatWindow
        self.chat_history = ChatHistory()
        window = LLMChatWindow(application=self, config=self.config, chat_history=self.chat_history)
        window.set_icon_name("org.fuentelibre.gtk_llm_Chat")
        window.present()

        # Configurar el manejador de eventos de teclado a nivel de aplicación
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        window.add_controller(key_controller)

        # Focus should be handled within LLMChatWindow if needed after init
        window.input_text.grab_focus()

        if self.config and (self.config.get('cid')
                            or self.config.get('continue_last')):
            # self.chat_history = ChatHistory() # Already initialized in __init__
            if not self.config.get('cid'):
                conversation = self.chat_history.get_last_conversation()
                if conversation:
                    self.config['cid'] = conversation['id']
                    self.config['name'] = conversation['name']
            else:
                conversation = self.chat_history.get_conversation(
                    self.config['cid'])
                if conversation:
                    self.config['name'] = conversation['name']
            name = self.config.get('name')
            if name:
                window.set_conversation_name(
                    name.strip().removeprefix("user: "))
            

            history = self.chat_history.get_conversation_history(self.config['cid'])

            # Obtener el modelo desde la tabla conversations, no desde el historial
            conversation_obj = self.chat_history.get_conversation(self.config['cid'])
            model_id = None
            if conversation_obj:
                model_id = conversation_obj.get('model')

            # Set the model in LLMClient *before* loading history
            if model_id:
                if not window.llm.set_model(model_id):
                    debug_print(f"Warning: Model {model_id} not found.")
            else:
                debug_print("Warning: No model found in conversation record.")

            # Load the history into the (now correctly configured) LLMClient
            if history:
                window.llm.load_history(history)

                # Display messages in the UI
                for entry in history:
                    window.display_message(
                        entry['prompt'],
                        sender='user',
                    )
                    window.display_message(
                        entry['response'],
                        sender='assistant',
                    )

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
        dialog = Gtk.MessageDialog(
            transient_for=self.get_active_window(),
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Are you sure you want to delete the conversation?")
        )

        def on_delete_response(dialog, response):
            if (response == Gtk.ResponseType.YES
                    and self.chat_history
                    and self.config.get('cid')):
                self.chat_history.delete_conversation(self.config['cid'])
                self.quit()
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


import gi
import json
import os
import re
import signal
import sys
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext

_ = gettext.gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__))) # No longer needed if imports are relative
from db_operations import ChatHistory
from chat_window import LLMChatWindow # Import the moved class


class LLMChatApplication(Adw.Application):
    """
    Clase para una instancia de un chat
    """

    def __init__(self):
        super().__init__(
            application_id="org.fuentelibre.gtk_llm_Chat",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )
        self.config = {}
        self.chat_history = ChatHistory() # Initialize here

        # Agregar manejador de señales
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
        print("\nCerrando aplicación...")
        self.quit()

    def do_startup(self):
        # Llamar al método padre usando do_startup
        Adw.Application.do_startup(self)

        # Inicializar gettext
        APP_NAME = "gtk-llm-chat"
        # Usar ruta absoluta para asegurar que se encuentre el directorio 'po'
        base_dir = os.path.dirname(__file__)
        LOCALE_DIR = os.path.abspath(os.path.join(base_dir, '..', 'po'))
        try:
            # Intentar establecer solo la categoría de mensajes
            locale.setlocale(locale.LC_MESSAGES, '')
        except locale.Error as e:
            print(f"Advertencia: No se pudo establecer la configuración regional: {e}")
        gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
        gettext.textdomain(APP_NAME)

        # Configurar el icono de la aplicación
        self._setup_icon()

        # Configurar acciones
        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self.on_rename_activate)
        self.add_action(rename_action)

        delete_action = Gio.SimpleAction.new("delete", None)  # Corrected: parameter_type should be None
        delete_action.connect("activate", self.on_delete_activate)
        self.add_action(delete_action)

        about_action = Gio.SimpleAction.new("about", None)  # Corrected: parameter_type should be None
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

    def get_application_version(self):
        """
        Obtiene la versión de la aplicación desde _version.py.
        """
        try:
            from gtk_llm_chat import _version
            return _version.__version__
        except ImportError:
            print("Error: _version.py no encontrado")
            return "Desconocida"
        return "Desconocida"

    def _setup_icon(self):
        """Configura el ícono de la aplicación"""
        # Establecer directorio de búsqueda
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(current_dir)

    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self, config=self.config)

        # Establecer directorio de búsqueda para el icono (ya se hace en do_startup)
        # current_dir = os.path.dirname(os.path.abspath(__file__)) # Redundant
        # icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default()) # Redundant
        # icon_theme.add_search_path(current_dir) # Redundant

        # Establecer el ícono por nombre (sin extensión .svg)
        window.set_icon_name("org.fuentelibre.gtk_llm_Chat")
        window.present()
        # window.input_text.grab_focus() # Focus should be handled within LLMChatWindow if needed after init

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
            try:
                history = self.chat_history.get_conversation_history(
                    self.config['cid'])
                # Cargar el historial en el LLMClient para mantener contexto
                if history:
                    window.llm.load_history(history)
                for entry in history:
                    if not window.title_widget.get_subtitle():
                        model_id = entry.get('model')
                        if model_id:
                            window.title_widget.set_subtitle(model_id)
                    window.display_message(
                        entry['prompt'],
                        is_user=True
                    )
                    window.display_message(
                        entry['response'],
                        is_user=False
                    )
            except ValueError as e:
                print(f"Error: {e}")
                return

    def on_rename_activate(self, action, param):
        """Renombra la conversación actual"""
        window = self.get_active_window()
        window.header.set_title_widget(window.title_entry)
        window.title_entry.grab_focus()

    def on_delete_activate(self, action, param):
        """Elimina la conversación actual"""
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
        """Muestra el diálogo 'Acerca de'"""
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

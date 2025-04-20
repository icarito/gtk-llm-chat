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

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory
from chat_window import LLMChatWindow

DEBUG = False


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
        # self.chat_history = ChatHistory() # Initialize here

        # Add signal handler
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        """Handles SIGINT signal to close the application"""
        debug_print(_("\nClosing application..."))
        self.quit()

    def do_startup(self):
        # Call the parent method using do_startup
        Adw.Application.do_startup(self)

        # Initialize gettext
        APP_NAME = "gtk-llm-chat"
        # Use absolute path to ensure 'po' directory is found
        base_dir = os.path.dirname(__file__)
        LOCALE_DIR = os.path.abspath(os.path.join(base_dir, '..', 'po'))
        try:
            # Attempt to set only the messages category
            locale.setlocale(locale.LC_MESSAGES, '')
        except locale.Error as e:
            debug_print(f"Warning: Could not set locale: {e}")
        gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
        gettext.textdomain(APP_NAME)

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
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(current_dir)

    def do_activate(self):
        # Initialize ChatHistory here
        self.chat_history = ChatHistory()
        # Create a new window for this instance, passing the existing chat_history
        window = LLMChatWindow(application=self, config=self.config, chat_history=self.chat_history)

        # Set search directory for the icon (already done in do_startup)
        # current_dir = os.path.dirname(os.path.abspath(__file__)) # Redundant
        # icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default()) # Redundant
        # icon_theme.add_search_path(current_dir) # Redundant

        # Set the icon by name
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
            
            history = self.chat_history.get_conversation_history(
                self.config['cid'])

            # Determine the model_id from the first history entry
            model_id = None
            if history:
                first_entry = history[0]
                model_id = first_entry.get('model')

            # Set the model in LLMClient *before* loading history
            if model_id:
                debug_print(f"Setting model in LLMClient to: {model_id}")  # Debug debug_print
                window.llm.set_model(model_id)  # Set the correct model
                # Subtitle is now updated via the 'model-loaded' signal in LLMChatWindow
                # window.title_widget.set_subtitle(model_id) # REMOVED
            else:
                # If no model in history, the LLMClient will load the default,
                # and the 'model-loaded' signal will update the subtitle accordingly.
                debug_print("Warning: No model found in the first history entry.")

            # Load the history into the (now correctly configured) LLMClient
            if history:
                window.llm.load_history(history)

                # Display messages in the UI
                for entry in history:
                    window.display_message(
                        entry['prompt'],
                        is_user=True
                    )
                    window.display_message(
                        entry['response'],
                        is_user=False
                    )

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

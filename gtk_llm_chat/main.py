import sys
import gi
import argparse

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from datetime import datetime as dt
from gi.repository import Gtk, Adw, Gio, Gdk, GLib, GObject
from gtk_llm_chat.llm_process import Message, LLMProcess
from gtk_llm_chat.markdown_view import MarkdownView

class LLMChatApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.gnome.LLMChat",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.config = None
        self.chat_history = None

    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self, config=self.config)
        window.present()
        window.input_text.grab_focus()

    def do_startup(self):
        Adw.Application.do_startup(self)

def main():
    # Parsear argumentos ANTES de que GTK los vea
    argv = [arg for arg in sys.argv if not arg.startswith(('--gtk', '--gdk', '--display'))]
    config = parse_args(argv)
    
    # Pasar solo los argumentos de GTK a la aplicación
    gtk_args = [arg for arg in sys.argv if arg.startswith(('--gtk', '--gdk', '--display'))]
    gtk_args.insert(0, sys.argv[0])  # Agregar el nombre del programa
    
    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    app.config = config
    return app.run(gtk_args)

if __name__ == "__main__":
    sys.exit(main())

"""
An applet to browse LLM conversations
"""
import os
import subprocess
import signal
import sys
import gettext
import locale

# Importar el cliente D-Bus compartido
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from dbus_client import open_conversation_dbus

ALT = False
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import Gio, Gtk, AyatanaAppIndicator3 as AppIndicator
except Exception as e:
    print(f"Error al importar dependencias GTK: {e}")
    from tk_llm_applet import main as main_alt
    ALT = True

# Inicializar gettext
_ = gettext.gettext


# Inicializar gettext
APP_NAME = "gtk-llm-chat"

if getattr(sys, 'frozen', False):
    base_path = os.path.join(sys._MEIPASS, 'gtk_llm_chat')
else:
    base_path = os.path.dirname(__file__)

LOCALE_DIR = os.path.abspath(os.path.join(base_path, '..', 'po'))

try:
    locale.setlocale(locale.LC_ALL, '')  # Config regional del sistema
    lang, _enc = locale.getlocale()
except Exception as e:
    print(f"Advertencia: No se pudo establecer la configuración regional: {e}", file=sys.stderr)
    lang = 'en_US'

try:
    translation = gettext.translation(APP_NAME, localedir=LOCALE_DIR, languages=[lang], fallback=True)
    translation.install()
    _ = translation.gettext  # Sobrescribe la función global _
except Exception as e:
    print(f"Error cargando traducciones: {e}", file=sys.stderr)
    _ = gettext.gettext  # fallback simple



sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory


def on_quit(*args):
    """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
    print(_("\nClosing application..."))
    # Usar sys.exit(0) para asegurar una salida limpia con código de retorno 0
    Gtk.main_quit()
    sys.exit(0)


def add_last_conversations_to_menu(menu, chat_history):
    """Adds the last conversations to the menu."""
    try:
        conversations = chat_history.get_conversations(limit=10, offset=0)
        for conversation in conversations:
            conversation_name = conversation['name'].strip().removeprefix("user: ")
            conversation_id = conversation['id']
            menu_item = Gtk.MenuItem(label=conversation_name)
            menu_item.connect("activate",
                              lambda w, id=conversation_id: open_conversation(id))
            menu.append(menu_item)
    finally:
        chat_history.close_connection()


def open_conversation(conversation_id=None):
    """Enviar un mensaje D-Bus para abrir una nueva conversación"""
    # Usar la implementación compartida del cliente D-Bus
    open_conversation_dbus(conversation_id)


def on_new_conversation(widget):
    open_conversation()


def create_menu(chat_history):
    """Creates the menu."""
    menu = Gtk.Menu()

    item = Gtk.MenuItem(label=_("New Conversation"))
    item.connect("activate", on_new_conversation)
    menu.append(item)

    separator = Gtk.SeparatorMenuItem()
    menu.append(separator)

    add_last_conversations_to_menu(menu, chat_history)

    separator = Gtk.SeparatorMenuItem()
    menu.append(separator)

    quit_item = Gtk.MenuItem(label=_("Quit"))
    quit_item.connect("activate", on_quit)
    menu.append(quit_item)

    menu.show_all()
    return menu

# Se eliminó open_new_conversation ya que usamos open_conversation directamente

def main(legacy=False):
    if ALT:
        return(main_alt(legacy))
    chat_history = ChatHistory()
    icon_path = os.path.join(base_path, 'hicolor/scalable/apps/', 'org.fuentelibre.gtk_llm_Chat.svg')
    indicator = AppIndicator.Indicator.new(
        "org.fuentelibre.gtk_llm_Applet",
        icon_path,
        AppIndicator.IndicatorCategory.APPLICATION_STATUS
    )
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    def on_db_changed(file_monitor, nada, file, event_type, indicator, chat_history, *args):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            indicator.set_menu(create_menu(chat_history))

    if hasattr(chat_history, 'db_path'):
        file = Gio.File.new_for_path(chat_history.db_path)
        file_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
        file_monitor.connect("changed", lambda *args: on_db_changed(*args, indicator, chat_history))

    indicator.set_menu(create_menu(chat_history))
    signal.signal(signal.SIGINT, on_quit)
    Gtk.main()
    
    # No abrir una nueva conversación automáticamente al salir


if __name__ == "__main__":
    main()

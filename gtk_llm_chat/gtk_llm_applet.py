"""
An applet to browse LLM conversations
"""
import os
import subprocess
import signal
import sys
import locale
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gio, Gtk, AyatanaAppIndicator3 as AppIndicator
import gettext

_ = gettext.gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory


def on_quit(*args):
    """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
    print(_("\nClosing application..."))
    Gtk.main_quit()


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


def open_conversation(conversation_id):
    subprocess.Popen(['llm', 'gtk-chat', '--cid', conversation_id])


def on_new_conversation(widget):
    subprocess.Popen(['llm', 'gtk-chat'])


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


def main():
    # Inicializar gettext para el applet
    APP_NAME = "gtk-llm-chat"  # Usar el mismo domain que la app principal
    # Usar ruta absoluta para asegurar que se encuentre el directorio 'po'
    LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'po'))
    try:
        # Intentar establecer solo la categoría de mensajes
        locale.setlocale(locale.LC_MESSAGES, '')
    except locale.Error as e:
        print("Advertencia: No se pudo establecer la configuración regional "
              f"para el applet: {e}", file=sys.stderr)
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)
    # La variable global _ ya está definida al inicio del archivo

    chat_history = ChatHistory()
    icon_path = os.path.join(os.path.dirname(__file__),
                             'hicolor/scalable/apps/',
                             'org.fuentelibre.gtk_llm_Chat.svg')
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
        file_monitor.connect("changed", lambda *args: on_db_changed(*args,
                                                                    indicator, chat_history))

    indicator.set_menu(create_menu(chat_history))

    # Agregar manejador de señales
    signal.signal(signal.SIGINT, on_quit)
    Gtk.main()


if __name__ == "__main__":
    main()

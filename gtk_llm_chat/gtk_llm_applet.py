"""
An applet to browse LLM conversations
"""
import os
import subprocess
import signal
import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gio, Gtk, AyatanaAppIndicator3 as AppIndicator

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory


def on_quit(*args):
    """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
    print("\nCerrando aplicación...")
    Gtk.main_quit()


def add_last_conversations_to_menu(menu):
    chat_history = ChatHistory()
    last_conversations = chat_history.get_conversations(limit=10, offset=0)
    chat_history.close()

    for conversation in last_conversations:
        conversation_name = conversation['name'].strip().removeprefix("user: ")
        conversation_id = conversation['id']
        menu_item = Gtk.MenuItem(label=conversation_name)
        menu_item.connect("activate",
                          lambda w, id=conversation_id: open_conversation(id))
        menu.append(menu_item)


def open_conversation(conversation_id):
    subprocess.Popen(['gtk-llm-chat', '--cid', conversation_id])


def on_new_conversation(widget):
    subprocess.Popen(['gtk-llm-chat'])


def create_menu():
    menu = Gtk.Menu()

    item = Gtk.MenuItem(label="Nueva conversación")
    item.connect("activate", on_new_conversation)
    menu.append(item)

    separator = Gtk.SeparatorMenuItem()
    menu.append(separator)

    add_last_conversations_to_menu(menu)

    separator = Gtk.SeparatorMenuItem()
    menu.append(separator)

    quit_item = Gtk.MenuItem(label="Salir")
    quit_item.connect("activate", on_quit)
    menu.append(quit_item)

    menu.show_all()
    return menu


def main():
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

    def on_db_changed(file_monitor, nada, file, event_type, indicator, *args):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            indicator.set_menu(create_menu())

    if hasattr(chat_history, 'db_path'):
        file = Gio.File.new_for_path(chat_history.db_path)
        file_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
        file_monitor.connect("changed", lambda *args: on_db_changed(*args,
                                                                    indicator))

    indicator.set_menu(create_menu())

    # Agregar manejador de señales
    signal.signal(signal.SIGINT, on_quit)
    Gtk.main()


if __name__ == "__main__":
    main()

# flake8: noqa E402
"""
An applet to browse LLM conversations
"""
from db_operations import ChatHistory
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, AyatanaAppIndicator3 as AppIndicator
import subprocess
import os

def on_menu_item_click(widget):
    print("¡Opción seleccionada!")

def on_quit(widget):
    Gtk.main_quit()

def add_last_conversations_to_menu(menu):
    chat_history = ChatHistory()
    last_conversations = chat_history.get_conversations(limit=10, offset=0)
    chat_history.close()

    for conversation in last_conversations:
        conversation_name = conversation['name'].removeprefix("user: ")
        menu_item = Gtk.MenuItem(label=conversation_name)
        menu_item.connect("activate", lambda w, cid=conversation['id']: open_conversation(cid))
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
    icon_path = os.path.join(os.path.dirname(__file__), 'hicolor/scalable/apps/robot.svg')
    indicator = AppIndicator.Indicator.new(
        "com.example.AppIndicatorDemo",
        icon_path,
        AppIndicator.IndicatorCategory.APPLICATION_STATUS
    )
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    indicator.set_menu(create_menu())

    Gtk.main()

if __name__ == "__main__":
    main()


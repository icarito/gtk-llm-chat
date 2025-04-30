import os
import sys
import signal
import subprocess
import gettext
import locale
from threading import Thread

from pystray import Icon, MenuItem, Menu
from PIL import Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

APP_NAME = "gtk-llm-chat"

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory

# Localización\ nAPP_NAME = "gtk-llm-chat"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'po'))
try:
    locale.setlocale(locale.LC_MESSAGES, '')
except locale.Error as e:
    print(f"Warning: could not set locale: {e}", file=sys.stderr)

gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.textdomain(APP_NAME)
_ = gettext.gettext


def open_conversation(conversation_id=None):
    args = ['llm', 'gtk-chat']
    if conversation_id:
        args += ['--cid', str(conversation_id)]
    subprocess.Popen(args)


def make_conv_action(cid):
    """Devuelve un callback icon, item -> open_conversation(cid)."""
    def action(icon, item):
        open_conversation(cid)
    return action


def get_conversations_menu():
    """Genera la lista de MenuItem para las últimas conversaciones."""
    chat_history = ChatHistory()
    items = []
    try:
        convs = chat_history.get_conversations(limit=10, offset=0)
        for conv in convs:
            label = conv['name'].strip().removeprefix("user: ")
            cid = conv['id']
            items.append(
                MenuItem(label, make_conv_action(cid))
            )
    finally:
        chat_history.close_connection()
    return items


def create_menu(icon):
    """Reconstruye todo el menú, llamando a get_conversations_menu()."""
    return Menu(
        MenuItem(_("New Conversation"), lambda icon, item: open_conversation()),
        Menu.SEPARATOR,
        *get_conversations_menu(),
        Menu.SEPARATOR,
        MenuItem(_("Quit"), lambda icon, item: icon.stop())
    )


def load_icon():
    # Asegúrate de tener un PNG; si solo tienes SVG, conviértelo previamente.
    icon_path = os.path.join(
        os.path.dirname(__file__),
        'hicolor/scalable/apps/',
        'org.fuentelibre.gtk_llm_Chat.png'
    )
    return Image.open(icon_path)


class DBChangeHandler(FileSystemEventHandler):
    """Maneja eventos de modificación/contenido en el fichero de base de datos."""
    def __init__(self, icon, db_path):
        super().__init__()
        self.icon = icon
        self.db_path = os.path.abspath(db_path)

    def on_modified(self, event):
        if os.path.abspath(event.src_path) == self.db_path:
            self.icon.menu = create_menu(self.icon)

    def on_created(self, event):
        if os.path.abspath(event.src_path) == self.db_path:
            self.icon.menu = create_menu(self.icon)


def run_systray():
    # Creamos el icon sin menú, luego lo asignamos para poder pasar el icon mismo
    icon = Icon("LLMChatApplet", load_icon(), _("LLM Conversations"))
    icon.menu = create_menu(icon)

    # Configurar watchdog para vigilar el archivo de base de datos
    chat_history = ChatHistory()
    db_path = getattr(chat_history, 'db_path', None)
    chat_history.close_connection()

    if db_path and os.path.exists(db_path):
        event_handler = DBChangeHandler(icon, db_path)
        observer = Observer()
        observer.schedule(event_handler, os.path.dirname(db_path), recursive=False)
        observer.daemon = True
        observer.start()

    try:
        icon.run()
    finally:
        if db_path and 'observer' in locals():
            observer.stop()
            observer.join()


def signal_handler(sig, frame):
    print(_("Exiting..."))
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def main():
    tray_thread = Thread(target=run_systray, daemon=True)
    tray_thread.start()
    tray_thread.join()

if __name__ == '__main__':
    main()


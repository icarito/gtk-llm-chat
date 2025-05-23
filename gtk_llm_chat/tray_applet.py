"""
tray_applet.py - Applet de bandeja multiplataforma usando pystray y Gio para D-Bus y monitorización
"""
import sys
import os
import signal
import locale
import gettext
import threading

from gtk_llm_chat.platform_utils import send_ipc_open_conversation, is_linux
from gtk_llm_chat.db_operations import ChatHistory

try:
    import pystray
    from PIL import Image
except ImportError:
    print("pystray y pillow son requeridos para el applet de bandeja.")
    sys.exit(1)

if is_linux():
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio
else:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("Watchdog is reaquired for tray applet.")
        sys.exit(1)


# --- i18n ---
APP_NAME = "gtk-llm-chat"
LOCALE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'po'))
lang = locale.getdefaultlocale()[0]
if lang:
    gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
    gettext.textdomain(APP_NAME)
    lang_trans = gettext.translation(APP_NAME, LOCALE_DIR, languages=[lang], fallback=True)
    lang_trans.install()
    _ = lang_trans.gettext
else:
    _ = lambda s: s

# --- Icono ---
def load_icon():
    if getattr(sys, 'frozen', False):
        base_path = os.path.join(
                sys._MEIPASS)
    else:
        base_path = os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    ".."))
    icon_path = os.path.join(
            base_path,
            'gtk_llm_chat',
            'hicolor', 
            'scalable', 'apps', 'org.fuentelibre.gtk_llm_Chat.png')
    
    # Can we have the icon in Cornflower blue?
    # icon_path = os.path.join(
    #    base_path,
    #    'windows',
    #    'org.fuentelibre.gtk_llm_Chat.png'
    #)
    return Image.open(icon_path)

# --- Acciones ---
def open_conversation(cid=None):
    # Asegura que el cid es string o None
    if cid is not None and not isinstance(cid, str):
        print(f"[tray_applet] ADVERTENCIA: open_conversation recibió cid tipo {type(cid)}: {cid}")
        return
    send_ipc_open_conversation(cid)

def make_conv_action(cid):
    def action(icon, item):
        # Asegura que el cid es string y nunca un objeto MenuItem
        if not isinstance(cid, str):
            print(f"[tray_applet] ADVERTENCIA: cid no es string, es {type(cid)}: {cid}")
            return
        open_conversation(cid)
    return action

def get_conversations_menu():
    chat_history = ChatHistory()
    items = []
    try:
        convs = chat_history.get_conversations(limit=10, offset=0)
        for conv in convs:
            label = conv['name'].strip().removeprefix("user: ")
            cid = conv['id']
            items.append(pystray.MenuItem(label, make_conv_action(cid)))
    finally:
        chat_history.close_connection()
    return items

def create_menu():
    base_items = [
        pystray.MenuItem(_("New Conversation"), lambda icon, item: open_conversation()),
        pystray.Menu.SEPARATOR,
        *get_conversations_menu(),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_("Quit"), lambda icon, item: icon.stop())
    ]
    return pystray.Menu(*base_items)

# --- Recarga del menú usando Gio.FileMonitor ---
class DBMonitor:
    def __init__(self, db_path, on_change):
        self.db_path = db_path
        self.on_change = on_change
        self._setup_monitor()
    def _setup_monitor(self):
        file = Gio.File.new_for_path(self.db_path)
        self.monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._on_db_changed)
    def _on_db_changed(self, monitor, file, other_file, event_type):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            self.on_change()

if not is_linux():
    # --- Watchdog para Windows ---
    class DBChangeHandler(FileSystemEventHandler):
        """Maneja eventos de modificación/contenido en el fichero de base de datos."""
        def __init__(self, db_path, on_change):
            super().__init__()
            self.db_path = os.path.abspath(db_path)
            self.on_change = on_change

        def on_modified(self, event):
            if not event.is_directory:
                self.on_change()

        def on_created(self, event):
            if os.path.abspath(event.src_path) == self.db_path:
                self.on_change()

# --- Señal para salir limpio ---
def on_quit_signal(sig, frame):
    print(_("\nClosing application..."))
    sys.exit(0)

signal.signal(signal.SIGINT, on_quit_signal)

# --- Main ---
def main():
    icon = pystray.Icon("LLMChatApplet", load_icon(), _(u"LLM Conversations"))
    # Menú inicial
    icon.menu = create_menu()

    # Monitorizar la base de datos
    chat_history = ChatHistory()
    db_path = getattr(chat_history, 'db_path', None)
    chat_history.close_connection()
    
    if db_path and os.path.exists(db_path):
        def reload_menu():
            icon.menu = create_menu()
        
        # Usar watchdog en Windows, Gio.FileMonitor en otras plataformas
        if not is_linux():
            print("[tray_applet] Usando watchdog para monitorización en Windows")
            event_handler = DBChangeHandler(db_path, reload_menu)
            observer = Observer()
            observer.schedule(event_handler, os.path.dirname(db_path), recursive=False)
            observer.daemon = True
            observer.start()
        else:
            print("[tray_applet] Usando Gio.FileMonitor para monitorización")
            # Gio requiere loop GLib, así que lo corremos en un hilo aparte
            def gio_loop():
                DBMonitor(db_path, reload_menu)
                from gi.repository import GLib
                GLib.MainLoop().run()
            t = threading.Thread(target=gio_loop, daemon=True)
            t.start()

    icon.run()

if __name__ == '__main__':
    from platform_utils import ensure_single_instance
    ensure_single_instance()
    main()

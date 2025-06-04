"""
tray_applet.py - Applet de bandeja multiplataforma usando pystray y Gio para D-Bus y monitorización
"""
import sys
import os
import signal
import locale
import gettext
import threading

from gtk_llm_chat.platform_utils import send_ipc_open_conversation, is_linux, is_mac
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
        self.db_filename = os.path.basename(db_path)
        self.on_change = on_change
        self._setup_monitor()
    
    def _setup_monitor(self):
        # Monitorear el directorio padre para detectar creación/cambios de logs.db
        dir_path = os.path.dirname(self.db_path)
        dir_file = Gio.File.new_for_path(dir_path)
        self.dir_monitor = dir_file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.dir_monitor.connect("changed", self._on_dir_changed)
        
        # También monitorear el archivo directamente si ya existe
        if os.path.exists(self.db_path):
            file = Gio.File.new_for_path(self.db_path)
            self.file_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.file_monitor.connect("changed", self._on_file_changed)
        else:
            self.file_monitor = None
    
    def _on_dir_changed(self, monitor, file, other_file, event_type):
        # Solo reaccionar si el archivo que cambió es logs.db
        if file and file.get_basename() == self.db_filename:
            if event_type in (Gio.FileMonitorEvent.CREATED, 
                            Gio.FileMonitorEvent.CHANGES_DONE_HINT):
                # Si logs.db fue creado y no tenemos monitor de archivo, crearlo
                if event_type == Gio.FileMonitorEvent.CREATED and self.file_monitor is None:
                    try:
                        file_obj = Gio.File.new_for_path(self.db_path)
                        self.file_monitor = file_obj.monitor_file(Gio.FileMonitorFlags.NONE, None)
                        self.file_monitor.connect("changed", self._on_file_changed)
                    except Exception as e:
                        print(f"[tray_applet] Error creando monitor de archivo: {e}")
                self.on_change()
    
    def _on_file_changed(self, monitor, file, other_file, event_type):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            self.on_change()

if not is_linux():
    # --- Watchdog para Windows y macOS ---
    class DBChangeHandler(FileSystemEventHandler):
        """Maneja eventos de modificación/contenido en el fichero de base de datos."""
        def __init__(self, db_path, on_change):
            super().__init__()
            self.db_path = os.path.abspath(db_path)
            self.db_filename = os.path.basename(db_path)
            self.on_change = on_change
            self.db_exists = os.path.exists(self.db_path)
            self._last_change_time = 0
            print(f"[tray_applet] Iniciando monitor de watchdog para: {self.db_path}")

        def _safe_on_change(self):
            """Llama on_change de forma segura con manejo de errores y debounce"""
            import time
            current_time = time.time()
            # Debounce: evitar llamadas múltiples en menos de 1 segundo
            if current_time - self._last_change_time < 1.0:
                return
            self._last_change_time = current_time
            
            try:
                print(f"[tray_applet] Recargando menú por cambios en logs.db")
                self.on_change()
            except Exception as e:
                print(f"[tray_applet] Error al recargar menú: {e}")

        def on_modified(self, event):
            # Solo reaccionar si el archivo modificado es logs.db
            if (not event.is_directory and 
                os.path.basename(event.src_path) == self.db_filename):
                print(f"[tray_applet] logs.db modificado: {event.src_path}")
                self._safe_on_change()

        def on_created(self, event):
            # Solo reaccionar si el archivo creado es logs.db
            if (not event.is_directory and 
                os.path.basename(event.src_path) == self.db_filename):
                self.db_exists = True
                print(f"[tray_applet] logs.db creado: {event.src_path}")
                self._safe_on_change()

        def on_moved(self, event):
            # Manejar cuando el archivo es movido/renombrado (como en SQLite con archivos temporales)
            if (not event.is_directory and 
                hasattr(event, 'dest_path') and event.dest_path and
                os.path.basename(event.dest_path) == self.db_filename):
                self.db_exists = True
                print(f"[tray_applet] logs.db movido: {event.dest_path}")
                self._safe_on_change()

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

    # Obtener el path de la base de datos sin instanciar ChatHistory innecesariamente
    import llm
    user_dir = llm.user_dir()
    db_path = os.path.join(user_dir, "logs.db")
    
    def reload_menu():
        icon.menu = create_menu()
    
    # Siempre monitorear el directorio para detectar creación/cambios de logs.db
    # Usar watchdog en Windows y macOS, Gio.FileMonitor en Linux
    if is_linux():
        print("[tray_applet] Usando Gio.FileMonitor para monitorización en Linux")
        # Gio requiere loop GLib, así que lo corremos en un hilo aparte
        def gio_loop():
            DBMonitor(db_path, reload_menu)
            from gi.repository import GLib
            GLib.MainLoop().run()
        t = threading.Thread(target=gio_loop, daemon=True)
        t.start()
    else:
        platform_name = "macOS" if is_mac() else "Windows"
        print(f"[tray_applet] Usando watchdog para monitorización en {platform_name}")
        event_handler = DBChangeHandler(db_path, reload_menu)
        observer = Observer()
        
        # Monitorear el directorio de la base de datos
        db_dir = os.path.dirname(db_path)
        observer.schedule(event_handler, db_dir, recursive=False)
        observer.daemon = True
        observer.start()
        
        print(f"[tray_applet] Monitoreando directorio: {db_dir}")
        
        # Si el archivo ya existe, forzar una recarga inicial del menú
        if os.path.exists(db_path):
            print(f"[tray_applet] logs.db ya existe, recargando menú inicial")
            reload_menu()

    icon.run()

if __name__ == '__main__':
    from platform_utils import ensure_single_instance
    ensure_single_instance()
    main()

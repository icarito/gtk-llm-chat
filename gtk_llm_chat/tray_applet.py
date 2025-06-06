"""
tray_applet.py - Applet de bandeja multiplataforma usando pystray y Gio para D-Bus y monitorización
"""
import sys
import os
import signal
import locale
import gettext
import threading

from .platform_utils import send_ipc_open_conversation, is_linux, is_mac
from .debug_utils import debug_print
from .db_operations import ChatHistory

try:
    import pystray
    from PIL import Image
except ImportError:
    debug_print("pystray y pillow son requeridos para el applet de bandeja.")
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
        debug_print("Watchdog is required for tray applet.")
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
    """Carga el icono para el tray. Prioriza SVG simbólico para tray, PNG para aplicación."""
    if getattr(sys, 'frozen', False):
        base_path = os.path.join(sys._MEIPASS)
    else:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # Lista de posibles ubicaciones de iconos (priorizar SVG simbólico para tray)
    icon_paths = [
        # SVG simbólico (preferido para tray)
        os.path.join('/app', 'share', 'icons', 'hicolor', 'symbolic', 'apps', 'org.fuentelibre.gtk_llm_Chat-symbolic.svg'),
        os.path.join(base_path, 'gtk_llm_chat', 'hicolor', 'symbolic', 'apps', 'org.fuentelibre.gtk_llm_Chat-symbolic.svg'),
        # PNG 48x48 específico para el tray
        os.path.join('/app', 'share', 'icons', 'hicolor', '48x48', 'apps', 'org.fuentelibre.gtk_llm_Chat-symbolic.png'),
        os.path.join(base_path, 'gtk_llm_chat', 'hicolor', '48x48', 'apps', 'org.fuentelibre.gtk_llm_Chat-symbolic.png'),
        # PNG normal
        os.path.join('/app', 'share', 'icons', 'hicolor', '48x48', 'apps', 'org.fuentelibre.gtk_llm_Chat.png'),
        os.path.join(base_path, 'gtk_llm_chat', 'hicolor', '48x48', 'apps', 'org.fuentelibre.gtk_llm_Chat.png'),
        # Otras opciones como fallback
        os.path.join('/app', 'share', 'icons', 'hicolor', 'scalable', 'apps', 'org.fuentelibre.gtk_llm_Chat.svg'),
    ]
    
    for icon_path in icon_paths:
        debug_print(f"[TRAY ICON] Intentando cargar icono para tray: {icon_path}")
        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path)
                debug_print(f"Icono PNG cargado exitosamente: {icon_path}")
                return img
            except Exception as e:
                debug_print(f"Error cargando icono desde {icon_path}: {e}")
                continue
    
    # Si no se encuentra ningún icono, crear uno por defecto
    debug_print("No se encontró icono, creando uno por defecto")
    # Crear un icono simple de 32x32 píxeles
    try:
        img = Image.new('RGBA', (32, 32), (100, 149, 237, 255))  # Cornflower blue
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 24, 24], fill=(255, 255, 255, 255))
        return img
    except Exception as e:
        debug_print(f"Error creando icono por defecto: {e}")
        # Fallback absoluto
        return Image.new('RGBA', (32, 32), (100, 149, 237, 255))

# --- Acciones ---
def open_conversation(cid=None):
    # Asegura que el cid es string o None
    if cid is not None and not isinstance(cid, str):
        debug_print(f"[tray_applet] ADVERTENCIA: open_conversation recibió cid tipo {type(cid)}: {cid}")
        return
    send_ipc_open_conversation(cid)

def make_conv_action(cid):
    def action(icon, item):
        # Asegura que el cid es string y nunca un objeto MenuItem
        if not isinstance(cid, str):
            debug_print(f"[tray_applet] ADVERTENCIA: cid no es string, es {type(cid)}: {cid}")
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
    """Clase simplificada para monitorear únicamente el archivo logs.db y notificar cambios."""
    def __init__(self, db_path, on_change):
        """
        Inicializa el monitor para logs.db.
        
        Args:
            db_path: Ruta completa al archivo logs.db
            on_change: Función a llamar cuando se detectan cambios
        """
        self.db_path = db_path
        self.db_filename = os.path.basename(db_path)
        self.on_change = on_change
        self._setup_monitor()
    
    def _setup_monitor(self):
        """Configura el monitor para logs.db utilizando Gio.FileMonitor."""
        # El applet solo debe monitorear logs.db, así que configuramos
        # directamente la monitorización del archivo
        if os.path.exists(self.db_path):
            file = Gio.File.new_for_path(self.db_path)
            self.file_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.file_monitor.connect("changed", self._on_file_changed)
            debug_print(f"[tray_applet] Monitoreando archivo existente logs.db")
        else:
            # Si no existe logs.db, solo monitoreamos el directorio para su creación
            dir_path = os.path.dirname(self.db_path)
            dir_file = Gio.File.new_for_path(dir_path)
            self.dir_monitor = dir_file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self.dir_monitor.connect("changed", self._on_dir_changed)
            self.file_monitor = None
            debug_print(f"[tray_applet] Esperando creación de logs.db en {dir_path}")
    
    def _on_dir_changed(self, monitor, file, other_file, event_type):
        """Detecta específicamente cuando se crea el archivo logs.db."""
        # Solo reaccionar si se crea logs.db (ningún otro archivo)
        if file and file.get_basename() == self.db_filename and event_type == Gio.FileMonitorEvent.CREATED:
            debug_print(f"[tray_applet] logs.db ha sido creado, iniciando monitorización del archivo")
            self.dir_monitor.cancel()
            file_obj = Gio.File.new_for_path(self.db_path)
            self.file_monitor = file_obj.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.file_monitor.connect("changed", self._on_file_changed)
            self.on_change()
    
    def _on_file_changed(self, monitor, file, other_file, event_type):
        """Notifica cuando se completan cambios en logs.db."""
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            self.on_change()

if not is_linux():
    # --- Watchdog simplificado para Windows y macOS ---
    class DBChangeHandler(FileSystemEventHandler):
        """Manejador de eventos simplificado que solo monitorea logs.db"""
        def __init__(self, db_path, on_change):
            super().__init__()
            self.db_path = os.path.abspath(db_path)
            self.db_filename = os.path.basename(db_path)
            self.on_change = on_change
            self._last_change_time = 0
            debug_print(f"[tray_applet] Iniciando monitor simplificado para: {self.db_path}")

        def _safe_on_change(self):
            """Llama on_change de forma segura con limitación de frecuencia"""
            import time
            current_time = time.time()
            # Evita llamadas múltiples en menos de 1 segundo
            if current_time - self._last_change_time < 1.0:
                return
            self._last_change_time = current_time
            
            try:
                debug_print(f"[tray_applet] Detectado cambio en logs.db, actualizando menú")
                self.on_change()
            except Exception as e:
                debug_print(f"[tray_applet] Error al actualizar menú: {e}")

        def on_modified(self, event):
            # Solo reaccionar si es logs.db
            if (not event.is_directory and 
                os.path.basename(event.src_path) == self.db_filename):
                self._safe_on_change()

        def on_created(self, event):
            # Solo reaccionar si es logs.db
            if (not event.is_directory and 
                os.path.basename(event.src_path) == self.db_filename):
                debug_print(f"[tray_applet] logs.db ha sido creado")
                self._safe_on_change()

        def on_moved(self, event):
            # SQLite a veces usa operaciones de movimiento durante transacciones
            if (not event.is_directory and 
                hasattr(event, 'dest_path') and event.dest_path and
                os.path.basename(event.dest_path) == self.db_filename):
                self._safe_on_change()

# --- Señal para salir limpio ---
def on_quit_signal(sig, frame):
    debug_print(_("\nClosing application..."))
    sys.exit(0)

signal.signal(signal.SIGINT, on_quit_signal)

# --- Main ---
def main():
    """Main function for the tray applet."""
    # Import ensure_single_instance here to avoid circular dependencies if platform_utils imports tray_applet
    from .platform_utils import ensure_single_instance
    # Ensure this is the only applet instance.
    # The returned object must be kept in scope to maintain the lock.
    _applet_instance_lock = ensure_single_instance("gtk_llm_applet")

    # Obtener el path de la base de datos
    from .platform_utils import ensure_user_dir_exists
    user_dir = ensure_user_dir_exists()
    db_path = os.path.join(user_dir, "logs.db")
    debug_print(f"[tray_applet] PATH ABSOLUTO DE logs.db MONITORIZADO: {db_path}")
    
    # Inicializar el icon de bandeja
    # En entorno Flatpak, usar un nombre consistente con el ID de la aplicación para el tray
    icon_id = "org.fuentelibre.gtk_llm_Chat" if os.path.exists('/.flatpak-info') else "LLMChatApplet"
    icon = pystray.Icon(icon_id, load_icon(), _(u"LLM Conversations"))
    
    def reload_menu():
        """Recarga el menú con las conversaciones actualizadas desde logs.db"""
        icon.menu = create_menu()
    
    # Verificar que logs.db existe antes de continuar
    if not os.path.exists(db_path):
        debug_print(f"[tray_applet] Error: No se encontró logs.db en {db_path}")
        debug_print(f"[tray_applet] El applet solo debe iniciarse después de que el usuario haya configurado un modelo")
        
        # Mostrar un menú básico para que el usuario pueda iniciar una nueva conversación
        # (que creará logs.db) o salir
        icon.menu = pystray.Menu(
            pystray.MenuItem(_("New Conversation"), lambda icon, item: open_conversation()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_("Quit"), lambda icon, item: icon.stop())
        )
    else:
        # Si logs.db existe, cargar las conversaciones
        debug_print(f"[tray_applet] Encontrado logs.db, cargando conversaciones")
        icon.menu = create_menu()
    
    # Configurar la monitorización de logs.db de forma simplificada
    if is_linux():
        debug_print("[tray_applet] Iniciando monitorización de logs.db (Linux)")
        # Gio requiere loop GLib, ejecutar en un hilo aparte
        def gio_loop():
            DBMonitor(db_path, reload_menu)
            from gi.repository import GLib
            GLib.MainLoop().run()
        threading.Thread(target=gio_loop, daemon=True).start()
    else:
        platform_name = "macOS" if is_mac() else "Windows"
        debug_print(f"[tray_applet] Iniciando monitorización de logs.db ({platform_name})")
        event_handler = DBChangeHandler(db_path, reload_menu)
        observer = Observer()
        # Solo monitoreamos el directorio que contiene logs.db
        db_dir = os.path.dirname(db_path)
        observer.schedule(event_handler, db_dir, recursive=False)
        observer.daemon = True
        observer.start()
    
    # Ejecutar el icono de bandeja
    icon.run()

if __name__ == '__main__':
    # ensure_single_instance is now called within main()
    main()

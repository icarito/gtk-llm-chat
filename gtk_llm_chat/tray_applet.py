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
        self.db_path = os.path.abspath(db_path)
        self.db_filename = os.path.basename(db_path)
        self.on_change = on_change
        self.file_monitor = None
        self.dir_monitor = None
        self._last_mtime = 0
        self._poll_timeout_id = None
        
        debug_print(f"[tray_applet] DBMonitor: Inicializando para {self.db_path}")
        debug_print(f"[tray_applet] DBMonitor: Archivo existe: {os.path.exists(self.db_path)}")
        debug_print(f"[tray_applet] DBMonitor: Directorio padre: {os.path.dirname(self.db_path)}")
        debug_print(f"[tray_applet] DBMonitor: Directorio padre existe: {os.path.exists(os.path.dirname(self.db_path))}")
        
        # Inicializar última modificación
        if os.path.exists(self.db_path):
            self._last_mtime = os.path.getmtime(self.db_path)
            
        self._setup_monitor()
        self._start_polling_backup()
    
    def _setup_monitor(self, is_retry_after_delete=False):
        """Configura el monitor para logs.db utilizando Gio.FileMonitor."""
        # Cancelar monitores existentes
        if hasattr(self, 'file_monitor') and self.file_monitor:
            self.file_monitor.cancel()
            self.file_monitor = None
        if hasattr(self, 'dir_monitor') and self.dir_monitor:
            self.dir_monitor.cancel()
            self.dir_monitor = None

        debug_print(f"[tray_applet] DBMonitor: Configurando monitor para {self.db_path}")
        debug_print(f"[tray_applet] DBMonitor: logs.db existe: {os.path.exists(self.db_path)}")
        debug_print(f"[tray_applet] DBMonitor: is_retry_after_delete: {is_retry_after_delete}")

        # Si el archivo logs.db existe Y NO es un reintento post-delete, monitorear archivo.
        # En todos los demás casos (archivo no existe, o es reintento post-delete), monitorear directorio.
        if os.path.exists(self.db_path) and not is_retry_after_delete:
            try:
                # Verificar permisos antes de configurar el monitor
                if not os.access(self.db_path, os.R_OK):
                    debug_print(f"[tray_applet] DBMonitor: ERROR - Sin permisos de lectura en {self.db_path}")
                    self._setup_directory_monitor()
                    return
                    
                file = Gio.File.new_for_path(self.db_path)
                self.file_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
                self.file_monitor.connect("changed", self._on_file_changed)
                debug_print(f"[tray_applet] DBMonitor: Monitoreando archivo logs.db directamente")
            except Exception as e:
                debug_print(f"[tray_applet] DBMonitor: Error configurando monitor de archivo: {e}")
                debug_print(f"[tray_applet] DBMonitor: Esto puede ocurrir en entornos sandbox - fallback a directorio")
                # Fallback a monitoreo de directorio
                self._setup_directory_monitor()
        else:
            self._setup_directory_monitor()
    
    def _setup_directory_monitor(self):
        """Configura monitoreo del directorio para detectar creación de logs.db."""
        dir_path = os.path.dirname(self.db_path)
        debug_print(f"[tray_applet] DBMonitor: Monitoreando directorio {dir_path} para detectar creación de logs.db")
        
        # Verificar que el directorio existe y es accesible
        if not os.path.exists(dir_path):
            debug_print(f"[tray_applet] DBMonitor: ERROR - Directorio {dir_path} no existe")
            return
            
        if not os.access(dir_path, os.R_OK):
            debug_print(f"[tray_applet] DBMonitor: ERROR - Sin permisos de lectura en {dir_path}")
            return
        
        try:
            dir_file = Gio.File.new_for_path(dir_path)
            self.dir_monitor = dir_file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self.dir_monitor.connect("changed", self._on_dir_changed)
            self.file_monitor = None
            debug_print(f"[tray_applet] DBMonitor: Monitor de directorio configurado correctamente")
        except Exception as e:
            debug_print(f"[tray_applet] DBMonitor: Error configurando monitor de directorio: {e}")
            debug_print(f"[tray_applet] DBMonitor: Puede ser un problema de permisos o entorno sandbox")
    
    def _on_dir_changed(self, monitor, file, other_file, event_type):
        """Detecta específicamente cuando se crea el archivo logs.db."""
        filename = file.get_basename() if file else "unknown"
        
        # Log todos los eventos de directorio para diagnóstico
        event_name = "UNKNOWN"
        try:
            event_name = event_type.value_name
        except:
            event_name = str(event_type)
        
        debug_print(f"[tray_applet] DBMonitor: Evento de directorio: {filename} -> {event_name}")
        
        # Solo reaccionar si se crea logs.db (ningún otro archivo)
        if file and filename == self.db_filename and event_type == Gio.FileMonitorEvent.CREATED:
            debug_print(f"[tray_applet] DBMonitor: logs.db ha sido creado, cambiando a monitorización de archivo")
            try:
                self.dir_monitor.cancel()
                file_obj = Gio.File.new_for_path(self.db_path)
                self.file_monitor = file_obj.monitor_file(Gio.FileMonitorFlags.NONE, None)
                self.file_monitor.connect("changed", self._on_file_changed)
                debug_print(f"[tray_applet] DBMonitor: Cambio a monitor de archivo exitoso")
                self.on_change()
            except Exception as e:
                debug_print(f"[tray_applet] DBMonitor: Error cambiando a monitor de archivo: {e}")
    
    def _on_file_changed(self, monitor, file, other_file, event_type):
        """Notifica cuando se completan cambios en logs.db."""
        # Loguear todos los eventos recibidos para diagnóstico
        event_name_str = "DESCONOCIDO"
        try:
            # Intentar obtener el nombre legible del evento
            event_name_str = Gio.FileMonitorEvent(event_type).value_name 
        except ValueError:
            # Si el valor numérico no corresponde a un miembro conocido de la enumeración
            event_name_str = f"DESCONOCIDO_EVENTO_VALOR_{event_type}"

        file_path_str = file.get_path() if file else 'None'
        other_file_path_str = other_file.get_path() if other_file else 'None'
        
        debug_print(f"[tray_applet] DBMonitor: Evento {event_type} ({event_name_str}) en '{file_path_str}', otro: '{other_file_path_str}'")

        # Solo procesar eventos relevantes para logs.db
        if file and file.get_path() == self.db_path:
            # Lista de eventos que indican cambios relevantes en la base de datos
            relevant_events = [
                Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                Gio.FileMonitorEvent.CHANGED,
                Gio.FileMonitorEvent.CREATED,
                Gio.FileMonitorEvent.ATTRIBUTE_CHANGED,  # Para cambios como touch
                Gio.FileMonitorEvent.PRE_UNMOUNT,       # SQLite puede hacer esto
                Gio.FileMonitorEvent.UNMOUNTED
            ]
            
            if event_type in relevant_events:
                debug_print(f"[tray_applet] DBMonitor: Detectado evento relevante {event_name_str} en logs.db - recargando menú")
                self.on_change()
            elif event_type == Gio.FileMonitorEvent.DELETED:
                debug_print(f"[tray_applet] DBMonitor: logs.db fue eliminado - volviendo a monitorear directorio")
                # Reconfigurar monitor para directorio
                self._setup_monitor(is_retry_after_delete=True)
                # Recargar menú (probablemente vacío)
                self.on_change()
            elif event_type == Gio.FileMonitorEvent.MOVED:
                debug_print(f"[tray_applet] DBMonitor: Detectado MOVED en logs.db - re-evaluando monitor")
                # SQLite a veces mueve archivos temporalmente
                self._setup_monitor(is_retry_after_delete=True)
                self.on_change()
            else:
                debug_print(f"[tray_applet] DBMonitor: Evento {event_name_str} no considerado relevante")
        else:
            debug_print(f"[tray_applet] DBMonitor: Evento en archivo diferente a logs.db, ignorado")

    def _start_polling_backup(self):
        """Inicia polling backup cada 5 segundos para detectar cambios que los monitores de archivo no capturen."""
        debug_print(f"[tray_applet] DBMonitor: Iniciando polling backup cada 5 segundos")
        
        def poll_for_changes():
            try:
                if os.path.exists(self.db_path):
                    current_mtime = os.path.getmtime(self.db_path)
                    if current_mtime != self._last_mtime:
                        debug_print(f"[tray_applet] DBMonitor: Polling detectó cambio en logs.db (mtime: {self._last_mtime} -> {current_mtime})")
                        self._last_mtime = current_mtime
                        self.on_change()
                else:
                    # Si el archivo no existe, reset mtime
                    if self._last_mtime != 0:
                        debug_print(f"[tray_applet] DBMonitor: Polling detectó que logs.db fue eliminado")
                        self._last_mtime = 0
                        self.on_change()
            except Exception as e:
                debug_print(f"[tray_applet] DBMonitor: Error en polling: {e}")
            
            # Programar próximo polling
            from gi.repository import GLib
            self._poll_timeout_id = GLib.timeout_add_seconds(5, poll_for_changes)
            return False  # No repetir automáticamente, lo controlamos manualmente
        
        # Iniciar el primer polling
        from gi.repository import GLib
        self._poll_timeout_id = GLib.timeout_add_seconds(5, poll_for_changes)

    def stop_monitoring(self):
        """Detiene todos los monitores y polling."""
        if self.file_monitor:
            self.file_monitor.cancel()
            self.file_monitor = None
        if self.dir_monitor:
            self.dir_monitor.cancel()
            self.dir_monitor = None
        if self._poll_timeout_id:
            from gi.repository import GLib
            GLib.source_remove(self._poll_timeout_id)
            self._poll_timeout_id = None
        debug_print(f"[tray_applet] DBMonitor: Monitoreo detenido")


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
            debug_print(f"[tray_applet] DBChangeHandler: Iniciando monitor para {self.db_path}")

        def _safe_on_change(self):
            """Llama on_change de forma segura con limitación de frecuencia"""
            import time
            current_time = time.time()
            # Evitar llamadas excesivamente frecuentes (debounce de 1 segundo)
            if current_time - self._last_change_time > 1.0:
                debug_print(f"[tray_applet] DBChangeHandler: Ejecutando on_change() - recargando menú")
                self._last_change_time = current_time
                try:
                    self.on_change()
                except Exception as e:
                    debug_print(f"[tray_applet] DBChangeHandler: Error en on_change(): {e}")
            else:
                debug_print(f"[tray_applet] DBChangeHandler: on_change() omitido por debounce")

        def on_modified(self, event):
            """Detecta modificaciones de logs.db"""
            if not event.is_directory and event.src_path == self.db_path:
                debug_print(f"[tray_applet] DBChangeHandler: logs.db modificado: {event.src_path}")
                self._safe_on_change()

        def on_created(self, event):
            """Detecta creación de logs.db"""
            if not event.is_directory and event.src_path == self.db_path:
                debug_print(f"[tray_applet] DBChangeHandler: logs.db creado: {event.src_path}")
                self._safe_on_change()

        def on_moved(self, event):
            """Detecta cuando se mueve logs.db (SQLite hace esto a veces)"""
            if not event.is_directory and (event.src_path == self.db_path or event.dest_path == self.db_path):
                debug_print(f"[tray_applet] DBChangeHandler: logs.db movido de {event.src_path} a {event.dest_path}")
                self._safe_on_change()

        def on_deleted(self, event):
            """Detecta eliminación de logs.db"""
            if not event.is_directory and event.src_path == self.db_path:
                debug_print(f"[tray_applet] DBChangeHandler: logs.db eliminado: {event.src_path}")
                self._safe_on_change()
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
    from .platform_utils import ensure_user_dir_exists, debug_database_monitoring
    from .debug_utils import DEBUG
    
    # Ejecutar diagnóstico en modo DEBUG
    if DEBUG:
        debug_database_monitoring()
    
    user_dir = ensure_user_dir_exists()
    db_path = os.path.join(user_dir, "logs.db")
    
    # Diagnóstico detallado del path de la base de datos
    debug_print(f"[tray_applet] === DIAGNÓSTICO DE MONITOREO ===")
    debug_print(f"[tray_applet] user_dir (llm.user_dir()): {user_dir}")
    debug_print(f"[tray_applet] PATH ABSOLUTO DE logs.db MONITORIZADO: {db_path}")
    debug_print(f"[tray_applet] logs.db existe: {os.path.exists(db_path)}")
    debug_print(f"[tray_applet] user_dir existe: {os.path.exists(user_dir)}")
    debug_print(f"[tray_applet] is_frozen: {getattr(sys, 'frozen', False)}")
    debug_print(f"[tray_applet] FLATPAK_ID: {os.environ.get('FLATPAK_ID', 'None')}")
    debug_print(f"[tray_applet] LLM_USER_PATH: {os.environ.get('LLM_USER_PATH', 'None')}")
    
    if os.path.exists(user_dir):
        try:
            contents = os.listdir(user_dir)
            debug_print(f"[tray_applet] Contenido de user_dir ({len(contents)} elementos):")
            for item in contents[:5]:  # Mostrar primeros 5
                debug_print(f"[tray_applet]   {item}")
            if len(contents) > 5:
                debug_print(f"[tray_applet]   ... y {len(contents) - 5} más")
        except Exception as e:
            debug_print(f"[tray_applet] Error listando user_dir: {e}")
    
    # Inicializar el icon de bandeja
    if is_linux():
        # La forma correcta y moderna: pasar el nombre.
        # El escritorio lo encontrará y le aplicará el tema correcto.
        icon_spec = "org.fuentelibre.gtk_llm_Chat-symbolic" 
    else:
        icon_spec = load_icon()

    icon = pystray.Icon(
        "org.fuentelibre.gtk_llm_Chat",
        icon_spec,
        _("LLM Conversations"))

    icon_id = "org.fuentelibre.gtk_llm_Chat" if os.path.exists('/.flatpak-info') else "LLMChatApplet"
    icon = pystray.Icon(icon_id, icon_spec, _(u"LLM Conversations"))
    
    def reload_menu():
        """Recarga el menú con las conversaciones actualizadas desde logs.db"""
        debug_print(f"[tray_applet] reload_menu() llamado - recargando conversaciones desde {db_path}")
        icon.menu = create_menu()
    
    # Verificar que logs.db existe antes de continuar
    if not os.path.exists(db_path):
        debug_print(f"[tray_applet] ADVERTENCIA: No se encontró logs.db en {db_path}")
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
        debug_print(f"[tray_applet] Encontrado logs.db, cargando conversaciones desde {db_path}")
        icon.menu = create_menu()
    
    # Configurar la monitorización de logs.db de forma simplificada
    debug_print(f"[tray_applet] Configurando monitorización de logs.db...")
    if is_linux():
        debug_print(f"[tray_applet] Iniciando monitorización Gio (Linux) para {db_path}")
        # Gio requiere loop GLib, ejecutar en un hilo aparte
        def gio_loop():
            try:
                db_monitor = DBMonitor(db_path, reload_menu)
                debug_print(f"[tray_applet] DBMonitor inicializado correctamente")
                from gi.repository import GLib
                loop = GLib.MainLoop()
                debug_print(f"[tray_applet] Iniciando GLib.MainLoop para monitorización")
                loop.run()
            except Exception as e:
                debug_print(f"[tray_applet] Error en gio_loop: {e}")
                import traceback
                traceback.print_exc()
        threading.Thread(target=gio_loop, daemon=True).start()
    else:
        platform_name = "macOS" if is_mac() else "Windows"
        debug_print(f"[tray_applet] Iniciando monitorización Watchdog ({platform_name}) para {db_path}")
        try:
            event_handler = DBChangeHandler(db_path, reload_menu)
            observer = Observer()
            # Solo monitoreamos el directorio que contiene logs.db
            db_dir = os.path.dirname(db_path)
            debug_print(f"[tray_applet] Monitoreando directorio: {db_dir}")
            observer.schedule(event_handler, db_dir, recursive=False)
            observer.daemon = True
            observer.start()
            debug_print(f"[tray_applet] Observer iniciado correctamente")
        except Exception as e:
            debug_print(f"[tray_applet] Error configurando Watchdog: {e}")
            import traceback
            traceback.print_exc()
    
    debug_print(f"[tray_applet] Iniciando icon.run() - el applet debería estar visible en la bandeja")
    # Ejecutar el icono de bandeja
    icon.run()

if __name__ == '__main__':
    # ensure_single_instance is now called within main()
    main()

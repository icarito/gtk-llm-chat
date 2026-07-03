import os
import sys
import subprocess
import pathlib
from .debug_utils import debug_print

DEBUG = os.environ.get('DEBUG') or False

def ensure_single_instance(name: str):
    """
    Ensures that only one instance of the application is running.
    On Linux, it uses an abstract socket.
    On Windows and macOS, it uses a lock file in the user's config directory.
    """
    if is_linux():
        import socket
        try:
            # Abstract socket: name starts with \0
            lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            lock_socket.bind(f"\0{name}")
            return lock_socket
        except socket.error:
            debug_print(f"Another instance of {name} is already running.")
            sys.exit(0)
    else:
        # For Windows and macOS, use a lock file
        lock_file = os.path.join(ensure_user_dir_exists(), f"{name}.lock")
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            return fd
        except OSError:
            debug_print(f"Another instance of {name} is already running.")
            sys.exit(0)

def is_linux():
    return sys.platform.startswith('linux')

def is_windows():
    return sys.platform == 'win32'

def is_mac():
    return sys.platform == 'darwin'

def is_flatpak():
    return os.path.exists('/.flatpak-info')

def is_frozen():
    return getattr(sys, 'frozen', False)

def send_ipc_open_conversation(cid):
    """
    Envía una señal para abrir una conversación a la app principal.
    En Linux usa D-Bus.
    """
    if not is_linux():
        debug_print("IPC not implemented for this platform yet.")
        return

    try:
        # Intentar usar gdbus para llamar al método OpenConversation
        # El ID de la aplicación debe coincidir con el registrado en chat_application.py
        app_id = "org.fuentelibre.gtk_llm_Chat"
        object_path = "/" + app_id.replace('.', '/')
        
        cmd = [
            'gdbus', 'call', '--session',
            '--dest', app_id,
            '--object-path', object_path,
            '--method', f"{app_id}.OpenConversation",
            cid
        ]
        
        subprocess.run(cmd, check=False, capture_output=True)
    except Exception as e:
        debug_print(f"Error sending IPC message: {e}")

def ensure_user_dir_exists():
    """
    Asegura que el directorio de usuario de llm exista.
    Retorna el path absoluto.
    """
    try:
        import llm
        user_dir = llm.user_dir()
        os.makedirs(user_dir, exist_ok=True)
        return user_dir
    except Exception as e:
        debug_print(f"[platform_utils] Error crítico obteniendo/creando directorio de usuario con llm.user_dir(): {e}")
        return None

def debug_frozen_environment():
    """
    Función de diagnóstico para aplicaciones congeladas (PyInstaller).
    """
    debug_print("=== DIAGNÓSTICO DE ENTORNO CONGELADO ===")
    debug_print(f"sys.frozen: {getattr(sys, 'frozen', False)}")
    debug_print(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'No disponible')}")
    debug_print(f"sys.executable: {sys.executable}")
    debug_print(f"Versión de Python: {sys.version}")
    debug_print(f"Plataforma: {sys.platform}")
    debug_print("=== FIN DIAGNÓSTICO ENTORNO CONGELADO ===\n")

if DEBUG and is_frozen():
    debug_frozen_environment()

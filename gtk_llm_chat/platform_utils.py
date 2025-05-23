"""
platform_utils.py - utilidades multiplataforma para gtk-llm-chat
"""
import sys
import subprocess
import os
import tempfile
from gtk_llm_chat.single_instance import SingleInstance

PLATFORM = sys.platform

DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

def ensure_single_instance(lockfile=None):
    """
    Asegura que solo haya una instancia de la aplicación en ejecución.
    """
    if not lockfile:
        lockdir = tempfile.gettempdir()
        lockfile = os.path.join(lockdir, 'gtk_llm_applet.lock')
    try:
        single_instance = SingleInstance(lockfile)
        return single_instance
    except RuntimeError as e:
        debug_print(f"{e}")
        sys.exit(1)

def is_linux():
    return PLATFORM.startswith('linux')

def is_windows():
    return PLATFORM.startswith('win')

def is_mac():
    return PLATFORM == 'darwin'

def is_frozen():
    return getattr(sys, 'frozen', False)


def launch_tray_applet(config):
    """
    Lanza el applet de bandeja
    """
    ensure_single_instance()
    try:
        from gtk_llm_chat.tray_applet import main
        main()
    except Exception as e:
        debug_print(f"Can't start tray app: {e}")
        # spawn_tray_applet(config)

def spawn_tray_applet(config):
    if is_frozen():
        if not config.get('applet'):
            # Relanzar el propio ejecutable con --applet
            args = [sys.executable, "--applet"]
            print(f"[platform_utils] Lanzando applet (frozen): {args}")
    else:
        # Ejecutar tray_applet.py con el intérprete
        applet_path = os.path.join(os.path.dirname(__file__), 'main.py')
        args = [sys.executable, applet_path, '--applet']
        print(f"[platform_utils] Lanzando applet (no frozen): {args}")
    subprocess.Popen(args)

def send_ipc_open_conversation(cid):
    """
    Envía una señal para abrir una conversación desde el applet a la app principal.
    En Linux usa D-Bus (Gio), en otros sistemas o si D-Bus falla, usa línea de comandos.
    """
    print(f"Enviando IPC para abrir conversación con CID: '{cid}'")
    if cid is not None and not isinstance(cid, str):
        print(f"ADVERTENCIA: El CID no es un string, es {type(cid)}")
        try:
            cid = str(cid)
        except Exception:
            cid = None

    if is_linux():
        try:
            import gi
            gi.require_version('Gio', '2.0')
            gi.require_version('GLib', '2.0')
            from gi.repository import Gio, GLib

            if cid is None:
                cid = ""
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            print(f"D-Bus: Conectado al bus, enviando mensaje OpenConversation con CID: '{cid}'")
            variant = GLib.Variant('(s)', (cid,))
            bus.call_sync(
                'org.fuentelibre.gtk_llm_Chat',
                '/org/fuentelibre/gtk_llm_Chat',
                'org.fuentelibre.gtk_llm_Chat',
                'OpenConversation',
                variant,
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
            print("D-Bus: Mensaje enviado correctamente")
            return True
        except Exception as e:
            print(f"Error enviando IPC D-Bus: {e}")
            print("Fallback a línea de comandos...")

    # Fallback multiplataforma o si D-Bus falló
    if is_frozen():
        exe = sys.executable
        args = [exe]
        if cid:
            args.append(f"--cid={cid}")
        print(f"Ejecutando fallback (frozen): {args}")
        subprocess.Popen(args)
    else:
        exe = sys.executable
        main_path = os.path.join(os.path.dirname(__file__), 'main.py')
        args = [exe, main_path]
        if cid:
            args.append(f"--cid={cid}")
        print(f"Ejecutando fallback (no frozen): {args}")
        subprocess.Popen(args)

def fork_or_spawn_applet(config):
    """Lanza el applet como proceso hijo (fork) en Unix si está disponible, o como subproceso en cualquier plataforma. Devuelve True si el proceso actual debe continuar con la app principal."""
    if config.get('no_applet'):
        return True
    # Solo fork en sistemas tipo Unix si está disponible
    if (is_linux() or is_mac()) and hasattr(os, 'fork'):
        pid = os.fork()
        if pid == 0:
            # Proceso hijo: applet
            launch_tray_applet(config)
            sys.exit(0)
        # Proceso padre: sigue con la app principal
        return True
    else:
        spawn_tray_applet(config)
        return True

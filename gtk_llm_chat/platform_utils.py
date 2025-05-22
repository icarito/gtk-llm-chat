"""
platform_utils.py - utilidades multiplataforma para gtk-llm-chat
"""
import sys
import subprocess
import os
import tempfile
import atexit

PLATFORM = sys.platform


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
    # Asegurar instancia única del applet
    ensure_single_instance()
    try:
        from gtk_llm_chat.tray_applet import main
        main()
        sys.exit(0)
    except Exception as e:
        if is_frozen():
            # Relanzar el propio ejecutable con --applet
            args = [sys.executable, "--applet"]
            print(f"[platform_utils] Error lanzando applet (frozen): {e}")
            # subprocess.Popen(args)
        else:
            # Ejecutar tray_applet.py con el intérprete
            applet_path = os.path.join(os.path.dirname(__file__), 'tray_applet.py')
            args = [sys.executable, applet_path]
            if config.get('cid'):
                args += ['--cid', config['cid']]
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

def ensure_single_instance(lock_file=None):
    """Evita múltiples instancias usando un pidfile (multiplataforma, thread-safe en Windows)."""
    import threading
    if lock_file is None:
        lock_file = os.path.join(tempfile.gettempdir(), 'gtk_llm_chat_applet.pid')
    print(f"[platform_utils] ensure_single_instance: pidfile={lock_file}", flush=True)
    pid = os.getpid()
    tid = threading.get_ident() if is_windows() else None
    # En Windows, el pidfile debe incluir el thread id para distinguir hilos
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                content = f.read().strip()
                if is_windows():
                    existing_pid, existing_tid = map(int, content.split(':'))
                    # Solo bloquear si el proceso sigue vivo
                    import ctypes
                    PROCESS_QUERY_INFORMATION = 0x1000
                    process = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, existing_pid)
                    if process != 0:
                        ctypes.windll.kernel32.CloseHandle(process)
                        print(f"[platform_utils] Otra instancia activa con PID {existing_pid}", flush=True)
                        print("Another instance of the applet is already running.")
                        sys.exit(1)
                    else:
                        print(f"[platform_utils] PID {existing_pid} no está activo (Windows), sobreescribiendo pidfile", flush=True)
                else:
                    existing_pid = int(content)
                    if existing_pid != pid:
                        try:
                            os.kill(existing_pid, 0)
                            print(f"[platform_utils] Otra instancia activa con PID {existing_pid}", flush=True)
                            print("Another instance of the applet is already running.")
                            sys.exit(1)
                        except OSError:
                            print(f"[platform_utils] PID {existing_pid} no está activo, sobreescribiendo pidfile", flush=True)
        except Exception as e:
            print(f"[platform_utils] Error leyendo pidfile: {e}", flush=True)
    # Escribimos nuestro PID (y TID en Windows)
    with open(lock_file, 'w') as f:
        if is_windows():
            f.write(f"{pid}:{tid}")
        else:
            f.write(str(pid))
    def cleanup():
        try:
            if os.path.exists(lock_file):
                with open(lock_file, 'r') as f:
                    content = f.read().strip()
                    if is_windows():
                        file_pid, file_tid = map(int, content.split(':'))
                        if file_pid == pid and file_tid == tid:
                            os.remove(lock_file)
                            print(f"[platform_utils] pidfile {lock_file} eliminado", flush=True)
                    else:
                        if content == str(pid):
                            os.remove(lock_file)
                            print(f"[platform_utils] pidfile {lock_file} eliminado", flush=True)
        except Exception as e:
            print(f"[platform_utils] Error eliminando pidfile: {e}", flush=True)
    atexit.register(cleanup)
    print(f"[platform_utils] Instancia registrada con PID {pid} TID {tid if is_windows() else ''}", flush=True)
    return lock_file

def maybe_fork_or_spawn_applet(config):
    """Lanza el applet como proceso hijo (fork) en Unix, en un hilo en Windows, o como subproceso en Mac. Devuelve True si el proceso actual debe continuar con la app principal."""
    if config.get('no_applet'):
        return True
    import threading
    # Solo fork en sistemas tipo Unix
    if is_linux() or is_mac():
        if hasattr(os, 'fork'):
            pid = os.fork()
            if pid == 0:
                # Proceso hijo: applet
                launch_tray_applet(config)
                sys.exit(0)
            # Proceso padre: sigue con la app principal
            return True
        else:
            # Mac sin fork: subproceso
            import subprocess
            subprocess.Popen([sys.executable, os.path.abspath(__file__), '--applet'])
            if config.get('applet'):
                return False
            return True
    elif is_windows():
        # En Windows, lanzar el applet en un hilo
        def tray_thread():
            launch_tray_applet(config)
        t = threading.Thread(target=tray_thread, daemon=True)
        t.start()
        if config.get('applet'):
            # Si solo se pidió el applet, el hilo principal debe esperar
            t.join()
            return False
        return True
    else:
        # Fallback: subproceso
        import subprocess
        subprocess.Popen([sys.executable, os.path.abspath(__file__), '--applet'])
        if config.get('applet'):
            return False
        return True

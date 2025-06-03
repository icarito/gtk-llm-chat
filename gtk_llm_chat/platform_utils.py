"""
platform_utils.py - utilidades multiplataforma para gtk-llm-chat
"""
import sys
import subprocess
import os
import tempfile
from single_instance import SingleInstance

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

def ensure_load_on_session_startup(enable=True):
    """
    Configura el applet para que arranque automáticamente al inicio de sesión.
    
    Args:
        enable (bool): True para habilitar autostart, False para deshabilitar
    
    Returns:
        bool: True si la operación fue exitosa, False en caso contrario
    """
    try:
        if is_linux():
            return _setup_autostart_linux(enable)
        elif is_windows():
            return _setup_autostart_windows(enable)
        elif is_mac():
            return _setup_autostart_macos(enable)
        else:
            debug_print("Plataforma no soportada para autostart")
            return False
    except Exception as e:
        debug_print(f"Error configurando autostart: {e}")
        return False

def _setup_autostart_linux(enable):
    """Configura autostart en Linux usando archivos .desktop"""
    autostart_dir = os.path.expanduser("~/.config/autostart")
    desktop_file = os.path.join(autostart_dir, "gtk-llm-chat-applet.desktop")
    
    if not enable:
        # Deshabilitar: eliminar archivo
        if os.path.exists(desktop_file):
            os.remove(desktop_file)
            debug_print(f"Autostart deshabilitado: eliminado {desktop_file}")
        return True
    
    # Habilitar: crear directorio si no existe
    os.makedirs(autostart_dir, exist_ok=True)
    
    # Determinar el comando a ejecutar
    if is_frozen():
        exec_command = f"{sys.executable} --applet"
    else:
        main_path = os.path.join(os.path.dirname(__file__), 'main.py')
        exec_command = f"{sys.executable} {main_path} --applet"
    
    # Contenido del archivo .desktop
    desktop_content = f"""[Desktop Entry]
Type=Application
Name=GTK LLM Chat Applet
Comment=System tray applet for GTK LLM Chat
Exec={exec_command}
Icon=org.fuentelibre.gtk_llm_Chat
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
Terminal=false
Categories=Utility;
"""
    
    # Escribir archivo
    with open(desktop_file, 'w') as f:
        f.write(desktop_content)
    
    # Hacer ejecutable
    os.chmod(desktop_file, 0o755)
    
    debug_print(f"Autostart habilitado: creado {desktop_file}")
    return True

def _setup_autostart_windows(enable):
    """Configura autostart en Windows usando el registro"""
    try:
        import winreg
    except ImportError:
        debug_print("winreg no disponible (¿no estás en Windows?)")
        return False
    
    # Clave del registro para Run
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    value_name = "GTKLLMChatApplet"
    
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if not enable:
                # Deshabilitar: eliminar entrada
                try:
                    winreg.DeleteValue(key, value_name)
                    debug_print("Autostart deshabilitado en registro de Windows")
                except FileNotFoundError:
                    pass  # Ya no existe
                return True
            
            # Habilitar: crear/actualizar entrada
            if is_frozen():
                exec_path = f'"{sys.executable}" --applet'
            else:
                main_path = os.path.join(os.path.dirname(__file__), 'main.py')
                exec_path = f'"{sys.executable}" "{main_path}" --applet'
            
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, exec_path)
            debug_print(f"Autostart habilitado en registro de Windows: {exec_path}")
            return True
            
    except Exception as e:
        debug_print(f"Error configurando registro de Windows: {e}")
        return False

def _setup_autostart_macos(enable):
    """Configura autostart en macOS usando LaunchAgents"""
    launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_file = os.path.join(launch_agents_dir, "org.fuentelibre.gtk-llm-chat-applet.plist")
    
    if not enable:
        # Deshabilitar: descargar y eliminar
        if os.path.exists(plist_file):
            # Intentar descargar el servicio
            try:
                subprocess.run(["launchctl", "unload", plist_file], check=False)
            except:
                pass
            os.remove(plist_file)
            debug_print(f"Autostart deshabilitado: eliminado {plist_file}")
        return True
    
    # Habilitar: crear directorio si no existe
    os.makedirs(launch_agents_dir, exist_ok=True)
    
    # Determinar argumentos del programa
    if is_frozen():
        program_path = sys.executable
        program_args = [program_path, "--applet"]
    else:
        main_path = os.path.join(os.path.dirname(__file__), 'main.py')
        program_args = [sys.executable, main_path, "--applet"]
    
    # Contenido del archivo plist
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>org.fuentelibre.gtk-llm-chat-applet</string>
    <key>ProgramArguments</key>
    <array>
{chr(10).join(f'        <string>{arg}</string>' for arg in program_args)}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>LaunchOnlyOnce</key>
    <true/>
</dict>
</plist>
"""
    
    # Escribir archivo
    with open(plist_file, 'w') as f:
        f.write(plist_content)
    
    # Cargar el servicio
    try:
        subprocess.run(["launchctl", "load", plist_file], check=True)
        debug_print(f"Autostart habilitado: creado y cargado {plist_file}")
    except subprocess.CalledProcessError as e:
        debug_print(f"Error cargando launchctl: {e}")
        # El archivo se creó pero no se pudo cargar
    
    return True

def is_loading_on_session_startup():
    """
    Verifica si el applet está configurado para arrancar automáticamente al inicio de sesión.
    
    Returns:
        bool: True si el autostart está habilitado, False en caso contrario
    """
    try:
        if is_linux():
            return _check_autostart_linux()
        elif is_windows():
            return _check_autostart_windows()
        elif is_mac():
            return _check_autostart_macos()
        else:
            debug_print("Plataforma no soportada para verificar autostart")
            return False
    except Exception as e:
        debug_print(f"Error verificando autostart: {e}")
        return False

def _check_autostart_linux():
    """Verifica autostart en Linux verificando archivo .desktop"""
    autostart_dir = os.path.expanduser("~/.config/autostart")
    desktop_file = os.path.join(autostart_dir, "gtk-llm-chat-applet.desktop")
    return os.path.exists(desktop_file)

def _check_autostart_windows():
    """Verifica autostart en Windows verificando el registro"""
    try:
        import winreg
    except ImportError:
        debug_print("winreg no disponible (¿no estás en Windows?)")
        return False
    
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    value_name = "GTKLLMChatApplet"
    
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, value_name)
                return bool(value)  # True si existe y tiene valor
            except FileNotFoundError:
                return False  # La entrada no existe
    except Exception as e:
        debug_print(f"Error verificando registro de Windows: {e}")
        return False

def _check_autostart_macos():
    """Verifica autostart en macOS verificando archivo .plist"""
    launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_file = os.path.join(launch_agents_dir, "org.fuentelibre.gtk-llm-chat-applet.plist")
    return os.path.exists(plist_file)

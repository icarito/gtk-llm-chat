"""
platform_utils.py - utilidades multiplataforma para gtk-llm-chat
"""
import sys
import subprocess
import os
import llm # Importar llm para usar llm.user_dir()
import tempfile

try:
    # Si se ejecuta como módulo del paquete
    from .single_instance import SingleInstance
    from .debug_utils import debug_print
    # Postponer import de chat_application hasta que sea necesario
except ImportError:
    # Si se ejecuta como script directo, añadir el directorio actual al path
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from single_instance import SingleInstance
    from debug_utils import debug_print

PLATFORM = sys.platform

DEBUG = os.environ.get('DEBUG') or False

def ensure_single_instance(name: str):
    """
    Ensures that only one instance of the application component with this 'name' is running.
    This is intended for use by the tray applet.
    Exits with sys.exit(1) if an instance is already running.
    Returns the SingleInstance object on success, to keep the lock.
    """
    lockdir = tempfile.gettempdir()
    lockfile_path = os.path.join(lockdir, f"gtk_llm_chat_{name}.lock")
    try:
        single_instance = SingleInstance(lockfile_path)
        # debug_print(f"Lock acquired for '{name}' at '{lockfile_path}'") # Minimal debug
        return single_instance
    except RuntimeError as e:
        # debug_print(f"Another instance of '{name}' is already running (lock at '{lockfile_path}'). Exiting.") # Minimal debug
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
    Launches the tray applet logic.
    This function is called INSIDE the process that WILL BE the applet.
    tray_applet.main() will handle its own single_instance logic.
    """
    # DO NOT call ensure_single_instance here. tray_applet.main() will.
    try:
        from .tray_applet import main as tray_main
        tray_main()
    except Exception as e:
        debug_print(f"Can't start tray app: {e}")

def spawn_tray_applet(config):
    if is_frozen():
        if not config.get('applet'):
            # Usar la variable de entorno APPIMAGE si está disponible
            appimage_path = os.environ.get("APPIMAGE")
            if appimage_path and os.path.exists(appimage_path):
                args = [appimage_path, "--applet"]
                debug_print(f"[platform_utils] Lanzando applet (AppImage): {args}")
            else:
                args = [sys.executable, "--applet"]
                debug_print(f"[platform_utils] Lanzando applet (frozen): {args}")
            subprocess.Popen(args)
            return
    
    # Detectar si estamos en Flatpak y usar el comando correcto
    is_flatpak = os.path.exists('/.flatpak-info') or os.environ.get('FLATPAK_ID')
    
    if is_flatpak:
        # En Flatpak, usar flatpak run con --applet
        flatpak_id = os.environ.get('FLATPAK_ID', 'org.fuentelibre.gtk_llm_Chat')
        args = ['flatpak-spawn', '--host', 'flatpak', 'run', flatpak_id, '--applet']
        debug_print(f"[platform_utils] Lanzando applet (Flatpak): {args}")
    else:
        # En entornos normales, ejecutar main.py directamente
        applet_path = os.path.join(os.path.dirname(__file__), 'main.py')
        args = [sys.executable, applet_path, '--applet']
        debug_print(f"[platform_utils] Lanzando applet (no frozen): {args}")
    
    try:
        subprocess.Popen(args)
    except Exception as e:
        debug_print(f"[platform_utils] Error lanzando applet: {e}")

def send_ipc_open_conversation(cid):
    """
    Envía una señal para abrir una conversación desde el applet a la app principal.
    En Linux usa D-Bus (Gio), en otros sistemas o si D-Bus falla, usa línea de comandos.
    """
    debug_print(f"Enviando IPC para abrir conversación con CID: '{cid}'")
    if cid is not None and not isinstance(cid, str):
        debug_print(f"ADVERTENCIA: El CID no es un string, es {type(cid)}")
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
            debug_print(f"D-Bus: Conectado al bus, enviando mensaje OpenConversation con CID: '{cid}'")
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
            debug_print("D-Bus: Mensaje enviado correctamente")
            return True
        except Exception as e:
            debug_print(f"Error enviando IPC D-Bus: {e}")
            debug_print("Fallback a línea de comandos...")

    # Fallback multiplataforma o si D-Bus falló
    if is_frozen():
        # Usar la variable de entorno APPIMAGE si está disponible
        appimage_path = os.environ.get("APPIMAGE")
        if appimage_path and os.path.exists(appimage_path):
            args = [appimage_path]
            if cid:
                args.append(f"--cid={cid}")
            debug_print(f"Ejecutando fallback (AppImage): {args}")
            subprocess.Popen(args)
        else:
            exe = sys.executable
            args = [exe]
            if cid:
                args.append(f"--cid={cid}")
            debug_print(f"Ejecutando fallback (frozen): {args}")
            subprocess.Popen(args)
    else:
        # En entorno normal (no frozen), intentar usar el comando de entrada si existe
        # Si estamos en un Flatpak, usar el comando directo de la aplicación
        if os.environ.get('FLATPAK_ID'):
            # Estamos en Flatpak, usar flatpak-spawn para ejecutar el comando en el host
            flatpak_id = os.environ.get('FLATPAK_ID', 'org.fuentelibre.gtk_llm_Chat')
            args = ['flatpak-spawn', '--host', 'flatpak', 'run', flatpak_id]
            if cid:
                args.append(f"--cid={cid}")
            debug_print(f"Ejecutando fallback (Flatpak): {args}")
            subprocess.Popen(args)
        else:
            # Entorno normal, usar python -m
            args = [sys.executable, '-m', 'gtk_llm_chat.main']
            if cid:
                args.append(f"--cid={cid}")
            debug_print(f"Ejecutando fallback (módulo): {args}")
            subprocess.Popen(args)

def fork_or_spawn_applet(config={}):
    """Lanza el applet como proceso hijo (fork) en Unix si está disponible, o como subproceso en cualquier plataforma.
    Solo lanza el applet si logs.db existe (lo que significa que ya se ha configurado al menos un modelo).
    Devuelve True si el proceso actual debe continuar con la app principal."""
    if config.get('no_applet'):
        debug_print("Applet deshabilitado explícitamente en la configuración.")
        return True
        
    # Verificar que logs.db exista antes de lanzar el applet
    user_dir = ensure_user_dir_exists()
    if not user_dir:
        debug_print("No se lanza el applet porque todavía no existe el directorio de usuario.")
        return True

    db_path = os.path.join(user_dir, 'logs.db')
    
    if not os.path.exists(db_path):
        debug_print("No se lanza el applet porque logs.db todavía no existe.")
        return True
        
    debug_print(f"Lanzando applet (logs.db existe en {db_path})")
    
    # Solo fork en sistemas tipo Unix si está disponible
    # En algunos ambientes Mac/AppImage es o era necesario/conveniente hacer fork - pero ahora no funciona?
    # Desactivado por ahora --icarito
    if (is_linux() or is_mac()) and hasattr(os, 'fork'):
        pid = os.fork()
        if pid == 0:
            # Proceso hijo: applet
            launch_tray_applet(config)
            sys.exit(0)
        # Proceso padre: sigue con la app principal
        return True
    else:
        # Windows o sistemas sin fork
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
        appimage_path = os.environ.get("APPIMAGE")
        if appimage_path and os.path.exists(appimage_path):
            exec_command = f"{appimage_path} --applet"
        else:
            exec_command = f"{sys.executable} --applet"
    else:
        # Detectar si estamos en Flatpak
        is_flatpak = os.path.exists('/.flatpak-info') or os.environ.get('FLATPAK_ID')
        
        if is_flatpak:
            # En Flatpak, usar flatpak run
            flatpak_id = os.environ.get('FLATPAK_ID', 'org.fuentelibre.gtk_llm_Chat')
            exec_command = f"flatpak run {flatpak_id} --applet"
        else:
            # En entornos normales
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

def ensure_user_dir_exists():
    """
    Asegura que el directorio de configuración/datos del usuario exista y lo devuelve.
    Delega a llm.user_dir() que maneja LLM_USER_PATH, XDG y directorios específicos de plataforma.
    """
    try:
        # llm.user_dir() usa LLM_USER_PATH si está seteado.
        # En Flatpak, el manifiesto setea LLM_USER_PATH a $HOME/.config/io.datasette.llm (del sandbox)
        # que es un montaje de ~/.config/io.datasette.llm (del host).
        # En otros sistemas, usa XDG_CONFIG_HOME o defaults de plataforma.
        user_dir = llm.user_dir()
        
        # El path devuelto por llm.user_dir() ya está expandido y es absoluto.
        debug_print(f"[platform_utils] llm.user_dir() resolvió a: {user_dir}")
        
        os.makedirs(user_dir, exist_ok=True)
        # debug_print(f"[platform_utils] Directorio de usuario asegurado: {user_dir}. Existe: {os.path.exists(user_dir)}")
        return user_dir
    except Exception as e: # Captura más genérica para errores inesperados
        debug_print(f"[platform_utils] Error crítico obteniendo/creando directorio de usuario con llm.user_dir(): {e}")
        # En caso de error, es mejor retornar None para que el llamador maneje la falla.
        return None

def debug_frozen_environment():
    """
    Función de diagnóstico para aplicaciones congeladas (PyInstaller).
    Diagnostica problemas con plugins LLM y carga de modelos.
    """
    debug_print("=== DIAGNÓSTICO DE ENTORNO CONGELADO ===")
    
    # Información básica del sistema
    debug_print(f"sys.frozen: {getattr(sys, 'frozen', False)}")
    debug_print(f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'No disponible')}")
    debug_print(f"sys.executable: {sys.executable}")
    debug_print(f"sys.path primeros 5 elementos: {sys.path[:5]}")
    
    # Diagnóstico detallado de importación de plugins LLM
    debug_print("=== LLM PLUGINS IMPORT TEST ===")
    core_and_plugins = [
        'llm',
        'llm_groq', 'llm_gemini', 'llm_openrouter', 
        'llm_perplexity', 'llm_anthropic', 'llm_deepseek', 'llm_grok'
    ]
    for pkg in core_and_plugins:
        try:
            mod = __import__(pkg)
            debug_print(f"  [OK] {pkg} importado correctamente: {getattr(mod, '__file__', 'builtin')}")
        except Exception as e:
            debug_print(f"  [FAIL] {pkg} ERROR: {e}")
            # Diagnóstico más profundo del error
            if "add_docstring" in str(e):
                debug_print(f"    >> Error de add_docstring detectado en {pkg}")
                debug_print(f"    >> Tipo de error: {type(e)}")
                debug_print(f"    >> Args del error: {e.args}")
                
                # Verificar si existe el módulo en _MEIPASS
                if hasattr(sys, '_MEIPASS'):
                    import glob
                    pkg_files = glob.glob(os.path.join(sys._MEIPASS, f"{pkg}*"))
                    debug_print(f"    >> Archivos {pkg}* en _MEIPASS: {pkg_files}")
                    
                    # Verificar archivos .so o .pyd (extensiones compiladas)
                    so_files = glob.glob(os.path.join(sys._MEIPASS, "**", "*.so"), recursive=True)
                    pyd_files = glob.glob(os.path.join(sys._MEIPASS, "**", "*.pyd"), recursive=True)
                    debug_print(f"    >> Total archivos .so: {len(so_files)}")
                    debug_print(f"    >> Total archivos .pyd: {len(pyd_files)}")
                    
                    # Buscar archivos relacionados con el paquete
                    related_so = [f for f in so_files if pkg.replace('_', '') in f.lower() or 'llm' in f.lower()]
                    related_pyd = [f for f in pyd_files if pkg.replace('_', '') in f.lower() or 'llm' in f.lower()]
                    debug_print(f"    >> Archivos .so relacionados con {pkg}: {related_so}")
                    debug_print(f"    >> Archivos .pyd relacionados con {pkg}: {related_pyd}")
            
            import traceback
            debug_print(f"    >> Traceback completo:")
            traceback.print_exc()
    
    # Diagnóstico adicional del entorno Python
    debug_print("=== DIAGNÓSTICO ADICIONAL DEL ENTORNO ===")
    debug_print(f"Versión de Python: {sys.version}")
    debug_print(f"Plataforma: {sys.platform}")
    debug_print(f"Arquitectura: {os.uname().machine if hasattr(os, 'uname') else 'unknown'}")
    
    # Verificar si hay conflictos de extensiones C
    try:
        import sqlite3
        debug_print(f"[OK] sqlite3 importado correctamente: {sqlite3.version}")
    except Exception as e:
        debug_print(f"[FAIL] Error importando sqlite3: {e}")
    
    try:
        import json
        debug_print(f"[OK] json importado correctamente")
    except Exception as e:
        debug_print(f"[FAIL] Error importando json: {e}")
    
    # Verificar bibliotecas compiladas comunes
    test_imports = ['hashlib', 'ssl', '_socket', 'zlib', 'bz2']
    debug_print("Verificando módulos con extensiones C:")
    for mod in test_imports:
        try:
            __import__(mod)
            debug_print(f"  [OK] {mod}")
        except Exception as e:
            debug_print(f"  [FAIL] {mod}: {e}")
    
    # Verificar disponibilidad de LLM si se pudo importar
    try:
        import llm
        debug_print(f"[OK] LLM importado correctamente")
        debug_print(f"LLM version: {getattr(llm, '__version__', 'desconocida')}")
        
        # Obtener modelos disponibles
        try:
            models = list(llm.get_models())
            debug_print(f"Total de modelos encontrados: {len(models)}")
            
            # Agrupar por proveedor
            providers = {}
            for model in models:
                provider = getattr(model, 'model_id', 'unknown').split('/')[0]
                if provider not in providers:
                    providers[provider] = 0
                providers[provider] += 1
            
            debug_print("Modelos por proveedor:")
            for provider, count in providers.items():
                debug_print(f"  {provider}: {count} modelos")
                
        except Exception as e:
            debug_print(f"[FAIL] Error obteniendo modelos: {e}")
            
        # Verificar modelo por defecto
        try:
            default_model = llm.get_default_model()
            debug_print(f"Modelo por defecto del sistema: {default_model}")
        except Exception as e:
            debug_print(f"[FAIL] Error obteniendo modelo por defecto: {e}")
            
    except ImportError as e:
        debug_print(f"[FAIL] Error importando LLM: {e}")
    
    debug_print("=== FIN DIAGNÓSTICO ENTORNO CONGELADO ===\n")


def debug_database_monitoring():
    """
    Función de diagnóstico para problemas de monitoreo de base de datos.
    Útil para el applet de bandeja que necesita monitorear logs.db.
    """
    debug_print("=== DIAGNÓSTICO DE MONITOREO DE BASE DE DATOS ===")
    
    try:
        user_dir = ensure_user_dir_exists()
        debug_print(f"Directorio de usuario LLM: {user_dir}")
        
        logs_db_path = os.path.join(user_dir, "logs.db")
        debug_print(f"Ruta logs.db: {logs_db_path}")
        
        if os.path.exists(logs_db_path):
            debug_print("[OK] logs.db existe")
            stat = os.stat(logs_db_path)
            debug_print(f"  Tamaño: {stat.st_size} bytes")
            debug_print(f"  Última modificación: {stat.st_mtime}")
        else:
            debug_print("[FAIL] logs.db no existe")
            
        # Verificar directorio padre
        if os.path.exists(user_dir):
            debug_print(f"[OK] Directorio de usuario existe")
            try:
                contents = os.listdir(user_dir)
                debug_print(f"  Contenido del directorio ({len(contents)} elementos):")
                for item in contents[:10]:  # Mostrar solo primeros 10
                    debug_print(f"    {item}")
                if len(contents) > 10:
                    debug_print(f"    ... y {len(contents) - 10} más")
            except Exception as e:
                debug_print(f"  [FAIL] Error listando directorio: {e}")
        else:
            debug_print("[FAIL] Directorio de usuario no existe")
            
    except Exception as e:
        debug_print(f"[FAIL] Error en diagnóstico de base de datos: {e}")
    
    debug_print("=== FIN DIAGNÓSTICO BASE DE DATOS ===\n")


# Llamada automática a diagnóstico si está en modo DEBUG y congelado
if DEBUG and is_frozen():
    debug_frozen_environment()

"""
platform_utils.py - utilidades multiplataforma para gtk-llm-chat
"""
import sys
import os
import llm # Importar llm para usar llm.user_dir()
import sqlite3
import glob
import traceback

try:
    # Si se ejecuta como módulo del paquete
    from .debug_utils import debug_print
    # Postponer import de chat_application hasta que sea necesario
except ImportError:
    # Si se ejecuta como script directo, añadir el directorio actual al path
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from debug_utils import debug_print

PLATFORM = sys.platform

DEBUG = os.environ.get('DEBUG') or False

def is_linux():
    return PLATFORM.startswith('linux')
def is_windows():
    return PLATFORM.startswith('win')

def is_mac():
    return PLATFORM == 'darwin'

def is_flatpak():
    """Detecta si estamos ejecutando dentro de un Flatpak"""
    return os.path.exists('/.flatpak-info') or os.environ.get('FLATPAK_ID')

def is_frozen():
    return getattr(sys, 'frozen', False)


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
            
            # Probar operaciones de lectura básicas
            try:
                import sqlite3
                conn = sqlite3.connect(logs_db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                debug_print(f"  Tablas en la BD: {[t[0] for t in tables]}")
                conn.close()
                debug_print("  [OK] Acceso de lectura a la BD funcional")
            except Exception as e:
                debug_print(f"  [FAIL] Error accediendo a la BD: {e}")
        else:
            debug_print("[FAIL] logs.db no existe")
            
        # Verificar directorio padre
        if os.path.exists(user_dir):
            debug_print(f"[OK] Directorio de usuario existe")
            try:
                contents = os.listdir(user_dir)
                debug_print(f"  Contenido del directorio ({len(contents)} elementos):")
                for item in contents[:10]:  # Mostrar solo primeros 10
                    item_path = os.path.join(user_dir, item)
                    is_dir = os.path.isdir(item_path)
                    item_type = "(DIR)" if is_dir else "(FILE)"
                    debug_print(f"    {item} {item_type}")
                if len(contents) > 10:
                    debug_print(f"    ... y {len(contents) - 10} más")
            except Exception as e:
                debug_print(f"  [FAIL] Error listando directorio: {e}")
        else:
            debug_print("[FAIL] Directorio de usuario no existe")
            
        # Verificar permisos
        try:
            import tempfile
            test_file = os.path.join(user_dir, "test_write.tmp")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            debug_print("[OK] Permisos de escritura en directorio de usuario")
        except Exception as e:
            debug_print(f"[FAIL] Error de permisos de escritura: {e}")
            
        # Verificar variables de entorno relevantes
        debug_print("Variables de entorno relevantes:")
        env_vars = ['LLM_USER_PATH', 'XDG_CONFIG_HOME', 'HOME', 'FLATPAK_ID', 'APPIMAGE']
        for var in env_vars:
            value = os.environ.get(var, 'None')
            debug_print(f"  {var}: {value}")
            
        # Información sobre el sistema de archivos
        try:
            import platform
            debug_print(f"Sistema operativo: {platform.system()} {platform.release()}")
            debug_print(f"Arquitectura: {platform.machine()}")
            
            if user_dir:
                import shutil
                total, used, free = shutil.disk_usage(user_dir)
                debug_print(f"Espacio en disco - Total: {total//1024//1024}MB, Usado: {used//1024//1024}MB, Libre: {free//1024//1024}MB")
        except Exception as e:
            debug_print(f"Error obteniendo info del sistema: {e}")
            
    except Exception as e:
        debug_print(f"[FAIL] Error en diagnóstico de base de datos: {e}")
        import traceback
        traceback.print_exc()
    
    debug_print("=== FIN DIAGNÓSTICO BASE DE DATOS ===\n")


# Llamada automática a diagnóstico si está en modo DEBUG y congelado
if DEBUG and is_frozen():
    debug_frozen_environment()

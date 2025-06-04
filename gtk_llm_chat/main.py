"""
Gtk LLM Chat - A frontend for `llm`
"""
import argparse
import sys
import time
from platform_utils import launch_tray_applet, fork_or_spawn_applet, debug_print

# Aplicar patch de compatibilidad NumPy/Python 3.13 lo antes posible
def apply_numpy_python313_compatibility_patch():
    """
    Aplica un patch de compatibilidad PREVENTIVO para NumPy en Python 3.13
    para solucionar errores de add_docstring en entornos congelados.
    Este debe ejecutarse ANTES de cualquier importación relacionada con numpy.
    """
    if sys.version_info >= (3, 13) and getattr(sys, 'frozen', False):
        try:
            # Estrategia: interceptar builtins.__import__ ANTES de que numpy se importe
            import builtins
            
            if not hasattr(builtins.__import__, '_numpy_python313_patched'):
                original_import = builtins.__import__
                
                def safe_import_wrapper(name, globals=None, locals=None, fromlist=(), level=0):
                    """Wrapper que intercepta errores de add_docstring durante importación."""
                    
                    try:
                        # Importación normal
                        module = original_import(name, globals, locals, fromlist, level)
                        
                        # Si es algo relacionado con numpy, aplicar patch inmediatamente
                        if ('numpy' in name or 
                            (fromlist and any('numpy' in str(f) for f in fromlist))):
                            _patch_module_add_docstring(module, name)
                        
                        return module
                        
                    except Exception as e:
                        if "add_docstring" in str(e) and "should be a str" in str(e):
                            debug_print(f"Intercepted add_docstring error in {name}: {e}")
                            
                            # Parche de emergencia: buscar y patchear add_docstring globalmente
                            _emergency_patch_add_docstring()
                            
                            # Reintentar importación
                            try:
                                return original_import(name, globals, locals, fromlist, level)
                            except Exception as retry_e:
                                debug_print(f"Failed to import {name} even after emergency patch: {retry_e}")
                                raise e
                        else:
                            raise
                
                def _patch_module_add_docstring(module, module_name):
                    """Patchea add_docstring en un módulo específico."""
                    if not module:
                        return
                    
                    # Lista de posibles ubicaciones de add_docstring
                    locations = [
                        (module, 'add_docstring'),
                        (getattr(module, '_core', None), 'add_docstring'),
                        (getattr(getattr(module, '_core', None), 'overrides', None), 'add_docstring')
                    ]
                    
                    for obj, attr in locations:
                        if obj and hasattr(obj, attr) and not hasattr(getattr(obj, attr), '_python313_safe'):
                            try:
                                original_func = getattr(obj, attr)
                                
                                def safe_add_docstring(func, docstring):
                                    # Normalizar docstring
                                    if docstring is None:
                                        docstring = ""
                                    elif not isinstance(docstring, str):
                                        try:
                                            docstring = str(docstring) if docstring else ""
                                        except:
                                            docstring = ""
                                    
                                    try:
                                        return original_func(func, docstring)
                                    except TypeError as e:
                                        if "should be a str" in str(e):
                                            # Asignación directa como fallback
                                            try:
                                                func.__doc__ = docstring
                                            except:
                                                pass
                                            return func
                                        raise
                                
                                safe_add_docstring._python313_safe = True
                                setattr(obj, attr, safe_add_docstring)
                                debug_print(f"[OK] Patched add_docstring in {module_name}.{attr}")
                                
                            except Exception as patch_e:
                                debug_print(f"Warning: Could not patch {module_name}.{attr}: {patch_e}")
                
                def _emergency_patch_add_docstring():
                    """Parche de emergencia que busca add_docstring en todos los módulos."""
                    for mod_name, mod in list(sys.modules.items()):
                        if mod and 'numpy' in mod_name:
                            _patch_module_add_docstring(mod, mod_name)
                
                # Aplicar el wrapper
                builtins.__import__ = safe_import_wrapper
                builtins.__import__._numpy_python313_patched = True
                debug_print("[OK] NumPy Python 3.13 compatibility wrapper installed")
                
        except Exception as e:
            debug_print(f"Warning: Could not install NumPy compatibility patch: {e}")

# Ejecutar el patch inmediatamente al cargar este módulo
apply_numpy_python313_compatibility_patch()

# Benchmark
benchmark_startup = '--benchmark-startup' in sys.argv
start_time = time.time() if benchmark_startup else None

def parse_args(argv):
    """Parsea los argumentos de la línea de comandos"""
    parser = argparse.ArgumentParser(description='GTK Frontend para LLM')
    parser.add_argument('--cid', type=str, help='ID de la conversación a continuar')
    parser.add_argument('-s', '--system', type=str, help='Prompt del sistema')
    parser.add_argument('-m', '--model', type=str, help='Modelo a utilizar')
    parser.add_argument('-c', '--continue-last', action='store_true', help='Continuar última conversación')
    parser.add_argument('-t', '--template', type=str, help='Template a utilizar')
    parser.add_argument('-p', '--param', nargs=2, action='append', metavar=('KEY', 'VALUE'), help='Parámetros para el template')
    parser.add_argument('-o', '--option', nargs=2, action='append', metavar=('KEY', 'VALUE'), help='Opciones para el modelo')
    parser.add_argument('-f', '--fragment', action='append', metavar='FRAGMENT', help='Fragmento (alias, URL, hash o ruta de archivo) para agregar al prompt')
    parser.add_argument('--benchmark-startup', action='store_true', help='Mide el tiempo hasta que la ventana se muestra y sale.')
    parser.add_argument('--applet', action='store_true', help='Inicia el applet de bandeja')
    args = parser.parse_args(argv[1:])
    config = {
        'cid': args.cid,
        'system': args.system,
        'model': args.model,
        'continue_last': args.continue_last,
        'template': args.template,
        'params': args.param,
        'options': args.option,
        'fragments': args.fragment,
        'benchmark_startup': args.benchmark_startup,
        'start_time': start_time,
        'applet': args.applet
    }
    return config

def main(argv=None):
    """
    Punto de entrada principal
    """
    if argv is None:
        argv = sys.argv
    config = parse_args(argv)

    # Si se pide el applet, lanzarlo y salir
    if config.get('applet'):
        launch_tray_applet(config)
        return 0
    else:
        fork_or_spawn_applet(config)

    # Lanzar la aplicación principal
    from chat_application import LLMChatApplication
    chat_app = LLMChatApplication(config)
    cmd_args = []
    if config.get('cid'):
        cmd_args.append(f"--cid={config['cid']}")
    if config.get('model'):
        cmd_args.append(f"--model={config['model']}")
    if config.get('template'):
        cmd_args.append(f"--template={config['template']}")
    return chat_app.run(cmd_args)

if __name__ == "__main__":
    result = main()
    sys.exit(result)

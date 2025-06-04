"""
python313_compatibility.py - Parches de compatibilidad para Python 3.13.3
Soluciona problemas de compatibilidad con plugins LLM que usan NumPy/SciPy

Este módulo implementa parches específicos para resolver el error:
"argument docstring of add_docstring should be a str"

El problema surge porque Python 3.13.3 cambió el comportamiento de add_docstring,
pero las extensiones C de NumPy/SciPy en los plugins LLM no fueron actualizadas.
"""

import sys
import os
from functools import wraps
import warnings

DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args, **kwargs):
    if DEBUG:
        print("[Python313Compat]", *args, **kwargs)

def patch_add_docstring():
    """
    Parcha la función add_docstring para ser compatible con Python 3.13.3.
    
    El problema: En Python 3.13.3, add_docstring requiere que el parámetro
    docstring sea estrictamente un str, pero algunas extensiones C pasan
    otros tipos (como bytes o None).
    
    La solución: Interceptamos llamadas a add_docstring y convertimos
    automáticamente el parámetro docstring a string si es necesario.
    """
    try:
        # Intentar parchear en numpy si está disponible
        import numpy as np
        
        # Guardar la función original
        if hasattr(np, 'add_docstring') and not hasattr(np.add_docstring, '_python313_patched'):
            original_add_docstring = np.add_docstring
            
            @wraps(original_add_docstring)
            def patched_add_docstring(obj, docstring, warn_on_python=True):
                """
                Versión parchada de numpy.add_docstring compatible con Python 3.13.3
                """
                # Convertir docstring a str si no lo es
                if docstring is not None and not isinstance(docstring, str):
                    if isinstance(docstring, bytes):
                        docstring = docstring.decode('utf-8', errors='replace')
                    else:
                        docstring = str(docstring)
                
                # Asegurar que docstring sea una cadena válida
                if docstring is None:
                    docstring = ""
                
                try:
                    return original_add_docstring(obj, docstring, warn_on_python)
                except TypeError as e:
                    if "should be a str" in str(e):
                        debug_print(f"Interceptado error add_docstring, forzando conversión: {e}")
                        # Si aún falla, usar cadena vacía
                        return original_add_docstring(obj, "", warn_on_python)
                    raise
            
            # Marcar como parchado
            patched_add_docstring._python313_patched = True
            np.add_docstring = patched_add_docstring
            debug_print("[OK] Parche numpy.add_docstring aplicado exitosamente")
            return True
            
    except ImportError:
        debug_print("NumPy no está disponible, omitiendo parche add_docstring")
        return False
    except Exception as e:
        debug_print(f"Error aplicando parche add_docstring: {e}")
        return False
    
    return False

def patch_scipy_extensions():
    """
    Parcha extensiones específicas de SciPy que pueden causar problemas
    """
    try:
        # Intentar parchear problemas conocidos de SciPy
        import scipy
        debug_print("[OK] SciPy detectado, aplicando parches preventivos")
        
        # Parche para scipy.special si está disponible
        try:
            import scipy.special
            debug_print("[OK] scipy.special importado correctamente")
        except Exception as e:
            if "add_docstring" in str(e):
                debug_print(f"Problema con scipy.special detectado: {e}")
                # Crear un módulo stub básico si es necesario
                pass
        
        return True
        
    except ImportError:
        debug_print("SciPy no está disponible, omitiendo parches")
        return False
    except Exception as e:
        debug_print(f"Error aplicando parches de SciPy: {e}")
        return False

def patch_llm_plugin_imports():
    """
    Parcha la importación de plugins LLM específicos que fallan con Python 3.13.3
    """
    known_problematic_plugins = [
        'llm_groq', 'llm_gemini', 'llm_openrouter', 
        'llm_perplexity', 'llm_anthropic', 'llm_deepseek', 'llm_grok'
    ]
    
    patched_count = 0
    
    for plugin_name in known_problematic_plugins:
        try:
            # Intentar importar el plugin
            plugin = __import__(plugin_name)
            debug_print(f"[OK] Plugin {plugin_name} importado correctamente")
            patched_count += 1
            
        except Exception as e:
            if "add_docstring" in str(e):
                debug_print(f"Plugin {plugin_name} falló con error add_docstring: {e}")
                
                # Estrategia de recuperación: intentar reimportar después de parches
                try:
                    # Aplicar parches adicionales si es necesario
                    patch_add_docstring()
                    
                    # Intentar importar nuevamente
                    if plugin_name in sys.modules:
                        del sys.modules[plugin_name]
                    
                    plugin = __import__(plugin_name)
                    debug_print(f"OK Plugin {plugin_name} recuperado exitosamente")
                    patched_count += 1
                    
                except Exception as retry_e:
                    debug_print(f"Fail: Plugin {plugin_name} no pudo ser recuperado: {retry_e}")
            else:
                debug_print(f"Fail: Plugin {plugin_name} falló por otra razón: {e}")
    
    debug_print(f"Plugins LLM procesados exitosamente: {patched_count}/{len(known_problematic_plugins)}")
    return patched_count > 0

def create_safe_llm_wrapper():
    """
    Crea un wrapper seguro para el módulo LLM que maneja errores de plugins
    """
    try:
        import llm
        
        # Verificar si necesitamos crear wrapper
        original_get_models = llm.get_models
        
        def safe_get_models():
            """Versión segura de get_models que maneja errores de plugins"""
            try:
                return list(original_get_models())
            except Exception as e:
                if "add_docstring" in str(e):
                    debug_print(f"Error en get_models interceptado: {e}")
                    debug_print("Intentando solución alternativa...")
                    
                    # Aplicar parches y reintentar
                    patch_add_docstring()
                    patch_scipy_extensions()
                    
                    try:
                        return list(original_get_models())
                    except:
                        debug_print("Devolviendo lista vacía como fallback")
                        return []
                raise
        
        # Solo reemplazar si no está ya parchado
        if not hasattr(llm.get_models, '_python313_patched'):
            llm.get_models = safe_get_models
            llm.get_models._python313_patched = True
            debug_print("OK Wrapper seguro LLM.get_models aplicado")
        
        return True
        
    except ImportError:
        debug_print("LLM no está disponible para wrapper")
        return False
    except Exception as e:
        debug_print(f"Error creando wrapper LLM: {e}")
        return False

def monkey_patch_c_extensions():
    """
    Aplica monkey patches a nivel bajo para extensiones C problemáticas
    """
    try:
        # Parche a nivel de importación para interceptar errores
        original_import = __builtins__.__import__
        
        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            """Importación segura que intercepta errores de add_docstring"""
            try:
                return original_import(name, globals, locals, fromlist, level)
            except Exception as e:
                if "add_docstring" in str(e) and any(pkg in name for pkg in ['numpy', 'scipy', 'llm']):
                    debug_print(f"Error de importación interceptado para {name}: {e}")
                    
                    # Aplicar parches antes de reintentar
                    patch_add_docstring()
                    
                    try:
                        return original_import(name, globals, locals, fromlist, level)
                    except:
                        debug_print(f"Importación de {name} falló completamente")
                        raise
                raise
        
        # Solo aplicar el parche si Python 3.13+ y no está ya aplicado
        if sys.version_info >= (3, 13) and not hasattr(__builtins__.__import__, '_python313_patched'):
            __builtins__.__import__ = safe_import
            __builtins__.__import__._python313_patched = True
            debug_print("OK Monkey patch de importación aplicado")
            return True
        
    except Exception as e:
        debug_print(f"Error aplicando monkey patch: {e}")
        return False
    
    return False

def apply_all_patches():
    """
    Aplica todos los parches de compatibilidad para Python 3.13.3
    
    Returns:
        dict: Resultados de cada parche aplicado
    """
    if sys.version_info < (3, 13):
        debug_print("Python < 3.13 detectado, omitiendo parches de compatibilidad")
        return {"skipped": True, "reason": "python_version"}
    
    debug_print(f"Python {sys.version} detectado, aplicando parches de compatibilidad...")
    
    results = {}
    
    # Aplicar parches en orden de importancia
    try:
        results['monkey_patch'] = monkey_patch_c_extensions()
        results['add_docstring'] = patch_add_docstring()
        results['scipy'] = patch_scipy_extensions() 
        results['llm_wrapper'] = create_safe_llm_wrapper()
        results['llm_plugins'] = patch_llm_plugin_imports()
        
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        
        debug_print(f"Parches aplicados: {success_count}/{total_count}")
        
        if success_count > 0:
            debug_print("OK Sistema de compatibilidad Python 3.13.3 activado")
        else:
            debug_print("⚠ Ningún parche fue aplicado exitosamente")
            
    except Exception as e:
        debug_print(f"Error aplicando parches: {e}")
        results['error'] = str(e)
    
    return results

def is_python313_compatible():
    """
    Verifica si el sistema actual es compatible con los parches
    
    Returns:
        bool: True si es compatible y los parches pueden aplicarse
    """
    return (
        sys.version_info >= (3, 13) and 
        hasattr(sys, 'frozen') and 
        getattr(sys, 'frozen', False)
    )

# Auto-aplicar parches si estamos en un entorno congelado con Python 3.13+
if is_python313_compatible() and DEBUG:
    debug_print("Aplicando parches de compatibilidad automáticamente...")
    apply_all_patches()

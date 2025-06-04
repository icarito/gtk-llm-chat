"""
Runtime hook para PyInstaller que soluciona incompatibilidades de NumPy
con Python 3.13 interceptando add_docstring a nivel muy bajo.
"""

import sys
import warnings

# Solo aplicar en Python 3.13+ y entornos congelados
if getattr(sys, 'frozen', False) and sys.version_info >= (3, 13):
    
    # Estrategia 1: Interceptar la función C add_docstring antes de que se use
    try:
        # Monkeypatch directo en el módulo sys para interceptar add_docstring
        original_add_docstring = None
        
        def create_safe_add_docstring(original_func):
            """Crea una versión segura de add_docstring."""
            def safe_add_docstring(func, docstring):
                # Normalizar docstring a string
                if docstring is None:
                    docstring = ""
                elif not isinstance(docstring, str):
                    try:
                        # Manejar bytes o otros tipos
                        if isinstance(docstring, bytes):
                            docstring = docstring.decode('utf-8', errors='replace')
                        else:
                            docstring = str(docstring) if docstring else ""
                    except Exception:
                        docstring = ""
                
                try:
                    return original_func(func, docstring)
                except TypeError as e:
                    if "should be a str" in str(e):
                        # Fallback directo
                        try:
                            func.__doc__ = docstring
                            return func
                        except Exception:
                            return func
                    raise
                except Exception:
                    # Para cualquier otro error, intentar asignación directa
                    try:
                        func.__doc__ = docstring
                        return func
                    except Exception:
                        return func
            
            return safe_add_docstring
        
        # Estrategia 2: Hook de importación más agresivo
        import builtins
        original_import = builtins.__import__
        
        def aggressive_numpy_patch_import(name, globals=None, locals=None, fromlist=(), level=0):
            """Hook de importación que patchea numpy de forma más agresiva."""
            
            # Verificar si se está importando algo relacionado con numpy
            numpy_related = (
                'numpy' in name or 
                (isinstance(fromlist, (list, tuple)) and any('numpy' in str(f) for f in fromlist)) or
                name.startswith('numpy') or
                name.endswith('numpy')
            )
            
            # Pre-patch antes de importar si es numpy
            if numpy_related:
                try:
                    # Intentar patchear add_docstring en el namespace global
                    import types
                    
                    # Buscar add_docstring en el módulo actual si existe
                    current_module = sys.modules.get(name)
                    if current_module:
                        if hasattr(current_module, 'add_docstring') and not hasattr(current_module.add_docstring, '_patched'):
                            current_module.add_docstring = create_safe_add_docstring(current_module.add_docstring)
                            current_module.add_docstring._patched = True
                            print(f"OK Pre-patched add_docstring in {name}")
                            
                except Exception as e:
                    pass  # Ignorar errores de pre-patch
            
            # Realizar importación normal
            try:
                module = original_import(name, globals, locals, fromlist, level)
            except Exception as e:
                if "add_docstring" in str(e) and "should be a str" in str(e):
                    print(f"⚠ Caught add_docstring error during import of {name}: {e}")
                    
                    # Intentar aplicar parche de emergencia
                    try:
                        # Buscar y patchear add_docstring en todos los módulos cargados
                        for mod_name, mod in sys.modules.items():
                            if mod and hasattr(mod, 'add_docstring') and not hasattr(mod.add_docstring, '_emergency_patched'):
                                try:
                                    mod.add_docstring = create_safe_add_docstring(mod.add_docstring)
                                    mod.add_docstring._emergency_patched = True
                                    print(f"OK Emergency patched add_docstring in {mod_name}")
                                except Exception:
                                    pass
                        
                        # Reintentar importación
                        module = original_import(name, globals, locals, fromlist, level)
                        print(f"OK Successfully imported {name} after emergency patch")
                        
                    except Exception as retry_e:
                        print(f"Fail: Failed to import {name} even after emergency patch: {retry_e}")
                        raise e  # Re-lanzar el error original
                else:
                    raise  # Re-lanzar otros errores
            
            # Post-patch después de importar exitosamente
            if numpy_related and module:
                try:
                    # Buscar add_docstring en el módulo importado y sus submódulos
                    modules_to_check = [module]
                    
                    # Agregar submódulos conocidos
                    if hasattr(module, '_core'):
                        modules_to_check.append(module._core)
                        if hasattr(module._core, 'overrides'):
                            modules_to_check.append(module._core.overrides)
                    
                    for mod in modules_to_check:
                        if mod and hasattr(mod, 'add_docstring') and not hasattr(mod.add_docstring, '_post_patched'):
                            mod.add_docstring = create_safe_add_docstring(mod.add_docstring)
                            mod.add_docstring._post_patched = True
                            print(f"OK Post-patched add_docstring in {getattr(mod, '__name__', 'unknown')}")
                            
                except Exception as e:
                    pass  # Ignorar errores de post-patch
            
            return module
        
        # Aplicar el hook de importación agresivo
        builtins.__import__ = aggressive_numpy_patch_import
        print("OK Aggressive NumPy Python 3.13 compatibility hook installed")
        
    except Exception as e:
        warnings.warn(f"Failed to install NumPy Python 3.13 compatibility hook: {e}", RuntimeWarning)

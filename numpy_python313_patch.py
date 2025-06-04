"""
Monkey patch para solucionar problemas de compatibilidad de NumPy con Python 3.13
en entornos congelados con PyInstaller.

El error "argument docstring of add_docstring should be a str" se produce cuando
NumPy intenta agregar docstrings pero recibe objetos no-string en Python 3.13.
"""

import sys
import warnings


def patch_numpy_add_docstring():
    """
    Aplica un monkey patch a la función add_docstring de NumPy para manejar
    argumentos no-string en Python 3.13.
    """
    try:
        # Solo aplicar el patch si estamos en Python 3.13+
        if sys.version_info < (3, 13):
            return
            
        # Intentar importar numpy
        import numpy
        
        # Verificar si numpy._core.overrides existe
        if hasattr(numpy, '_core') and hasattr(numpy._core, 'overrides'):
            overrides_module = numpy._core.overrides
        else:
            # Fallback para versiones más antiguas
            try:
                import numpy.core.overrides as overrides_module
            except ImportError:
                return
        
        # Verificar si add_docstring existe
        if not hasattr(overrides_module, 'add_docstring'):
            return
            
        # Guardar la función original
        original_add_docstring = overrides_module.add_docstring
        
        def patched_add_docstring(func, docstring):
            """
            Versión patcheada de add_docstring que maneja argumentos no-string.
            """
            try:
                # Asegurar que docstring sea un string
                if docstring is None:
                    docstring = ""
                elif not isinstance(docstring, str):
                    # Intentar convertir a string de forma segura
                    try:
                        docstring = str(docstring) if docstring else ""
                    except:
                        docstring = ""
                
                # Llamar a la función original con el docstring convertido
                return original_add_docstring(func, docstring)
                
            except Exception as e:
                # Si todo falla, emitir una advertencia pero no crashear
                warnings.warn(
                    f"add_docstring patch failed for {func}: {e}",
                    RuntimeWarning,
                    stacklevel=2
                )
                # Intentar asignar el docstring directamente como fallback
                try:
                    if hasattr(func, '__doc__'):
                        func.__doc__ = docstring
                except:
                    pass
                return func
        
        # Aplicar el patch
        overrides_module.add_docstring = patched_add_docstring
        
        print("OK Numpy add_docstring patch aplicado correctamente para Python 3.13")
        
    except Exception as e:
        # Si hay cualquier error en el patching, solo emitir una advertencia
        warnings.warn(
            f"No se pudo aplicar el patch de NumPy para Python 3.13: {e}",
            RuntimeWarning
        )


def apply_llm_compatibility_patches():
    """
    Aplica patches de compatibilidad para todos los plugins LLM en Python 3.13.
    """
    # Aplicar el patch principal de NumPy
    patch_numpy_add_docstring()
    
    # Lista de plugins LLM que pueden necesitar el patch
    llm_plugins = [
        'llm',
        'llm_groq', 
        'llm_gemini',
        'llm_openrouter',
        'llm_perplexity',
        'llm_anthropic',
        'llm_deepseek',
        'llm_grok'
    ]
    
    patched_count = 0
    
    for plugin in llm_plugins:
        try:
            # Intentar importar el plugin para forzar la aplicación del patch
            __import__(plugin)
            patched_count += 1
        except Exception as e:
            if "add_docstring" in str(e):
                print(f"⚠ Plugin {plugin} aún tiene problemas de add_docstring: {e}")
            else:
                print(f"ⓘ Plugin {plugin} no pudo ser importado (probablemente no instalado): {e}")
    
    print(f"OK Patches de compatibilidad aplicados a {patched_count} plugins LLM")


if __name__ == "__main__":
    print("Aplicando patches de compatibilidad NumPy/Python 3.13...")
    apply_llm_compatibility_patches()
    print("Patches aplicados.")

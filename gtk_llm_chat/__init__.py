"""
Módulo de inicialización del paquete gtk_llm_chat.
Aplica parches de compatibilidad necesarios antes de importar cualquier otra cosa.
"""

import sys

# Aplicar parches de compatibilidad Python 3.13 inmediatamente
if sys.version_info >= (3, 13) and getattr(sys, 'frozen', False):
    try:
        from . import python313_compatibility
        python313_compatibility.apply_all_patches()
    except Exception as e:
        print(f"Warning: Could not apply Python 3.13 compatibility patches: {e}")
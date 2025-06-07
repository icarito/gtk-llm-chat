"""
debug_utils.py - helpers puros sin dependencias de GTK ni gi
"""
import os

DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args, **kwargs):
    """Prints arguments if the global DEBUG flag is True.

    Args:
        *args: Variable length argument list to print.
        **kwargs: Arbitrary keyword arguments to print.

    Returns:
        None.
    """
    if DEBUG:
        print(*args, **kwargs)

"""
debug_utils.py - helpers puros sin dependencias de GTK ni gi
"""
import os

DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

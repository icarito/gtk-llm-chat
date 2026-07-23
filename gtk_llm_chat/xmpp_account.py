"""
xmpp_account.py - persistencia de la cuenta XMPP (spec 001).

El JID y el nombre del recurso van en un archivo JSON plano dentro del
directorio de usuario de la app (el mismo que usa `llm`, vía
platform_utils.ensure_user_dir_exists) — nunca en logs.db, que es
propiedad de `llm` (ver docs/data-model.md).

La contraseña NUNCA toca el disco: vive en el keyring del sistema
(Secret Service en Linux vía el paquete `keyring`, el mismo enfoque que
usa Gajim).
"""
import json
import os
import socket

import keyring

from .debug_utils import debug_print
from .platform_utils import ensure_user_dir_exists

KEYRING_SERVICE = 'gtk-llm-chat-xmpp'
ACCOUNT_FILENAME = 'xmpp_account.json'


def _account_file_path():
    user_dir = ensure_user_dir_exists()
    if not user_dir:
        return None
    return os.path.join(user_dir, ACCOUNT_FILENAME)


def save_account(jid: str, password: str, omemo_enabled: bool = False):
    """Guarda el JID en disco y la contraseña en el keyring del sistema."""
    path = _account_file_path()
    if not path:
        raise RuntimeError("No se pudo determinar el directorio de usuario")

    # Intentar cargar la configuración existente para mantener el label si ya existe
    existing_label = None
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
                existing_label = data.get('omemo_device_label')
        except Exception:
            pass

    # Generar label automático si se activa OMEMO por primera vez (sin label previo)
    if omemo_enabled and not existing_label:
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "localhost"
        existing_label = f"gtk-llm-chat on {hostname}"

    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'jid': jid,
            'omemo': omemo_enabled,
            'omemo_device_label': existing_label
        }, f, indent=2)

    keyring.set_password(KEYRING_SERVICE, jid, password)
    debug_print(f"xmpp_account: cuenta guardada para {jid} (password en keyring), OMEMO={omemo_enabled}, label={existing_label}")


def load_account():
    """Devuelve (jid, password) de la cuenta configurada, o None si no hay ninguna.

    Si el JID está en disco pero el keyring no tiene la contraseña
    (keyring reinstalado, backend distinto, etc.) se devuelve None: la
    cuenta se considera no utilizable hasta reconfigurarla.
    """
    path = _account_file_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as err:
        debug_print(f"xmpp_account: error leyendo {path}: {err}")
        return None
    jid = data.get('jid')
    if not jid:
        return None
    password = keyring.get_password(KEYRING_SERVICE, jid)
    if not password:
        debug_print(f"xmpp_account: JID {jid} en disco pero sin password en keyring")
        return None
    return jid, password


def is_omemo_enabled() -> bool:
    """Devuelve si OMEMO está habilitado para la cuenta configurada."""
    path = _account_file_path()
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            return bool(data.get('omemo', False) or data.get('omemo_enabled', False))
    except Exception:
        return False


def load_omemo_device_label() -> str:
    """Devuelve el label de dispositivo OMEMO actual o generado."""
    path = _account_file_path()
    if not path or not os.path.exists(path):
        return "gtk-llm-chat"
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            return data.get('omemo_device_label') or "gtk-llm-chat"
    except Exception:
        return "gtk-llm-chat"


def has_account() -> bool:
    return load_account() is not None


def delete_account():
    """Elimina la cuenta configurada (disco + keyring), si existe."""
    path = _account_file_path()
    if path and os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                jid = json.load(f).get('jid')
            if jid:
                try:
                    keyring.delete_password(KEYRING_SERVICE, jid)
                except keyring.errors.PasswordDeleteError:
                    pass
        finally:
            os.remove(path)

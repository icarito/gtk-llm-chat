"""
Cliente IPC multiplataforma para los applets de GTK-LLM-Chat
Solo usa D-Bus (GIO) en Linux, fallback en otras plataformas.
"""
import os
import sys
import subprocess


def open_conversation(conversation_id=None):
    """
    Envía un mensaje a la aplicación principal para abrir una conversación.
    En Linux usa D-Bus (GIO), en otras plataformas hace fallback.
    """
    if sys.platform != 'linux':
        # En Mac y Windows, fallback directo
        fallback_open_conversation(conversation_id)
        return False
    try:
        import gi
        gi.require_version('Gio', '2.0')
        gi.require_version('GLib', '2.0')
        from gi.repository import Gio, GLib
    except ImportError:
        print("GIO/GLib no disponible, usando método alternativo")
        fallback_open_conversation(conversation_id)
        return False
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        parameters = GLib.Variant('(s)', [conversation_id or ""])
        result = connection.call_sync(
            'org.fuentelibre.gtk_llm_Chat',
            '/org/fuentelibre/gtk_llm_Chat',
            'org.fuentelibre.gtk_llm_Chat',
            'OpenConversation',
            parameters,
            GLib.VariantType('()'),
            Gio.DBusCallFlags.NONE,
            -1,
            None
        )
        print("Conversación abierta con éxito mediante GIO")
        return True
    except Exception as e:
        print(f"Error al comunicarse mediante GIO: {e}")
        fallback_open_conversation(conversation_id)
        return False

def fallback_open_conversation(conversation_id=None):
    """
    Método alternativo para abrir conversación si falla D-Bus.
    Inicia la aplicación directamente usando subprocess.
    """
    cmd_args = []
    if conversation_id:
        cmd_args = ['--cid=' + str(conversation_id)]
    if getattr(sys, 'frozen', False):
        base = os.path.abspath(os.path.dirname(sys.argv[0]))
        executable = "gtk-llm-chat"
        if sys.platform == "win32":
            executable += ".exe"
        elif sys.platform == "linux" and os.environ.get('_PYI_ARCHIVE_FILE'):
            base = os.path.dirname(os.environ.get('_PYI_ARCHIVE_FILE'))
            if os.environ.get('APPIMAGE'):
                executable = 'AppRun'
        full_cmd = [os.path.join(base, executable)] + cmd_args
    else:
        executable = sys.executable
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_script = os.path.join(script_dir, "main.py")
        full_cmd = [executable, main_script] + cmd_args
    try:
        print(f"Iniciando aplicación con proceso: {full_cmd}")
        subprocess.Popen(full_cmd)
    except Exception as e:
        print(f"Error al iniciar la aplicación: {e}")

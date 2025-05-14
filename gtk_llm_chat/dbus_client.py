"""
Cliente D-Bus común para los applets de GTK-LLM-Chat
Proporciona funcionalidad D-Bus compartida para tk_llm_applet.py y gtk_llm_applet.py
Utiliza GIO/GObject directamente para la comunicación
"""
import os
import sys
import subprocess

# Intentar importar GIO/GObject para comunicación directa
try:
    import gi
    gi.require_version('Gio', '2.0')
    gi.require_version('GLib', '2.0')
    from gi.repository import Gio, GLib
    have_gio = True
except ImportError:
    print("Warning: GIO/GObject not available, direct communication will not work")
    have_gio = False


def open_conversation_dbus(conversation_id=None):
    """
    Envía un mensaje a la aplicación principal para abrir una conversación.
    Utiliza GIO directamente a través de GApplication.
    
    Args:
        conversation_id: ID de la conversación a abrir, o None para una nueva
        
    Returns:
        bool: True si se envió con éxito, False si se usó el método de respaldo
    """
    # Si GIO no está disponible, usar fallback inmediatamente
    if not have_gio:
        print("GIO no disponible, usando método alternativo")
        fallback_open_conversation(conversation_id)
        return False
        
    try:
        # Crear una conexión D-Bus a través de GIO
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        
        # Preparar los parámetros para la llamada
        parameters = GLib.Variant('(s)', [conversation_id or ""])
        
        # Llamar al método OpenConversation en la interfaz D-Bus
        result = connection.call_sync(
            'org.fuentelibre.ChatApplication',           # Nombre del bus
            '/org/fuentelibre/ChatApplication',          # Ruta del objeto
            'org.fuentelibre.ChatApplication',           # Interfaz
            'OpenConversation',                          # Método
            parameters,                                  # Parámetros
            GLib.VariantType('()'),                      # Tipo de retorno (vacío)
            Gio.DBusCallFlags.NONE,                      # Flags
            -1,                                          # Timeout (default)
            None                                         # Cancelable
        )
        
        print("Conversación abierta con éxito mediante GIO")
        return True
        
    except Exception as e:
        print(f"Error al comunicarse mediante GIO: {e}")
        # Intentar con una alternativa: GApplication directamente
        try:
            print("Intentando con GApplication.open_remote...")
            # Crear una instancia de GApplication para comunicación
            app = Gio.Application.new('org.fuentelibre.gtk_llm_Chat', 
                                      Gio.ApplicationFlags.IS_SERVICE)
            
            # Preparar los argumentos
            args = []
            if conversation_id:
                args = ['--cid', str(conversation_id)]
            
            # Convertir argumentos a formato GVariant
            arguments = GLib.Variant.new_strv(args)
            
            # Activar la aplicación remota
            app.open_remote(arguments, None)
            print("Aplicación activada mediante GApplication")
            return True
            
        except Exception as e2:
            print(f"Error al usar GApplication: {e2}")
            # Usar el método de fallback como último recurso
            fallback_open_conversation(conversation_id)
            return False


def fallback_open_conversation(conversation_id=None):
    """
    Método alternativo para abrir conversación si fallan los métodos de GIO/GApplication.
    Inicia la aplicación directamente usando subprocess.
    
    Args:
        conversation_id: ID de la conversación a abrir, o None para una nueva
    """
    # Preparar argumentos básicos
    cmd_args = []
    if conversation_id:
        cmd_args = ['--cid=' + str(conversation_id)]
    
    # Manejar caso de aplicación "congelada" (PyInstaller, etc.)
    if getattr(sys, 'frozen', False):
        # Aplicación empaquetada (PyInstaller)
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
        # Desarrollo - usar el intérprete Python actual
        executable = sys.executable
        # La ruta al módulo principal
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_script = os.path.join(script_dir, "main.py")
        full_cmd = [executable, main_script] + cmd_args
    
    try:
        print(f"Iniciando aplicación con proceso: {full_cmd}")
        subprocess.Popen(full_cmd)
    except Exception as e:
        print(f"Error al iniciar la aplicación: {e}")

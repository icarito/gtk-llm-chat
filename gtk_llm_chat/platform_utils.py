"""
platform_utils.py - utilidades multiplataforma para gtk-llm-chat
"""
import sys
import subprocess
import os

PLATFORM = sys.platform


def is_linux():
    return PLATFORM.startswith('linux')

def is_windows():
    return PLATFORM.startswith('win')

def is_mac():
    return PLATFORM == 'darwin'


def launch_tray_applet(config):
    """
    Lanza el applet de bandeja como subproceso usando pystray en todas las plataformas.
    """
    # Asume que tray_applet.py está en el mismo directorio que main.py
    applet_path = os.path.join(os.path.dirname(__file__), 'tray_applet.py')
    args = [sys.executable, applet_path]
    # Puedes pasar argumentos relevantes desde config si es necesario
    if config.get('cid'):
        args += ['--cid', config['cid']]
    subprocess.Popen(args)


def send_ipc_open_conversation(cid):
    """
    Envía una señal para abrir una conversación desde el applet a la app principal.
    En Linux usa D-Bus (Gio), en otros sistemas usa línea de comandos.
    """
    print(f"Enviando IPC para abrir conversación con CID: '{cid}'")
    
    # Asegurarse de que el cid sea un string o None
    if cid is not None and not isinstance(cid, str):
        print(f"ADVERTENCIA: El CID no es un string, es {type(cid)}")
        try:
            cid = str(cid)
        except:
            cid = None
    
    if is_linux():
        try:
            import gi
            gi.require_version('Gio', '2.0')
            gi.require_version('GLib', '2.0')
            from gi.repository import Gio, GLib
            
            # Asegurarnos de que el CID sea un string válido para D-Bus
            if cid is None:
                cid = ""
                
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            print(f"D-Bus: Conectado al bus, enviando mensaje OpenConversation con CID: '{cid}'")
            
            # Enviar la llamada D-Bus
            variant = GLib.Variant('(s)', (cid,))
            result = bus.call_sync(
                'org.fuentelibre.gtk_llm_Chat',
                '/org/fuentelibre/gtk_llm_Chat',
                'org.fuentelibre.gtk_llm_Chat',
                'OpenConversation',
                variant,
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
            print("D-Bus: Mensaje enviado correctamente")
            return True
        except Exception as e:
            print(f"Error enviando IPC D-Bus: {e}")
            print("Fallback a línea de comandos...")
    
    # Fallback para cualquier plataforma o si D-Bus falló
    print("Usando fallback por línea de comandos")
    exe = sys.executable
    main_path = os.path.join(os.path.dirname(__file__), 'main.py')
    cmd = [exe, main_path]
    if cid:
        cmd.append(f"--cid={cid}")
    
    print(f"Ejecutando comando: {cmd}")
    subprocess.Popen(cmd)

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

def is_frozen():
    return getattr(sys, 'frozen', False)


def launch_tray_applet(config):
    """
    Lanza el applet de bandeja
    """
    #try:
    from tray_applet import main
    main()
    #except Exception as e:
    #    if is_frozen():
    #        # Relanzar el propio ejecutable con --applet
    #        args = [sys.executable, "--applet"]
    #        print(f"[platform_utils] Error lanzando applet (frozen): {e}")
    #        # subprocess.Popen(args)
    #    else:
    #        # Ejecutar tray_applet.py con el intérprete
    #        applet_path = os.path.join(os.path.dirname(__file__), 'tray_applet.py')
    #        args = [sys.executable, applet_path]
    #        if config.get('cid'):
    #            args += ['--cid', config['cid']]
    #        print(f"[platform_utils] Lanzando applet (no frozen): {args}")
    #        subprocess.Popen(args)

def send_ipc_open_conversation(cid):
    """
    Envía una señal para abrir una conversación desde el applet a la app principal.
    En Linux usa D-Bus (Gio), en otros sistemas o si D-Bus falla, usa línea de comandos.
    """
    print(f"Enviando IPC para abrir conversación con CID: '{cid}'")
    if cid is not None and not isinstance(cid, str):
        print(f"ADVERTENCIA: El CID no es un string, es {type(cid)}")
        try:
            cid = str(cid)
        except Exception:
            cid = None

    if is_linux():
        try:
            import gi
            gi.require_version('Gio', '2.0')
            gi.require_version('GLib', '2.0')
            from gi.repository import Gio, GLib

            if cid is None:
                cid = ""
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            print(f"D-Bus: Conectado al bus, enviando mensaje OpenConversation con CID: '{cid}'")
            variant = GLib.Variant('(s)', (cid,))
            bus.call_sync(
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

    # Fallback multiplataforma o si D-Bus falló
    if is_frozen():
        exe = sys.executable
        args = [exe]
        if cid:
            args.append(f"--cid={cid}")
        print(f"Ejecutando fallback (frozen): {args}")
        subprocess.Popen(args)
    else:
        exe = sys.executable
        main_path = os.path.join(os.path.dirname(__file__), 'main.py')
        args = [exe, main_path]
        if cid:
            args.append(f"--cid={cid}")
        print(f"Ejecutando fallback (no frozen): {args}")
        subprocess.Popen(args)

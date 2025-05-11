"""
Gtk LLM Chat - A frontend for `llm`
"""
import argparse
import os
import sys
import time
import threading
import subprocess

from gi.repository import Gio

# Record start time if benchmarking
benchmark_startup = '--benchmark-startup' in sys.argv
start_time = time.time() if benchmark_startup else None


sys.path.append(os.path.dirname(os.path.abspath(__file__)))

TRAY_PROCESS = None

def parse_args(argv):
    """Parsea los argumentos de la línea de comandos"""
    parser = argparse.ArgumentParser(description='GTK Frontend para LLM')
    parser.add_argument('--cid', type=str,
                        help='ID de la conversación a continuar')
    parser.add_argument('-s', '--system', type=str, help='Prompt del sistema')
    parser.add_argument('-m', '--model', type=str, help='Modelo a utilizar')
    parser.add_argument('-c', '--continue-last', action='store_true',
                        help='Continuar última conversación')
    parser.add_argument('-t', '--template', type=str,
                        help='Template a utilizar')
    parser.add_argument('-p', '--param', nargs=2, action='append',
                        metavar=('KEY', 'VALUE'),
                        help='Parámetros para el template')
    parser.add_argument('-o', '--option', nargs=2, action='append',
                        metavar=('KEY', 'VALUE'),
                        help='Opciones para el modelo')
    parser.add_argument('-f', '--fragment', action='append',
                        metavar='FRAGMENT',
                        help='Fragmento (alias, URL, hash o ruta de archivo) para agregar al prompt')
    parser.add_argument('--benchmark-startup', action='store_true',
                        help='Mide el tiempo hasta que la ventana se muestra y sale.')
    parser.add_argument('--applet', action='store_true',
                        help='Start applet')


    # Parsear solo nuestros argumentos
    args = parser.parse_args(argv[1:])

    # Crear diccionario de configuración
    config = {
        'cid': args.cid,
        'system': args.system,
        'model': args.model,
        'continue_last': args.continue_last,
        'template': args.template,
        'params': args.param,
        'options': args.option,
        'fragments': args.fragment,
        'benchmark_startup': args.benchmark_startup,
        'start_time': start_time,
        'applet': args.applet
    }

    return config


def create_tray_icon():
    """Runs the tray icon in a subprocess to avoid mixing GTK3 and GTK4."""
    import subprocess
    subprocess.Popen([sys.executable, '-m', 'gtk_llm_chat.tk_llm_applet'])


def is_instance_running(app_id):
    """Check if an instance of the application is already running."""
    try:
        app = Gio.Application.new(app_id, Gio.ApplicationFlags.FLAGS_NONE)
        app.connect("activate", lambda _: print("Señal enviada a la instancia existente."))
        if not app.register():
            print("Otra instancia ya está en ejecución.")
            app.activate()  # Enviar señal a la instancia existente
            return True
    except Exception as e:
        print(f"Error al registrar la aplicación: {e}")
        return True
    return False

def launch_tray_applet():
    """Launch the tray applet in a separate subprocess."""
    global TRAY_PROCESS
    TRAY_PROCESS = subprocess.Popen([sys.executable, "gtk_llm_chat/gtk_llm_applet.py"])

def main(argv=None):
    """
    Aquí inicia todo
    """
    if argv is None:
        argv = sys.argv

    # Eliminar el lanzamiento del applet desde aquí
    # launch_tray_applet()

    # Continuar con la aplicación principal
    from chat_application import LLMChatApplication
    config = parse_args(argv)
    chat_app = LLMChatApplication(config=config)
    return chat_app.run()

if __name__ == "__main__":
    sys.exit(main())

    # Eliminar manejo redundante del proceso del applet
    # if TRAY_PROCESS:
    #     print("Terminando proceso del applet...")
    #     TRAY_PROCESS.terminate()
    #     try:
    #         TRAY_PROCESS.wait(timeout=5)
    #         print("Proceso terminado correctamente.")
    #     except subprocess.TimeoutExpired:
    #         print("Proceso no terminó a tiempo, matando a la fuerza.")
    #         TRAY_PROCESS.kill()
    #         TRAY_PROCESS.wait()
# flake8: noqa E402

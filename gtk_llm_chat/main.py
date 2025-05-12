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
from db_operations import ChatHistory

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

def main(argv=None):
    """
    Aquí inicia todo
    """
    if argv is None:
        argv = sys.argv

    # Crear configuración desde argumentos
    config = parse_args(argv)
    
    # Procesar la bandera continue_last si está presente
    if config.get('continue_last'):
        try:
            chat_history = ChatHistory()
            last_conversation = chat_history.get_last_conversation()
            if last_conversation and last_conversation.get('id'):
                config['cid'] = last_conversation['id']
                print(f"Continuando última conversación con ID: {config['cid']}")
            else:
                print("No se encontró una conversación anterior para continuar")
        except Exception as e:
            print(f"Error al obtener la última conversación: {e}")
    
    # Imprimir configuración para depuración
    print(f"Iniciando aplicación con configuración: {config}")

    # Crear la aplicación y ejecutarla
    from chat_application import LLMChatApplication
    chat_app = LLMChatApplication(config)
    
    # Si hay argumentos de línea de comandos para el CID, model, etc., pasarlos explícitamente
    cmd_args = []
    if config.get('cid'):
        cmd_args.append(f"--cid={config['cid']}")
    if config.get('model'):
        cmd_args.append(f"--model={config['model']}")
    if config.get('template'):
        cmd_args.append(f"--template={config['template']}")
    
    if cmd_args:
        return chat_app.run(cmd_args)
    else:
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

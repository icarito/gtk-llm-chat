"""
Gtk LLM Chat - A frontend for `llm`
"""
import argparse
import os
import sys
import time

# Record start time if benchmarking
benchmark_startup = '--benchmark-startup' in sys.argv
start_time = time.time() if benchmark_startup else None


sys.path.append(os.path.dirname(os.path.abspath(__file__)))


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


def main(argv=None):
    """
    Aquí inicia todo
    """
    if argv is None:
        argv = sys.argv
    
    # Parsear argumentos ANTES de que GTK los vea
    argv = [arg for arg in argv if not arg.startswith(
        ('--gtk', '--gdk', '--display'))]
    config = parse_args(argv)

    # Pasar solo los argumentos de GTK a la aplicación
    gtk_args = [arg for arg in sys.argv if arg.startswith(
        ('--gtk', '--gdk', '--display'))]
    gtk_args.insert(0, sys.argv[0])  # Agregar el nombre del programa

    if config['applet']:
        from gtk_llm_applet import main
        main()
        sys.exit(0)

    # Crear y ejecutar la aplicación
    from chat_application import LLMChatApplication
    app = LLMChatApplication()
    app.config = config
    return app.run(gtk_args)


if __name__ == "__main__":
    sys.exit(main())

# flake8: noqa E402

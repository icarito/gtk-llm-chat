import llm
import click
import time


@llm.hookimpl
def register_commands(cli):

    @cli.command(name="gtk-applet")
    def run_applet():
        """Runs the applet"""
        from gtk_llm_chat.gtk_llm_applet import main
        main()

    @cli.command(name="gtk-chat")
    @click.option("--cid", type=str,
                  help='ID de la conversación a continuar')
    @click.option('-s', '--system', type=str, help='Prompt del sistema')
    @click.option('-m', '--model', type=str, help='Modelo a utilizar')
    @click.option(
        "-c",
        "--continue-last",
        is_flag=True,
        help="Continuar la última conversación.",
    )
    @click.option('-t', '--template', type=str,
                  help='Template a utilizar')
    @click.option(
        "-p",
        "--param",
        multiple=True,
        type=(str, str),
        metavar='KEY VALUE',
        help="Parámetros para el template",
    )
    @click.option(
        "-o",
        "--option",
        multiple=True,
        type=(str, str),
        metavar='KEY VALUE',
        help="Opciones para el modelo",
    )
    @click.option(
        "-f",
        "--fragment",
        multiple=True,
        type=str,
        metavar='FRAGMENT',
        help="Fragmento (alias, URL, hash o ruta de archivo) para agregar al prompt",
    )
    @click.option(
            "--benchmark-startup",
        is_flag=True,
        help="Mide el tiempo hasta que la ventana se muestra y sale.",
    )
    def run_gui(cid, system, model, continue_last, template, param, option, fragment, benchmark_startup):
        """Runs a GUI for the chatbot"""
        # Record start time if benchmarking
        start_time = time.time() if benchmark_startup else None

        from gtk_llm_chat.chat_application import LLMChatApplication
        # Crear diccionario de configuración
        config = {
            'cid': cid,
            'system': system,
            'model': model,
            'continue_last': continue_last,
            'template': template,
            'params': param,
            'options': option,
            'fragments': fragment, # Add fragments to the config
            'benchmark_startup': benchmark_startup, # Add benchmark flag
            'start_time': start_time, # Pass start time if benchmarking
        }

        # Crear y ejecutar la aplicación
        app = LLMChatApplication()
        app.config = config
        return app.run()

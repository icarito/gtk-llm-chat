import llm
import click


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
    def run_gui(cid, system, model, continue_last, template, param, option):
        """Runs a GUI for the chatbot"""
        from gtk_llm_chat.chat_application import LLMChatApplication
        # Crear diccionario de configuración
        config = {
            'cid': cid,
            'system': system,
            'model': model,
            'continue_last': continue_last,
            'template': template,
            'params': param,
            'options': option
        }

        # Crear y ejecutar la aplicación
        app = LLMChatApplication()
        app.config = config
        return app.run()

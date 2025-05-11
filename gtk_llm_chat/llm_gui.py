import llm
import click
import time


@llm.hookimpl
def register_commands(cli):

    @cli.command(name="gtk-applet")
    def run_applet():
        """Runs the applet"""
        try:
            from gtk_llm_applet import main
        except Exception as e:
            from tk_llm_applet import main
        finally:
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
        from gtk_llm_chat.db_operations import ChatHistory
        
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
        
        # Procesar la bandera continue_last si está presente
        if continue_last:
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

        # Crear y ejecutar la aplicación
        app = LLMChatApplication(config)
        
        # Transformar la configuración en argumentos de línea de comandos
        cmd_args = []
        if config.get('cid'):
            cmd_args.append(f"--cid={config['cid']}")
        if config.get('model'):
            cmd_args.append(f"--model={config['model']}")
        if config.get('template'):
            cmd_args.append(f"--template={config['template']}")
        
        if cmd_args:
            return app.run(cmd_args)
        else:
            return app.run()

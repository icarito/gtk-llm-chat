"""
Manejo simplificado del proceso LLM como subproceso.
"""
from datetime import datetime
from gi.repository import GLib, Gio, GObject


class Message:
    """
    Representa un mensaje
    """

    def __init__(self, content, sender="user", timestamp=None):
        self.content = content
        self.sender = sender
        self.timestamp = timestamp or datetime.now()


class LLMProcess(GObject.Object):
    """
    Maneja el subproceso LLM y emite señales con las respuestas
    """
    __gsignals__ = {
        # Emite cada token de respuesta
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emite el nombre del modelo
        'model-name': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emite cuando está listo para nueva entrada
        'ready': (GObject.SignalFlags.RUN_LAST, None, ()),
        # Emite cando llm reporta un error
        'error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emite cuando el proceso termina
        'process-terminated': (GObject.SignalFlags.RUN_LAST, None, (int,))
    }

    def __init__(self, config=None):
        GObject.Object.__init__(self)
        self.process = None
        self.is_generating = False
        self.launcher = None
        self.config = config or {}
        self.token_queue = []  # Cola para almacenar tokens
        self.reading_response = False
        self._error_buffer = ""
        self.process_finished = False

    def initialize(self):
        """Inicia el proceso LLM"""
        try:
            if not self.process:
                print("Iniciando proceso LLM...")
                self.launcher = Gio.SubprocessLauncher.new(
                    Gio.SubprocessFlags.STDIN_PIPE |
                    Gio.SubprocessFlags.STDOUT_PIPE |
                    Gio.SubprocessFlags.STDERR_PIPE
                )

                # Construir comando con argumentos
                cmd = ['llm', 'chat']

                # Agregar argumentos básicos
                if self.config.get('cid'):
                    cmd.extend(['--cid', self.config['cid']])
                elif self.config.get('continue_last'):
                    cmd.append('-c')

                if self.config.get('system'):
                    cmd.extend(['-s', self.config['system']])

                if self.config.get('model'):
                    cmd.extend(['-m', self.config['model']])

                # Agregar template y parámetros
                if self.config.get('template'):
                    cmd.extend(['-t', self.config['template']])

                if self.config.get('params'):
                    for param in self.config['params']:
                        cmd.extend(['-p', param[0], param[1]])

                # Agregar opciones del modelo
                if self.config.get('options'):
                    for opt in self.config.get('options'):
                        cmd.extend(['-o', opt[0], opt[1]])

                try:
                    print(f"Ejecutando comando: {' '.join(cmd)}")
                    self.process = self.launcher.spawnv(cmd)
                    self.process.wait_async(None, self._on_process_finished)
                except GLib.Error as e:
                    print(f"Error al iniciar LLM: {str(e)}")
                    return

                # Configurar streams
                self.stdin = self.process.get_stdin_pipe()
                self.stdout = self.process.get_stdout_pipe()
                self.stderr = self.process.get_stderr_pipe()

                # Leer mensaje inicial
                self.stdout.read_bytes_async(
                    4096,
                    GLib.PRIORITY_DEFAULT,
                    None,
                    self._handle_initial_output
                )

                self.stderr.read_bytes_async(
                    4096,
                    GLib.PRIORITY_DEFAULT,
                    None,
                    self._handle_error
                )
        except Exception as e:
            print(f"Error inesperado: {str(e)}")

    def send_message(self, messages):
        """Ejecuta el LLM con los mensajes dados"""
        if not self.process:
            self.initialize()
            return

        try:
            self.is_generating = True

            # Enviar solo el último mensaje
            if messages:
                # Enviar mensaje sin formateo especial
                message = messages[-1]
                stdin_data = f"{message.sender}: {message.content}\n"
                if "\n" in message.content:
                    stdin_data = f"""!multi
                    {message.sender}: {message.content}
                    !end\n"""
                self.stdin.write_bytes(GLib.Bytes(stdin_data.encode("utf-8")))

            self._read_response(self._emit_response)

        except Exception as e:
            print(f"Error ejecutando LLM: {e}")
            self.is_generating = False

    def _handle_initial_output(self, stdout, result):
        """Maneja la salida inicial del proceso"""
        try:
            bytes_read = stdout.read_bytes_finish(result)
            if bytes_read:
                text = bytes_read.get_data().decode('utf-8')
                # Extraer el nombre del modelo si está presente
                if "Chatting with" in text:
                    model_name = text.split("Chatting with")[
                        1].split("\n")[0].strip()
                    print(f"Usando modelo: {model_name}")
                    self.emit('model-name', model_name)

                # Continuar leyendo la respuesta
                self._read_response(self._emit_response)

        except Exception as e:
            print(f"Error leyendo salida inicial: {e}")

    def _read_response(self, callback, accumulated=""):
        """Lee la respuesta del LLM de forma incremental"""
        if not self.reading_response and not self.process_finished:
            self.reading_response = True
            # Leer bytes de forma asíncrona
            self.stdout.read_bytes_async(
                1024,
                GLib.PRIORITY_DEFAULT,
                None,
                self._handle_response,
                callback
            )

    def _emit_response(self, text):
        """Emite la señal de respuesta"""
        # Agregar token a la cola
        self.token_queue.append(text)
        # Emitir señal con el token
        self.emit('response', text)

    def _handle_response(self, stdout, result, user_data):
        """Maneja cada token de la respuesta"""
        callback = user_data
        try:
            bytes_read = stdout.read_bytes_finish(result)
            if not self.process_finished:
                if bytes_read:
                    text = bytes_read.get_data().decode('utf-8')

                    # Detectar si el modelo está listo para nueva entrada
                    if text.strip() == ">" or \
                            text.endswith("\n> ") or \
                            text.endswith("> "):
                        self.emit('ready')
                    else:
                        # Emitir el token recibido
                        callback(text)
                        print(text, end="", flush=True)

                    self.reading_response = False
                    self._read_response(callback)
                else:
                    self.is_generating = False
        except Exception as e:
            print(f"Error leyendo respuesta: {e}")
            self.reading_response = False
            self.is_generating = False

    def _handle_error(self, stderr, result):
        """Maneja los errores del proceso"""
        try:
            bytes_read = stderr.read_bytes_finish(result)
            if bytes_read:
                chunk = bytes_read.get_data().decode('utf-8')
                self._error_buffer += chunk
                if chunk:
                    stderr.read_bytes_async(
                        4096,
                        GLib.PRIORITY_DEFAULT,
                        None,
                        self._handle_error
                    )
                else:
                    self.emit('error', self._error_buffer)
                    self._error_buffer = ""
        except Exception as e:
            print(f"Error leyendo salida de error: {e}")

    def _on_process_finished(self, process, result):
        """Maneja la terminación del subproceso."""
        exit_status = process.wait_finish(result)
        self.process_finished = True
        self.emit('process-terminated', exit_status)

    def cancel(self):
        """Cancela la generación actual"""
        self.is_generating = False
        if self.process:
            self.process.force_exit()
            self.is_generating = False
            try:
                self.stdin.close()
            except Exception:
                pass
            self.token_queue.clear()  # Limpiar la cola de tokens


GObject.type_register(LLMProcess)

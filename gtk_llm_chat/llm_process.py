import gi
from gi.repository import GLib, Gio
from datetime import datetime

from gi.repository import GObject


class Message:
    def __init__(self, content, sender="user", timestamp=None):
        self.content = content
        self.sender = sender
        self.timestamp = timestamp or datetime.now()


class LLMProcess(GObject.Object):
    __gsignals__ = {
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'model-name': (GObject.SignalFlags.RUN_LAST, None, (str,))
    }

    def __init__(self, config=None):
        GObject.Object.__init__(self)
        self.process = None
        self.is_running = False
        self.launcher = None
        self.config = config or {}

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
                    for opt in self.config['options']:
                        cmd.extend(['-o', opt[0], opt[1]])

                try:
                    print(f"Ejecutando comando: {' '.join(cmd)}")
                    self.process = self.launcher.spawnv(cmd)
                except GLib.Error as e:
                    print(f"Error al iniciar LLM: {str(e)}")
                    return

                # Configurar streams
                self.stdin = self.process.get_stdin_pipe()
                self.stdout = self.process.get_stdout_pipe()

                # Leer mensaje inicial
                self.stdout.read_bytes_async(
                    4096,
                    GLib.PRIORITY_DEFAULT,
                    None,
                    self._handle_initial_output
                )
        except Exception as e:
            print(f"Error inesperado: {str(e)}")

    def execute(self, messages):
        """Ejecuta el LLM con los mensajes dados"""
        if not self.process:
            self.initialize()
            return

        try:
            self.is_running = True

            # Enviar solo el último mensaje
            if messages:
                stdin_data = f"{messages[-1].sender}: {messages[-1].content}\n"
                print(f"Enviando al LLM:\n{stdin_data}")
                self.stdin.write_bytes(GLib.Bytes(stdin_data.encode('utf-8')))

            self._read_response(self._emit_response)

        except Exception as e:
            print(f"Error ejecutando LLM: {e}")
            self.is_running = False

    def _handle_initial_output(self, stdout, result):
        """Maneja la salida inicial del proceso"""
        try:
            bytes_read = stdout.read_bytes_finish(result)
            if bytes_read:
                text = bytes_read.get_data().decode('utf-8')
                if "Chatting with" in text:
                    model_name = text.split("Chatting with")[
                        1].split("\n")[0].strip()
                    print(f"Usando modelo: {model_name}")
                    end_of_model_name = text.find("\n")
                    text = text[end_of_model_name + 1:].strip()
                    self.emit('model-name', model_name)
                else:
                    self._read_response(self._emit_response)
                    print(
                        f"No se encontró 'Chatting with' en la salida inicial: {text}")
        except Exception as e:
            print(f"Error leyendo salida inicial: {e}")

    def _read_response(self, callback, accumulated=""):
        """Lee la respuesta del LLM de forma incremental"""
        if not self.is_running:
            print("No se está ejecutando, saliendo de _read_response")
            return

        self.stdout.read_bytes_async(
            1024,  # tamaño del buffer
            GLib.PRIORITY_DEFAULT,
            None,  # cancelable
            self._handle_response,
            (callback, accumulated)
        )

    def _emit_response(self, text):
        """Emite la señal de respuesta"""
        self.emit('response', text)

    def _handle_response(self, stdout, result, user_data):
        """Maneja cada chunk de la respuesta"""
        callback, accumulated = user_data
        try:
            bytes_read = stdout.read_bytes_finish(result)
            if bytes_read:
                text = bytes_read.get_data().decode('utf-8')
                accumulated += text

                # Solo actualizar si hay contenido
                if accumulated.strip():
                    # Si este chunk es solo '>' y no hay más datos, es el prompt final
                    if text.strip() == ">" and accumulated.endswith("\n> "):
                        # Quitar el último '>'
                        final_text = accumulated.strip()[:-1].strip()
                        if final_text:
                            callback(final_text)
                            print(text)
                        self.is_running = False
                        return
                    callback(accumulated.strip())
                    print(text, end="")
                    # print(f"Emitiendo respuesta: {accumulated.strip()}")
                    self.emit('response', accumulated.strip())

                self._read_response(callback, accumulated)
            else:
                # No hay más datos para leer
                if accumulated.strip():
                    callback(accumulated.strip())
                self.is_running = False

        except Exception as e:
            print(f"Error leyendo respuesta: {e}")
            self.is_running = False

    def cancel(self):
        """Cancela la generación actual"""
        self.is_running = False
        if self.process:
            self.process.force_exit()


GObject.type_register(LLMProcess)

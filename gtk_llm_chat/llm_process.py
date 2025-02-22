import gi
from gi.repository import GLib, Gio
from datetime import datetime  # Asegurando que datetime esté correctamente importado

class Message:
    def __init__(self, content, sender="user", timestamp=None):
        self.content = content
        self.sender = sender
        self.timestamp = timestamp or datetime.now()

class LLMProcess:
    def __init__(self, config=None):
        self.process = None
        self.is_running = False
        self.launcher = None
        self.config = config or {}
        self.stdout = None  # Asegurando que stdout esté inicializado

    def initialize(self, callback):
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
                    callback(None, f"Error al iniciar LLM: {str(e)}")
                    return

                # Configurar streams
                self.stdin = self.process.get_stdin_pipe()
                self.stdout = self.process.get_stdout_pipe()

                # Leer mensaje inicial
                self.stdout.read_bytes_async(
                    4096,
                    GLib.PRIORITY_DEFAULT,
                    None,
                    self._handle_initial_output,
                    callback
                )
        except Exception as e:
            callback(None, f"Error inesperado: {str(e)}")

    def _handle_initial_output(self, stdout, result, callback):
        """Maneja la salida inicial del proceso"""
        try:
            bytes_read = stdout.read_bytes_finish(result)
            if bytes_read:
                text = bytes_read.get_data().decode('utf-8')
                if "Chatting with" in text:
                    model_name = text.split("Chatting with")[1].split("\n")[0].strip()
                    print(f"Usando modelo: {model_name}")
                    callback(model_name)
                    return
            callback(None)
        except Exception as e:
            print(f"Error leyendo salida inicial: {e}")
            callback(None)

    def execute(self, messages, callback):
        """Ejecuta el LLM con los mensajes dados"""
        if not self.process:
            self.initialize(lambda _: self.execute(messages, callback))
            return

        try:
            self.is_running = True

            # Enviar solo el último mensaje
            if messages:
                stdin_data = f"{messages[-1].sender}: {messages[-1].content}\n"
                print(f"Enviando al LLM:\n{stdin_data}")
                self.stdin.write_bytes(GLib.Bytes(stdin_data.encode('utf-8')))

            # Leer respuesta
            self._read_response(callback)
        except Exception as e:
            print(f"Error ejecutando LLM: {e}")
            callback(None)
            self.is_running = False

    def _read_response(self, callback, accumulated=""):
        """Lee la respuesta del LLM de forma incremental"""
        if not self.is_running:
            return

        self.stdout.read_bytes_async(
            1024,  # tamaño del buffer
            GLib.PRIORITY_DEFAULT,
            None,  # cancelable
            self._handle_response,
            (callback, accumulated)
        )

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
                    # Si este chunk es solo '>' y no hay más datos es el prompt final
                    if text.strip() == ">":
                        final_text = accumulated.strip()[:-1].strip()  # Quitar el último '>'
                        if final_text:
                            callback(final_text)
                        self.is_running = False
                        return
                    callback(accumulated.strip())

                self._read_response(callback, accumulated)
            else:
                # No hay más datos para leer
                if accumulated.strip():
                    callback(accumulated.strip())
                self.is_running = False
        except Exception as e:
            print(f"Error leyendo respuesta: {e}")
            callback(None)
            self.is_running = False
        self.is_running = False
import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

import asyncio
import subprocess
import threading
from datetime import datetime
from gi.repository import Gtk, Adw, Gio, Gdk, GLib


class Message:
    def __init__(self, content, sender="user", timestamp=None):
        self.content = content
        self.sender = sender
        self.timestamp = timestamp or datetime.now()


class MessageWidget(Gtk.Box):
    """Widget para mostrar un mensaje individual"""

    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        # Configurar el estilo según el remitente
        is_user = message.sender == "user"
        self.add_css_class('message')
        self.add_css_class('user-message' if is_user else 'assistant-message')

        # Configurar alineación
        self.set_halign(Gtk.Align.END if is_user else Gtk.Align.START)
        self.set_margin_start(50 if is_user else 6)
        self.set_margin_end(6 if is_user else 50)
        self.set_margin_top(3)
        self.set_margin_bottom(3)

        # Crear el contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('message-content')

        # Agregar el texto del mensaje
        label = Gtk.Label(label=message.content)
        label.set_wrap(True)
        label.set_selectable(True)
        label.set_xalign(0)
        message_box.append(label)

        # Agregar timestamp
        time_label = Gtk.Label(
            label=message.timestamp.strftime("%H:%M"),
            css_classes=['timestamp']
        )
        time_label.set_halign(Gtk.Align.END)
        message_box.append(time_label)

        self.append(message_box)

        # Guardar referencia al label para actualizaciones
        self.content_label = label

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.content_label.set_text(new_content)


class LLMProcess:
    def __init__(self):
        self.process = None
        self.is_running = False
        self.launcher = None

    def initialize(self, callback):
        """Inicia el proceso LLM"""
        if not self.process:
            print("Iniciando proceso LLM...")
            self.launcher = Gio.SubprocessLauncher.new(
                Gio.SubprocessFlags.STDIN_PIPE | 
                Gio.SubprocessFlags.STDOUT_PIPE |
                Gio.SubprocessFlags.STDERR_PIPE
            )
            self.process = self.launcher.spawnv(['llm', 'chat'])
            
            # Configurar streams
            self.stdin = self.process.get_stdin_pipe()
            self.stdout = self.process.get_stdout_pipe()
            
            # Leer mensaje inicial
            self.stdout.read_bytes_async(
                4096,  # tamaño del buffer
                GLib.PRIORITY_DEFAULT,
                None,  # cancelable
                self._handle_initial_output,
                callback
            )

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
                if text.strip() == ">":  # Prompt encontrado
                    if accumulated:  # Solo llamar callback si hay respuesta
                        callback(accumulated.strip())
                    self.is_running = False
                    return

                accumulated += text
                if accumulated.strip():  # Solo actualizar si hay contenido
                    callback(accumulated.strip())
                self._read_response(callback, accumulated)
            else:
                if accumulated.strip():  # Solo llamar callback si hay respuesta
                    callback(accumulated.strip())
                self.is_running = False

        except Exception as e:
            print(f"Error leyendo respuesta: {e}")
            callback(None)
            self.is_running = False

    def cancel(self):
        """Cancela la generación actual"""
        self.is_running = False
        if self.process:
            self.process.force_exit()


class LLMChatApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.gnome.LLMChat",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )

    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self)
        window.present()


class LLMChatWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Inicializar LLMProcess
        self.llm = LLMProcess()
        
        # Configurar la ventana principal
        self.set_title("LLM Chat")
        self.set_default_size(600, 700)

        # Inicializar la cola de mensajes (solo para mostrar)
        self.message_queue = []
        
        # Mantener referencia al último mensaje enviado
        self.last_message = None

        # Contenedor principal
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # ScrolledWindow para el historial de mensajes
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Contenedor para mensajes
        self.messages_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.messages_box.set_margin_top(12)
        self.messages_box.set_margin_bottom(12)
        self.messages_box.set_margin_start(12)
        self.messages_box.set_margin_end(12)
        scroll.set_child(self.messages_box)

        # Área de entrada
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.set_margin_top(6)
        input_box.set_margin_bottom(6)
        input_box.set_margin_start(6)
        input_box.set_margin_end(6)

        # TextView para entrada
        self.input_text = Gtk.TextView()
        self.input_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_text.set_pixels_above_lines(3)
        self.input_text.set_pixels_below_lines(3)
        self.input_text.set_pixels_inside_wrap(3)
        self.input_text.set_hexpand(True)

        # Configurar altura dinámica
        buffer = self.input_text.get_buffer()
        buffer.connect('changed', self._on_text_changed)

        # Configurar atajo de teclado Enter
        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._on_key_pressed)
        self.input_text.add_controller(key_controller)

        # Botón enviar
        send_button = Gtk.Button(label="Enviar")
        send_button.connect('clicked', self._on_send_clicked)
        send_button.add_css_class('suggested-action')

        # Ensamblar la interfaz
        input_box.append(self.input_text)
        input_box.append(send_button)

        main_box.append(scroll)
        main_box.append(input_box)

        self.set_content(main_box)

        # Agregar CSS provider
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data("""
            .message { padding: 8px; }
            .message-content { padding: 6px; }
            
            .user-message .message-content {
                background-color: @blue_3;
                border-radius: 12px 12px 0 12px;
            }
            
            .assistant-message .message-content {
                background-color: @card_bg_color;
                border-radius: 12px 12px 12px 0;
            }
            
            .timestamp {
                font-size: 0.8em;
                opacity: 0.7;
            }
        """.encode())

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Agregar soporte para cancelación
        self.current_message_widget = None
        
        # Configurar atajo para cancelación
        cancel_controller = Gtk.EventControllerKey()
        cancel_controller.connect('key-pressed', self._on_cancel_pressed)
        self.add_controller(cancel_controller)

        # Iniciar el LLM al arrancar
        self.llm.initialize(self._handle_initial_response)

    def _on_text_changed(self, buffer):
        lines = buffer.get_line_count()
        # Ajustar altura entre 3 y 6 líneas
        new_height = min(max(lines * 20, 60), 120)
        self.input_text.set_size_request(-1, new_height)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Return:
            # Permitir Shift+Enter para nuevas líneas
            if not (state & Gdk.ModifierType.SHIFT_MASK):
                self._on_send_clicked(None)
                return True
        return False

    def _sanitize_input(self, text):
        """Sanitiza el texto de entrada"""
        return text.strip()

    def _add_message_to_queue(self, content, sender="user"):
        """Agrega un nuevo mensaje a la cola y lo muestra"""
        if content := self._sanitize_input(content):
            message = Message(content, sender)
            self.message_queue.append(message)
            
            if sender == "user":
                self.last_message = message

            # Crear y mostrar el widget del mensaje
            message_widget = MessageWidget(message)
            self.messages_box.append(message_widget)

            # Auto-scroll al último mensaje
            self._scroll_to_bottom()

            print(f"[{message.timestamp}] {message.sender}: {message.content}")
            return True
        return False

    def _on_send_clicked(self, button):
        buffer = self.input_text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(),
                             buffer.get_end_iter(), True)
        
        if self._add_message_to_queue(text):
            buffer.set_text("")
            # Usar GLib.idle_add para ejecutar la tarea asíncrona
            GLib.idle_add(self._start_llm_task)
    
    def _start_llm_task(self):
        """Inicia la tarea del LLM"""
        print("Iniciando tarea LLM...")
        
        # Crear widget vacío para la respuesta
        self.current_message_widget = MessageWidget(
            Message("", sender="assistant"))
        self.messages_box.append(self.current_message_widget)
        
        # Solo enviar el último mensaje
        if self.last_message:
            self.llm.execute([self.last_message], self._handle_llm_response)
        return False

    def _handle_initial_response(self, model_name):
        """Maneja la respuesta inicial del LLM"""
        if model_name:
            self._add_message_to_queue(
                f"Iniciando chat con {model_name}",
                "system"
            )

    def _handle_llm_response(self, response):
        """Maneja la respuesta del LLM"""
        if response is not None:
            self.current_message_widget.update_content(response)
            self._scroll_to_bottom()
        else:
            if self.current_message_widget:
                self.current_message_widget.get_parent().remove(self.current_message_widget)
                self.current_message_widget = None

    def _on_cancel_pressed(self, controller, keyval, keycode, state):
        """Maneja la cancelación con Ctrl+C"""
        if keyval == Gdk.KEY_c and state & Gdk.ModifierType.CONTROL_MASK:
            if self.llm.is_running:
                self.llm.cancel()
            return True
        return False

    def _scroll_to_bottom(self):
        """Desplaza la vista al último mensaje"""
        def scroll_after():
            adj = self.messages_box.get_parent().get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
        # Programar el scroll para después de que se actualice el layout
        GLib.idle_add(scroll_after)


def main():
    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

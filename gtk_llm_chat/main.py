import sys
import gi
import argparse

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

import asyncio
import subprocess
import threading
from datetime import datetime
from gi.repository import Gtk, Adw, Gio, Gdk, GLib, GObject
from gtk_llm_chat.llm_process import Message, LLMProcess
from gtk_llm_chat.markdownview import MarkdownView


class ErrorWidget(Gtk.Box):
    """Widget para mostrar mensajes de error"""
    
    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.add_css_class('error-message')
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(3)
        self.set_margin_bottom(3)
        
        # Icono de advertencia
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.add_css_class('error-icon')
        self.append(icon)
        
        # Contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('error-content')
        
        # Texto del error
        label = Gtk.Label(label=message)
        label.set_wrap(True)
        label.set_xalign(0)
        message_box.append(label)
        
        self.append(message_box)


class MessageWidget(Gtk.Box):
    """Widget para mostrar un mensaje individual"""

    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        # Configurar el estilo según el remitente
        is_user = message.sender == "user"
        self.add_css_class('message')
        self.add_css_class('user-message' if is_user else 'assistant-message')

        # Crear un contenedor con margen para centrar el contenido
        margin_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        margin_box.set_hexpand(True)
        
        # Crear el contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('message-content')
        message_box.set_hexpand(True)
        
        # Agregar espaciadores flexibles a los lados
        if is_user:
            margin_box.append(Gtk.Box(hexpand=True))  # Espaciador izquierdo
            margin_box.append(message_box)
            margin_box.append(Gtk.Box(hexpand=False))  # Espaciador derecho pequeño
        else:
            margin_box.append(Gtk.Box(hexpand=False))  # Espaciador izquierdo pequeño
            margin_box.append(message_box)
            margin_box.append(Gtk.Box(hexpand=True))  # Espaciador derecho

        # Quitar el prefijo "user:" si existe
        content = message.content
        if is_user and content.startswith("user:"):
            content = content[5:].strip()
            
        # Usar MarkdownView para el contenido
        self.content_view = MarkdownView()
        self.content_view.set_hexpand(True)
        self.content_view.set_markdown(content)
        message_box.append(self.content_view)

        # Agregar timestamp
        time_label = Gtk.Label(
            label=message.timestamp.strftime("%H:%M"),
            css_classes=['timestamp']
        )
        time_label.set_halign(Gtk.Align.END)
        message_box.append(time_label)

        self.append(margin_box)

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.content_view.set_markdown(new_content)
        # Asegurar que se haga scroll al actualizar el contenido
        window = self.get_root()
        if isinstance(window, LLMChatWindow):
            window._scroll_to_bottom()


def parse_args(argv):
    """Parsea los argumentos de la línea de comandos"""
    parser = argparse.ArgumentParser(description='GTK Frontend para LLM')
    parser.add_argument('--cid', type=str, help='ID de la conversación a continuar')
    parser.add_argument('-s', '--system', type=str, help='Prompt del sistema')
    parser.add_argument('-m', '--model', type=str, help='Modelo a utilizar')
    parser.add_argument('-c', '--continue-last', action='store_true', 
                       help='Continuar última conversación')
    parser.add_argument('-t', '--template', type=str, help='Template a utilizar')
    parser.add_argument('-p', '--param', nargs=2, action='append', 
                       metavar=('KEY', 'VALUE'), help='Parámetros para el template')
    parser.add_argument('-o', '--option', nargs=2, action='append',
                       metavar=('KEY', 'VALUE'), help='Opciones para el modelo')
    
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
        'options': args.option
    }
    
    return config


class LLMChatApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.gnome.LLMChat",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.config = None
        self.chat_history = None
        
        # Agregar manejador de señales
        import signal
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
        print("\nCerrando aplicación...")
        self.quit()

    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self, config=self.config)
        window.present()
        window.input_text.grab_focus()  # Enfocar el cuadro de entrada

        if self.config and self.config.get('cid'):
            from gtk_llm_chat.db_operations import ChatHistory
            self.chat_history = ChatHistory()
            try:
                history = self.chat_history.get_conversation_history(self.config['cid'])
                # Aquí deberías implementar la lógica para mostrar el historial
                # en tu interfaz gráfica
                for entry in history:
                    # Asumiendo que tienes un método para mostrar mensajes
                    window.display_message(
                        entry['prompt'],
                        is_user=True
                    )
                    window.display_message(
                        entry['response'],
                        is_user=False
                    )
            except ValueError as e:
                print(f"Error: {e}")
                return

    def do_startup(self):
        # Llamar al método padre usando do_startup
        Adw.Application.do_startup(self)
        
        # Configurar acciones
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

    def on_about_activate(self, action, param):
        """Muestra el diálogo Acerca de"""
        about = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            application_name="LLM Chat",
            application_icon="dialog-information-symbolic",
            developer_name="Sebastian Silva",
            version="1.0",
            developers=["Sebastian Silva <sebastian@fuentelibre.org>"],
            copyright="© 2024 Sebastian Silva"
        )
        about.present()

    def do_shutdown(self):
        """Limpia recursos antes de cerrar la aplicación"""
        print("Cerrando conexiones...")
        if self.chat_history:
            self.chat_history.close()
        
        # Obtener la ventana activa y cerrar el LLM si está corriendo
        window = self.get_active_window()
        if window and hasattr(window, 'llm'):
            if window.llm.is_running:
                window.llm.cancel()
        
        # Llamar al método padre
        Adw.Application.do_shutdown(self)


class LLMChatWindow(Adw.ApplicationWindow):
    def __init__(self, config=None, **kwargs):
        super().__init__(**kwargs)
        
        # Conectar señal de cierre de ventana
        self.connect('close-request', self._on_close_request)
        
        # Asegurar que config no sea None
        self.config = config or {}
        
        # Inicializar LLMProcess con la configuración
        self.llm = LLMProcess(self.config)
        
        # Mantener referencia a la clase Message
        self.Message = Message
        
        # Configurar la ventana principal
        title = self.config.get('template') or "LLM Chat"  # Asegurar que title nunca sea None
        self.set_title(title)
        self.set_default_size(600, 700)
        
        # Inicializar la cola de mensajes
        self.message_queue = []
        
        # Mantener referencia al último mensaje enviado
        self.last_message = None
        
        # Crear header bar
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle.new(title, "Iniciando...")
        header.set_title_widget(self.title_widget)
        
        # Botón de menú
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        
        # Crear menú
        menu = Gio.Menu.new()
        menu.append("Acerca de", "app.about")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        # Contenedor principal
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(header)

        # Contenedor para el chat
        chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
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

        chat_box.append(scroll)
        chat_box.append(input_box)
        
        main_box.append(chat_box)
        
        self.set_content(main_box)
        
        # Agregar CSS provider
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data("""
            .message { 
                padding: 8px;
            }
            
            .message-content { 
                padding: 6px;
                min-width: 400px;
            }
            
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
            
            .error-message {
                background-color: alpha(@error_color, 0.1);
                border-radius: 6px;
                padding: 8px;
            }
            
            .error-icon {
                color: @error_color;
            }
            
            .error-content {
                padding: 3px;
            }
            
            textview {
                background: none;
                color: inherit;
                padding: 3px;
            }
            
            textview text {
                background: none;
            }
            
            .user-message textview text {
                color: white;
            }
            
            .user-message textview text selection {
                background-color: rgba(255,255,255,0.3);
                color: white;
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

        # Configurar atajo para Escape
        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect('key-pressed', self._on_escape_pressed)
        self.add_controller(escape_controller)

        # Iniciar el LLM al arrancar
        self.llm.initialize()

        # Conectar la señal de respuesta del LLM
        self.llm.connect('response', self._on_llm_response)

        # Conectar la señal de nombre del modelo del LLM
        self.llm.connect('model-name', self._on_llm_model_name)

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
            message = self.Message(content, sender)
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
            self.Message("", sender="assistant"))
        self.messages_box.append(self.current_message_widget)
        
        # Solo enviar el último mensaje
        if self.last_message:
            self.llm.execute([self.last_message])
        return

    def _show_error(self, message):
        """Muestra un mensaje de error en el chat"""
        error_widget = ErrorWidget(message)
        self.messages_box.append(error_widget)
        self._scroll_to_bottom()

    def _handle_initial_response(self, model_name):
        """Maneja la respuesta inicial del LLM"""
        if model_name:
            self.title_widget.set_subtitle(model_name)
        else:
            self._show_error("No se pudo iniciar el chat con el modelo")
            self.title_widget.set_subtitle("Sin conexión")

    def _on_llm_model_name(self, llm_process, model_name):
        """Maneja la señal de nombre del modelo del LLM"""
        self._handle_initial_response(model_name)

    def _handle_llm_response(self, response):
        """Maneja la respuesta del LLM"""
        if response is None:
            if self.current_message_widget:
                self.current_message_widget.get_parent().remove(self.current_message_widget)
                self.current_message_widget = None
            self._show_error("Error al generar respuesta. Intente nuevamente.")
        else:
            self.current_message_widget.update_content(response)
            self._scroll_to_bottom()

    def _on_llm_response(self, llm_process, response):
        """Maneja la señal de respuesta del LLM"""
        if self.current_message_widget:
            self.current_message_widget.update_content(response)
            self._scroll_to_bottom()

    def _on_cancel_pressed(self, controller, keyval, keycode, state):
        """Maneja la cancelación con Ctrl+C"""
        if keyval == Gdk.KEY_c and state & Gdk.ModifierType.CONTROL_MASK:
            if self.llm.is_running:
                self.llm.cancel()
            return True
        return False

    def _on_escape_pressed(self, controller, keyval, keycode, state):
        """Maneja la tecla Escape"""
        if keyval == Gdk.KEY_Escape:
            self.minimize()
            return True
        return False

    def _scroll_to_bottom(self):
        """Desplaza la vista al último mensaje"""
        def scroll_after():
            scroll = self.messages_box.get_parent()
            adj = scroll.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False  # Importante para que no se repita
        # Programar el scroll para después de que se actualice el layout
        GLib.timeout_add(50, scroll_after)  # Pequeño delay para asegurar que el layout está actualizado

    def display_message(self, content, is_user=True):
        """Muestra un mensaje en la ventana de chat"""
        message = self.Message(content, "user" if is_user else "assistant")
        message_widget = MessageWidget(message)
        self.messages_box.append(message_widget)
        GLib.idle_add(self._scroll_to_bottom)

    def _on_close_request(self, window):
        """Maneja el cierre de la ventana de manera elegante"""
        if self.llm.is_running:
            self.llm.cancel()
        return False  # Permite que la ventana se cierre


def main():
    # Parsear argumentos ANTES de que GTK los vea
    argv = [arg for arg in sys.argv if not arg.startswith(('--gtk', '--gdk', '--display'))]
    config = parse_args(argv)
    
    # Pasar solo los argumentos de GTK a la aplicación
    gtk_args = [arg for arg in sys.argv if arg.startswith(('--gtk', '--gdk', '--display'))]
    gtk_args.insert(0, sys.argv[0])  # Agregar el nombre del programa
    
    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    app.config = config
    return app.run(gtk_args)


if __name__ == "__main__":
    sys.exit(main())

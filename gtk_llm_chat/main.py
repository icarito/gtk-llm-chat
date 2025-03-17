"""
Gtk LLM Chat - A frontend for `llm`
"""
import argparse
import os
import json
import re
import signal
import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory
from markdownview import MarkdownView
from llm_process import Message, LLMProcess



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
            # Espaciador derecho pequeño
            margin_box.append(Gtk.Box(hexpand=False))
        else:
            # Espaciador izquierdo pequeño
            margin_box.append(Gtk.Box(hexpand=False))
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
    """
    Clase para una instancia de un chat
    """

    def __init__(self):
        super().__init__(
            application_id="org.fuentelibre.gtk_llm_Chat",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )
        self.config = {}
        self.chat_history = None

        # Agregar manejador de señales
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
        print("\nCerrando aplicación...")
        self.quit()

    def do_startup(self):
        # Llamar al método padre usando do_startup
        Adw.Application.do_startup(self)

        # Configurar el icono de la aplicación
        self._setup_icon()

        # Configurar acciones
        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self.on_rename_activate)
        self.add_action(rename_action)

        delete_action = Gio.SimpleAction.new("delete", None)
        delete_action.connect("activate", self.on_delete_activate)
        self.add_action(delete_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

        self.set_accels_for_action("app.rename", ["<Alt>R"])

    def _setup_icon(self):
        """Configura el ícono de la aplicación"""
        # Establecer directorio de búsqueda
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(current_dir)

    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self, config=self.config)

        # Establecer el ícono por nombre (sin extensión .svg)
        window.set_icon_name("org.fuentelibre.gtk_llm_Chat")
        window.present()
        window.input_text.grab_focus()  # Enfocar el cuadro de entrada

        if self.config and (self.config.get('cid')
                            or self.config.get('continue_last')):
            self.chat_history = ChatHistory()
            if not self.config.get('cid'):
                conversation = self.chat_history.get_last_conversation()
                if conversation:
                    self.config['cid'] = conversation['id']
                    self.config['name'] = conversation['name']
            else:
                conversation = self.chat_history.get_conversation(
                    self.config['cid'])
                if conversation:
                    self.config['name'] = conversation['name']
            name = self.config.get('name')
            if name:  
                window.set_conversation_name(name.strip().removeprefix("user: "))
            try:
                history = self.chat_history.get_conversation_history(
                    self.config['cid'])
                for entry in history:
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

    def on_rename_activate(self, action, param):
        """Renombra la conversación actual"""
        window = self.get_active_window()
        window.header.set_title_widget(window.title_entry)
        window.title_entry.grab_focus()

    def on_delete_activate(self, action, param):
        """Elimina la conversación actual"""
        dialog = Gtk.MessageDialog(
            transient_for=self.get_active_window(),
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="¿Está seguro que desea eliminar la conversación?"
        )
        def on_delete_response(dialog, response):
            if response == Gtk.ResponseType.YES and self.chat_history and self.config.get('cid'):
                self.chat_history.delete_conversation(self.config['cid'])
                self.quit()
            dialog.destroy()

        dialog.connect("response", on_delete_response)
        dialog.present()

    def on_about_activate(self, action, param):
        """Muestra el diálogo Acerca de"""
        about = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            application_name="Gtk LLM Chat",
            application_icon="org.fuentelibre.gtk_llm_Chat",
            website="https://github.com/icarito/gtk_llm_chat",
            comments="Un frontend para LLM",
            license_type=Gtk.License.GPL_3_0,
            developer_name="Sebastian Silva",
            version="1.0",
            developers=["Sebastian Silva <sebastian@fuentelibre.org>"],
            copyright="© 2024 Sebastian Silva"
        )
        about.present()

    def do_shutdown(self):
        """Limpia recursos antes de cerrar la aplicación"""
        if self.chat_history:
            self.chat_history.close()

        # Obtener la ventana activa y cerrar el LLM si está corriendo
        window = self.get_active_window()
        if window and hasattr(window, 'llm'):
            if window.llm.is_generating:
                window.llm.cancel()

        # Llamar al método padre
        Adw.Application.do_shutdown(self)


class LLMChatWindow(Adw.ApplicationWindow):
    """
    A chat window
    """

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
        # Asegurar que title nunca sea None
        title = self.config.get('template') or "LLM Chat"
        self.title_entry = Gtk.Entry()
        self.title_entry.set_hexpand(True)
        self.title_entry.set_text(title)
        self.title_entry.connect('activate', self._on_save_title)
        self.set_title(title)

        focus_controller = Gtk.EventControllerKey()
        focus_controller.connect("key-pressed", self._cancel_set_title)
        self.title_entry.add_controller(focus_controller)

        self.set_default_size(600, 700)

        # Inicializar la cola de mensajes
        self.message_queue = []

        # Mantener referencia al último mensaje enviado
        self.last_message = None

        # Crear header bar
        self.header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle.new(title, "Iniciando...")
        self.header.set_title_widget(self.title_widget)

        # Botón de menú
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")

        # Crear menú
        menu = Gio.Menu.new()

        # Crear item "Renombrar"
        menu.append("Renombrar", "app.rename")

        # Crear item "Eliminar" con ícono - TODO Needs workaround GNOME attitude XXX
        #delete_item = Gio.MenuItem.new("Eliminar", "app.delete")
        #delete_icon = Gio.ThemedIcon.new_with_default_fallbacks("edit-delete")
        #delete_item.set_icon(delete_icon)
        menu.append("Eliminar", "app.delete")

        # Crear item "Acerca de"
        menu.append("Acerca de", "app.about")

        # Crear un popover para el menú
        popover = Gtk.PopoverMenu()
        menu_button.set_popover(popover)
        popover.set_menu_model(menu)
        

        # Rename button
        rename_button = Gtk.Button()
        rename_button.set_icon_name("document-edit-symbolic")
        rename_button.connect('clicked', 
                              lambda x: self.get_application().on_rename_activate(None, None))

        self.header.pack_end(menu_button)
        self.header.pack_end(rename_button)

        # Contenedor principal
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(self.header)

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
        self.send_button = Gtk.Button(label="Enviar")
        self.send_button.connect('clicked', self._on_send_clicked)
        self.send_button.add_css_class('suggested-action')

        # Ensamblar la interfaz
        input_box.append(self.input_text)
        input_box.append(self.send_button)

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

        # Variable para acumular la respuesta
        self.accumulated_response = ""

        # Iniciar el LLM al arrancar
        self.llm.initialize()

        # Conectar la señal de respuesta del LLM
        self.llm.connect('response', self._on_llm_response)

        # Conectar la señal de nombre del modelo del LLM
        self.llm.connect('ready', self._on_llm_ready)

        # Conectar la señal de nombre del modelo del LLM
        self.llm.connect('model-name', self._on_llm_model_name)

        # Conectar los errres
        self.llm.connect("error", lambda llm, msg: self._show_error(msg))

        # Si el proceso termina, bloqueemos la entrada
        self.llm.connect("process-terminated", lambda llm,
                         e: self.set_enabled(False))

    def set_conversation_name(self, title):
        """Establece el título de la ventana"""
        self.title_widget.set_title(title)
        self.title_entry.set_text(title)
        self.set_title(title)

    def _on_save_title(self, widget):
        app = self.get_application()
        app.chat_history.set_conversation_title(
            self.config.get('cid'), self.title_entry.get_text())
        self.header.set_title_widget(self.title_widget)
        new_title = self.title_entry.get_text()

        self.title_widget.set_title(new_title)
        self.set_title(new_title)
    
    def _cancel_set_title(self, controller, keyval, keycode, state):
        """Cancela la edición y restaura el título anterior"""
        if keyval == Gdk.KEY_Escape:
            self.header.set_title_widget(self.title_widget)
            self.title_entry.set_text(self.title_widget.get_title())

    def set_enabled(self, enabled):
        """Habilita o deshabilita la entrada de texto"""
        self.input_text.set_sensitive(enabled)
        self.send_button.set_sensitive(enabled)

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

            print(f"\n\n{message.sender}: {message.content}\n")
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

        # Crear widget vacío para la respuesta
        self.accumulated_response = ""  # Reiniciar la respuesta acumulada
        self.current_message_widget = MessageWidget(
            self.Message("", sender="assistant"))
        self.messages_box.append(self.current_message_widget)

        # Solo enviar el último mensaje

        if self.last_message:
            self.llm.send_message([self.last_message])
        return

    def _show_error(self, message):
        """Muestra un mensaje de error en el chat"""
        print(message, file=sys.stderr)
        if self.current_message_widget and self.current_message_widget in self.messages_box.get_children():
            self.messages_box.remove(self.current_message_widget)
            self.current_message_widget = None
        if message.startswith("Traceback"):
            message = message.split("\n")[-2]
            # Let's see if we find some json in the message
            try:
                json_part = re.search(r"{.*}", message).group()
                error = json.loads(json_part.replace("'", '"')
                                            .replace('None', 'null'))
                message = error.get('error').get('message')
            except json.JSONDecodeError:
                pass
        error_widget = ErrorWidget(message)
        self.messages_box.append(error_widget)
        self._scroll_to_bottom()

    def _on_llm_model_name(self, llm_process, model_name):
        """Maneja la señal de nombre del modelo del LLM"""
        self.title_widget.set_subtitle(model_name)
        self.config['model'] = model_name

    def _on_llm_ready(self, llm_process):
        """Maneja la señal de que el LLM está listo para nueva entrada"""
        self.input_text.grab_focus()  # Enfocar el cuadro de entrada


    def _on_llm_response(self, llm_process, response):
        """Maneja la señal de respuesta del LLM"""
        # Obtener el contenido actual y agregar el nuevo token
        if not self.current_message_widget:
            return

        # Actualizar el widget con la respuesta acumulada
        self.accumulated_response += response

        self.current_message_widget.update_content(self.accumulated_response)
        self._scroll_to_bottom(False)

    def _scroll_to_bottom(self, force=True):
        """Desplaza la vista al último mensaje"""
        scroll = self.messages_box.get_parent()
        adj = scroll.get_vadjustment()
        def scroll_after():
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        # Pequeño delay para asegurar que el layout está actualizado
        if force or adj.get_value() == adj.get_upper() - adj.get_page_size():
            GLib.timeout_add(50, scroll_after)

    def display_message(self, content, is_user=True):
        """Muestra un mensaje en la ventana de chat"""
        message = self.Message(content, "user" if is_user else "assistant")
        message_widget = MessageWidget(message)
        self.messages_box.append(message_widget)
        GLib.idle_add(self._scroll_to_bottom)

    def _on_close_request(self, window):
        """Maneja el cierre de la ventana de manera elegante"""
        if self.llm.is_generating:
            self.llm.cancel()
        sys.exit()
        return False  # Permite que la ventana se cierre


def main():
    """
    Aquí inicia todo
    """
    # Parsear argumentos ANTES de que GTK los vea
    argv = [arg for arg in sys.argv if not arg.startswith(
        ('--gtk', '--gdk', '--display'))]
    config = parse_args(argv)

    # Pasar solo los argumentos de GTK a la aplicación
    gtk_args = [arg for arg in sys.argv if arg.startswith(
        ('--gtk', '--gdk', '--display'))]
    gtk_args.insert(0, sys.argv[0])  # Agregar el nombre del programa

    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    app.config = config
    return app.run(gtk_args)


if __name__ == "__main__":
    sys.exit(main())

# flake8: noqa E402

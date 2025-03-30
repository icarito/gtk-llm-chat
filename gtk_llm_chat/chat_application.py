import gi
import json
import os
import re
import signal
import sys
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext

_ = gettext.gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient
from widgets import Message, MessageWidget, ErrorWidget
from db_operations import ChatHistory


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
        try:
            self.llm = LLMClient(self.config)
        except Exception as e:
            # TODO: Mostrar error de inicialización en la UI de forma más
            # elegante
            print(f"Error fatal al inicializar LLMClient: {e}")
            # Podríamos cerrar la app o mostrar un diálogo aquí
            sys.exit(1)

        # Configurar la ventana principal
        # Asegurar que title nunca sea None
        # Keep "LLM Chat" as it is generally understood
        title = self.config.get('template') or _("LLM Chat")
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
        self.title_widget = Adw.WindowTitle.new(title, _("Initializing..."))

        # Obtener y mostrar el ID del modelo en el subtítulo
        model_id = self.llm.get_model_id()
        if model_id:
            self.title_widget.set_subtitle(model_id)

        self.header.set_title_widget(self.title_widget)

        # Botón de menú
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")

        # Crear menú
        menu = Gio.Menu.new()
        menu.append(_("Rename"), "app.rename")
        menu.append(_("Delete"), "app.delete")
        menu.append(_("About"), "app.about")

        # Crear un popover para el menú
        popover = Gtk.PopoverMenu()
        menu_button.set_popover(popover)
        popover.set_menu_model(menu)

        # Rename button
        rename_button = Gtk.Button()
        rename_button.set_icon_name("document-edit-symbolic")
        rename_button.connect('clicked',
                              lambda x: self.get_application()
                              .on_rename_activate(None, None))

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
        self.send_button = Gtk.Button(label=_("Send"))
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

        # Ya no se necesita inicializar explícitamente LLMClient

        # Conectar las nuevas señales de LLMClient
        self.llm.connect('response', self._on_llm_response)
        self.llm.connect('error', self._on_llm_error)  # Use dedicated method
        self.llm.connect('finished', self._on_llm_finished)

        # Eliminar conexiones a señales antiguas
        # self.llm.connect('ready', self._on_llm_ready)
        # self.llm.connect('model-name', self._on_llm_model_name)
        # self.llm.connect("process-terminated", ...)

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
            message = Message(content, sender)
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
        text = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        )
        sanitized_text = self._sanitize_input(text)

        if sanitized_text:
            # Añadir mensaje a la cola ANTES de limpiar el buffer
            self._add_message_to_queue(sanitized_text, sender="user")
            buffer.set_text("")
            # Deshabilitar entrada y empezar tarea LLM
            self.set_enabled(False)
            # Pasar el texto sanitizado directamente
            GLib.idle_add(self._start_llm_task, sanitized_text)

    def _start_llm_task(self, prompt_text):
        """Inicia la tarea del LLM con el prompt dado."""

        # Crear widget vacío para la respuesta
        self.accumulated_response = ""  # Reiniciar la respuesta acumulada
        # Usar la clase Message importada
        self.current_message_widget = MessageWidget(
            Message("", sender="assistant")
        )
        self.messages_box.append(self.current_message_widget)

        # Enviar el prompt usando LLMClient
        self.llm.send_message(prompt_text)

        # Devolver False para que idle_add no se repita
        return GLib.SOURCE_REMOVE

    def _on_llm_error(self, llm_client, message):
        """Muestra un mensaje de error en el chat"""
        print(message, file=sys.stderr)
        # Verificar si el widget actual existe y es hijo del messages_box
        if self.current_message_widget is not None:
            is_child = (self.current_message_widget.get_parent() ==
                        self.messages_box)
            # Si es hijo, removerlo
            if is_child:
                self.messages_box.remove(self.current_message_widget)
                self.current_message_widget = None
        if message.startswith("Traceback"):
            message = message.split("\n")[-2]
            # Let's see if we find some json in the message
            try:
                match = re.search(r"{.*}", message)
                if match:
                    json_part = match.group()
                    error = json.loads(json_part.replace("'", '"')
                                                .replace('None', 'null'))
                    message = error.get('error').get('message')
            except json.JSONDecodeError:
                pass
        error_widget = ErrorWidget(message)
        self.messages_box.append(error_widget)
        self._scroll_to_bottom()

    # _on_llm_model_name y _on_llm_ready ya no son necesarios con LLMClient

    def _on_llm_finished(self, llm_client, success: bool):
        """Maneja la señal 'finished' de LLMClient."""
        print(f"LLM finished. Success: {success}")
        # Habilitar la entrada de nuevo, independientemente del éxito/error
        # ya que el proceso ha terminado.
        # El error ya se mostró si success es False.
        self.set_enabled(True)
        # Opcional: Enfocar input si fue exitoso?
        if success:
            # Guardar en el historial si la respuesta fue exitosa
            app = self.get_application()
            cid = self.config.get('cid')
            model_id = self.llm.get_model_id()  # Obtener model_id
            # Si no teníamos un CID (nueva conversación) y el cliente LLM ya tiene uno
            # (porque la primera respuesta se procesó y guardó), lo guardamos.
            if not cid and self.llm.get_conversation_id():
                new_cid = self.llm.get_conversation_id()
                self.config['cid'] = new_cid
                print(f"Nueva conversación creada con ID: {new_cid}")
                # Asegurarse que chat_history esté inicializado si es una nueva conv
                if not app.chat_history:
                    app.chat_history = ChatHistory()
                # Generar nombre predeterminado y crear registro en 'conversations'
                default_name = _("New Conversation")  # Default initial name
                if self.last_message:
                    prompt_words = self.last_message.content.split()
                    # Usar las primeras 5 palabras como nombre, o menos si son pocas
                    default_name = " ".join(prompt_words[:5])
                    if len(prompt_words) > 5:
                        default_name += _("...")  # Indicate it's a summary

                # Llamar a la nueva función para crear la entrada en conversations
                # Es importante hacerlo ANTES de add_history_entry
                app.chat_history\
                    .create_conversation_if_not_exists(new_cid, default_name)

                # Actualizar título de la ventana con el nombre predeterminado
                self.set_conversation_name(default_name)

                # Actualizar la variable local cid para el guardado posterior
                cid = new_cid

            if app.chat_history and cid and self.last_message and model_id:
                try:
                    app.chat_history.add_history_entry(
                        cid,
                        self.last_message.content,
                        self.accumulated_response,
                        model_id  # Pasar model_id
                    )
                except Exception as e:
                    # Manejar posible error al guardar (opcional)
                    print(f"Error al guardar en historial: {e}")

            self.input_text.grab_focus()

    def _on_llm_response(self, llm_client, response):
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
        message = Message(content, "user" if is_user else "assistant")
        message_widget = MessageWidget(message)
        self.messages_box.append(message_widget)
        GLib.idle_add(self._scroll_to_bottom)

    def _on_close_request(self, window):
        """Maneja el cierre de la ventana de manera elegante"""
        # LLMClient.cancel() ya verifica internamente si está generando
        self.llm.cancel()
        sys.exit()
        return False  # Permite que la ventana se cierre


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

        # Agregar manejafrom markdownview import MarkdownViewdor de señales
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        """Maneja la señal SIGINT (Ctrl+C) de manera elegante"""
        print("\nCerrando aplicación...")
        self.quit()

    def do_startup(self):
        # Llamar al método padre usando do_startup
        Adw.Application.do_startup(self)

        # Inicializar gettext
        APP_NAME = "gtk-llm-chat"
        # Usar ruta absoluta para asegurar que se encuentre el directorio 'po'
        base_dir = os.path.dirname(__file__)
        LOCALE_DIR = os.path.abspath(os.path.join(base_dir, '..', 'po'))
        try:
            # Intentar establecer solo la categoría de mensajes
            locale.setlocale(locale.LC_MESSAGES, '')
        except locale.Error as e:
            print(f"Advertencia: No se pudo establecer la configuración regional: {e}")
        gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
        gettext.textdomain(APP_NAME)

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
                window.set_conversation_name(
                    name.strip().removeprefix("user: "))
            try:
                history = self.chat_history.get_conversation_history(
                    self.config['cid'])
                # Cargar el historial en el LLMClient para mantener contexto
                if history:
                    window.llm.load_history(history)
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
            text=_("Are you sure you want to delete the conversation?")
        )

        def on_delete_response(dialog, response):
            if (response == Gtk.ResponseType.YES
                    and self.chat_history
                    and self.config.get('cid')):
                self.chat_history.delete_conversation(self.config['cid'])
                self.quit()
            dialog.destroy()

        dialog.connect("response", on_delete_response)
        dialog.present()

    def on_about_activate(self, action, param):
        """Muestra el diálogo Acerca de"""
        about = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            # Keep "Gtk LLM Chat" as the application name
            application_name=_("Gtk LLM Chat"),
            application_icon="org.fuentelibre.gtk_llm_Chat",
            website="https://github.com/icarito/gtk_llm_chat",
            comments=_("A frontend for LLM"),
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
            # LLMClient.cancel() ya verifica internamente si está generando
            window.llm.cancel()

        # Llamar al método padre
        Adw.Application.do_shutdown(self)

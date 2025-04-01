import gi
import json
import os
import re
import signal
import sys
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, Gdk, GLib
import locale
import gettext

_ = gettext.gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_client import LLMClient
from widgets import Message, MessageWidget, ErrorWidget
from db_operations import ChatHistory


class LLMChatWindow(Gtk.Window):
    """
    A chat window
    """

    def __init__(self, config=None, **kwargs):
        super().__init__(**kwargs)

        # Conectar señal de cierre de ventana
        self.connect('delete-event', self._on_close_request)

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

        # Reemplazamos el controlador por conexión directa de señales en Gtk 3
        self.title_entry.connect("key-press-event", self._on_key_press)

        self.set_default_size(600, 700)

        # Inicializar la cola de mensajes
        self.message_queue = []

        # Mantener referencia al último mensaje enviado
        self.last_message = None
        
        self.headerbar = Gtk.HeaderBar()
        # Acceder al método desde la aplicación, no desde la ventana
        self.set_titlebar(self.headerbar)
        self.set_title("LLM Chat")

        # Contenedor principal
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # No header in GTK3, title is enough

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
        scroll.add(self.messages_box)

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
        # Menu Bar for GTK3
        menubar = Gtk.MenuBar()
        main_box.pack_start(menubar, False, False, 0)

        # File Menu
        filemenu = Gtk.Menu()
        filem = Gtk.MenuItem(_("File"))
        filem.set_submenu(filemenu)
        menubar.append(filem)

        # Rename Item
        rename_item = Gtk.MenuItem(_("Rename"))
        rename_item.connect('activate', self._on_menu_rename_activate)
        filemenu.append(rename_item)

        # Delete Item
        delete_item = Gtk.MenuItem(_("Delete"))
        delete_item.connect('activate', self._on_menu_delete_activate)
        filemenu.append(delete_item)

        # Help Menu
        helpmenu = Gtk.Menu()
        helpm = Gtk.MenuItem(_("Help"))
        helpm.set_submenu(helpmenu)
        menubar.append(helpm)

        # About Item
        about_item = Gtk.MenuItem(_("About"))
        about_item.connect('activate', self._on_menu_about_activate)
        helpmenu.append(about_item)

        self.input_text.set_hexpand(True)
        self.input_text.set_pixels_inside_wrap(3)

        # Configurar altura dinámica
        buffer = self.input_text.get_buffer()
        buffer.connect('changed', self._on_text_changed)

        # Configurar atajo de teclado Enter
        key_controller = Gtk.EventControllerKey()
        key_controller.connect('key-pressed', self._on_key_pressed)
        # Verificar si key_controller es Gtk.EventControllerKey
        # Si no es así, corregir la creación del controlador previamente
        # Suponiendo que key_controller es correcto, probar con:
        # self.input_text.add_controller(key_controller)

        # Botón enviar
        self.send_button = Gtk.Button(label=_("Send"))
        self.send_button.connect('clicked', self._on_send_clicked)
        # self.send_button.add_css_class('suggested-action')

        # Ensamblar la interfaz
        input_box.add(self.input_text)
        input_box.add(self.send_button)

        chat_box.add(scroll)
        chat_box.add(input_box)
        
        main_box.pack_start(chat_box, True, True, 0)
        
        self.add(main_box)

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
        # GTK3 sin title_widget, se usa directamente set_title
        self.set_title(title)

    def _on_save_title(self, widget):
        app = self.get_application()
        app.chat_history.set_conversation_title(
            self.config.get('cid'), self.title_entry.get_text())
        # GTK3 - directamente set_title
        new_title = self.title_entry.get_text()
        self.set_title(new_title)

    def _cancel_set_title(self, controller, keyval, keycode, state):
        """Cancela la edición y restaura el título anterior"""
        if keyval == Gdk.KEY_Escape:
            # GTK3 - directamente set_title con el título actual
            current_title = self.get_title()  # Obtener título actual
            self.set_title(current_title)
            self.title_entry.set_text(current_title)

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

    def _on_key_press(self, widget, event):
        """Maneja eventos de teclado para cancelar edición del título"""
        if event.keyval == Gdk.KEY_Escape:
            self.title_entry.set_text(self.config.get('template') or _("LLM Chat"))
            return True  # Evitar propagación
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
            self.messages_box.add(message_widget)

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
        self.messages_box.pack_start(self.current_message_widget, True, True, 0)

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
        self.messages_box.pack_start(error_widget, True, True, 0)
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
        self.messages_box.add(message_widget)
        GLib.idle_add(self._scroll_to_bottom)

    def _on_close_request(self, window):
        """Maneja el cierre de la ventana de manera elegante"""
        # LLMClient.cancel() ya verifica internamente si está generando
        self.llm.cancel()
        sys.exit()

    def _on_menu_rename_activate(self, item):
        self.get_application().on_rename_activate(None, None)

    def _on_menu_delete_activate(self, item):
        self.get_application().on_delete_activate(None, None)

    def _on_menu_about_activate(self, item):
        self.get_application().on_about_activate(None, None)

        return False  # Permite que la ventana se cierre


class LLMChatApplication(Gtk.Application):
    """
    Clase para una instancia de un chat
    """

    def __init__(self):
        Gtk.Application.__init__(
            self,
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
        Gtk.Application.do_startup(self)

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

    def get_application_version(self):
        """
        Obtiene la versión de la aplicación desde _version.py.
        """
        try:
            from gtk_llm_chat import _version
            return _version.__version__
        except ImportError:
            print("Error: _version.py no encontrado")
            return "Desconocida"
        return "Desconocida"

    def _setup_icon(self):
        """Configura el ícono de la aplicación"""
        # Establecer directorio de búsqueda
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_default()
        icon_theme.append_search_path(current_dir)

    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self, config=self.config)

        # Establecer directorio de búsqueda
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_default()
        icon_theme.append_search_path(current_dir)

        # Establecer el ícono por nombre (sin extensión .svg)
        window.set_icon_name("org.fuentelibre.gtk_llm_Chat")
        window.show_all()
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
        # GTK3 no tiene header bar con title_widget, usamos window title directamente
        # window.header.set_title_widget(window.title_entry) # No header bar in GTK3
        window.set_title(_("Rename Conversation"))  # Provisional
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
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_transient_for(self.get_active_window())
        about_dialog.set_program_name(_("Gtk LLM Chat"))
        about_dialog.set_logo_icon_name("org.fuentelibre.gtk_llm_Chat")
        about_dialog.set_website("https://github.com/icarito/gtk_llm_chat")
        about_dialog.set_comments(_("A frontend for LLM"))
        about_dialog.set_license_type(Gtk.License.GPL3)
        about_dialog.set_authors(["Sebastian Silva <sebastian@fuentelibre.org>"])
        about_dialog.set_version(self.get_application_version())
        about_dialog.set_copyright("© 2024 Sebastian Silva")
        about_dialog.show_all()

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
        Gtk.Application.do_shutdown(self)

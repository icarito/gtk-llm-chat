import gi
import json
import os
import re
import sys
import time
import locale
import gettext
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib, GObject

from llm_client import LLMClient, DEFAULT_CONVERSATION_NAME
from widgets import Message, MessageWidget, ErrorWidget
from db_operations import ChatHistory
from chat_application import _
from chat_sidebar import ChatSidebar # <--- Importar la nueva clase
from llm import get_default_model

DEBUG = os.environ.get('DEBUG') or False


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


class LLMChatWindow(Adw.ApplicationWindow):
    """
    A chat window
    """

    def __init__(self, config=None, chat_history=None, **kwargs):
        super().__init__(**kwargs)
        self.insert_action_group('app', self.get_application())

        # Conectar señal de cierre de ventana
        self.connect('close-request', self._on_close_request)
        self.connect('show', self._on_window_show)  # Connect to the 'show' signal

        # Inicializar flags para carga de historial
        self._history_loaded = False
        self._history_displayed = False

        # Asegurar que config no sea None
        self.config = config or {}
        
        # Extraer cid de la configuración
        self.cid = self.config.get('cid')
        debug_print(f"Inicializando ventana con CID: {self.cid}")
        
        # Store benchmark flag and start time from config
        self.benchmark_startup = self.config.get('benchmark_startup', False)
        self.start_time = self.config.get('start_time')

        # Use the passed chat_history or create one if not provided (fallback)
        if chat_history:
            self.chat_history = chat_history
        else:
            debug_print(
                "Warning: chat_history not provided to LLMChatWindow, creating new instance.")
            self.chat_history = ChatHistory()

        # Inicializar LLMClient con la configuración
        # self.llm will be initialized later, after UI setup potentially
        self.llm = None

        # Configurar la ventana principal
        # Si hay un CID, intentar obtener el título de la conversación desde el inicio
        title = DEFAULT_CONVERSATION_NAME()
        if self.cid:
            try:
                conversation = self.chat_history.get_conversation(self.cid)
                if conversation:
                    if conversation.get('title'):
                        title = conversation['title']
                    elif conversation.get('name'):  # En algunas BD puede estar como 'name'
                        title = conversation['name']
                    debug_print(f"Título inicial cargado de conversación: {title}")
            except Exception as e:
                debug_print(f"Error al cargar título inicial: {e}")
        else:
            # Si no hay CID, usar template si existe
            if self.config.get('template'):
                title = self.config.get('template')
                
        self.title_entry = Gtk.Entry()
        self.title_entry.set_hexpand(True)
        self.title_entry.set_text(title)
        self.title_entry.connect('activate', self._on_save_title)

        focus_controller = Gtk.EventControllerKey()
        focus_controller.connect("key-pressed", self._cancel_set_title)
        self.title_entry.add_controller(focus_controller)

        # Add a key controller for Ctrl+W
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_ctrl_w_pressed)
        self.add_controller(key_controller)

        self.set_default_size(400, 600)

        # Mantener referencia al último mensaje enviado
        self.last_message = None

        # Crear header bar
        self.header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle.new(title, "")
        self.header.set_title_widget(self.title_widget)
        self.set_title(title)  # Set window title based on initial title

        # --- Botones de la Header Bar ---
        # --- Botón para mostrar/ocultar el panel lateral (sidebar) ---
        self.sidebar_button = Gtk.ToggleButton()
        self.sidebar_button.set_icon_name("open-menu-symbolic") # O "view-reveal-symbolic"
        self.sidebar_button.set_tooltip_text(_("Model Settings"))
        # No conectar 'toggled' aquí si usamos bind_property

        # Crear botón Rename
        rename_button = Gtk.Button()
        rename_button.set_icon_name("document-edit-symbolic")
        rename_button.set_tooltip_text(_("Rename"))
        rename_button.connect('clicked', lambda x: self.get_application().on_rename_activate(None, None))

        self.header.pack_end(self.sidebar_button)
        self.header.pack_end(rename_button)

        # --- Fin Botones Header Bar ---


        # --- Contenedor principal (OverlaySplitView) ---
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_vexpand(True)
        self.split_view.set_collapsed(True) # Empezar colapsado
        self.split_view.set_show_sidebar(False)
        self.split_view.set_min_sidebar_width(280)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.set_sidebar_position(Gtk.PackType.END)

        # Conectar la propiedad 'show-sidebar' del split_view al estado del botón
        self.split_view.bind_property(
            "show-sidebar", self.sidebar_button, "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        # Conectar al cambio de 'show-sidebar' para cambiar el icono y foco
        self.split_view.connect("notify::show-sidebar", self._on_sidebar_visibility_changed)


        # --- Contenido principal (el chat) ---
        chat_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
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
        self.messages_box.set_can_focus(False)
        scroll.set_child(self.messages_box)
        # Área de entrada
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.add_css_class('toolbar')
        input_box.add_css_class('card')
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
        buffer = self.input_text.get_buffer()
        buffer.connect('changed', self._on_text_changed)
        key_controller_input = Gtk.EventControllerKey()
        key_controller_input.connect('key-pressed', self._on_key_pressed)
        self.input_text.add_controller(key_controller_input)
        # Botón enviar
        self.send_button = Gtk.Button(label=_("Send"))
        self.send_button.connect('clicked', self._on_send_clicked)
        self.send_button.add_css_class('suggested-action')
        # Ensamblar la interfaz de chat
        input_box.append(self.input_text)
        input_box.append(self.send_button)
        chat_content_box.append(scroll)
        chat_content_box.append(input_box)


        # Establecer el contenido principal en el split_view
        self.split_view.set_content(chat_content_box)

        # --- Panel Lateral (Sidebar) ---
        # Initialize LLMClient *after* basic UI setup
        try:
            debug_print(f"Inicializando LLMClient con config: {self.config}")
            self.llm = LLMClient(self.config, self.chat_history)
            # Connect signals *here*
            self.llm.connect('model-loaded', self._on_model_loaded)  # Ensure this is connected
            self.llm.connect('response', self._on_llm_response)
            self.llm.connect('error', self._on_llm_error)
            self.llm.connect('finished', self._on_llm_finished)
            
            if self.cid:
                debug_print(f"LLMChatWindow: usando CID existente: {self.cid}")
            else:
                debug_print("LLMChatWindow: sin CID específico, creando nueva conversación")
                
        except Exception as e:
            debug_print(_(f"Fatal error starting LLMClient: {e}"))
            # Display error in UI instead of exiting?
            error_widget = ErrorWidget(f"Fatal error starting LLMClient: {e}")
            self.messages_box.append(error_widget)
            self.set_enabled(False)  # Disable input if LLM fails critically
            # Optionally: sys.exit(1) if it should still be fatal

        # Obtener el modelo predeterminado o el modelo de la conversación activa
        if not self.config.get('cid'):
            default_model_id = get_default_model()
            if default_model_id:
                self.config['model'] = default_model_id
                debug_print(f"Usando modelo predeterminado: {default_model_id}")
        else:
            model_id = self.llm.get_model_id()
            self.config['model'] = model_id
            debug_print(f"Usando modelo de la conversación: {model_id}")
            
            # Cargar el título de la conversación existente si hay un cid
            try:
                conversation = self.chat_history.get_conversation(self.cid)
                if conversation and conversation.get('title'):
                    title = conversation['title']
                    self.set_conversation_name(title)
                    debug_print(f"Cargando título de conversación existente: {title}")
            except Exception as e:
                debug_print(f"Error al cargar el título de la conversación: {e}")

        self.title_widget.set_subtitle(self.config['model'])

        # Crear el sidebar con el modelo actual
        self.model_sidebar = ChatSidebar(config=self.config, llm_client=self.llm)
        # Establecer el panel lateral en el split_view
        self.split_view.set_sidebar(self.model_sidebar)

        # --- Ensamblado Final ---
        # El contenedor principal ahora incluye la HeaderBar y el SplitView
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root_box.append(self.header)
        root_box.append(self.split_view) # Añadir el split_view aquí

        # Establecer el contenido de la ventana
        self.set_content(root_box) # El root_box es el nuevo contenido

        # Agregar CSS provider
        self._setup_css()

        # Agregar soporte para cancelación
        self.current_message_widget = None
        self.accumulated_response = ""

        # Add a focus controller to the window
        focus_controller_window = Gtk.EventControllerFocus.new()
        focus_controller_window.connect("enter", self._on_focus_enter)
        self.add_controller(focus_controller_window)

    # Resetear el stack al cerrar el sidebar
    def _on_sidebar_visibility_changed(self, split_view, param):
        show_sidebar = split_view.get_show_sidebar()
        if not show_sidebar:
            self.model_sidebar.stack.set_visible_child_name("actions")
            self.input_text.grab_focus()

    def _setup_css(self):
        css_provider = Gtk.CssProvider()
        # Añadir estilo para el sidebar si es necesario
        data = """
            /* ... (estilos existentes) ... */

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

            /* Estilos opcionales para el sidebar */
            /* .sidebar-title { ... } */
        """
        # Some platform-specific CSS:
        if sys.platform.startswith('win'):
            data += """
                window {
                    box-shadow: none;
                    margin: -12px;
                    border-radius: 0px;
                    padding: 6px;
                }
            """
        elif sys.platform.startswith('darwin'):
            self.header.set_decoration_layout('close,minimize,maximize:')
            def find_window_controls(parent):
                if not parent:
                    return None
                child = parent.get_first_child()
                while child:
                    if isinstance(child, Gtk.WindowControls):
                        return child
                    found_in_child = find_window_controls(child)
                    if found_in_child:
                        return found_in_child
                    hijo = hijo.get_next_sibling()
                return None
            controls = find_window_controls(self.header)
            controls.set_use_native_controls(True)
            data += """
                window {
                    border-radius: 10px;
                }
            """
        
        css_provider.load_from_data(data, -1) # Usar -1

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def set_conversation_name(self, title):
        """Establece el título de la ventana"""
        debug_print(f"Estableciendo título de la conversación: '{title}'")
        self.title_widget.set_title(title)
        self.title_entry.set_text(title)
        self.set_title(title)  # Actualizar también el título de la ventana

    def _on_save_title(self, widget):
        app = self.get_application()
        conversation_id = self.config.get('cid')
        if conversation_id:
            self.chat_history.set_conversation_title(
                conversation_id, self.title_entry.get_text())
            debug_print(f"Guardando título para conversación {conversation_id}: {self.title_entry.get_text()}")
        else:
            debug_print("Conversation ID is not available yet. Title update deferred.")
            # Schedule the title update for the next prompt
            def update_title_on_next_prompt(llm_client, response):
                conversation_id = self.config.get('cid')
                debug_print(f"Conversation ID post-respuesta: {conversation_id}")
                if conversation_id:
                    self.chat_history.set_conversation_title(
                        conversation_id, self.title_entry.get_text())
                    self.llm.disconnect_by_func(update_title_on_next_prompt)
            self.llm.connect('response', update_title_on_next_prompt)
        self.header.set_title_widget(self.title_widget)
        new_title = self.title_entry.get_text()

        self.title_widget.set_title(new_title)
        self.set_title(new_title)

    def _cancel_set_title(self, controller, keyval, keycode, state):
        """Cancela la edición y restaura el título anterior"""
        if keyval == Gdk.KEY_Escape:
            self.header.set_title_widget(self.title_widget)
            self.title_entry.set_text(self.title_widget.get_title())

    def _on_ctrl_w_pressed(self, controller, keyval, keycode, state):
        """Handles Ctrl+W to remove the conversation."""
        if keyval == Gdk.KEY_w and state & Gdk.ModifierType.CONTROL_MASK:
            app = self.get_application()
            app.on_delete_activate(None, None)
            return True
        return False

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

    def display_message(self, content, sender="user"):
        """
        Displays a message in the chat window.

        Args:
            content (str): The text content of the message.
            sender (str): The sender of the message ("user" or "assistant").
        """
        message = Message(content, sender)

        if sender == "user":
            self.last_message = message
            # Clear the input buffer after sending a user message
            buffer = self.input_text.get_buffer()
            buffer.set_text("", 0)

        # Create the message widget
        message_widget = MessageWidget(message)

        # Connect to the 'map' signal to scroll *after* the widget is shown
        def scroll_on_map(widget, *args):
            # Use timeout_add to ensure scrolling happens after a short delay
            def do_scroll():
                self._scroll_to_bottom(True) # Force scroll
                return GLib.SOURCE_REMOVE # Run only once
            GLib.timeout_add(50, do_scroll) # Delay of 50ms
            # Return False because we are using connect_after
            return False

        # Use connect_after for potentially better timing
        signal_id = message_widget.connect_after('map', scroll_on_map)

        # Add the widget to the box
        self.messages_box.append(message_widget)

        return message_widget

    def _on_model_loaded(self, llm_client, model_id):
        """Maneja el evento cuando se carga un modelo."""
        debug_print(f"Modelo cargado correctamente: {model_id}")
        
        # Actualizar el título de la ventana con el nombre del modelo
        self.title_widget.set_subtitle(model_id)
        
        # Verificar si necesitamos cargar una conversación existente basada en CID
        if self.cid:
            debug_print(f"Verificando conversación existente para CID: {self.cid}")
            try:
                conversation = self.chat_history.get_conversation(self.cid)
                if conversation:
                    debug_print(f"Conversación encontrada en BD: {conversation}")
                    # Usar el título de la conversación si existe
                    if conversation.get('title'):
                        title = conversation['title']
                        self.set_conversation_name(title)
                        debug_print(f"Título actualizado para conversación: {title}")
                    elif conversation.get('name'):  # En algunas BD puede estar como 'name' en lugar de 'title'
                        title = conversation['name']
                        self.set_conversation_name(title)
                        debug_print(f"Título actualizado para conversación (name): {title}")
                    
                    # Cargar explícitamente los mensajes de la conversación
                    history_entries = self.chat_history.get_conversation_history(self.cid)
                    
                    if history_entries:
                        debug_print(f"Se encontraron {len(history_entries)} mensajes para mostrar")
                        # Asegurarse de que este método se ejecute solo una vez
                        # Agregar una flag para evitar cargas duplicadas
                        if not hasattr(self, '_history_loaded') or not self._history_loaded:
                            self._history_loaded = True
                            GLib.idle_add(self._load_and_display_history, history_entries)
                    else:
                        debug_print("No se encontraron mensajes en el historial")
                else:
                    debug_print(f"No se encontró la conversación con CID: {self.cid}")
            except Exception as e:
                debug_print(f"Error al recuperar conversación en _on_model_loaded: {e}")
                import traceback
                debug_print(traceback.format_exc())
        else:
            debug_print("Sin CID específico, no se carga ninguna conversación")
            
    def _load_and_display_history(self, history_entries):
        """Método auxiliar para cargar y mostrar el historial después de que la UI esté lista."""
        try:
            debug_print("Cargando y mostrando historial de conversación...")
            # Verificar que no se haya cargado ya el historial (doble verificación)
            if hasattr(self, '_history_displayed') and self._history_displayed:
                debug_print("El historial ya ha sido mostrado, evitando duplicación")
                return False
                
            self._history_displayed = True
            self._display_conversation_history(history_entries)
            
            # Asegurarse de que se haga scroll al final
            GLib.timeout_add(100, self._scroll_to_bottom)
            
            return False  # Ejecutar solo una vez
        except Exception as e:
            debug_print(f"Error al cargar historial: {e}")
            import traceback
            debug_print(traceback.format_exc())
            return False  # Ejecutar solo una vez

    def _on_send_clicked(self, button):
        buffer = self.input_text.get_buffer()
        text = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        )

        if text:
            # Display user message
            self.display_message(text, sender="user")
            # Deshabilitar entrada y empezar tarea LLM
            self.set_enabled(False)
            # NEW: Crear el widget de respuesta aquí
            self.current_message_widget = self.display_message("", sender="assistant")
            # Call _on_llm_response with an empty string to update the widget
            self._on_llm_response(self.llm, "")
            GLib.idle_add(self._start_llm_task, text)

    def _start_llm_task(self, prompt_text):
        """Inicia la tarea del LLM con el prompt dado."""
        # Enviar el prompt usando LLMClient
        self.llm.send_message(prompt_text)

        # Devolver False para que idle_add no se repita
        return GLib.SOURCE_REMOVE

    def _on_llm_error(self, llm_client, message):
        """Muestra un mensaje de error en el chat"""
        debug_print(message, file=sys.stderr)
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

    def _on_llm_finished(self, llm_client, success: bool):
        """Maneja la señal 'finished' de LLMClient."""
        self.set_enabled(True)
        self.accumulated_response = ""
        self.input_text.grab_focus()

        # Actualizar el conversation_id en la configuración si no existe
        if success and not self.config.get('cid'):
            conversation_id = self.llm.get_conversation_id()
            if conversation_id:
                self.config['cid'] = conversation_id
                self.cid = conversation_id
                debug_print(f"Conversation ID updated in config: {conversation_id}")
                # Registrar la ventana en el mapa global de ventanas por CID
                app = self.get_application()
                if hasattr(app, '_window_by_cid'):
                    # Elimina el registro anterior si existe
                    for key, win in list(app._window_by_cid.items()):
                        if win is self and key != conversation_id:
                            del app._window_by_cid[key]
                    app._window_by_cid[conversation_id] = self

    def _on_llm_response(self, llm_client, response):
        """Maneja la señal de respuesta del LLM"""
        if not self.current_message_widget:
            return

        # Actualizar el conversation_id en la configuración al recibir la primera respuesta
        if not self.config.get('cid'):
            conversation_id = self.llm.get_conversation_id()
            if conversation_id:
                self.config['cid'] = conversation_id
                self.cid = conversation_id
                debug_print(f"Conversation ID updated early in config: {conversation_id}")
                # Registrar la ventana en el mapa global de ventanas por CID
                app = self.get_application()
                if hasattr(app, '_window_by_cid'):
                    for key, win in list(app._window_by_cid.items()):
                        if win is self and key != conversation_id:
                            del app._window_by_cid[key]
                    app._window_by_cid[conversation_id] = self

        self.accumulated_response += response
        GLib.idle_add(self.current_message_widget.update_content,
                      self.accumulated_response)
        GLib.idle_add(self._scroll_to_bottom, False)

    def _scroll_to_bottom(self, force=True):
        scroll = self.messages_box.get_parent()
        adj = scroll.get_vadjustment()
        upper = adj.get_upper()
        page_size = adj.get_page_size()
        value = adj.get_value()

        bottom_distance = upper - (value + page_size)
        threshold = page_size * 0.1  # 10% del viewport

        if force:
            adj.set_value(upper - page_size)
            return

        if bottom_distance < threshold:
            def scroll_after():
                adj.set_value(upper - page_size)
                return False
            GLib.timeout_add(50, scroll_after)

    def _on_close_request(self, window):
        # Eliminar del registro de ventanas si corresponde
        app = self.get_application()
        cid = getattr(self, 'cid', None)
        if hasattr(app, '_window_by_cid') and cid and cid in app._window_by_cid:
            debug_print(f"Eliminando ventana del registro para CID: {cid}")
            del app._window_by_cid[cid]
        # Lógica de cierre global: si es la última ventana
        if len(app.get_windows()) <= 1:
            debug_print("Última ventana cerrada saliendo de la aplicación (desde chat_window)")
            app.quit()
        # Permitir el cierre de la ventana
        return False

    def _on_window_show(self, window):
        """Set focus to the input text when the window is shown."""
        # Handle benchmark startup
        if self.benchmark_startup and self.start_time:
            end_time = time.time()
            elapsed_time = end_time - self.start_time
            print(f"Startup time: {elapsed_time:.4f} seconds")
            # Use GLib.idle_add to exit after the current event loop iteration
            GLib.idle_add(self.get_application().quit)
            return  # Don't grab focus if we are exiting

        # Verificación de integridad: si tenemos un CID pero después de un tiempo no se ha cargado 
        # el historial, intentar cargarlo explícitamente aquí
        if self.cid and not (hasattr(self, '_history_loaded') and self._history_loaded):
            debug_print("Verificación de integridad: el historial no se ha cargado a pesar de tener un CID")
            
            def delayed_history_check():
                if not (hasattr(self, '_history_loaded') and self._history_loaded):
                    debug_print("Iniciando carga de historial de emergencia...")
                    # Reintentar carga de historial
                    try:
                        conversation = self.chat_history.get_conversation(self.cid)
                        if conversation:
                            # Verificar también el título de la conversación
                            if conversation.get('title'):
                                self.set_conversation_name(conversation['title'])
                                debug_print(f"Título actualizado en carga de emergencia: {conversation['title']}")
                            elif conversation.get('name'):
                                self.set_conversation_name(conversation['name'])
                                debug_print(f"Título actualizado en carga de emergencia: {conversation['name']}")
                                
                            history_entries = self.chat_history.get_conversation_history(self.cid)
                            if history_entries:
                                self._history_loaded = True
                                self._load_and_display_history(history_entries)
                    except Exception as e:
                        debug_print(f"Error en carga de emergencia: {e}")
                return False  # Ejecutar solo una vez
                
            # Verificar después de un breve retraso
            GLib.timeout_add(500, delayed_history_check)
        
        self.input_text.grab_focus()

    def _display_conversation_history(self, history_entries):
        """Muestra el historial de conversación en la UI."""
        # Limpiar contenedor de mensajes existentes
        for child in self.messages_box:
            self.messages_box.remove(child)
            
        # Verificar que tengamos entradas válidas
        if not history_entries:
            debug_print("No hay entradas de historial para mostrar")
            return
            
        debug_print(f"Mostrando {len(history_entries)} mensajes de historial")
        debug_print(f"Detalle de las entradas: {history_entries}")
        
        # Mostrar cada mensaje en la UI
        for entry in history_entries:
            try:
                debug_print(f"Procesando entrada: {entry}")
                
                # Verificar campos obligatorios en la entrada
                prompt = entry.get('prompt')
                response = entry.get('response')
                
                if prompt:
                    debug_print(f"Creando mensaje de usuario con: {prompt[:50]}...")
                    # Crear un objeto Message antes de pasarlo a MessageWidget
                    msg = Message(prompt, sender="user")
                    user_message = MessageWidget(msg)
                    self.messages_box.append(user_message)
                else:
                    debug_print("Entrada sin prompt, saltando mensaje de usuario")
                    
                if response:
                    debug_print(f"Creando mensaje de asistente con: {response[:50]}...")
                    # Crear un objeto Message antes de pasarlo a MessageWidget
                    msg = Message(response, sender="assistant")
                    assistant_message = MessageWidget(msg)
                    self.messages_box.append(assistant_message)
                else:
                    debug_print("Entrada sin response, saltando mensaje de asistente")
            except Exception as e:
                debug_print(f"Error al mostrar mensaje de historial: {e}")
                debug_print(f"Excepción completa:", exc_info=True)
        
        # Scroll hasta el final cuando todos los mensajes estén en pantalla
        GLib.idle_add(self._scroll_to_bottom)

    def _on_focus_enter(self, controller):
        """Set focus to the input text when the window gains focus."""
        # Solo poner el foco si el sidebar no está visible
        if not self.split_view.get_show_sidebar():
            self.input_text.grab_focus()

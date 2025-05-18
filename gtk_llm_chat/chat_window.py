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
        # Conectar la señal model-changed del sidebar a un manejador en la ventana
        self.model_sidebar.connect('model-changed', self._on_sidebar_model_changed)
        # Establecer el panel lateral en el split_view
        self.split_view.set_sidebar(self.model_sidebar)

        # --- Ensamblado Final ---
        # El contenedor principal ahora incluye la HeaderBar y el SplitView
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root_box.append(self.header)
        root_box.append(self.split_view) # Añadir el split_view aquí

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(None)  # Se establecerá después
        self.toast_overlay.set_child(root_box)
        self.set_content(self.toast_overlay)

        # Banner para API key faltante (inicialmente oculto)
        self.api_key_banner = Adw.Banner()
        self.api_key_banner.set_title(_('API key required for this model'))
        self.api_key_banner.set_button_label(_('Select Model'))
        self.api_key_banner.set_revealed(False)
        self.api_key_banner.connect('button-clicked', self._on_api_key_banner_button_clicked)
        # Insertar el banner debajo del header y antes del split_view
        root_box.insert_child_after(self.api_key_banner, self.header)

        # Agregar CSS provider
        self._setup_css()

        # Agregar soporte para cancelación
        self.current_message_widget = None
        self.accumulated_response = ""

        # Add a focus controller to the window
        focus_controller_window = Gtk.EventControllerFocus.new()
        focus_controller_window.connect("enter", self._on_focus_enter)
        self.add_controller(focus_controller_window)

        # Mostrar banner si falta API key para el modelo actual
        self._update_api_key_banner_visibility()

    # Resetear el stack al cerrar el sidebar
    def _on_sidebar_visibility_changed(self, split_view, param):
        show_sidebar = split_view.get_show_sidebar()
        # Actualizar visibilidad del banner cuando cambia la visibilidad del sidebar
        self._update_api_key_banner_visibility() 
        if not show_sidebar:
            if hasattr(self.model_sidebar, 'stack'): # Check if model_sidebar and stack exist
                self.model_sidebar.stack.set_visible_child_name("actions")
            if hasattr(self, 'input_text'): # Check if input_text exists
                self.input_text.grab_focus()

    def _on_sidebar_model_changed(self, sidebar, model_id):
        """Manejador para cuando el modelo cambia desde el sidebar."""
        debug_print(f"Solicitud de cambio de modelo desde sidebar a: {model_id}")

        if self.llm.model and self.llm.model.id == model_id:
            debug_print(f"Modelo {model_id} ya está activo.")
            # self.split_view.set_show_sidebar(False) # Opcional: cerrar sidebar
            return

        # Informar a LLMClient para que cambie el modelo.
        # Esto activará la señal 'model-loaded', que actualizará la UI.
        self.llm.set_model(model_id) 

        # La notificación de Toast para la selección de un modelo no predeterminado puede permanecer aquí.
        try:
            # Asumiendo que get_default_model está importado o disponible globalmente.
            # Si está en llm_client, podría ser self.llm.get_default_model_id() o similar.
            # Por ahora, se asume que get_default_model() es accesible.
            default_model = get_default_model() 
            if model_id != default_model:
                self.add_toast(
                    _(f"Modelo cambiado a {model_id}."),
                    action_label=_("Establecer como predeterminado"),
                    action_callback=lambda *args: self.model_sidebar._on_set_default_model_clicked(None)
                )
        except NameError: # Si get_default_model no está definido
            debug_print("get_default_model no encontrado para la notificación de toast.")
            # Considerar importar get_default_model de llm_client si es necesario
            # from .llm_client import get_default_model
        except Exception as e:
            debug_print(f"Error al mostrar toast de cambio de modelo: {e}")

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
        css_provider.load_from_data(data.encode('UTF-8'), -1) # Usar -1

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._update_api_key_banner_visibility()

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
        """Maneja el evento cuando se carga un modelo en LLMClient."""
        debug_print(f"LLMChatWindow._on_model_loaded: Modelo '{model_id}' cargado en LLMClient.")
        self.title_widget.set_subtitle(model_id)
        
        # Sincronizar self.config['model'] por si acaso.
        if self.config.get('model') != model_id:
            debug_print(f"Sincronizando self.config['model'] a '{model_id}' en _on_model_loaded.")
            self.config['model'] = model_id

        if self.cid:
            debug_print(f"Contexto de conversación CID: {self.cid}. Verificando historial.")
            # Usar un indicador para asegurar que la visualización del historial se inicie solo una vez
            # por contexto de CID relevante. Se reinicia si el CID cambia o la ventana se reutiliza.
            if getattr(self, '_history_display_initiated_for_cid', None) != self.cid:
                try:
                    conversation = self.chat_history.get_conversation(self.cid)
                    if conversation:
                        debug_print(f"Conversación encontrada en BD: {conversation.get('title', 'Sin título')}")
                        title_to_set = conversation.get('title') or conversation.get('name')
                        if title_to_set:
                            self.set_conversation_name(title_to_set)
                        
                        history_entries = self.chat_history.get_conversation_history(self.cid)
                        if history_entries:
                            debug_print(f"Se encontraron {len(history_entries)} mensajes. Programando visualización.")
                            self._history_display_initiated_for_cid = self.cid 
                            GLib.idle_add(self._load_and_display_history, history_entries)
                        else:
                            debug_print("No se encontraron mensajes en el historial. Limpiando área de mensajes.")
                            self._clear_messages_box() 
                            self._history_display_initiated_for_cid = self.cid # Marcar como "manejado"
                    else:
                        debug_print(f"No se encontró la conversación con CID: {self.cid}. Limpiando área de mensajes.")
                        self._clear_messages_box()
                        self._history_display_initiated_for_cid = self.cid # Marcar como "manejado"
                except Exception as e:
                    debug_print(f"Error al procesar conversación en _on_model_loaded: {e}", exc_info=True)
            else:
                debug_print(f"Visualización de historial para CID {self.cid} ya fue iniciada o está en proceso.")
        else:
            debug_print("Sin CID específico. Limpiando área de mensajes para nueva conversación.")
            self._clear_messages_box()
            if hasattr(self, '_history_display_initiated_for_cid'):
                delattr(self, '_history_display_initiated_for_cid')
            
        self._update_api_key_banner_visibility()

    def _clear_messages_box(self):
        """Limpia todos los mensajes del messages_box y reinicia indicadores de historial."""
        debug_print("Limpiando messages_box.")
        while child := self.messages_box.get_first_child():
            self.messages_box.remove(child)
        
        # Reiniciar el indicador en _load_and_display_history para permitir que nuevo historial se muestre.
        if hasattr(self, '_history_displayed'):
            self._history_displayed = False
        # No reiniciar _history_display_initiated_for_cid aquí directamente, 
        # _on_model_loaded lo maneja basado en si hay un self.cid.

    def _load_and_display_history(self, history_entries):
        """Carga y muestra el historial. Evita la re-ejecución si ya se mostró."""
        try:
            debug_print("Solicitud para cargar y mostrar historial de conversación...")
            # Este indicador previene re-mostrar si la función es llamada accidentalmente de nuevo
            # para el mismo "evento de carga lógico". Se reinicia por _clear_messages_box.
            if hasattr(self, '_history_displayed') and self._history_displayed:
                debug_print("El historial ya ha sido procesado por _load_and_display_history, evitando duplicación.")
                return GLib.SOURCE_REMOVE
                
            self._history_displayed = True # Marcar que este evento de carga ha procesado la visualización.
            self._display_conversation_history(history_entries) # Llama a la lógica de visualización real
            
            # Asegurar scroll al final después de que los widgets se hayan mapeado.
            GLib.timeout_add(150, lambda: self._scroll_to_bottom(force=True))
            
            return GLib.SOURCE_REMOVE # Ejecutar solo una vez por llamada a GLib.idle_add
        except Exception as e:
            debug_print(f"Error en _load_and_display_history: {e}", exc_info=True)
            return GLib.SOURCE_REMOVE # Asegurar que no se reintente en caso de error aquí

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
                debug_print(f"Conversation ID updated in config: {conversation_id}")

    def _on_llm_response(self, llm_client, response):
        """Maneja la señal de respuesta del LLM"""
        if not self.current_message_widget:
            return

        # Actualizar el conversation_id en la configuración al recibir la primera respuesta
        if not self.config.get('cid'):
            conversation_id = self.llm.get_conversation_id()
            if conversation_id:
                self.config['cid'] = conversation_id
                debug_print(f"Conversation ID updated early in config: {conversation_id}")

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
        # Lógica de cierre global: si es la última ventana y no hay tray, salir (solo Linux)
        if hasattr(app, '_should_start_tray') and app._should_start_tray():
            if len(app.get_windows()) <= 1 and (not getattr(app, 'tray_process', None) or app.tray_process.poll() is not None):
                debug_print("Última ventana cerrada y tray no activo, saliendo de la aplicación (desde chat_window)")
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
        self._clear_messages_box() # Limpiar mensajes existentes primero

        if not history_entries:
            debug_print("No hay entradas de historial para mostrar después de limpiar.")
            return
            
        debug_print(f"Mostrando {len(history_entries)} mensajes de historial")
        
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

    def add_toast(self, message, action_label=None, action_callback=None):
        toast = Adw.Toast(title=message)
        if action_label and action_callback:
            toast.set_button_label(action_label)
            toast.connect('button-clicked', lambda *_: action_callback())
        self.toast_overlay.add_toast(toast)

    def _on_api_key_banner_button_clicked(self, banner):
        """Manejador para el clic del botón en el banner de API key."""
        self.split_view.set_show_sidebar(True)
        # Asegurarse de que la sección de selección de modelo esté visible en el sidebar
        if hasattr(self.model_sidebar, 'stack'):
            self.model_sidebar.stack.set_visible_child_name("model_selection")

    def _update_api_key_banner_visibility(self):
        """Actualiza la visibilidad del banner de API key."""
        if not hasattr(self, 'model_sidebar') or not hasattr(self.model_sidebar, 'needs_api_key_for_current_model'):
            self.api_key_banner.set_revealed(False)
            return

        sidebar_visible = self.split_view.get_show_sidebar()
        needs_key = self.model_sidebar.needs_api_key_for_current_model()

        if needs_key and not sidebar_visible:
            self.api_key_banner.set_revealed(True)
        else:
            self.api_key_banner.set_revealed(False)

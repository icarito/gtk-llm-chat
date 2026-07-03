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

from .llm_client import LLMClient, DEFAULT_CONVERSATION_NAME
from .widgets import Message, MessageWidget, ErrorWidget
from .db_operations import ChatHistory
from .chat_application import _
from .chat_sidebar import ChatSidebar # <--- Importar la nueva clase
from llm import get_default_model
from .style_manager import style_manager
from .resource_manager import resource_manager
from .debug_utils import debug_print
import traceback

DEBUG = os.environ.get('DEBUG') or False


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


class LLMChatWindow(Adw.ApplicationWindow):
    """
    A chat window
    """

    def __init__(self, config=None, chat_history=None, backend=None, **kwargs):
        super().__init__(**kwargs)
        self.insert_action_group('app', self.get_application())

        # Aplicar clase CSS para la ventana principal - sin cargar recursos aún
        style_manager.apply_to_widget(self, "main-container")

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

        # Backend de conversación (contrato ChatBackend). Si se inyecta uno
        # (p.ej. XmppConversation), se usa tal cual y se omite todo lo
        # específico de LLMClient (sidebar de modelo, modelo por defecto).
        # Si no, el comportamiento es exactamente el de siempre: se crea
        # un LLMClient más abajo, tras el setup básico de la UI.
        self.backend = backend
        self._injected_backend = backend is not None
        self._composing_timeout_id = None
        self.roster_sidebar = None

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

        # Add a key controller for global shortcuts (Ctrl+W, Ctrl+M, Ctrl+S, Ctrl+N)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_global_shortcuts)
        self.add_controller(key_controller)

        # Fijar tamaño por defecto y mínimo para evitar problemas de layout/segfault
        self.set_default_size(420, 550)
        self.set_size_request(400, 300)  # tamaño mínimo seguro

        # Mantener referencia al último mensaje enviado
        self.last_message = None

        # Crear header bar
        self.header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle.new(title, "")
        self.header.set_title_widget(self.title_widget)
        self.set_title(title)  # Set window title based on initial title

        # Workaround de controles nativos en macOS (centralizado, con delay para asegurar renderizado)
        import sys
        if sys.platform == 'darwin':
            def _apply_native_controls():
                style_manager.apply_macos_native_window_controls(self.header)
                return False  # Ejecutar solo una vez
            GLib.idle_add(_apply_native_controls)

        # --- Indicador de estado de conexión (solo backends no-LLM, spec 001) ---
        self.connection_status_label = Gtk.Label()
        self.connection_status_label.add_css_class("dim-label")
        self.connection_status_label.add_css_class("caption")
        self.connection_status_label.set_visible(self._injected_backend)
        if self._injected_backend:
            self.header.pack_start(self.connection_status_label)

        # --- Botones de la Header Bar ---
        # --- Botón para mostrar/ocultar el panel lateral (sidebar) ---
        self.sidebar_button = Gtk.ToggleButton()
        resource_manager.set_widget_icon_name(self.sidebar_button, "brain-symbolic")
        self.sidebar_button.set_tooltip_text(_("Model Settings"))
        # No conectar 'toggled' aquí si usamos bind_property
        # Backends no-LLM no tienen sidebar de modelo en el MVP (spec 001)
        self.sidebar_button.set_visible(not self._injected_backend)

        # Botón de contactos (roster) a la IZQUIERDA, solo para XMPP (spec 002)
        self.roster_button = Gtk.ToggleButton()
        resource_manager.set_widget_icon_name(self.roster_button, "system-users-symbolic")
        self.roster_button.set_tooltip_text(_("Contacts"))
        self.roster_button.set_visible(self._injected_backend)

        # Crear botón Rename
        rename_button = Gtk.Button()
        resource_manager.set_widget_icon_name(rename_button, "document-edit-symbolic")
        rename_button.set_tooltip_text(_("Rename"))
        rename_button.connect('clicked', lambda x: self.get_application().on_rename_activate(None, None))

        # --- Menú principal (hamburguesa): punto de entrada a nuevas
        # conversaciones LLM y XMPP (spec 002) ---
        primary_menu = Gio.Menu()
        primary_menu.append(_("New LLM Conversation"), "app.new-conversation")
        primary_menu.append(_("New XMPP Conversation…"), "app.new-xmpp-conversation")
        xmpp_section = Gio.Menu()
        xmpp_section.append(_("XMPP Account…"), "app.xmpp-account")
        primary_menu.append_section(None, xmpp_section)
        self.primary_menu_button = Gtk.MenuButton()
        resource_manager.set_widget_icon_name(self.primary_menu_button, "view-more-symbolic")
        self.primary_menu_button.set_tooltip_text(_("Main Menu"))
        self.primary_menu_button.set_menu_model(primary_menu)

        self.header.pack_end(self.primary_menu_button)
        self.header.pack_end(self.sidebar_button)
        self.header.pack_end(rename_button)
        self.header.pack_start(self.roster_button)

        # --- Fin Botones Header Bar ---

        # --- Contenedor principal (OverlaySplitView) ---
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_vexpand(True)
        self.split_view.set_collapsed(True) # Empezar colapsado
        self.split_view.set_show_sidebar(False)
        self.split_view.set_min_sidebar_width(280)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.set_sidebar_position(Gtk.PackType.END)

        # Conectar la propiedad 'show-sidebar' del split_view al botón que
        # corresponda: el de modelo (derecha) en modo LLM, el de contactos
        # (izquierda) en modo XMPP.
        toggle_button = self.roster_button if self._injected_backend else self.sidebar_button
        self.split_view.bind_property(
            "show-sidebar", toggle_button, "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        # Conectar al cambio de 'show-sidebar' para cambiar el icono y foco
        self.split_view.connect("notify::show-sidebar", self._on_sidebar_visibility_changed)

        # --- Contenido principal (el chat) ---
        chat_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        style_manager.apply_to_widget(chat_content_box, "chat-container")
        
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
        style_manager.apply_to_widget(self.messages_box, "messages-container")
        scroll.set_child(self.messages_box)
        
        # Área de entrada
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.add_css_class('toolbar')
        input_box.add_css_class('card')
        style_manager.apply_to_widget(input_box, "input-container")
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
        style_manager.apply_to_widget(self.input_text, "input-text")
        buffer = self.input_text.get_buffer()
        buffer.connect('changed', self._on_text_changed)
        key_controller_input = Gtk.EventControllerKey()
        key_controller_input.connect('key-pressed', self._on_key_pressed)
        self.input_text.add_controller(key_controller_input)
        
        # Botón enviar
        self.send_button = Gtk.Button(label=_("Send"))
        self.send_button.connect('clicked', self._on_send_clicked)
        self.send_button.add_css_class('suggested-action')
        style_manager.apply_to_widget(self.send_button, "primary-button")
        
        # Ensamblar la interfaz de chat
        input_box.append(self.input_text)
        input_box.append(self.send_button)
        chat_content_box.append(scroll)
        chat_content_box.append(input_box)

        # Establecer el contenido principal en el split_view
        self.split_view.set_content(chat_content_box)

        # --- Panel Lateral (Sidebar) ---
        if self._injected_backend:
            # Backend no-LLM (p.ej. XmppConversation): ya viene construido
            # y conectado a su sesión propia. Solo cablear las señales del
            # contrato ChatBackend; nada de modelo/proveedor/sidebar LLM.
            self.backend.connect('ready', self._on_backend_ready)
            self.backend.connect('response', self._on_llm_response)
            self.backend.connect('error', self._on_llm_error)
            self.backend.connect('finished', self._on_llm_finished)
            self.backend.connect('state-changed', self._on_backend_state_changed)
            self.backend.connect('typing', self._on_backend_typing)
            self.title_widget.set_subtitle(self.backend.get_display_name())
            # Estado inicial: la sesión puede ya estar 'connected' antes de
            # que esta ventana exista (el roster picker implica sesión viva).
            session = getattr(self.backend, 'session', None)
            self._last_connection_state = session.state if session else 'connected'
            self._update_connection_status(self._last_connection_state)
            self.model_sidebar = None
            # Panel de contactos (roster) dockeado a la IZQUIERDA (spec 002),
            # opuesto al sidebar de modelo LLM que va a la derecha.
            if session is not None:
                from .xmpp_roster_sidebar import XmppRosterSidebar
                self.roster_sidebar = XmppRosterSidebar(
                    session, on_contact_selected=self._on_roster_contact_selected)
                self.split_view.set_sidebar_position(Gtk.PackType.START)
                self.split_view.set_sidebar(self.roster_sidebar)
        else:
            # Initialize the backend *after* basic UI setup
            try:
                debug_print(f"Inicializando LLMClient con config: {self.config}")
                self.backend = LLMClient(self.config, self.chat_history)
                # Connect ChatBackend signals *here*
                self.backend.connect('ready', self._on_backend_ready)
                self.backend.connect('response', self._on_llm_response)
                self.backend.connect('error', self._on_llm_error)
                self.backend.connect('finished', self._on_llm_finished)

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
                model_id = self.backend.get_model_id()
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
            self.model_sidebar = ChatSidebar(config=self.config, llm_client=self.backend)
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
            if self.model_sidebar is not None:
                self.model_sidebar.stack.set_visible_child_name("actions")
            self.input_text.grab_focus()

    def _on_roster_contact_selected(self, bare_jid):
        """Un contacto elegido en el roster sidebar (spec 002): abre/enfoca
        su ventana de conversación. Delega en la aplicación, que mantiene el
        registro de ventanas por conversación."""
        app = self.get_application()
        session = getattr(self.backend, 'session', None)
        if app is not None and session is not None and \
                hasattr(app, 'open_xmpp_conversation'):
            app.open_xmpp_conversation(session, bare_jid)
        # Colapsar el panel tras elegir, para dar foco al chat
        self.split_view.set_show_sidebar(False)

    def _setup_css(self):
        """Aplica estilos CSS específicos para la ventana de chat."""
        # Los estilos base ya están cargados por style_manager
        # Solo necesitamos estilos específicos del chat
        
        css_provider = Gtk.CssProvider()
        
        # Estilos específicos para mensajes de chat
        chat_specific_css = """
            /* Estilos específicos para mensajes de chat */
            .message-content {
                padding: 12px 16px;
                min-width: 300px;
            }

            .user-message .message-content {
                background: linear-gradient(135deg, @theme_selected_bg_color, 
                                          shade(@theme_selected_bg_color, 0.9));
                color: @theme_selected_fg_color;
                border-radius: 18px 18px 4px 18px;
                margin-left: 60px;
            }

            .assistant-message .message-content {
                background-color: @theme_base_color;
                color: @theme_text_color;
                border: 1px solid alpha(@theme_fg_color, 0.1);
                border-radius: 18px 18px 18px 4px;
                margin-right: 60px;
            }

            .message textview {
                background: transparent;
                color: inherit;
                padding: 0;
                border: none;
            }

            .message textview text {
                background: transparent;
                color: inherit;
            }

            .user-message textview text selection {
                background-color: alpha(@theme_selected_fg_color, 0.3);
                color: @theme_selected_fg_color;
            }

            .assistant-message textview text selection {
                background-color: alpha(@theme_selected_bg_color, 0.3);
                color: @theme_text_color;
            }

            .timestamp {
                font-size: 0.85em;
                opacity: 0.7;
                margin-top: 4px;
            }

            .error-message {
                background-color: alpha(@error_color, 0.1);
                border: 1px solid @error_color;
                border-radius: 8px;
                padding: 12px;
                margin: 8px;
            }

            .error-icon {
                color: @error_color;
                margin-right: 8px;
            }
        """
        
        # Agregar estilos específicos por plataforma si es necesario
        platform_specific = style_manager.get_platform()
        
        if platform_specific == 'windows':
            chat_specific_css += """
                /* Ajustes específicos para Windows */
                window {
                    box-shadow: none;
                }
            """
        elif platform_specific == 'macos':
            # Configurar controles de ventana nativos para macOS
            self.header.set_decoration_layout('close,minimize,maximize:')
            chat_specific_css += """
                /* Ajustes específicos para macOS */
                window {
                    border-radius: 8px;
                }
            """
        
        try:
            css_provider.load_from_data(chat_specific_css, -1)
            
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1  # Mayor prioridad que los estilos base
            )
            debug_print("[OK] Chat-specific CSS loaded successfully")
        except Exception as e:
            debug_print(f"[FAIL] Error loading chat CSS: {e}")

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
            def update_title_on_next_prompt(backend, response):
                conversation_id = self.config.get('cid')
                debug_print(f"Conversation ID post-respuesta: {conversation_id}")
                if conversation_id:
                    self.chat_history.set_conversation_title(
                        conversation_id, self.title_entry.get_text())
                    self.backend.disconnect_by_func(update_title_on_next_prompt)
            self.backend.connect('response', update_title_on_next_prompt)
        self.header.set_title_widget(self.title_widget)
        new_title = self.title_entry.get_text()

        self.title_widget.set_title(new_title)
        self.set_title(new_title)

    def _cancel_set_title(self, controller, keyval, keycode, state):
        """Cancela la edición y restaura el título anterior"""
        if keyval == Gdk.KEY_Escape:
            self.header.set_title_widget(self.title_widget)
            self.title_entry.set_text(self.title_widget.get_title())


    def _on_global_shortcuts(self, controller, keyval, keycode, state):
        """
        Atajos de teclado globales:
        Ctrl+W: Borrar conversación (ya implementado)
        Ctrl+M: Abrir selector de modelo
        Ctrl+S: Cambiar system prompt
        Ctrl+N: Nueva conversación
        """
        # Ctrl+W: Borrar conversación
        if keyval == Gdk.KEY_w and state & Gdk.ModifierType.CONTROL_MASK:
            app = self.get_application()
            app.on_delete_activate(None, None)
            return True

        # Ctrl+M: Abrir selector de modelo (no aplica a backends no-LLM)
        if keyval == Gdk.KEY_m and state & Gdk.ModifierType.CONTROL_MASK:
            if self.model_sidebar is not None:
                # Mostrar el sidebar y cambiar a la página del selector de modelo
                self.split_view.set_show_sidebar(True)
                if hasattr(self.model_sidebar, 'stack'):
                    self.model_sidebar.stack.set_visible_child_name("model_selector")
            return True

        # Ctrl+S: Cambiar system prompt (no aplica a backends no-LLM)
        if keyval == Gdk.KEY_s and state & Gdk.ModifierType.CONTROL_MASK:
            if self.model_sidebar is not None:
                # Mostrar el sidebar y abrir el diálogo de system prompt
                self.split_view.set_show_sidebar(True)
                if hasattr(self.model_sidebar, '_on_system_prompt_button_clicked'):
                    # Simular click en el botón de system prompt
                    self.model_sidebar._on_system_prompt_button_clicked(None)
            return True

        # Ctrl+N: Nueva conversación
        if keyval == Gdk.KEY_n and state & Gdk.ModifierType.CONTROL_MASK:
            app = self.get_application()
            if hasattr(app, 'open_conversation_window'):
                app.open_conversation_window({})
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

        # Notificar 'composing' al backend (spec 001, T8). No-op en LLMClient.
        if self.backend is not None:
            has_text = buffer.get_char_count() > 0
            self.backend.notify_composing(has_text)
            if self._composing_timeout_id:
                GLib.source_remove(self._composing_timeout_id)
                self._composing_timeout_id = None
            if has_text:
                # Sin más tecleo en 5s, avisar que se dejó de escribir
                self._composing_timeout_id = GLib.timeout_add_seconds(
                    5, self._on_composing_timeout)

    def _on_composing_timeout(self):
        self._composing_timeout_id = None
        if self.backend is not None:
            self.backend.notify_composing(False)
        return GLib.SOURCE_REMOVE

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

    def _update_connection_status(self, state):
        """Refleja el estado de conexión del backend en el header (spec 001, T7)."""
        labels = {
            'connecting': _("Connecting…"),
            'connected': _("Connected"),
            'disconnected': _("Disconnected"),
        }
        self.connection_status_label.set_label(labels.get(state, state))
        self.connection_status_label.remove_css_class("error")
        if state == 'disconnected':
            self.connection_status_label.add_css_class("error")

    def _restore_connection_status(self):
        """Restaura el indicador al último estado de conexión conocido tras
        mostrar un error no fatal (spec 001, review fix)."""
        self._update_connection_status(getattr(self, '_last_connection_state', 'connected'))
        return GLib.SOURCE_REMOVE

    def _on_backend_state_changed(self, backend, state):
        """Maneja la señal 'state-changed' del backend (spec 001, T7)."""
        debug_print(f"Estado de conexión del backend: {state}")
        self._last_connection_state = state
        self._update_connection_status(state)

    def _on_backend_typing(self, backend, is_typing):
        """Maneja la señal 'typing' del backend: el contacto está escribiendo
        (spec 001, T8, XEP-0085). Reusa el indicador de conexión, ya que
        ambos son estados efímeros de la contraparte."""
        if is_typing:
            self.connection_status_label.set_label(_("Typing…"))
            self.connection_status_label.remove_css_class("error")
        else:
            self._update_connection_status(getattr(self, '_last_connection_state', 'connected'))

    def _on_backend_ready(self, backend, display_name):
        """Maneja la señal 'ready' del backend (modelo cargado / sesión lista)."""
        debug_print(f"Backend listo: {display_name}")

        # Actualizar el subtítulo de la ventana con el nombre a mostrar
        self.title_widget.set_subtitle(display_name)
        
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
            # Ya se envía el mensaje: cancelar el aviso pendiente de 'composing'
            if self._composing_timeout_id:
                GLib.source_remove(self._composing_timeout_id)
                self._composing_timeout_id = None
            # Display user message
            self.display_message(text, sender="user")
            # Deshabilitar entrada y empezar tarea
            self.set_enabled(False)
            if self._injected_backend:
                # Backends de mensajería (XMPP): no hay una respuesta que
                # rellenar; los mensajes entrantes crean su propia burbuja
                # cuando llegan (_on_llm_response). No dejar un placeholder.
                self.current_message_widget = None
            else:
                # LLM: crear ya la burbuja de respuesta que el stream irá
                # rellenando vía 'response'.
                self.current_message_widget = self.display_message("", sender="assistant")
                self._on_llm_response(self.backend, "")
            GLib.idle_add(self._start_llm_task, text)

    def _start_llm_task(self, prompt_text):
        """Inicia la tarea del backend con el prompt dado."""
        # Enviar el prompt usando el ChatBackend
        self.backend.send_message(prompt_text)

        # Devolver False para que idle_add no se repita
        return GLib.SOURCE_REMOVE

    def _on_llm_error(self, llm_client, message):
        """Muestra un mensaje de error en el chat"""
        debug_print(message, file=sys.stderr)
        if self._injected_backend:
            # Un error de sesión (p.ej. roster fallido) no siempre viene
            # acompañado de 'state-changed'; reflejarlo brevemente en el
            # header. Pero si la sesión sigue conectada (error no fatal),
            # restaurar el estado real tras unos segundos para no dejar
            # "Error" pegado permanentemente.
            self.connection_status_label.set_label(_("Error"))
            self.connection_status_label.add_css_class("error")
            session = getattr(self.backend, 'session', None)
            if session is not None and session.is_connected:
                GLib.timeout_add_seconds(4, self._restore_connection_status)
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
            conversation_id = self.backend.get_conversation_id()
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
        """Maneja la señal de respuesta del backend.

        LLM: rellena la burbuja de assistant creada al enviar (streaming).
        Backends de mensajería (XMPP): cada 'response' es un mensaje
        entrante completo e independiente; crea su propia burbuja.
        """
        if self._injected_backend:
            self.accumulated_response = ""
            self.current_message_widget = self.display_message(
                response, sender="assistant")
            GLib.idle_add(self._scroll_to_bottom, False)
            return

        if not self.current_message_widget:
            return

        # Actualizar el conversation_id en la configuración al recibir la primera respuesta
        if not self.config.get('cid'):
            conversation_id = self.backend.get_conversation_id()
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
        # Cancelar el aviso pendiente de 'composing' para que no dispare
        # contra una ventana ya destruida (enviaría un chatstate espurio).
        if self._composing_timeout_id:
            GLib.source_remove(self._composing_timeout_id)
            self._composing_timeout_id = None
        # Liberar el backend (XmppConversation: suelta sus handlers de la
        # sesión compartida; LLMClient: no-op). Seguro llamarlo siempre.
        if self.backend is not None:
            self.backend.shutdown()
        # El roster sidebar también tiene handlers en la sesión compartida.
        if self.roster_sidebar is not None:
            self.roster_sidebar.shutdown()
        # Eliminar del registro de ventanas (por valor: cubre tanto las
        # claves por CID de LLM como las claves "xmpp:…" de spec 002).
        app = self.get_application()
        if hasattr(app, '_window_by_cid'):
            for key, win in list(app._window_by_cid.items()):
                if win is self:
                    debug_print(f"Eliminando ventana del registro: {key}")
                    del app._window_by_cid[key]
        # Lógica de cierre global: si es la última ventana
        if len(app.get_windows()) <= 1:
            debug_print("Última ventana cerrada saliendo de la aplicación (desde chat_window)")
            app.quit()
        # Permitir el cierre de la ventana
        return False

    def _on_window_show(self, window):
        """Set focus to the input text when the window is shown."""
        # Configurar recursos de forma segura cuando la ventana se muestra
        if not hasattr(self, '_resources_configured'):
            try:
                # Configurar recursos en el hilo principal sin threading adicional
                from .resource_manager import resource_manager
                if not resource_manager._icon_theme_configured:
                    resource_manager.setup_icon_theme()
                self._resources_configured = True
                debug_print("Recursos configurados al mostrar ventana")
            except Exception as e:
                debug_print(f"Error configurando recursos en window show: {e}")
        
        # Handle benchmark startup
        if self.benchmark_startup and self.start_time:
            end_time = time.time()
            elapsed_time = end_time - self.start_time
            debug_print(f"Startup time: {elapsed_time:.4f} seconds")
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

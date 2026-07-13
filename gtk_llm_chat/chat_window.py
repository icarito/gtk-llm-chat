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
from gi.repository import Gtk, Adw, Gio, Gdk, GLib, GObject, Pango

from .llm_client import LLMClient, DEFAULT_CONVERSATION_NAME
from .widgets import Message, MessageWidget, ErrorWidget
from .db_operations import ChatHistory
from .chat_application import _
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

    def __init__(self, config=None, chat_history=None, backend=None,
                 xmpp_session=None, **kwargs):
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

        # Estado del backend (contrato ChatBackend) y su sidebar — inicializado
        # aquí y poblado de verdad por _bind_backend() más abajo en este
        # __init__ (y, potencialmente, de nuevo más tarde para transformar
        # la ventana in-place; spec 003 T7). _injected_backend se calcula ya
        # (solo depende de los parámetros de entrada, no del backend en sí)
        # porque el chrome del header construido más abajo decide su propio
        # aspecto (qué botón mostrar, a qué lado) según este flag.
        self.backend = None
        self._backend_handler_ids = []
        self._session_handler_ids = []
        self._xmpp_session = None
        self._injected_backend = backend is not None or xmpp_session is not None
        self._composing_timeout_id = None
        self._sticky_response_cards = []
        self._sticky_response_items = []
        self._sticky_response_next_id = 0
        self._approval_bypass_updating = False
        self.roster_sidebar = None
        self.model_sidebar = None
        self.model_options = None

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
        self._title_is_user_renamed = False

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
        self.header.set_centering_policy(Adw.CenteringPolicy.LOOSE)
        self.title_widget = Adw.WindowTitle.new(title, "")
        self.title_presence_dot = Gtk.Image.new_from_icon_name("media-record-symbolic")
        self.title_presence_dot.add_css_class("success")
        self.title_presence_dot.set_tooltip_text(_("Online"))
        self.title_presence_dot.set_valign(Gtk.Align.CENTER)
        self.title_presence_dot.set_visible(False)

        self.header_title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.header_title_box.set_hexpand(True)
        self.header_title_box.set_halign(Gtk.Align.START)
        self.header_title_box.set_valign(Gtk.Align.CENTER)
        self.header_title_box.append(self.title_presence_dot)
        self.title_widget.set_hexpand(True)
        self.title_widget.set_halign(Gtk.Align.START)
        self.header_title_box.append(self.title_widget)
        self.header_title_stack = Gtk.Stack()
        self.header_title_stack.set_hexpand(True)
        self.header_title_stack.set_halign(Gtk.Align.START)
        self.header_title_stack.add_named(self.header_title_box, "title")
        self.header_title_stack.add_named(self.title_entry, "edit")
        self.header_title_stack.set_visible_child_name("title")
        self.header.set_title_widget(Gtk.Box())
        self.header.pack_start(self.header_title_stack)
        self.set_title(title)  # Set window title based on initial title

        # Workaround de controles nativos en macOS (centralizado, con delay para asegurar renderizado)
        import sys
        if sys.platform == 'darwin':
            def _apply_native_controls():
                style_manager.apply_macos_native_window_controls(self.header)
                return False  # Ejecutar solo una vez
            GLib.idle_add(_apply_native_controls)

        # --- Barra de estado XMPP: mantiene el headerbar solo para título y acciones. ---
        self.xmpp_toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.xmpp_toolbar.set_visible(self._injected_backend)

        self.xmpp_status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.xmpp_status_bar.add_css_class("toolbar")
        self.xmpp_status_bar.add_css_class("flat")
        self.xmpp_status_bar.set_margin_start(12)
        self.xmpp_status_bar.set_margin_end(12)
        self.xmpp_status_bar.set_margin_top(0)
        self.xmpp_status_bar.set_margin_bottom(0)
        self.xmpp_status_bar.set_visible(self._injected_backend)
        self.title_presence_dot.set_visible(False)

        self.connection_status_label = Gtk.Label()
        self.connection_status_label.add_css_class("dim-label")
        self.connection_status_label.add_css_class("caption")
        self.connection_status_label.set_xalign(0)

        self.contact_status_label = Gtk.Label()
        self.contact_status_label.add_css_class("dim-label")
        self.contact_status_label.add_css_class("caption")
        self.contact_status_label.set_xalign(1)
        self.contact_status_label.set_hexpand(True)
        self.contact_status_label.set_ellipsize(Pango.EllipsizeMode.END)

        self.xmpp_status_bar.append(self.connection_status_label)
        self.xmpp_status_bar.append(self.contact_status_label)

        self.xmpp_controls_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.xmpp_controls_bar.add_css_class("toolbar")
        self.xmpp_controls_bar.add_css_class("flat")
        self.xmpp_controls_bar.set_margin_start(12)
        self.xmpp_controls_bar.set_margin_end(12)
        self.xmpp_controls_bar.set_margin_bottom(4)

        self.agent_options_button = Gtk.MenuButton()
        self.agent_options_button.add_css_class("flat")
        self.agent_options_button.set_tooltip_text(_("Agent controls"))
        self.agent_options_button.set_child(
            resource_manager.create_icon_widget("emblem-system-symbolic"))
        self.agent_options_popover = Gtk.Popover()
        agent_options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        agent_options_box.set_margin_top(10)
        agent_options_box.set_margin_bottom(10)
        agent_options_box.set_margin_start(10)
        agent_options_box.set_margin_end(10)
        self.approval_bypass_toggle = Gtk.ToggleButton(label=_("Approval bypass"))
        self.approval_bypass_toggle.add_css_class("flat")
        self.approval_bypass_toggle.set_tooltip_text(
            _("Temporarily auto-approve agent approval requests"))
        self.approval_bypass_toggle.connect("toggled", self._on_approval_bypass_toggled)
        self.approval_bypass_toggle.set_sensitive(False)
        agent_options_box.append(self.approval_bypass_toggle)
        self.agent_options_popover.set_child(agent_options_box)
        self.agent_options_button.set_popover(self.agent_options_popover)
        self.agent_options_button.set_sensitive(False)
        self.xmpp_controls_bar.append(self.agent_options_button)

        self.agent_activity_label = Gtk.Label()
        self.agent_activity_label.add_css_class("caption")
        self.agent_activity_label.set_xalign(0)
        self.agent_activity_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.agent_activity_label.set_hexpand(True)
        self.xmpp_controls_bar.append(self.agent_activity_label)

        self.agent_context_label = Gtk.Label()
        self.agent_context_label.add_css_class("caption")
        self.agent_context_label.add_css_class("dim-label")
        self.agent_context_label.set_xalign(1)
        self.agent_context_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.xmpp_controls_bar.append(self.agent_context_label)

        self.xmpp_toolbar.append(self.xmpp_status_bar)
        self.xmpp_toolbar.append(self.xmpp_controls_bar)

        # --- Botones de la Header Bar ---
        # --- Botón para mostrar/ocultar el panel lateral (sidebar) ---
        self.sidebar_button = Gtk.ToggleButton()
        resource_manager.set_widget_icon_name(self.sidebar_button, "brain-symbolic")
        self.sidebar_button.set_tooltip_text(_("Roster"))
        # No conectar 'toggled' aquí si usamos bind_property
        # Backends no-LLM no tienen sidebar de modelo en el MVP (spec 001)
        self.sidebar_button.set_visible(False)

        # Botón de roster: misma superficie para LLM y XMPP.
        self.roster_button = Gtk.ToggleButton()
        resource_manager.set_widget_icon_name(self.roster_button, "system-users-symbolic")
        self.roster_button.set_tooltip_text(_("Roster"))
        self.roster_button.set_visible(True)

        # Crear botón Rename
        rename_button = Gtk.Button()
        resource_manager.set_widget_icon_name(rename_button, "document-edit-symbolic")
        rename_button.set_tooltip_text(_("Rename"))
        rename_button.connect('clicked', lambda x: self.get_application().on_rename_activate(None, None))

        # --- Menú principal (hamburguesa): punto de entrada a nuevas
        # conversaciones LLM y XMPP (spec 002) ---
        primary_menu = Gio.Menu()
        primary_menu.append(_("New Conversation"), "app.new-conversation")
        xmpp_section = Gio.Menu()
        xmpp_section.append(_("XMPP Account…"), "app.xmpp-account")
        xmpp_section.append(_("Reconnect XMPP"), "app.xmpp-reconnect")
        xmpp_section.append(_("Disconnect XMPP"), "app.xmpp-disconnect")
        xmpp_section.append(_("Remove XMPP Account…"), "app.xmpp-remove-account")
        primary_menu.append_section(None, xmpp_section)
        self.primary_menu_button = Gtk.MenuButton()
        resource_manager.set_widget_icon_name(self.primary_menu_button, "view-more-symbolic")
        self.primary_menu_button.set_tooltip_text(_("Main Menu"))
        self.primary_menu_button.set_menu_model(primary_menu)

        self.agent_menu_button = Gtk.MenuButton()
        resource_manager.set_widget_icon_name(
            self.agent_menu_button, "applications-system-symbolic")
        self.agent_menu_button.set_tooltip_text(_("Agent"))
        self.agent_menu_button.set_visible(False)

        self.header.pack_end(self.primary_menu_button)
        self.header.pack_end(self.agent_menu_button)
        self.header.pack_end(self.sidebar_button)
        self.header.pack_end(rename_button)
        self.header.pack_end(self.roster_button)

        # --- Fin Botones Header Bar ---

        # --- Contenedor principal (OverlaySplitView) ---
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_vexpand(True)
        self.split_view.set_collapsed(True) # Empezar colapsado
        self.split_view.set_show_sidebar(False)
        self.split_view.set_min_sidebar_width(280)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.set_sidebar_position(Gtk.PackType.END)

        # El binding 'show-sidebar' <-> botón toggle se crea en _bind_backend
        # (spec 003, T7), ya que depende de qué botón corresponde al tipo de
        # backend actual y puede cambiar si la ventana se re-bindea.
        # Conectar al cambio de 'show-sidebar' para cambiar el icono y foco
        self.split_view.connect("notify::show-sidebar", self._on_sidebar_visibility_changed)

        # --- Contenido principal (el chat) ---
        chat_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        style_manager.apply_to_widget(chat_content_box, "chat-container")
        
        # ScrolledWindow para el historial de mensajes
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.connect("edge-reached", self._on_edge_reached)
        self.message_scroll = scroll
        # Al redimensionar la ventana, mantener anclado el último mensaje
        # visible: se guarda la distancia al fondo mientras el usuario hace
        # scroll y se restaura cuando cambia el alto del viewport (page_size).
        self._scroll_bottom_distance = 0.0
        self._scroll_last_page_size = 0.0
        self._restoring_scroll = False
        vadj = scroll.get_vadjustment()
        vadj.connect("value-changed", self._on_vadj_value_changed)
        vadj.connect("changed", self._on_vadj_changed)
        
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

        self.sticky_response_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sticky_response_box.set_margin_top(6)
        self.sticky_response_box.set_margin_start(6)
        self.sticky_response_box.set_margin_end(6)
        self.sticky_response_box.set_visible(False)

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
        chat_content_box.append(self.sticky_response_box)
        chat_content_box.append(input_box)

        # Establecer el contenido principal en el split_view
        self.split_view.set_content(chat_content_box)

        # --- Panel Lateral (Sidebar) y backend ---
        # Extraído a _bind_backend (spec 003, T7): el chrome de arriba (header,
        # split_view, área de chat) se construye una sola vez aquí; el backend
        # y su sidebar se pueden re-bindear más tarde sobre la misma ventana
        # sin reconstruir nada — ver _bind_backend / _unbind_backend.
        self._bind_backend(backend=backend, xmpp_session=xmpp_session)

        # --- Ensamblado Final ---
        # El contenedor principal ahora incluye la HeaderBar y el SplitView
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root_box.append(self.header)
        root_box.append(self.xmpp_toolbar)
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

        self._xmpp_history_batch = None
        self._xmpp_history_actions_batch = None


    def _unbind_backend(self):
        """Suelta el backend y el sidebar actuales de esta ventana (spec 003,
        T7): desconecta handlers de sesiones compartidas y limpia las
        referencias, dejando la ventana lista para un _bind_backend nuevo o
        para cerrarse. Idempotente — seguro llamarla aunque no haya nada que
        soltar (ventana recién construida)."""
        if self._composing_timeout_id:
            GLib.source_remove(self._composing_timeout_id)
            self._composing_timeout_id = None
        if self.backend is not None:
            # Desconectar las señales explícitamente antes de soltar la
            # referencia: shutdown()/cancel() no garantiza que el backend
            # deje de emitir (p.ej. LLMClient.cancel() es un no-op, su hilo
            # de streaming sigue corriendo y llamando GLib.idle_add). Sin
            # esto, una señal tardía del backend viejo llega igual a estos
            # mismos handlers y corrompe el estado de la conversación nueva
            # (self.cid, self.accumulated_response, current_message_widget).
            for handler_id in self._backend_handler_ids:
                self.backend.disconnect(handler_id)
            self.backend.shutdown()
        self._backend_handler_ids = []
        if self._xmpp_session is not None:
            for handler_id in self._session_handler_ids:
                self._xmpp_session.disconnect(handler_id)
        self._session_handler_ids = []
        if self.roster_sidebar is not None:
            self.roster_sidebar.shutdown()
            self.roster_sidebar = None
        self.model_sidebar = None
        self.model_options = None
        self.backend = None
        self._xmpp_session = None
        # Una nueva conversación (o la misma reabierta) necesita su propio
        # historial: sin esto, los flags "ya cargado" de la conversación
        # anterior bloquean permanentemente _load_and_display_history.
        self._history_loaded = False
        self._history_displayed = False
        self.current_message_widget = None
        self.accumulated_response = ""
        self._xmpp_history_batch = []
        self._xmpp_history_actions_batch = []
        self._xmpp_history_loaded = False
        self._xmpp_backfill_remaining = 0
        self._agent_command_client = None
        self._clear_sticky_response_cards()
        for child in list(self.messages_box):
            self.messages_box.remove(child)
        # Deshacer el binding show-sidebar <-> botón toggle del bind anterior;
        # si no, cada _bind_backend acumularía otro binding sobre la misma
        # propiedad (fuga y comportamiento errático al alternar toggles).
        if getattr(self, '_sidebar_toggle_binding', None) is not None:
            self._sidebar_toggle_binding.unbind()
            self._sidebar_toggle_binding = None

    def _bind_backend(self, backend=None, xmpp_session=None):
        """Conecta un backend (y su sidebar) a esta ventana — spec 003, T7.

        Se llama una vez desde __init__ para el estado inicial, y puede
        volver a llamarse más tarde para transformar una ventana ya viva
        (p.ej. el picker de contacto XMPP al elegir uno, o el sidebar de
        conversaciones LLM al elegir una distinta) sin reconstruir el
        chrome (header, split_view, área de chat), que ya existe.

        Args:
            backend: ChatBackend ya construido (p.ej. XmppConversation) a
                inyectar en la ventana en vez del LLMClient por defecto.
            xmpp_session: sesión XMPP sin contacto elegido todavía —
                la ventana muestra el roster y espera selección.
        """
        self._unbind_backend()
        self._title_is_user_renamed = False
        self._xmpp_session = xmpp_session
        self._injected_backend = backend is not None or xmpp_session is not None

        # El chrome (botones, posición del split_view) refleja el tipo de
        # backend; se actualiza aquí porque puede cambiar entre llamadas
        # (p.ej. una ventana XMPP vacía nunca pasa a modo LLM en la práctica,
        # pero el flag sí puede alternar entre "sin contacto" y "con contacto").
        self.xmpp_toolbar.set_visible(self._injected_backend)
        self.xmpp_status_bar.set_visible(self._injected_backend)
        self.sidebar_button.set_visible(False)
        self.roster_button.set_visible(True)
        self.agent_menu_button.set_visible(False)
        toggle_button = self.roster_button
        self._sidebar_toggle_binding = self.split_view.bind_property(
            "show-sidebar", toggle_button, "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.set_enabled(True)
        self.split_view.set_collapsed(True)
        self.split_view.set_show_sidebar(False)

        if self._injected_backend:
            # Backend no-LLM (p.ej. XmppConversation): ya viene construido
            # y conectado a su sesión propia. Solo cablear las señales del
            # contrato ChatBackend; nada de modelo/proveedor/sidebar LLM.
            self.backend = backend
            session = getattr(backend, 'session', None) or xmpp_session
            self._xmpp_session = session
            if backend is not None:
                self._backend_handler_ids = [
                    backend.connect('ready', self._on_backend_ready),
                    backend.connect('response', self._on_llm_response),
                    backend.connect('response-correction',
                                    self._on_llm_response_correction),
                    backend.connect('error', self._on_llm_error),
                    backend.connect('finished', self._on_llm_finished),
                    backend.connect('state-changed', self._on_backend_state_changed),
                    backend.connect('typing', self._on_backend_typing),
                    backend.connect('quick-responses', self._on_quick_responses),
                    backend.connect('commands', self._on_commands),
                ]
                self._update_xmpp_title_status()
                self._refresh_agent_menu()
            else:
                # Sin contacto elegido aún: mostrar el roster, deshabilitar
                # el chat hasta que el usuario elija una fila (spec 003).
                self.title_widget.set_subtitle("")
                self.title_presence_dot.set_visible(False)
                self.contact_status_label.set_label(_("Choose a contact"))
                self.set_enabled(False)
            # Estado inicial: la sesión puede ya estar 'connected' antes de
            # que esta ventana exista (el roster picker implica sesión viva).
            self._last_connection_state = session.state if session else 'connected'
            self._update_connection_status(self._last_connection_state)
            # Roster unificado dockeado a la izquierda.
            if session is not None:
                self._session_handler_ids = [
                    session.connect('contact-status-changed',
                                    self._on_contact_status_changed),
                    session.connect('presence-changed',
                                    self._on_contact_presence_changed),
                ]
                from .chat_roster_sidebar import ChatRosterSidebar
                self.roster_sidebar = ChatRosterSidebar(
                    config=self.config,
                    chat_history=self.chat_history,
                    xmpp_session=session,
                    on_llm_conversation_selected=self._on_llm_conversation_selected,
                    on_xmpp_contact_selected=self._on_roster_contact_selected,
                    on_xmpp_account=self._open_xmpp_account_from_sidebar)
                self.model_sidebar = self.roster_sidebar
                self.model_options = self.roster_sidebar.options_sidebar
                self.split_view.set_sidebar_position(Gtk.PackType.START)
                self.split_view.set_sidebar(self.roster_sidebar)
                if backend is None:
                    # Sin contacto: el roster se ve de entrada, no detrás
                    # de un toggle — es lo único que hay que hacer aquí.
                    self.split_view.set_show_sidebar(True)
                    self.split_view.set_collapsed(False)
        else:
            # Initialize the backend *after* basic UI setup
            try:
                debug_print(f"Inicializando LLMClient con config: {self.config}")
                self.backend = LLMClient(self.config, self.chat_history)
                # Connect ChatBackend signals *here*
                self._backend_handler_ids = [
                    self.backend.connect('ready', self._on_backend_ready),
                    self.backend.connect('response', self._on_llm_response),
                    self.backend.connect('error', self._on_llm_error),
                    self.backend.connect('finished', self._on_llm_finished),
                ]

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

            app = self.get_application()
            session = None
            if app is not None and hasattr(app, 'get_xmpp_session_for_roster'):
                session = app.get_xmpp_session_for_roster()
            self._xmpp_session = session
            if session is not None:
                self._session_handler_ids = [
                    session.connect('contact-status-changed',
                                    self._on_contact_status_changed),
                    session.connect('presence-changed',
                                    self._on_contact_presence_changed),
                ]

            # Roster unificado: conversaciones LLM y contactos XMPP en el
            # mismo panel. Las opciones de modelo quedan como segundo nivel.
            from .chat_roster_sidebar import ChatRosterSidebar
            self.model_sidebar = ChatRosterSidebar(
                config=self.config,
                llm_client=self.backend,
                chat_history=self.chat_history,
                xmpp_session=session,
                on_llm_conversation_selected=self._on_llm_conversation_selected,
                on_xmpp_contact_selected=self._on_roster_contact_selected,
                on_xmpp_account=self._open_xmpp_account_from_sidebar)
            self.roster_sidebar = self.model_sidebar
            self.model_options = self.model_sidebar.options_sidebar
            self.split_view.set_sidebar(self.model_sidebar)
            self.split_view.set_sidebar_position(Gtk.PackType.START)

    # Resetear el stack al cerrar el sidebar
    def _on_sidebar_visibility_changed(self, split_view, param):
        show_sidebar = split_view.get_show_sidebar()
        if not show_sidebar:
            if self.model_sidebar is not None:
                self.model_sidebar.show_list()
            if self.model_options is not None:
                self.model_options.stack.set_visible_child_name("actions")
            self.input_text.grab_focus()

    def _on_roster_contact_selected(self, bare_jid):
        """Un contacto elegido en el roster unificado: abre/enfoca su chat."""
        app = self.get_application()
        session = getattr(self.backend, 'session', None) or self._xmpp_session
        if session is None:
            return
        if self.backend is None:
            # Esta ventana era el picker de contacto (sin conversación
            # elegida aún, spec 003): transformarla en la conversación
            # in-place (T7) en vez de abrir una segunda ventana y cerrar
            # esta — misma ventana, registrada en la app para focus-or-open.
            conversation = session.get_conversation(bare_jid)
            self._bind_backend(backend=conversation)
            if app is not None and hasattr(app, '_window_by_cid'):
                app._window_by_cid[f"xmpp:{session.bare_jid}:{bare_jid}"] = self
        elif app is not None and hasattr(app, 'open_xmpp_conversation'):
            # Ventana ya en una conversación: cambiar de contacto abre/
            # enfoca la ventana de ese contacto vía el registro habitual.
            app.open_xmpp_conversation(session, bare_jid)
            self.split_view.set_show_sidebar(False)

    def _open_xmpp_account_from_sidebar(self):
        app = self.get_application()
        if app is None:
            return
        if hasattr(app, '_open_xmpp_account_dialog'):
            app._open_xmpp_account_dialog(
                on_ready=lambda _jid: self._refresh_xmpp_session_from_account())
        elif hasattr(app, 'on_xmpp_account_activate'):
            app.on_xmpp_account_activate(None, None)

    def _refresh_xmpp_session_from_account(self):
        app = self.get_application()
        if app is None or not hasattr(app, 'get_xmpp_session_for_roster'):
            return
        session = app.get_xmpp_session_for_roster()
        if self.backend is None or getattr(self.backend, 'session', None) is not None:
            self._bind_backend(xmpp_session=session)
        else:
            self._replace_roster_sidebar(session)

    def _replace_roster_sidebar(self, session):
        if self._xmpp_session is not None:
            for handler_id in self._session_handler_ids:
                self._xmpp_session.disconnect(handler_id)
        self._session_handler_ids = []
        if self.roster_sidebar is not None:
            self.roster_sidebar.shutdown()
        self._xmpp_session = session
        if session is not None:
            self._session_handler_ids = [
                session.connect('contact-status-changed',
                                self._on_contact_status_changed),
                session.connect('presence-changed',
                                self._on_contact_presence_changed),
            ]
        from .chat_roster_sidebar import ChatRosterSidebar
        self.model_sidebar = ChatRosterSidebar(
            config=self.config,
            llm_client=self.backend,
            chat_history=self.chat_history,
            xmpp_session=session,
            on_llm_conversation_selected=self._on_llm_conversation_selected,
            on_xmpp_contact_selected=self._on_roster_contact_selected,
            on_xmpp_account=self._open_xmpp_account_from_sidebar)
        self.roster_sidebar = self.model_sidebar
        self.model_options = self.model_sidebar.options_sidebar
        self.split_view.set_sidebar_position(Gtk.PackType.START)
        self.split_view.set_sidebar(self.model_sidebar)

    def _on_llm_conversation_selected(self, cid):
        """Una conversación LLM elegida en el roster: cambia esta ventana
        in-place salvo que ya tenga una ventana registrada."""
        if cid == self.cid:
            self.split_view.set_show_sidebar(False)
            return
        app = self.get_application()
        existing = getattr(app, '_window_by_cid', {}).get(cid) if app else None
        if existing is not None and existing is not self:
            existing.present()
            self.split_view.set_show_sidebar(False)
            return

        # Sin ventana propia: transformar esta misma ventana in-place.
        # _bind_backend's rama LLM lee self.config['cid'] para construir el
        # LLMClient correcto (mismo camino que __init__ usa al abrir con
        # un CID existente), así que basta con actualizarlo antes de llamar.
        old_cid = self.cid
        old_xmpp_key = None
        old_session = getattr(self.backend, 'session', None)
        old_bare_jid = getattr(self.backend, 'bare_jid', None)
        if old_session is not None and old_bare_jid:
            old_xmpp_key = f"xmpp:{old_session.bare_jid}:{old_bare_jid}"
        self.config['cid'] = cid
        self.cid = cid
        self._bind_backend(backend=None)
        if app is not None and hasattr(app, '_window_by_cid'):
            if old_cid and app._window_by_cid.get(old_cid) is self:
                del app._window_by_cid[old_cid]
            if old_xmpp_key and app._window_by_cid.get(old_xmpp_key) is self:
                del app._window_by_cid[old_xmpp_key]
            app._window_by_cid[cid] = self
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

            .sticky-response-card {
                padding: 8px;
                border: 1px solid alpha(@theme_fg_color, 0.14);
                background-color: @theme_base_color;
            }

            .sticky-response-count {
                font-weight: bold;
            }

            .sticky-response-popover-row {
                padding: 8px;
                border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
            }

            .sticky-response-detail {
                font-size: 0.88em;
                opacity: 0.78;
            }

            .command-result-message .message-content {
                border-left: 3px solid alpha(@accent_color, 0.75);
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

    def _restore_header_title_widget(self):
        self.header_title_stack.set_visible_child_name("title")

    def begin_title_edit(self):
        self.title_entry.set_text(self.title_widget.get_title())
        self.header_title_stack.set_visible_child_name("edit")
        self.title_entry.grab_focus()

    def _on_save_title(self, widget):
        app = self.get_application()
        if self._injected_backend:
            self._title_is_user_renamed = True
            self._restore_header_title_widget()
            new_title = self.title_entry.get_text()
            self.title_widget.set_title(new_title)
            self.set_title(new_title)
            return

        conversation_id = self.config.get('cid')
        if conversation_id:
            self.chat_history.set_conversation_title(
                conversation_id, self.title_entry.get_text())
            debug_print(f"Guardando título para conversación {conversation_id}: {self.title_entry.get_text()}")
            if self.model_sidebar is not None:
                self.model_sidebar.refresh()
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
        self._restore_header_title_widget()
        new_title = self.title_entry.get_text()

        self.title_widget.set_title(new_title)
        self.set_title(new_title)

    def _cancel_set_title(self, controller, keyval, keycode, state):
        """Cancela la edición y restaura el título anterior"""
        if keyval == Gdk.KEY_Escape:
            self._restore_header_title_widget()
            self.title_entry.set_text(self.title_widget.get_title())


    def _on_global_shortcuts(self, controller, keyval, keycode, state):
        """
        Atajos de teclado globales:
        Ctrl+W: Borrar conversación (ya implementado)
        Ctrl+M: Abrir selector de modelo
        Ctrl+S: Cambiar system prompt
        Ctrl+N: Nueva conversación
        Ctrl+Q: Salir de la aplicación
        """
        # Ctrl+Q: Salir de la aplicación (quit explícito, sin importar
        # si hay sesión XMPP activa — a diferencia de cerrar la última
        # ventana, esto es una intención inequívoca del usuario).
        if keyval == Gdk.KEY_q and state & Gdk.ModifierType.CONTROL_MASK:
            app = self.get_application()
            if app is not None:
                app.quit()
            return True
        # Ctrl+W: Borrar conversación
        if keyval == Gdk.KEY_w and state & Gdk.ModifierType.CONTROL_MASK:
            app = self.get_application()
            app.on_delete_activate(None, None)
            return True

        # Ctrl+M: Abrir selector de modelo (no aplica a backends no-LLM)
        if keyval == Gdk.KEY_m and state & Gdk.ModifierType.CONTROL_MASK:
            if self.model_sidebar is not None and self.model_options is not None:
                # Mostrar el sidebar, ir a opciones, y a la página del selector
                self.split_view.set_show_sidebar(True)
                self.model_sidebar.show_options()
                self.model_options.stack.set_visible_child_name("model_selector")
            return True

        # Ctrl+S: Cambiar system prompt (no aplica a backends no-LLM)
        if keyval == Gdk.KEY_s and state & Gdk.ModifierType.CONTROL_MASK:
            if self.model_sidebar is not None and self.model_options is not None:
                # Mostrar el sidebar, ir a opciones, y abrir el diálogo de system prompt
                self.split_view.set_show_sidebar(True)
                self.model_sidebar.show_options()
                if hasattr(self.model_options, '_on_system_prompt_button_clicked'):
                    self.model_options._on_system_prompt_button_clicked(None)
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
        if self._is_composition_key(keyval, state):
            return False
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            # Permitir Shift+Enter para nuevas líneas
            if not (state & Gdk.ModifierType.SHIFT_MASK):
                self._on_send_clicked(None)
                return True
        return False

    @staticmethod
    def _is_composition_key(keyval, state):
        key_name = Gdk.keyval_name(keyval) or ""
        return (
            key_name.startswith("dead_") or
            keyval in (Gdk.KEY_Multi_key, Gdk.KEY_ISO_Level3_Shift)
        )

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
        """Refleja el estado de conexión del backend en la barra XMPP."""
        labels = {
            'connecting': _("Connecting…"),
            'reconnecting': _("Reconnecting…"),
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
        previous = getattr(self, '_last_connection_state', None)
        self._last_connection_state = state
        self._update_connection_status(state)
        # Al (re)conectar, ponerse al día con los mensajes que llegaron
        # mientras la sesión estuvo caída. La carga inicial la hace
        # _load_xmpp_history; aquí solo cubrimos la transición de un estado
        # no-conectado a 'connected' una vez que el historial ya se mostró.
        if (state == 'connected' and previous not in (None, 'connected')
                and getattr(self, '_xmpp_history_loaded', False)):
            self._catch_up_xmpp_history()

    def _catch_up_xmpp_history(self):
        """Trae por MAM los mensajes recibidos mientras estábamos offline y
        los añade al final de la conversación (spec 004, reconexión)."""
        backend = self.backend
        if backend is None or not hasattr(backend, 'load_history_from_mam'):
            return
        # Tratar el lote resultante como backfill para que se anexe abajo
        # (mensajes más nuevos), no como scroll-hacia-arriba (prepend).
        # Solo subir el contador si de verdad se lanzó la consulta, o el
        # 'history-complete' que lo decrementa nunca llegaría.
        self._xmpp_backfill_remaining += 1
        if not backend.load_history_from_mam():
            self._xmpp_backfill_remaining -= 1

    def _on_backend_typing(self, backend, is_typing):
        """Maneja la señal 'typing' del backend: el contacto está escribiendo
        (spec 001, T8, XEP-0085)."""
        if is_typing:
            bare_jid = getattr(self.backend, 'bare_jid', None)
            self.contact_status_label.set_label(
                f"{bare_jid} - {_('Typing…')}" if bare_jid else _("Typing…"))
        else:
            self._update_xmpp_title_status()

    def _on_contact_status_changed(self, session, bare_jid):
        active_bare = getattr(self.backend, 'bare_jid', None)
        if bare_jid == active_bare:
            self._update_xmpp_title_status()
            self._refresh_agent_menu()

    def _on_contact_presence_changed(self, session, bare_jid, state):
        active_bare = getattr(self.backend, 'bare_jid', None)
        if bare_jid == active_bare:
            self._update_xmpp_title_status()

    def _update_xmpp_title_status(self):
        if self.backend is None:
            return
        session = getattr(self.backend, 'session', None)
        bare_jid = getattr(self.backend, 'bare_jid', None)
        if session is None or bare_jid is None:
            self.title_widget.set_subtitle("")
            self.title_presence_dot.set_visible(False)
            self.contact_status_label.set_label(self.backend.get_display_name())
            self._update_agent_controls(False)
            self._update_agent_state_chips("")
            return
        display_name = self.backend.get_display_name()
        if not self._title_is_user_renamed:
            self.title_widget.set_title(display_name)
            self.title_entry.set_text(display_name)
            self.set_title(display_name)
        self.title_widget.set_subtitle("")
        status = session.get_contact_status(bare_jid)
        presence = session.get_presence(bare_jid)
        is_online = presence == 'online'
        self.title_presence_dot.set_visible(is_online)
        presence_label = _("Online") if is_online else _("Offline")
        display_status = status or presence_label
        self.contact_status_label.set_label(bare_jid)
        self.contact_status_label.set_tooltip_text(display_status)
        self._update_agent_state_chips(display_status)
        self._update_agent_controls(session.is_agent_contact(bare_jid))

    def _update_agent_controls(self, is_agent):
        if not hasattr(self, 'approval_bypass_toggle'):
            return
        self.approval_bypass_toggle.set_sensitive(bool(is_agent))
        self.agent_options_button.set_sensitive(bool(is_agent))

    def _update_agent_state_chips(self, status):
        if not hasattr(self, 'agent_activity_label'):
            return
        parts = [part.strip() for part in str(status or "").split("|") if part.strip()]
        activity = self._friendly_agent_activity(parts[0] if parts else "")
        details = " | ".join(parts[1:])
        self.agent_activity_label.set_label(activity)
        self.agent_activity_label.set_tooltip_text(str(status or ""))
        self.agent_context_label.set_label(details)
        self.agent_context_label.set_tooltip_text(details)
        lower = str(status or "").lower()
        if "bypass de aprobaciones: activo" in lower or "approval bypass: active" in lower:
            self._approval_bypass_updating = True
            self.approval_bypass_toggle.set_active(True)
            self._approval_bypass_updating = False
        elif "bypass de aprobaciones: apagado" in lower or "approval bypass: off" in lower:
            self._approval_bypass_updating = True
            self.approval_bypass_toggle.set_active(False)
            self._approval_bypass_updating = False

    @staticmethod
    def _friendly_agent_activity(activity):
        text = str(activity or "").strip()
        lower = text.lower()
        if lower == "processing":
            return _("Trabajando")
        if lower == "available":
            return _("Disponible")
        if lower == "waiting":
            return _("En espera")
        if lower.startswith("tool:"):
            return _("Usando herramienta: ") + text.split(":", 1)[1].strip()
        return text

    def _refresh_agent_menu(self):
        if self.backend is None:
            self.agent_menu_button.set_visible(False)
            return
        session = getattr(self.backend, 'session', None)
        bare_jid = getattr(self.backend, 'bare_jid', None)
        if session is None or bare_jid is None or not session.is_agent_contact(bare_jid):
            self.agent_menu_button.set_visible(False)
            return
        self.agent_menu_button.set_visible(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        compact = Gtk.Button(label=_("Compact Context"))
        compact.connect("clicked", lambda _b: self._confirm_agent_text_command(
            _("Compact Context"), _("Ask the agent to compact its current context?"),
            "/compact"))
        clear = Gtk.Button(label=_("Clear Context"))
        clear.add_css_class("destructive-action")
        clear.connect("clicked", lambda _b: self._confirm_agent_text_command(
            _("Clear Context"), _("Ask the agent to clear its current context?"),
            "/clear", destructive=True))
        box.append(compact)
        box.append(clear)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.append(separator)

        loading = Gtk.Label(label=_("Loading commands…"))
        loading.add_css_class("dim-label")
        box.append(loading)
        popover = Gtk.Popover()
        popover.set_child(box)
        self.agent_menu_button.set_popover(popover)
        self._load_agent_commands(box, loading)

    def _on_approval_bypass_toggled(self, button):
        if self._approval_bypass_updating:
            return
        mode = 'activar' if button.get_active() else 'apagar'
        self._run_approval_bypass_command(mode)

    def _run_approval_bypass_command(self, mode):
        if self.backend is None:
            return
        session = getattr(self.backend, 'session', None)
        bare_jid = getattr(self.backend, 'bare_jid', None)
        if session is None or bare_jid is None:
            return

        from .xmpp_commands import XmppCommandClient, next_action_for
        from nbxmpp.modules.dataforms import SimpleDataForm, create_field

        client = XmppCommandClient(session, bare_jid)
        self._agent_command_client = client

        def revert_toggle():
            self._approval_bypass_updating = True
            self.approval_bypass_toggle.set_active(not self.approval_bypass_toggle.get_active())
            self._approval_bypass_updating = False

        def on_error(message):
            revert_toggle()
            self._on_llm_error(self.backend, message)

        def submit_bypass_form(result):
            fields = [
                create_field('list-single', var='mode', value='on' if mode == 'activar' else 'off'),
                create_field('text-single', var='minutes', value='15'),
            ]
            dataform = SimpleDataForm(type_='submit', fields=fields)

            def on_done(done):
                self.connection_status_label.set_label(_("Approval bypass updated"))
                GLib.timeout_add_seconds(3, self._restore_connection_status)

            client.execute(
                result, on_done, on_error,
                action=next_action_for(result), dataform=dataform)

        def on_commands(commands):
            command = next((cmd for cmd in commands
                            if getattr(cmd, 'node', '') == 'approval-bypass'), None)
            if command is None:
                revert_toggle()
                self._on_llm_error(self.backend, _("Agent does not expose approval-bypass."))
                return
            client.execute(command, submit_bypass_form, on_error)

        client.request_commands(on_commands, on_error)

    def _confirm_agent_text_command(self, heading, body, command, destructive=False):
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=heading,
            body=body,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("send", _("Send"))
        if destructive:
            dialog.set_response_appearance("send", Adw.ResponseAppearance.DESTRUCTIVE)
        else:
            dialog.set_response_appearance("send", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")

        def on_response(_dialog, response):
            if response == "send" and self.backend is not None:
                self.display_message(command, sender="user")
                self.backend.send_message(command)

        dialog.connect("response", on_response)
        dialog.present()

    def _load_agent_commands(self, box, loading):
        from .xmpp_commands import XmppCommandClient

        client = XmppCommandClient(self.backend.session, self.backend.bare_jid)
        self._agent_command_client = client

        def on_success(commands):
            box.remove(loading)
            for command in commands:
                button = Gtk.Button(label=command.name or command.node)
                button.connect("clicked", self._on_agent_command_clicked, client, command)
                box.append(button)
            if not commands:
                empty = Gtk.Label(label=_("No agent commands"))
                empty.add_css_class("dim-label")
                box.append(empty)

        def on_error(message):
            loading.set_label(message)
            loading.add_css_class("error")

        client.request_commands(on_success, on_error)

    def _on_agent_command_clicked(self, _button, client, command):
        self._execute_agent_command(client, command)

    def _execute_agent_command(self, client, command):
        """Ejecuta un comando ad-hoc (XEP-0050) y maneja la respuesta:
        si el agente devuelve un formulario (XEP-0004), lo muestra; si el
        comando ya terminó (o no lleva datos), muestra el resultado.

        Punto único usado tanto por el menú de comandos del agente como por
        los comandos inline anunciados en un mensaje — ambos pasan por el
        flujo con formularios, no por el viejo send_command (que los
        ignoraba)."""
        from .xmpp_commands import (
            XmppCommandFormDialog,
            is_completed,
            next_action_for,
        )

        def on_error(message):
            self._on_llm_error(self.backend, message)

        def handle_result(result):
            if is_completed(result):
                self._display_command_result(result)
                return
            if result.data is None:
                self._display_command_result(result)
                return

            def on_submit(dataform):
                client.execute(
                    result, handle_result, on_error,
                    action=next_action_for(result), dataform=dataform)

            XmppCommandFormDialog(self, result, on_submit).present()

        client.execute(command, handle_result, on_error)

    def _display_command_result(self, command):
        from .xmpp_commands import command_result_body
        title = command.name or _("Agent Command")
        body = command_result_body(command)
        message = Message(f"**{title}**\n\n{body}", "assistant")
        widget = MessageWidget(message)
        widget.add_css_class("command-result-message")
        self.messages_box.append(widget)
        GLib.idle_add(self._scroll_to_bottom, False)

    def _on_backend_ready(self, backend, display_name):
        """Maneja la señal 'ready' del backend (modelo cargado / sesión lista)."""
        debug_print(f"Backend listo: {display_name}")

        if self._injected_backend:
            self._update_xmpp_title_status()
            self._load_xmpp_history()
            return

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

    def _load_xmpp_history(self):
        if not hasattr(self, '_xmpp_history_loaded') or not self._xmpp_history_loaded:
            self._xmpp_history_loaded = True
            backend = self.backend
            if backend is None:
                return
            for child in list(self.messages_box):
                self.messages_box.remove(child)
            self._history_displayed = False
            self._xmpp_backfill_remaining = 2
            self._xmpp_history_batch = []
            self._xmpp_history_actions_batch = []
            hid1 = backend.connect('history-message', self._on_xmpp_history_message)
            hid2 = backend.connect('history-complete', self._on_xmpp_history_complete)
            hid3 = backend.connect('history-actions', self._on_xmpp_history_actions)
            self._backend_handler_ids.append(hid1)
            self._backend_handler_ids.append(hid2)
            self._backend_handler_ids.append(hid3)
            def load_initial_history():
                backend.load_history_from_cache()
                if not backend.load_history_from_mam():
                    self._xmpp_backfill_remaining -= 1
                return GLib.SOURCE_REMOVE

            GLib.idle_add(load_initial_history)

    def _on_xmpp_history_message(self, backend, body, direction, timestamp):
        self._xmpp_history_batch.append((body, direction, timestamp))

    def _on_xmpp_history_actions(self, backend, body, timestamp,
                                 quick_responses, commands):
        self._xmpp_history_actions_batch.append(
            (body, timestamp, quick_responses, commands))

    def _on_xmpp_history_complete(self, backend, has_more):
        batch = self._xmpp_history_batch
        action_batch = self._xmpp_history_actions_batch
        is_backfill = self._xmpp_backfill_remaining > 0
        if batch:
            if is_backfill:
                for body, direction, timestamp in batch:
                    self._display_history_bubble(body, direction, timestamp)
            else:
                for body, direction, timestamp in reversed(batch):
                    self._prepend_history_bubble(body, direction, timestamp)
            self._history_displayed = True
        for body, timestamp, quick_responses, commands in action_batch:
            self._restore_history_actions(body, timestamp, quick_responses, commands)
        if is_backfill:
            self._xmpp_backfill_remaining -= 1
        self._xmpp_history_batch = []
        self._xmpp_history_actions_batch = []
        if is_backfill:
            self._scroll_to_bottom_after_history_load()

    def _restore_history_actions(self, body, timestamp, quick_responses, _commands):
        if quick_responses and not self._history_quick_response_was_answered(
                timestamp, quick_responses):
            self._add_sticky_response_card(
                quick_responses,
                lambda response: self._send_restored_quick_response(response),
                detail_text=Message.compact_blank_lines(body))

    def _history_quick_response_was_answered(self, timestamp, quick_responses):
        request_dt = self._parse_history_ts(timestamp)
        if request_dt is None:
            return False
        values = {
            response.get('value', '')
            for response in quick_responses
            if response.get('value')
        }
        if not values:
            return False
        if hasattr(self.backend, 'quick_response_was_answered'):
            return self.backend.quick_response_was_answered(timestamp, values)
        for body, direction, msg_timestamp in self._xmpp_history_batch:
            if direction != 'out' or body not in values:
                continue
            msg_dt = self._parse_history_ts(msg_timestamp)
            if msg_dt is not None and msg_dt > request_dt:
                return True
        return False

    def _send_restored_quick_response(self, response):
        value = response.get('value', '')
        label = response.get('label') or value
        if value and hasattr(self.backend, 'send_quick_response'):
            self.backend.send_quick_response(value, label)

    def _display_history_bubble(self, body, direction, timestamp):
        sender = "user" if direction == 'out' else "assistant"
        msg = Message(body, sender, timestamp=self._parse_history_ts(timestamp))
        widget = MessageWidget(msg)
        self.messages_box.append(widget)

    def _prepend_history_bubble(self, body, direction, timestamp):
        sender = "user" if direction == 'out' else "assistant"
        msg = Message(body, sender, timestamp=self._parse_history_ts(timestamp))
        widget = MessageWidget(msg)
        self.messages_box.prepend(widget)

    @staticmethod
    def _parse_history_ts(timestamp):
        """Convierte el timestamp del historial (ISO-8601, o epoch en cachés
        viejas) a datetime local para la burbuja. None si no se puede: así
        Message cae en datetime.now() como último recurso.

        Se muestra en hora local (astimezone) porque los timestamps se
        guardan en UTC pero MessageWidget hace strftime('%H:%M')."""
        if timestamp is None:
            return None
        from datetime import datetime
        try:
            if isinstance(timestamp, (int, float)):
                return datetime.fromtimestamp(timestamp)
            text = str(timestamp)
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                # Cachés viejas guardaron epoch como texto ("1752341421.7").
                return datetime.fromtimestamp(float(text))
        except (ValueError, TypeError, OSError):
            return None
        # ISO aware (UTC) -> hora local; naive se asume ya local.
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt

    def _on_edge_reached(self, scroll, pos):
        if pos == Gtk.PositionType.TOP and self.backend is not None:
            self.backend.load_more_history()

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
            self._scroll_to_bottom_after_history_load()
            
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

        # Red de seguridad: registrar la ventana por CID si _on_llm_response
        # no llegó a hacerlo (p.ej. sin chunks pero success=True). El caso
        # normal ya lo registra _on_llm_response con el primer chunk.
        if success and not self.cid:
            conversation_id = self.backend.get_conversation_id()
            if conversation_id:
                self.config['cid'] = conversation_id
                self.cid = conversation_id
                debug_print(f"Conversation ID updated in config: {conversation_id}")
                app = self.get_application()
                if hasattr(app, '_window_by_cid'):
                    for key, win in list(app._window_by_cid.items()):
                        if win is self and key != conversation_id:
                            del app._window_by_cid[key]
                    app._window_by_cid[conversation_id] = self

        # Refrescar el sidebar de conversaciones: para el caso normal (CID
        # nuevo) es aquí, no en _on_llm_response, donde la fila ya existe
        # en la tabla conversations — LLMClient._process_stream la crea en
        # su 'finally', que corre justo antes de emitir esta señal.
        if success and self.model_sidebar is not None:
            self.model_sidebar.refresh()

    def _on_llm_response(self, llm_client, response):
        """Maneja la señal de respuesta del backend.

        LLM: rellena la burbuja de assistant creada al enviar (streaming).
        Backends de mensajería (XMPP): cada 'response' es un mensaje
        entrante completo e independiente; crea su propia burbuja.
        """
        if self._injected_backend:
            self.accumulated_response = ""
            if self._is_context_unavailable_response(response):
                self.current_message_widget = None
                self._display_context_unavailable(response)
            else:
                self.current_message_widget = self.display_message(
                    response, sender="assistant")
            GLib.idle_add(self._scroll_to_bottom, False)
            return

        if not self.current_message_widget:
            return

        # Actualizar el conversation_id en la configuración al recibir la primera
        # respuesta. NO refrescar el sidebar aquí: la fila en la tabla
        # conversations recién se crea en el 'finally' de
        # LLMClient._process_stream, que corre después de terminado el
        # streaming (señal 'finished'); refrescar antes no mostraría nada
        # nuevo. El refresh vive en _on_llm_finished.
        if not self.cid:
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

    @staticmethod
    def _is_context_unavailable_response(response):
        text = str(response or "").lower()
        return (
            "ctx unavailable" in text or
            "context unavailable" in text
        )

    def _display_context_unavailable(self, response):
        message = _("Claude context is unavailable.")
        details = self._context_limit_details(response)
        if details:
            message = f"{message}\n{details}"
        else:
            message = (
                f"{message}\n"
                f"{_('Session limit: not reported by the agent.')}"
            )
        message = (
            f"{message}\n"
            f"{_('Try compacting or clearing the agent context, or start a new session.')}"
        )
        self.messages_box.append(ErrorWidget(message))

    @staticmethod
    def _context_limit_details(response):
        detail_lines = []
        for line in str(response or "").splitlines():
            clean = line.strip()
            if not clean:
                continue
            clean_lower = clean.lower()
            if "ctx unavailable" in clean_lower or "context unavailable" in clean_lower:
                continue
            if re.search(r"\b(limit|remaining|reset|usage|token|session|quota)\b",
                         clean_lower):
                detail_lines.append(clean)
            if len(detail_lines) >= 6:
                break
        return "\n".join(detail_lines)

    def _on_llm_response_correction(self, backend, body):
        """XEP-0308 correction: reemplaza el contenido de la burbuja actual
        en lugar de crear una nueva. Mantiene intactos los botones de
        quick-response y commands ya anexados."""
        if self.current_message_widget is None:
            return
        GLib.idle_add(self.current_message_widget.update_content, body)
        GLib.idle_add(self._scroll_to_bottom, False)

    def _add_sticky_response_card(self, responses, on_selected, detail_text=None):
        if not responses:
            return

        item = {
            'id': self._sticky_response_next_id,
            'responses': list(responses),
            'on_selected': on_selected,
            'detail_text': detail_text or "",
        }
        self._sticky_response_next_id += 1
        self._sticky_response_items.insert(0, item)
        self._rebuild_sticky_response_box()

    def _rebuild_sticky_response_box(self):
        for child in list(self.sticky_response_box):
            self.sticky_response_box.remove(child)
        if not self._sticky_response_items:
            self.sticky_response_box.set_visible(False)
            return

        item = self._sticky_response_items[0]
        responses = item['responses']
        detail_text = item.get('detail_text') or ""
        count = len(self._sticky_response_items)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        card.add_css_class("sticky-response-card")
        card.set_margin_start(0)
        card.set_margin_end(0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_halign(Gtk.Align.FILL)
        title_text = _("Response needed")
        if count > 1:
            title_text = _("Response needed") + f" ({count})"
        title = Gtk.Label(label=title_text)
        title.add_css_class("caption-heading")
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)
        if count > 1:
            counter = Gtk.MenuButton()
            counter.add_css_class("flat")
            counter.set_tooltip_text(_("Show pending responses"))
            counter_child = Gtk.Label(label=str(count))
            counter_child.add_css_class("sticky-response-count")
            counter.set_child(counter_child)
            popover = Gtk.Popover()
            popover.set_child(self._build_sticky_response_popover())
            counter.set_popover(popover)
            header.append(counter)
        if detail_text:
            info_button = Gtk.MenuButton()
            info_button.add_css_class("flat")
            info_button.set_tooltip_text(_("Show question context"))
            info_button.set_child(
                resource_manager.create_icon_widget("dialog-information-symbolic"))
            popover = Gtk.Popover()
            detail = Gtk.Label(label=detail_text)
            detail.set_wrap(True)
            detail.set_xalign(0)
            detail.set_selectable(True)
            detail.set_max_width_chars(72)
            detail.set_margin_top(10)
            detail.set_margin_bottom(10)
            detail.set_margin_start(10)
            detail.set_margin_end(10)
            popover.set_child(detail)
            info_button.set_popover(popover)
            header.append(info_button)
        card.append(header)
        if detail_text:
            preview = Gtk.Label(label=self._sticky_detail_preview(detail_text))
            preview.add_css_class("sticky-response-detail")
            preview.set_xalign(0)
            preview.set_wrap(True)
            preview.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            preview.set_lines(2)
            preview.set_ellipsize(Pango.EllipsizeMode.END)
            card.append(preview)

        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(99)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_halign(Gtk.Align.FILL)
        flow.set_valign(Gtk.Align.START)
        flow.add_css_class("quick-responses")

        buttons = []

        def handle_click(_button, response):
            for btn in buttons:
                btn.set_sensitive(False)
            self._remove_sticky_response_item(item['id'])
            item['on_selected'](response)

        for response in responses:
            label = response.get('label') or response.get('name') or response.get('value', '')
            if not label:
                continue
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
            button.connect("clicked", handle_click, response)
            flow.append(button)
            buttons.append(button)

        if not buttons:
            return
        card.append(flow)
        self.sticky_response_box.append(card)
        self.sticky_response_box.set_visible(True)

    def _build_sticky_response_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        for index, item in enumerate(self._sticky_response_items, start=1):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            row.add_css_class("sticky-response-popover-row")
            title = Gtk.Label(label=_("Pending response") + f" {index}")
            title.add_css_class("caption-heading")
            title.set_xalign(0)
            row.append(title)
            detail_text = item.get('detail_text') or ""
            if detail_text:
                preview = Gtk.Label(label=self._sticky_detail_preview(detail_text, max_chars=220))
                preview.set_xalign(0)
                preview.set_wrap(True)
                preview.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                preview.add_css_class("sticky-response-detail")
                row.append(preview)
            flow = Gtk.FlowBox()
            flow.set_max_children_per_line(99)
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_halign(Gtk.Align.FILL)
            flow.add_css_class("quick-responses")
            buttons = []

            def handle_click(_button, response, current_item=item, current_buttons=buttons):
                for btn in current_buttons:
                    btn.set_sensitive(False)
                self._remove_sticky_response_item(current_item['id'])
                current_item['on_selected'](response)

            for response in item['responses']:
                label = response.get('label') or response.get('name') or response.get('value', '')
                if not label:
                    continue
                button = Gtk.Button(label=label)
                button.add_css_class("pill")
                button.connect("clicked", handle_click, response)
                flow.append(button)
                buttons.append(button)
            if buttons:
                row.append(flow)
            box.append(row)
        return box

    @staticmethod
    def _sticky_detail_preview(detail_text, max_chars=160):
        text = Message.compact_blank_lines(detail_text).replace("\n", " ")
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}..."

    def _remove_sticky_response_item(self, item_id):
        self._sticky_response_items = [
            item for item in self._sticky_response_items
            if item.get('id') != item_id
        ]
        self._rebuild_sticky_response_box()

    def _clear_sticky_response_cards(self):
        for child in list(self.sticky_response_box):
            self.sticky_response_box.remove(child)
        self._sticky_response_cards = []
        self._sticky_response_items = []
        if hasattr(self, 'sticky_response_box'):
            self.sticky_response_box.set_visible(False)

    def _current_agent_message_text(self):
        message = getattr(self.current_message_widget, 'message', None)
        if message is None:
            return ""
        return Message.compact_blank_lines(message.content)

    def _on_quick_responses(self, backend, responses):
        if self.current_message_widget is None:
            return

        # Multi-pregunta: NO ocultar los botones de preguntas anteriores al
        # llegar una nueva. NanoClaw admite varias preguntas abiertas a la
        # vez y su backend retira los botones de cada pregunta cuando se
        # responde; el cliente ya no fuerza "solo la más reciente"
        # (divergencia deliberada de XEP-0439 §6).
        def on_selected(response):
            value = response.get('value', '')
            label = response.get('label') or value
            if not value:
                return
            if hasattr(backend, 'send_quick_response'):
                backend.send_quick_response(value, label)

        self._add_sticky_response_card(
            responses, on_selected,
            detail_text=self._current_agent_message_text())

    def _on_commands(self, backend, commands):
        if self.current_message_widget is None:
            return

        def on_selected(command):
            name = command.get('name', '')
            node = command.get('node', '')
            jid = command.get('jid', '')
            if not name or not node or not jid:
                return
            # Los comandos inline también pasan por el flujo ad-hoc completo
            # (con formularios XEP-0004), no por el viejo send_command. Se
            # arma un AdHocCommand mínimo a partir del anuncio inline.
            session = getattr(backend, 'session', None)
            bare_jid = getattr(backend, 'bare_jid', None)
            if session is None or bare_jid is None:
                return
            from .xmpp_commands import XmppCommandClient
            from nbxmpp.structs import AdHocCommand
            from nbxmpp.protocol import JID
            client = XmppCommandClient(session, bare_jid)
            # Mantener viva la referencia: XmppCommandClient guarda callbacks
            # pendientes y no debe recolectarse antes de que llegue la
            # respuesta (mismo cuidado que _agent_command_client).
            self._agent_command_client = client
            adhoc = AdHocCommand(jid=JID.from_string(jid), node=node, name=name)
            self._execute_agent_command(client, adhoc)

        self._add_sticky_response_card(
            commands, on_selected,
            detail_text=self._current_agent_message_text())

    def _on_vadj_value_changed(self, adj):
        """El usuario (o el código) movió el scroll: recordar la distancia
        actual al fondo, para poder reanclarla al redimensionar. Se ignora
        mientras nosotros mismos restauramos el valor (evita realimentación)."""
        if self._restoring_scroll:
            return
        upper = adj.get_upper()
        page_size = adj.get_page_size()
        self._scroll_bottom_distance = max(0.0, upper - (adj.get_value() + page_size))

    def _on_vadj_changed(self, adj):
        """Cambió el rango del adjustment. Si fue por un cambio de alto del
        viewport (page_size), es un redimensionado: reanclar el último
        mensaje visible restaurando la distancia al fondo guardada. Un cambio
        que solo afecta 'upper' (mensaje nuevo, carga de historial) no se
        toca aquí — de eso se encarga _scroll_to_bottom."""
        page_size = adj.get_page_size()
        if page_size == self._scroll_last_page_size:
            return
        self._scroll_last_page_size = page_size
        upper = adj.get_upper()
        target = max(0.0, upper - page_size - self._scroll_bottom_distance)
        if abs(target - adj.get_value()) < 1.0:
            return
        self._restoring_scroll = True
        adj.set_value(target)
        self._restoring_scroll = False

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

    def _scroll_to_bottom_after_history_load(self):
        def scroll_once():
            self._scroll_to_bottom(True)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(scroll_once)
        for delay in (50, 150, 300):
            GLib.timeout_add(delay, scroll_once)

    def _on_close_request(self, window):
        # Soltar backend/sidebar/timeout pendiente (spec 003, T7: mismo
        # helper que usa _bind_backend para transformar la ventana in-place).
        self._unbind_backend()
        # Eliminar del registro de ventanas (por valor: cubre tanto las
        # claves por CID de LLM como las claves "xmpp:…" de spec 002).
        app = self.get_application()
        if hasattr(app, '_window_by_cid'):
            for key, win in list(app._window_by_cid.items()):
                if win is self:
                    debug_print(f"Eliminando ventana del registro: {key}")
                    del app._window_by_cid[key]
        # Lógica de cierre global: si es la última ventana, salir — salvo
        # que haya una sesión XMPP conectada (spec 003, criterio 4: cerrar
        # una ventana de chat no debe desloguearte de XMPP, igual que en
        # cualquier cliente XMPP normal). La app queda viva en segundo
        # plano y se puede resurgir vía el ícono de la app / D-Bus.
        if len(app.get_windows()) <= 1:
            xmpp_session = getattr(app, '_xmpp_session', None)
            if xmpp_session is not None and xmpp_session.is_connected:
                debug_print(
                    "Última ventana cerrada, pero hay sesión XMPP activa: "
                    "la app sigue corriendo en segundo plano")
            else:
                debug_print("Última ventana cerrada, sin sesión XMPP: saliendo de la aplicación")
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
        self._scroll_to_bottom_after_history_load()

    def _on_focus_enter(self, controller):
        """Set focus to the input text when the window gains focus."""
        # Solo poner el foco si el sidebar no está visible
        if not self.split_view.get_show_sidebar():
            self.input_text.grab_focus()

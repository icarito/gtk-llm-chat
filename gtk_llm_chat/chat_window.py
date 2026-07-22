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
from .xmpp_client import XmppSession
from .voice_recorder import VoiceRecorder, VoiceRecorderError
from .audio_utils import audio_mime_for_file
import traceback

DEBUG = os.environ.get('DEBUG') or False


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


class VoiceRecordState:
    IDLE = 0
    HOLDING = 1
    LOCKED = 2
    CANCELLING = 3
    CAPTURED = 4
    UPLOADING = 5
    FAILED = 6


class LLMChatWindow(Adw.ApplicationWindow):
    """
    A chat window
    """

    # Alto del campo de entrada, en px: arranca en ~3 líneas y deja de crecer
    # a ~6, a partir de donde hace scroll interno.
    _INPUT_MIN_HEIGHT = 60
    _INPUT_MAX_HEIGHT = 120

    # Panel de actividad de herramientas. Antes era un tope fijo de 144px
    # (~6 líneas monoespaciadas): la salida de casi cualquier exec real
    # —git status, un traceback, un ls largo— se cortaba y obligaba a hacer
    # scroll dentro de una ventanita. Ahora es proporcional a la ventana, con
    # un suelo utilizable y un techo que no se coma la conversación.
    _TOOL_OUTPUT_MIN_HEIGHT = 260
    _TOOL_OUTPUT_MAX_HEIGHT = 560
    _TOOL_OUTPUT_HEIGHT_FRACTION = 0.42

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
        # Burbujas ya pintadas (ver _history_bubble_key): el catch-up de MAM
        # solapa hacia atrás y reenvía mensajes que ya están en pantalla.
        self._history_keys = set()
        # Contacto para el que está construido el sidebar de ajustes (ver
        # _update_settings_panel): sin esto se reconstruía en cada latido.
        self._settings_panel_for = None
        # El usuario está cargando historial VIEJO (subió al borde de arriba):
        # ese lote no debe hacer saltar la vista al fondo.
        self._loading_older_history = False
        self._post_layout_scroll_pending = False
        self._post_layout_scroll_force = False
        self._post_layout_scroll_settle_id = None
        self._post_layout_scroll_watch_id = None
        self._scroll_animation_tick_id = None
        self._scroll_animation_adj = None
        self._scroll_animation_start_value = 0.0
        self._scroll_animation_target = 0.0
        self._scroll_animation_started_at = 0.0
        self._scroll_animation_duration = 0.0
        self._suppress_text_changed = False
        self._pending_messaging_send_text = None
        self._pending_messaging_send_tick_id = None
        self._pending_messaging_send_timeout_id = None
        self._pending_messaging_send_ticks_left = 0

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
        # aquí y poblado por _bind_backend() más abajo en este __init__. El
        # backend siempre llega construido desde la aplicación (spec 009): la
        # ventana no sabe fabricar ninguno, sólo hablar con el contrato.
        self.backend = None
        self._backend_handler_ids = []
        self._session_handler_ids = []
        self._xmpp_session = None
        self._composing_timeout_id = None
        self._streaming_finalize_timeout_ids = {}
        self._delivery_widgets = {}
        self._pending_delivery_widgets = {}
        self._typing_row = None
        self._last_live_sender = None
        self._message_widgets_by_id = {}
        # Approval bodies wait briefly for their command metadata and become
        # one sticky panel instead of an assistant bubble plus a panel.
        self._pending_action_bodies = {}
        self._tool_output_request_ids = set()
        self._tool_history_request_ids = set()
        self._telemetry_tool_widget = None
        self._telemetry_tool_name = None
        self._restored_active_tool_panel = False
        self._approval_toast_request_ids = set()
        self._last_toast_signature = None
        self._sticky_response_cards = []
        self._sticky_response_items = []
        self._sticky_response_next_id = 0
        self._voice_state = VoiceRecordState.IDLE
        self._voice_recorder: VoiceRecorder | None = None
        self._voice_file_path: str | None = None
        self._voice_duration: float = 0.0
        self._voice_timer_id: int | None = None
        self._voice_blink_id: int | None = None
        self._voice_bubble: object | None = None
        self._voice_retry_path: str | None = None
        self._rendered_response_request_ids = set()
        self._is_agent_contact = False
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
        # El panel de herramientas (tool_output_scroll, creado más abajo) se
        # calcula contra el alto real de la ventana en _sync_tool_output_height.
        # notify::default-height cubre el resize del usuario; "map" cubre el
        # primer alto que asigna el WM, que puede diferir del default si la
        # sesión anterior quedó maximizada o en tiling.
        self.connect("map", lambda *_: self._sync_tool_output_height())

        # Mantener referencia al último mensaje enviado
        self.last_message = None

        # Crear header bar
        self.header = Adw.HeaderBar()
        self.header.set_centering_policy(Adw.CenteringPolicy.LOOSE)
        self.title_widget = Adw.WindowTitle.new(title, "")
        self.title_presence_dot = Gtk.Image.new_from_icon_name("media-record-symbolic")
        self._title_presence_css = set()
        self._set_title_presence_state(XmppSession.PRESENCE_OFFLINE)
        self.title_presence_dot.set_valign(Gtk.Align.CENTER)
        self.title_presence_dot.set_visible(False)

        self.header_title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.header_title_box.set_hexpand(True)
        self.header_title_box.set_halign(Gtk.Align.START)
        self.header_title_box.set_valign(Gtk.Align.CENTER)
        # El punto de presencia queda centrado en vertical (15 px arriba y
        # abajo), pero el pack_start del header sólo deja 7 px por la izquierda:
        # se le añaden los que faltan para que respire igual por los dos lados.
        self.header_title_box.set_margin_start(8)
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
        self.xmpp_toolbar.set_visible(xmpp_session is not None or backend is not None)

        self.xmpp_status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.xmpp_status_bar.add_css_class("toolbar")
        self.xmpp_status_bar.add_css_class("flat")
        self.xmpp_status_bar.set_margin_start(12)
        self.xmpp_status_bar.set_margin_end(12)
        self.xmpp_status_bar.set_margin_top(0)
        self.xmpp_status_bar.set_margin_bottom(0)
        self.xmpp_status_bar.set_visible(xmpp_session is not None or backend is not None)
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

        # La telemetría del agente (actividad, contexto, modelo) y el bypass de
        # aprobaciones vivían aquí, en una barra propia bajo el header. Ahora la
        # telemetría está en el área de entrada (junto al texto que el usuario
        # mira) y el bypass es un comando del menú de agente, así que esta barra
        # se quedó sólo con el estado de conexión.
        self.xmpp_toolbar.append(self.xmpp_status_bar)

        # Tool activity lives outside the message list. Its bounded viewport
        # updates independently, avoiding a full bubble/list reflow for every
        # progress edit or long tool status line.
        self.tool_output_label = Gtk.Label()
        self.tool_output_label.set_xalign(0)
        self.tool_output_label.set_yalign(0)
        self.tool_output_label.set_wrap(True)
        self.tool_output_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.tool_output_label.set_selectable(True)
        self.tool_output_label.add_css_class('monospace')
        self.tool_output_scroll = Gtk.ScrolledWindow()
        self.tool_output_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # Altura adaptativa: 144px fijos dejaban ~6 líneas monoespaciadas, muy
        # poco para la salida de un exec (un `git status` o un traceback ya se
        # cortaban). Se recalcula contra la altura real de la ventana en
        # _sync_tool_output_height; este valor es sólo el arranque, antes de
        # que la ventana tenga tamaño asignado.
        self.tool_output_scroll.set_max_content_height(
            self._TOOL_OUTPUT_MIN_HEIGHT)
        self.tool_output_scroll.set_propagate_natural_height(True)
        self.tool_output_scroll.set_child(self.tool_output_label)
        self.tool_output_panel = Adw.Bin()
        self.tool_output_panel.add_css_class('card')
        self.tool_output_panel.add_css_class('tool-output-panel')
        self.tool_output_panel.set_margin_start(6)
        self.tool_output_panel.set_margin_end(6)
        self.tool_output_panel.set_margin_bottom(6)
        self.tool_output_panel.set_child(self.tool_output_scroll)
        self.tool_output_panel.set_visible(False)

        # --- Botones de la Header Bar ---
        # (El viejo toggle "brain" del sidebar de modelo ya no existe: ese panel
        # vive ahora en el sidebar derecho, tras settings_button.)

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

        # Ajustes del backend (sidebar derecho): los comandos del agente, o los
        # parámetros del modelo. Sustituye al viejo popover de comandos, que no
        # daba espacio para descripciones ni formularios.
        self.settings_button = Gtk.ToggleButton()
        resource_manager.set_widget_icon_name(
            self.settings_button, "applications-system-symbolic")
        self.settings_button.set_tooltip_text(_("Settings"))
        self.settings_button.set_visible(False)
        # El binding con settings_split se hace más abajo: el split todavía no
        # existe en este punto.

        self.header.pack_end(self.primary_menu_button)
        self.header.pack_end(self.settings_button)
        self.header.pack_end(rename_button)
        self.header.pack_end(self.roster_button)

        # --- Fin Botones Header Bar ---

        # --- Contenedores (dos OverlaySplitView anidados) ---
        # Antes había uno solo que se movía de lado según el backend, así que
        # roster y ajustes no podían verse a la vez y competían por el mismo
        # hueco. Ahora son dos: roster a la izquierda, ajustes del backend a la
        # derecha, independientes.
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_vexpand(True)
        self.split_view.set_collapsed(True) # Empezar colapsado
        self.split_view.set_show_sidebar(False)
        self.split_view.set_min_sidebar_width(280)
        self.split_view.set_max_sidebar_width(400)
        self.split_view.set_sidebar_position(Gtk.PackType.END)

        # Sidebar derecho: lo que el backend tenga que ofrecer — parámetros del
        # modelo (LLM) o los comandos del agente (XMPP). Ver _update_settings_panel.
        self.settings_split = Adw.OverlaySplitView()
        self.settings_split.set_vexpand(True)
        self.settings_split.set_collapsed(True)
        self.settings_split.set_show_sidebar(False)
        self.settings_split.set_min_sidebar_width(300)
        self.settings_split.set_max_sidebar_width(420)
        self.settings_split.set_sidebar_position(Gtk.PackType.END)
        self.settings_split.bind_property(
            "show-sidebar", self.settings_button, "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        # El binding 'show-sidebar' <-> botón toggle se crea en _bind_backend
        # (spec 003, T7), ya que depende de qué botón corresponde al tipo de
        # backend actual y puede cambiar si la ventana se re-bindea.
        # Conectar al cambio de 'show-sidebar' para cambiar el icono y foco
        self.split_view.connect("notify::show-sidebar", self._on_sidebar_visibility_changed)
        # El panel de herramientas se redimensiona con la ventana: sin esto el
        # tope quedaba fijado al arranque, cuando la ventana todavía no tiene
        # su tamaño real (maximizada, restaurada de sesión, o en tiling).
        self.connect("notify::default-height", self._on_window_height_changed)
        self.connect("notify::maximized", self._on_window_height_changed)

        # --- Contenido principal (el chat) ---
        chat_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        style_manager.apply_to_widget(chat_content_box, "chat-container")
        
        # ScrolledWindow para el historial de mensajes
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # El scroll cinético/overlay introduce interpolaciones de `value` que
        # pueden desanclar temporalmente el follow-bottom y retrasar la
        # percepción de "mensaje enviado" hasta la próxima interacción.
        if hasattr(scroll, 'set_kinetic_scrolling'):
            scroll.set_kinetic_scrolling(False)
        if hasattr(scroll, 'set_overlay_scrolling'):
            scroll.set_overlay_scrolling(False)
        scroll.connect("edge-reached", self._on_edge_reached)
        self.message_scroll = scroll
        # Al redimensionar la ventana, mantener anclado el último mensaje
        # visible: se guarda la distancia al fondo mientras el usuario hace
        # scroll y se restaura cuando cambia el alto del viewport (page_size).
        self._scroll_bottom_distance = 0.0
        self._scroll_last_page_size = 0.0
        self._restoring_scroll = False
        # Último `upper` visto. Sirve para distinguir "el usuario movió el
        # scroll" de "el contenido creció bajo sus pies" — ver
        # _on_vadj_value_changed: confundirlos dejaba el scroll a media burbuja.
        self._scroll_last_upper = 0.0
        self._content_added_pending = False
        # Seguir el fondo mientras el usuario no se haya ido hacia arriba. Es
        # una *intención*, no una posición: se decide cuando el usuario mueve
        # el scroll y se aplica después de cada layout, ya con el `upper` real.
        # Calcularlo en el momento de añadir contenido no funciona — GTK aún no
        # ha reasignado la altura, así que `upper` está desactualizado y el
        # scroll se queda corto (visible como retraso durante el streaming).
        self._stick_to_bottom = True
        vadj = scroll.get_vadjustment()
        vadj.connect("value-changed", self._on_vadj_value_changed)
        vadj.connect("changed", self._on_vadj_changed)
        vadj.connect("notify::upper", self._on_vadj_range_notify)
        vadj.connect("notify::page-size", self._on_vadj_range_notify)
        self._scroll_last_value = vadj.get_value()
        user_scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL)
        user_scroll.connect("scroll", self._on_user_scroll_intent)
        scroll.add_controller(user_scroll)
        
        # Contenedor para mensajes
        self.messages_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.messages_box.set_margin_top(12)
        self.messages_box.set_margin_bottom(12)
        self.messages_box.set_margin_start(12)
        self.messages_box.set_margin_end(12)
        self.messages_box.set_can_focus(False)
        style_manager.apply_to_widget(self.messages_box, "messages-container")
        self._messages_box_last_height = 0
        scroll.set_child(self.messages_box)

        self.sticky_response_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sticky_response_box.set_margin_top(6)
        self.sticky_response_box.set_margin_start(6)
        self.sticky_response_box.set_margin_end(6)
        self.sticky_response_box.set_visible(False)

        # Área de entrada: una columna con la telemetría alrededor del texto —
        # uso de contexto arriba, y abajo el modelo activo junto a la acción
        # (enviar / cancelar). Toda la información de estado vive aquí, en el
        # sitio donde el usuario ya está mirando, en vez de en una barra aparte.
        self.input_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.input_box.add_css_class('toolbar')
        self.input_box.add_css_class('card')
        style_manager.apply_to_widget(self.input_box, "input-container")
        self.input_box.set_margin_top(6)
        self.input_box.set_margin_bottom(6)
        self.input_box.set_margin_start(6)
        self.input_box.set_margin_end(6)

        # Uso de contexto. Arranca oculto: sólo hay dato cuando el agente lo
        # publica en su presencia (ctx_used/ctx_max), y una barra vacía sin
        # significado es peor que ninguna barra.
        self.context_level = Gtk.LevelBar()
        self.context_level.set_min_value(0.0)
        self.context_level.set_max_value(1.0)
        self.context_level.set_mode(Gtk.LevelBarMode.CONTINUOUS)
        # Un offset da nombre (= clase CSS) al tramo que llega HASTA su valor, y
        # GTK aplica el primero cuyo valor supere al actual. De ahí que haga
        # falta uno que cubra hasta el tope: sin él, un contexto lleno se
        # quedaría sin clase y perdería el color de aviso. Los nombres son
        # propios porque los de GTK (low/high/full) nombran el tramo *inferior*,
        # justo al revés de lo que se lee.
        self.context_level.add_offset_value('ctx-ok', 0.75)
        self.context_level.add_offset_value('ctx-warn', 0.90)
        self.context_level.add_offset_value('ctx-danger', 1.0)
        self.context_level.add_css_class('context-level')
        self.context_level.set_visible(False)
        style_manager.apply_to_widget(self.context_level, "context-level")
        self.input_box.append(self.context_level)

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
        # Un EventControllerKey sobre el TextView intercepta también las dead
        # keys antes de que lleguen al IM context. Los shortcuts declarativos
        # sólo observan Enter y dejan acentos/composición enteramente a GTK.
        input_shortcuts = Gtk.ShortcutController()
        for enter_key in (
                Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            trigger = Gtk.KeyvalTrigger.new(
                enter_key, Gdk.ModifierType(0))
            action = Gtk.CallbackAction.new(self._send_from_input_shortcut)
            input_shortcuts.add_shortcut(Gtk.Shortcut.new(trigger, action))
        self.input_text.add_controller(input_shortcuts)

        # El TextView crece con el texto envuelto y no se recorta solo: el tope
        # lo pone el ScrolledWindow, que a partir de max_content_height empieza
        # a hacer scroll en vez de seguir empujando el resto de la ventana.
        self.input_scroll = Gtk.ScrolledWindow()
        self.input_scroll.set_policy(
            Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.input_scroll.set_min_content_height(self._INPUT_MIN_HEIGHT)
        self.input_scroll.set_max_content_height(self._INPUT_MAX_HEIGHT)
        self.input_scroll.set_propagate_natural_height(True)
        self.input_scroll.set_hexpand(True)
        self.input_scroll.set_child(self.input_text)

        self.recording_revealer = Gtk.Revealer()
        self.recording_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.recording_revealer.set_child(self._build_recording_panel())
        self.recording_revealer.set_reveal_child(False)

        self.input_overlay = Gtk.Overlay()
        self.input_overlay.set_child(self.input_scroll)
        self.input_overlay.add_overlay(self.recording_revealer)
        self.input_overlay.set_hexpand(True)

        self.input_box.append(self.input_overlay)

        # Fila inferior: modelo activo (izquierda) · actividad · acción (derecha)
        input_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Adjuntar archivo (XEP-0363). Sólo tiene sentido con un backend XMPP:
        # el backend LLM local no sube archivos a ningún sitio.
        self.attach_button = Gtk.Button()
        self.attach_button.add_css_class('flat')
        resource_manager.set_widget_icon_name(
            self.attach_button, "mail-attachment-symbolic")
        self.attach_button.set_tooltip_text(_("Attach a file"))
        self.attach_button.connect('clicked', self._on_attach_clicked)
        self.attach_button.set_visible(False)
        input_actions.append(self.attach_button)

        # Badge del modelo activo, y a la vez el acceso a sus ajustes: en LLM
        # abre el panel de parámetros que ya existe; con un agente, su comando
        # `model` (ver _on_model_badge_clicked). Es un Button y no un MenuButton
        # porque no despliega un menú fijo — enruta a dos sitios distintos.
        self.model_badge = Gtk.Button()
        self.model_badge.add_css_class('pill')
        self.model_badge.add_css_class('flat')
        self.model_badge.set_tooltip_text(_("Model settings"))
        self.model_badge.set_visible(False)
        self.model_badge.connect('clicked', self._on_model_badge_clicked)
        style_manager.apply_to_widget(self.model_badge, "model-badge")
        input_actions.append(self.model_badge)

        # Qué está haciendo el agente ahora mismo (Trabajando, Usando
        # herramienta: X…). Vacío cuando no hay nada que contar.
        self.activity_label = Gtk.Label()
        self.activity_label.add_css_class('caption')
        self.activity_label.add_css_class('dim-label')
        self.activity_label.set_xalign(0)
        self.activity_label.set_hexpand(True)
        self.activity_label.set_ellipsize(Pango.EllipsizeMode.END)
        input_actions.append(self.activity_label)

        # Botón enviar
        self.send_button = Gtk.Button(label=_("Send"))
        self.send_button.connect('clicked', self._on_send_clicked)
        self.send_button.add_css_class('suggested-action')
        style_manager.apply_to_widget(self.send_button, "primary-button")

        # Mientras genera, Enviar cede su sitio a un spinner + Cancelar: el
        # mismo hueco, así que la fila no salta de ancho al cambiar de estado.
        self.busy_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.busy_spinner = Gtk.Spinner()
        self.stop_button = Gtk.Button(label=_("Stop"))
        self.stop_button.add_css_class('destructive-action')
        self.stop_button.connect('clicked', self._on_stop_clicked)
        self.busy_box.append(self.busy_spinner)
        self.busy_box.append(self.stop_button)

        self.action_stack = Gtk.Stack()
        self.action_stack.set_transition_type(
            Gtk.StackTransitionType.CROSSFADE)
        self.action_stack.add_named(self.send_button, 'send')
        self.action_stack.add_named(self.busy_box, 'busy')
        self.action_stack.set_visible_child_name('send')
        input_actions.append(self.action_stack)

        self.mic_button = Gtk.Button()
        self.mic_button.add_css_class('flat')
        resource_manager.set_widget_icon_name(
            self.mic_button, 'audio-input-microphone-symbolic',
            fallback='microphone-symbolic')
        self.mic_button.set_tooltip_text(_('Hold to record voice message'))
        self.mic_button.set_visible(False)

        long_press = Gtk.GestureLongPress.new()
        long_press.connect('pressed', self._on_mic_pressed)
        long_press.connect('cancelled', self._on_mic_cancelled)
        self.mic_button.add_controller(long_press)

        drag = Gtk.GestureDrag.new()
        drag.connect('drag-begin', self._on_mic_drag_begin)
        drag.connect('drag-update', self._on_mic_drag_update)
        drag.connect('drag-end', self._on_mic_drag_end)
        self.mic_button.add_controller(drag)

        input_actions.append(self.mic_button)

        self.input_box.append(input_actions)

        # El toast vive sólo sobre la lista de mensajes. Las acciones
        # pendientes quedan arriba y fuera del overlay, de modo que una
        # notificación nunca tape el approval sticky.
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(scroll)

        # Ensamblar la interfaz de chat
        chat_content_box.append(self.sticky_response_box)
        chat_content_box.append(self.toast_overlay)
        chat_content_box.append(self.input_box)

        # El chat vive dentro del split de ajustes, y ése dentro del del roster:
        # roster | chat | ajustes, cada panel con su propio toggle.
        self.settings_split.set_content(chat_content_box)
        self.split_view.set_content(self.settings_split)

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
        root_box.append(self.tool_output_panel)
        root_box.append(self.split_view) # Añadir el split_view aquí

        # Establecer el contenido de la ventana
        self.set_content(root_box)

        # Agregar CSS provider
        self._setup_css()

        # Agregar soporte para cancelación
        self.current_message_widget = None
        self.accumulated_response = ""
        self._delivery_widgets = {}
        self._pending_delivery_widgets = {}
        self._message_widgets_by_id = {}
        self._typing_row = None
        self._last_live_sender = None

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
        for timeout_id in self._streaming_finalize_timeout_ids.values():
            GLib.source_remove(timeout_id)
        self._streaming_finalize_timeout_ids = {}
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
            # XmppConversation is owned and canonicalized by the shared
            # XmppSession, not by an individual window. Shutting it down here
            # removes it from session._conversations; the window then binds
            # the now-orphaned object while incoming stanzas are delivered to
            # a newly-created instance. GNOME notifications still fire at the
            # session level, but this window never receives the message.
            # Disconnecting the window's signal handlers above is sufficient;
            # the session itself disposes conversations on account shutdown.
            if getattr(self.backend, 'session', None) is None:
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
        self._rendered_response_request_ids = set()

    def _build_recording_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        style_manager.apply_to_widget(box, 'recording-panel')
        box.set_valign(Gtk.Align.CENTER)
        box.set_margin_start(6)
        box.set_margin_end(6)

        self.discard_button = Gtk.Button()
        self.discard_button.add_css_class('flat')
        self.discard_button.add_css_class('destructive-action')
        resource_manager.set_widget_icon_name(
            self.discard_button, 'user-trash-symbolic',
            fallback='edit-delete-symbolic')
        self.discard_button.set_tooltip_text(_('Discard recording'))
        self.discard_button.connect('clicked', lambda *_: self._discard_recording())
        box.append(self.discard_button)

        self.recording_dot = Gtk.Label(label='\u25cf')
        style_manager.apply_to_widget(self.recording_dot, 'recording-dot')
        self.recording_dot.add_css_class('recording-dot')
        box.append(self.recording_dot)

        self.recording_timer_label = Gtk.Label(label='00:00')
        style_manager.apply_to_widget(
            self.recording_timer_label, 'recording-timer')
        box.append(self.recording_timer_label)

        self.recording_instructions_label = Gtk.Label(
            label=_('Slide left to cancel, up to lock'))
        self.recording_instructions_label.set_hexpand(True)
        self.recording_instructions_label.set_halign(Gtk.Align.CENTER)
        style_manager.apply_to_widget(
            self.recording_instructions_label, 'recording-instructions')
        box.append(self.recording_instructions_label)

        self.lock_image = Gtk.Image()
        resource_manager.set_widget_icon_name(
            self.lock_image, 'changes-prevent-symbolic',
            fallback='lock-symbolic')
        box.append(self.lock_image)

        return box

    def _on_mic_pressed(self, _gesture, _x, _y):
        if self._voice_state != VoiceRecordState.IDLE:
            return
        self._begin_recording()

    def _on_mic_cancelled(self, _gesture):
        if self._voice_state in (VoiceRecordState.HOLDING,):
            self._cancel_recording()

    def _on_mic_drag_begin(self, _gesture, start_x, start_y):
        if self._voice_state not in (VoiceRecordState.HOLDING,
                                     VoiceRecordState.LOCKED):
            return
        self._drag_start_x = start_x
        self._drag_start_y = start_y

    def _on_mic_drag_update(self, gesture, _offset_x, offset_y):
        if self._voice_state not in (VoiceRecordState.HOLDING,
                                     VoiceRecordState.LOCKED):
            return
        ok, start_x, start_y = gesture.get_start_point()
        if not ok:
            return
        if offset_y - start_y < -50 and self._voice_state == VoiceRecordState.HOLDING:
            self._voice_state = VoiceRecordState.LOCKED
            self.recording_instructions_label.set_label(
                _('Locked — tap to stop'))

    def _on_mic_drag_end(self, gesture, offset_x, offset_y):
        ok, start_x, start_y = gesture.get_start_point()
        if ok and offset_x - start_x < -80 and self._voice_state in (
                VoiceRecordState.HOLDING, VoiceRecordState.LOCKED):
            self._cancel_recording()
            return
        if self._voice_state == VoiceRecordState.LOCKED:
            return
        if self._voice_state == VoiceRecordState.HOLDING:
            self._finish_recording()

    def _begin_recording(self):
        if self._voice_state != VoiceRecordState.IDLE:
            return
        try:
            self._voice_recorder = VoiceRecorder()
            self._voice_file_path = self._voice_recorder.start()
            self._voice_duration = 0.0
            self._voice_state = VoiceRecordState.HOLDING
            if hasattr(self.input_text, 'set_editable'):
                self.input_text.set_editable(False)
            self.mic_button.add_css_class('suggested-action')
            self.recording_revealer.set_reveal_child(True)
            self.recording_timer_label.set_label('00:00')
            self.recording_instructions_label.set_label(
                _('Slide left to cancel, up to lock'))
            self._voice_timer_id = GLib.timeout_add(
                100, self._update_recording_timer)
            self._voice_blink_id = GLib.timeout_add(
                500, self._blink_recording_dot)
        except VoiceRecorderError as exc:
            self._voice_state = VoiceRecordState.FAILED
            self._show_recording_error(str(exc))
            self._reset_recording_ui()
            self._cleanup_recording()

    def _finish_recording(self):
        if self._voice_state not in (VoiceRecordState.HOLDING,
                                     VoiceRecordState.LOCKED):
            return
        file_path, duration = self._voice_recorder.stop()
        if duration < 3.0:
            self._voice_recorder._delete_file()
            self._voice_state = VoiceRecordState.IDLE
            self._voice_file_path = None
            self._voice_duration = 0.0
            self._reset_recording_ui()
            error_dialog = Gtk.AlertDialog()
            error_dialog.set_message(
                _('Recording too short — at least 3 seconds required'))
            error_dialog.show(self)
            return
        self._voice_duration = duration
        self._voice_file_path = file_path
        self._voice_state = VoiceRecordState.CAPTURED
        self._reset_recording_ui()
        self._show_voice_bubble()
        self._upload_voice_note()

    def _show_voice_bubble(self):
        if not self._voice_file_path:
            return
        body = self._voice_file_path or ''
        widget = self.display_message(body, sender='user')
        widget.set_delivery_state('pending')
        self._voice_bubble = widget
        self._voice_retry_path = self._voice_file_path

    def _cancel_recording(self):
        if self._voice_state not in (VoiceRecordState.HOLDING,
                                     VoiceRecordState.LOCKED):
            return
        self._voice_recorder.cancel()
        self._voice_state = VoiceRecordState.IDLE
        self._voice_file_path = None
        self._voice_duration = 0.0
        self._reset_recording_ui()

    def _discard_recording(self):
        if self._voice_state in (VoiceRecordState.HOLDING,
                                 VoiceRecordState.LOCKED):
            self._cancel_recording()
        elif self._voice_state == VoiceRecordState.CAPTURED:
            self._cleanup_recording()
            self._voice_state = VoiceRecordState.IDLE

    def _reset_recording_ui(self):
        self.mic_button.remove_css_class('suggested-action')
        self.recording_revealer.set_reveal_child(False)
        if hasattr(self.input_text, 'set_editable'):
            self.input_text.set_editable(True)
        if self._voice_timer_id:
            GLib.source_remove(self._voice_timer_id)
            self._voice_timer_id = None
        if self._voice_blink_id:
            GLib.source_remove(self._voice_blink_id)
            self._voice_blink_id = None

    def _cleanup_recording(self):
        if self._voice_recorder:
            self._voice_recorder.cancel()
            self._voice_recorder = None
        self._voice_file_path = None
        self._voice_duration = 0.0

    def _update_recording_timer(self) -> bool:
        if self._voice_state not in (VoiceRecordState.HOLDING,
                                     VoiceRecordState.LOCKED):
            self._voice_timer_id = None
            return GLib.SOURCE_REMOVE
        elapsed = self._voice_recorder._start_time
        if elapsed:
            secs = int(time.monotonic() - elapsed)
            minutes, seconds = divmod(secs, 60)
            self.recording_timer_label.set_label(f'{minutes:02d}:{seconds:02d}')
        return GLib.SOURCE_CONTINUE

    def _blink_recording_dot(self) -> bool:
        if self._voice_state not in (VoiceRecordState.HOLDING,
                                     VoiceRecordState.LOCKED):
            self._voice_blink_id = None
            return GLib.SOURCE_REMOVE
        self.recording_dot.set_visible(
            not self.recording_dot.get_visible())
        return GLib.SOURCE_CONTINUE

    def _show_recording_error(self, message):
        error_label = Gtk.Label(label=message)
        error_label.add_css_class('error')
        self.input_overlay.add_overlay(error_label)
        GLib.timeout_add(3000, lambda: (
            self.input_overlay.remove_overlay(error_label),
            GLib.SOURCE_REMOVE)[1])

    def _upload_voice_note(self):
        if not self.is_messaging_backend or not self._voice_file_path:
            self._voice_state = VoiceRecordState.IDLE
            self._cleanup_recording()
            return
        self._voice_state = VoiceRecordState.UPLOADING
        mime = audio_mime_for_file(self._voice_file_path)
        self._record_send_attempt()

        def on_done(ok, detail):
            GLib.idle_add(lambda: self._on_voice_upload_done(ok, detail))

        session = getattr(self.backend, 'session', None)
        if session is None:
            self._voice_state = VoiceRecordState.FAILED
            return
        session.send_file(
            self.backend.bare_jid, self._voice_file_path, on_done)

    def _record_send_attempt(self):
        history = getattr(
            getattr(self.backend, 'session', None), 'history', None)
        if history is None:
            return
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        body = self._voice_file_path or ''
        mime = audio_mime_for_file(self._voice_file_path)
        history.record_message(
            self.backend.bare_jid, body, 'out', ts,
            attachment_url=None,
            attachment_mime_type=mime or RECORDING_MIME,
            attachment_duration=self._voice_duration,
            attachment_local_path=self._voice_file_path,
            attachment_state='uploading')

    def _on_voice_upload_done(self, ok, detail):
        if self._voice_state != VoiceRecordState.UPLOADING:
            return GLib.SOURCE_REMOVE
        history = getattr(
            getattr(self.backend, 'session', None), 'history', None)
        if self._voice_bubble:
            if ok:
                self._voice_bubble.set_delivery_state('sent')
                self._voice_bubble.update_content(detail)
                self._voice_state = VoiceRecordState.IDLE
            else:
                self._voice_bubble.set_delivery_state('failed')
                self._voice_state = VoiceRecordState.FAILED
                self._voice_retry_path = self._voice_file_path
        else:
            if ok:
                self._voice_state = VoiceRecordState.IDLE
            else:
                self._voice_state = VoiceRecordState.FAILED
                self._voice_retry_path = self._voice_file_path
        if ok:
            if history and self._voice_file_path:
                history.update_attachment_state(
                    self.backend.bare_jid, self._voice_file_path, 'out',
                    'sent', attachment_url=detail)
            self._cleanup_recording()
        else:
            if history and self._voice_file_path:
                history.update_attachment_state(
                    self.backend.bare_jid, self._voice_file_path, 'out',
                    'failed')
        self._voice_bubble = None
        return GLib.SOURCE_REMOVE
        # Identidad de cada burbuja ya pintada, para que el solape del catch-up
        # no la repinte. Se vacía con las burbujas: si no, al reabrir la
        # conversación el historial se descartaría entero por "ya visto".
        self._history_keys = set()
        # Para qué contacto se construyó el sidebar de ajustes. Se invalida aquí
        # (la ventana pasa a otra conversación) y NO en cada cambio de presencia.
        self._settings_panel_for = None
        # Otra conversación arranca sin nadie leyendo hacia atrás.
        self._loading_older_history = False
        self._agent_command_client = None
        self._cancel_pending_messaging_send()
        if self._post_layout_scroll_watch_id is not None:
            GLib.source_remove(self._post_layout_scroll_watch_id)
            self._post_layout_scroll_watch_id = None
        self._cancel_scroll_animation()
        if self._post_layout_scroll_settle_id is not None:
            GLib.source_remove(self._post_layout_scroll_settle_id)
            self._post_layout_scroll_settle_id = None
        self._post_layout_scroll_pending = False
        self._post_layout_scroll_force = False
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
        self.backend = backend
        # La sesión XMPP puede venir del propio backend (una conversación con un
        # contacto) o suelta (ventana que aún no eligió con quién hablar).
        session = getattr(backend, 'session', None) or xmpp_session
        self._xmpp_session = session

        has_conversation = backend is not None
        is_xmpp = session is not None
        self.xmpp_toolbar.set_visible(is_xmpp)
        self.xmpp_status_bar.set_visible(is_xmpp)
        self.roster_button.set_visible(True)
        self._sidebar_toggle_binding = self.split_view.bind_property(
            "show-sidebar", self.roster_button, "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        # Sin conversación (el picker) no hay a quién escribirle: ocultar la
        # barra de escribir entera, no deshabilitarla vía set_enabled(False)
        # más abajo. Ese método reutiliza _set_busy(True) — pensado para
        # "generando respuesta" — y activaba el spinner con el botón "Stop"
        # indefinidamente, sin que nada lo apagara (no hay backend generando
        # nada acá, y tocar "Stop" tampoco haría nada porque backend es
        # None). set_enabled no toca visibilidad, así que si esta llamada
        # SÍ trae backend (conversión del picker al elegir un contacto)
        # tiene que reaparecer explícitamente acá.
        self.input_box.set_visible(has_conversation)
        self.set_enabled(True)
        self.split_view.set_collapsed(True)
        self.split_view.set_show_sidebar(False)

        # Las señales del contrato ChatBackend, sin mirar de qué tipo es: un
        # backend que no emita alguna (LLMClient no emite 'typing') simplemente
        # nunca dispara ese handler.
        if backend is not None:
            self._backend_handler_ids = [
                backend.connect('ready', self._on_backend_ready),
                backend.connect('response', self._on_llm_response),
                backend.connect('response-message', self._on_response_message),
                backend.connect('response-correction',
                                self._on_llm_response_correction),
                backend.connect('own-carbon-resolved',
                                self._on_own_carbon_resolved),
                backend.connect('own-message', self._on_own_message),
                backend.connect('error', self._on_llm_error),
                backend.connect('finished', self._on_llm_finished),
                backend.connect('state-changed', self._on_backend_state_changed),
                backend.connect('typing', self._on_backend_typing),
                backend.connect('delivery-state', self._on_delivery_state),
                backend.connect('quick-responses', self._on_quick_responses),
                backend.connect('commands', self._on_commands),
            ]
            # Adjuntar sólo se ofrece si el backend sabe subir archivos
            # (XMPP vía XEP-0363); el backend LLM local no.
            self.attach_button.set_visible(hasattr(backend, 'send_file'))
            self.mic_button.set_visible(hasattr(backend, 'send_file'))
            # El cid sale de la config, no del backend: LLMClient.get_conversation_id()
            # fuerza la carga del modelo y, si aún no hay conversación, se INVENTA
            # una nueva — con lo que la ventana acababa apuntando a una conversación
            # vacía en vez de a la que se pidió abrir. El backend publica su cid
            # definitivo en 'ready' (ver _on_backend_ready), que es cuando ya lo sabe.
            self.cid = self.config.get('cid')

        if session is not None:
            self._session_handler_ids = [
                session.connect('contact-status-changed',
                                self._on_contact_status_changed),
                session.connect('presence-changed',
                                self._on_contact_presence_changed),
                session.connect('agent-telemetry-changed',
                                self._on_agent_telemetry_changed),
                session.connect('avatar-changed', self._on_avatar_changed),
                session.connect('chat-message-delivered',
                                self._on_session_chat_message_delivered),
            ]
            self._last_connection_state = session.state
            self._update_connection_status(self._last_connection_state)

        # XmppConversation se cachea por bare JID y puede haber emitido `ready`
        # antes de que esta ventana conectara sus handlers. Una señal describe
        # una transición, no el estado actual: al enlazar una conversación a una
        # sesión que YA está conectada hay que reconciliar ese estado ahora.
        # _load_xmpp_history es idempotente, así que el idle propio de una
        # conversación recién creada puede llegar después sin duplicar nada.
        if backend is not None and is_xmpp and session.is_connected:
            GLib.idle_add(
                self._on_backend_ready, backend, backend.get_display_name())

        # El historial NO se pide aquí. Lo carga _on_backend_ready, que es
        # cuando el backend está de verdad listo: en XMPP eso significa sesión
        # conectada (sin conexión, la consulta MAM se descarta en silencio y el
        # chat se queda vacío), y en LLM, modelo cargado y cid conocido.
        if has_conversation and is_xmpp:
            self._update_xmpp_title_status()

        # Roster unificado (izquierda): conversaciones LLM y contactos XMPP.
        from .chat_roster_sidebar import ChatRosterSidebar
        self.roster_sidebar = ChatRosterSidebar(
            config=self.config,
            llm_client=backend if not is_xmpp else None,
            chat_history=self.chat_history,
            xmpp_session=session,
            on_llm_conversation_selected=self._on_llm_conversation_selected,
            on_xmpp_contact_selected=self._on_roster_contact_selected,
            on_xmpp_account=self._open_xmpp_account_from_sidebar)
        self.model_sidebar = self.roster_sidebar
        self.model_options = self.roster_sidebar.options_sidebar
        self.split_view.set_sidebar_position(Gtk.PackType.START)
        self.split_view.set_sidebar(self.roster_sidebar)

        if not has_conversation:
            # Ventana sin conversación (el "picker"): el roster se ve de
            # entrada, no escondido tras un toggle. input_box ya se ocultó
            # arriba (ver comentario junto a self.input_box.set_visible).
            self.split_view.set_show_sidebar(True)
            self.split_view.set_collapsed(False)

        self._update_settings_panel()

    @property
    def is_messaging_backend(self):
        """True si el backend es de mensajería (XMPP): hay una sesión y un
        contacto al otro lado. Sustituye al viejo _injected_backend, que decía
        "el backend me lo dieron construido" — algo que ahora es siempre cierto
        (spec 009) y que además nunca fue la pregunta que se quería hacer."""
        return self._xmpp_session is not None

    def _on_session_chat_message_delivered(self, _session, bare_jid, body,
                                           actions, request_id, replace_id):
        """Reconcile session delivery when a stale backend lost its signal.

        The canonical XmppConversation normally emits synchronously before
        this hook, so request_id deduplication makes the common path a no-op.
        This path exists for lifecycle races: notification and persistence
        succeeded, but the open window was still bound to an older backend.
        """
        if getattr(self.backend, 'bare_jid', None) != bare_jid:
            return
        stable_id = replace_id or request_id
        if replace_id:
            if (replace_id in self._message_widgets_by_id or
                    replace_id in self._pending_action_bodies):
                self._on_llm_response_correction(
                    self.backend, replace_id, body)
            else:
                self._on_response_message(self.backend, replace_id, body)
            return
        if (stable_id and (
                stable_id in self._message_widgets_by_id or
                stable_id in self._pending_action_bodies or
                stable_id in self._rendered_response_request_ids)):
            return
        self._on_response_message(self.backend, request_id, body)
        action_list = list(actions or [])
        if not action_list:
            return
        if any(item.get('node') and item.get('jid') for item in action_list):
            self._on_commands(self.backend, action_list, request_id)
        else:
            self._on_quick_responses(self.backend, action_list, request_id)

    def _update_settings_panel(self):
        """Puebla el sidebar derecho con lo que el backend actual ofrezca.

        No se pregunta "¿esto es LLM o XMPP?", sino "¿qué ajustes tienes?" — un
        agente ofrece sus comandos ad-hoc, un modelo local sus parámetros, y un
        contacto XMPP normal nada (entonces el panel y su botón desaparecen).

        El panel se CACHEA por contacto. Antes se reconstruía en cada llamada, y
        como _on_contact_status_changed llama aquí, cada latido de presencia del
        agente (cada 10s, y alternando chat/dnd mientras trabaja) creaba un
        AgentCommandsSidebar nuevo — que pide los comandos por XMPP al
        construirse. Resultado: una ráfaga de disco#items cada pocos segundos
        contra el gateway, multiplicada por cada ventana abierta. Además era
        destructivo: reconstruir el panel se llevaba por delante el formulario
        XEP-0004 que el usuario estuviera rellenando.
        """
        key = self._settings_panel_key()
        if key == self._settings_panel_for:
            return
        self._settings_panel_for = key

        panel = self._build_settings_panel()
        self.settings_split.set_sidebar(panel)
        self.settings_button.set_visible(panel is not None)
        if panel is None:
            self.settings_split.set_show_sidebar(False)

    def _settings_panel_key(self):
        """Qué panel toca. Sólo cambia al cambiar de conversación — no cuando el
        agente cambia de estado, que es lo que dispara la mayoría de llamadas."""
        if self.backend is None:
            return None
        session = getattr(self.backend, 'session', None)
        bare_jid = getattr(self.backend, 'bare_jid', None)
        if session is not None and bare_jid:
            # is_agent_contact SÍ puede cambiar (las caps del contacto llegan
            # después del roster), así que entra en la clave: en cuanto sabemos
            # que es un agente, el panel se construye — pero una sola vez.
            return ('xmpp', bare_jid, session.is_agent_contact(bare_jid))
        return ('llm', self.cid)

    def _build_settings_panel(self):
        if self.backend is None:
            return None

        session = getattr(self.backend, 'session', None)
        bare_jid = getattr(self.backend, 'bare_jid', None)
        if session is not None and bare_jid:
            # Sólo un agente expone comandos; un contacto humano no tiene
            # ajustes que ofrecer aquí.
            if not session.is_agent_contact(bare_jid):
                return None
            from .agent_commands_sidebar import AgentCommandsSidebar
            return AgentCommandsSidebar(
                session, bare_jid,
                on_error=lambda msg: self._on_llm_error(self.backend, msg))

        # Backend LLM: los parámetros del modelo, que hasta ahora vivían
        # escondidos dentro del stack del roster (a la izquierda).
        return self.model_options

    # Resetear el stack al cerrar el sidebar
    def _on_sidebar_visibility_changed(self, split_view, param):
        # Al cerrar el roster, volver a su lista (los ajustes del modelo ya no
        # son una página suya: viven en el sidebar derecho).
        if not split_view.get_show_sidebar():
            if self.roster_sidebar is not None:
                self.roster_sidebar.show_list()
            self.input_text.grab_focus()

    def _on_window_height_changed(self, *_args):
        self._sync_tool_output_height()

    def _sync_tool_output_height(self):
        """Recalcula el tope del panel de actividad contra el alto real de la
        ventana. Proporcional en vez de fijo: en una ventana grande se ve la
        salida completa de un exec normal; en una chica no se come el chat."""
        height = self.get_height()
        if height <= 0:
            # Sin superficie asignada todavía (arranque): mantener el mínimo
            # ya puesto por __init__ en vez de calcular sobre un 0.
            return
        target = int(height * self._TOOL_OUTPUT_HEIGHT_FRACTION)
        target = max(self._TOOL_OUTPUT_MIN_HEIGHT,
                     min(self._TOOL_OUTPUT_MAX_HEIGHT, target))
        self.tool_output_scroll.set_max_content_height(target)

    def _on_roster_contact_selected(self, bare_jid):
        """Un contacto XMPP elegido en el roster: abre/enfoca su ventana."""
        session = getattr(self.backend, 'session', None) or self._xmpp_session
        if session is None:
            return
        self._open_from_roster({
            'kind': 'xmpp',
            'session': session,
            'account': session.bare_jid,
            'jid': bare_jid,
        })

    def _on_llm_conversation_selected(self, cid):
        """Una conversación LLM elegida en el roster: abre/enfoca su ventana,
        igual que un contacto XMPP. Antes esto transformaba la ventana actual,
        que era la razón de todo el trasiego de claves del registro."""
        if cid == self.cid:
            self.split_view.set_show_sidebar(False)
            return
        self._open_from_roster({'kind': 'llm', 'cid': cid})

    def _open_from_roster(self, descriptor):
        """Abre la conversación elegida. Si esta ventana es el picker (aún no
        tiene conversación), se convierte en ella en vez de dejar una ventana
        vacía huérfana; si ya tiene una, la nueva va en su propia ventana."""
        app = self.get_application()
        if app is None:
            return
        self.split_view.set_show_sidebar(False)

        # Si ya existe una ventana registrada para esta conversación, es la
        # dueña: enfocarla y no duplicar. Sin este chequeo, convertir el picker
        # (backend is None) reescribía su clave en el registro, dejando dos
        # ventanas para el mismo JID y huérfana la original.
        key = app.conversation_key(descriptor)
        if key is not None:
            existing = app._window_by_cid.get(key)
            if existing is not None and existing is not self:
                existing.present()
                return

        if self.backend is None:
            backend = app.build_backend(descriptor, self.chat_history)
            self.config['cid'] = descriptor.get('cid') or self.config.get('cid')
            self.cid = descriptor.get('cid')
            self._bind_backend(backend=backend,
                               xmpp_session=descriptor.get('session'))
            if key:
                app._window_by_cid[key] = self
            return

        app.open_conversation(descriptor)

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

            .streaming-message .message-content {
                border-color: alpha(@accent_color, 0.72);
                background-color: alpha(@accent_color, 0.06);
            }

            .recording-panel {
                background-color: alpha(@theme_bg_color, 0.95);
                border: 1px solid alpha(@theme_fg_color, 0.14);
                border-radius: 8px;
                padding: 6px;
            }

            .recording-dot {
                color: @destructive_color;
                font-weight: bold;
                font-size: 18px;
            }

            .recording-timer {
                font-family: monospace;
                font-size: 14px;
            }

            .recording-instructions {
                font-size: 12px;
                opacity: 0.75;
            }

            .markdown-table {
                margin: 0;
            }

            .table-header-cell {
                font-weight: bold;
                background-color: alpha(@theme_fg_color, 0.08);
                border-bottom: 1px solid alpha(@theme_fg_color, 0.14);
            }

            .audio-message {
                margin: 6px 0;
            }

            .audio-bubble {
                margin: 8px 0;
                padding: 8px;
                border: 1px solid alpha(@theme_fg_color, 0.12);
                border-radius: 8px;
                background-color: alpha(@theme_fg_color, 0.04);
            }

            .delivery-failed .message-content {
                border: 1px solid alpha(@error_color, 0.75);
            }

            .typing-row {
                margin-left: 42px;
                padding: 4px 8px;
            }

            .tool-activity-line {
                opacity: 0.72;
                font-family: monospace;
            }

            .tool-output-panel {
                padding: 8px;
                border-left: 3px solid alpha(@accent_color, 0.75);
                background-color: alpha(@theme_fg_color, 0.035);
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
                border: 1px solid alpha(@accent_color, 0.70);
                border-left-width: 4px;
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
        if self.is_messaging_backend:
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
            self._open_model_options(page="model_selector")
            return True

        # Ctrl+S: Cambiar system prompt (no aplica a backends no-LLM)
        if keyval == Gdk.KEY_s and state & Gdk.ModifierType.CONTROL_MASK:
            self._open_model_options()
            if self.model_options is not None and hasattr(
                    self.model_options, '_on_system_prompt_button_clicked'):
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
        """Habilita o deshabilita la entrada de texto.

        Deshabilitado equivale a "generando": es el único punto por el que pasan
        tanto el envío como el fin (éxito o error), así que el spinner y el botón
        de cancelar se conmutan aquí en vez de en cada sitio que emite.
        """
        self.input_text.set_sensitive(enabled)
        self.send_button.set_sensitive(enabled)
        self._set_busy(not enabled)

    def _set_busy(self, busy):
        self.action_stack.set_visible_child_name('busy' if busy else 'send')
        if busy:
            self.busy_spinner.start()
        else:
            self.busy_spinner.stop()
            # La actividad la publica el agente por presencia; al terminar no
            # llega ningún "ya no hago nada", así que se limpia aquí.
            self.activity_label.set_label("")

    def _on_stop_clicked(self, _button):
        if self.backend is not None:
            self.backend.cancel()
        # No esperamos al backend para devolver el control: si cancel() no
        # produjera un 'finished', el usuario se quedaría con la UI bloqueada.
        self.set_enabled(True)

    def _on_text_changed(self, buffer):
        if self._suppress_text_changed:
            if DEBUG:
                debug_print("[send] text-changed suppressed")
            return
        # La altura ya no se calcula aquí: get_line_count() sólo cuenta líneas
        # lógicas, así que un párrafo largo sin saltos contaba como una sola y
        # el TextView crecía sin tope al envolverse. Ahora el alto lo negocian
        # el TextView y su ScrolledWindow (min/max_content_height).

        # Notificar 'composing' al backend (spec 001, T8). No-op en LLMClient.
        if self.backend is not None:
            has_text = buffer.get_char_count() > 0
            if DEBUG:
                debug_print(f"[send] text-changed has_text={has_text}")
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

    def _send_from_input_shortcut(self, _widget, _args):
        self._on_send_clicked(None)
        return True

    def display_message(self, content, sender="user", timestamp=None):
        """
        Displays a message in the chat window.

        Args:
            content (str): The text content of the message.
            sender (str): The sender of the message ("user" or "assistant").
            timestamp (datetime, optional): Hora real del mensaje. Sin esto,
                Message cae en datetime.now() (hora de RENDERIZADO), lo que
                rompía _has_recent_matching_bubble (ventana de 60s) contra el
                timestamp real que trae el catch-up de MAM al reconectar —
                el mismo mensaje terminaba pintado dos veces si pasaba más de
                un minuto entre la burbuja en vivo y la re-sincronización.
        """
        message = Message(content, sender, timestamp=timestamp)

        if sender == "user":
            self.last_message = message

        # Create the message widget. Markdown también para XMPP: los agentes
        # responden en markdown, y las burbujas del historial ya se pintaban
        # con MarkdownView (default de MessageWidget) — texto plano en vivo
        # dejaba el render inconsistente entre sesión y recarga.
        use_markdown = True
        avatar_path = None
        avatar_anchor = (sender == 'assistant' and self.is_messaging_backend
                         and self._last_live_sender != 'assistant')
        if avatar_anchor:
            session = getattr(self.backend, 'session', None)
            bare_jid = getattr(self.backend, 'bare_jid', None)
            if session is not None and bare_jid is not None:
                avatar_path = session.avatar_paths.get(bare_jid)
                session.fetch_avatar(bare_jid)
        message_widget = MessageWidget(
            message, use_markdown=use_markdown, avatar_path=avatar_path,
            avatar_anchor=avatar_anchor,
            on_retry=self._retry_message if sender == 'user' else None)
        self._last_live_sender = sender
        if DEBUG:
            debug_print(f"[send] display_message sender={sender} len={len(str(content or ''))}")

        # Reconciliar intención con posición REAL antes de que append cambie
        # upper. El flag puede quedar stale tras un relayout; si físicamente
        # estábamos al fondo, una respuesta nueva debe seguirse suavemente.
        adj = self.message_scroll.get_vadjustment()
        if self._at_bottom(adj):
            self._stick_to_bottom = True

        # Enviar un mensaje propio es intención explícita de volver al fondo;
        # la llegada de uno del asistente no, así que ahí se respeta que el
        # usuario pueda estar leyendo más arriba.
        force = sender == "user"

        # Mensajes en vivo de XMPP: append directo para que se vean de inmediato
        # y no dependan de timestamp/ordenado de historial.
        if self.is_messaging_backend:
            self.messages_box.append(message_widget)
            self._content_added_pending = True
            GLib.idle_add(lambda: setattr(self, '_content_added_pending', False)
                          or GLib.SOURCE_REMOVE)
            if DEBUG:
                debug_print(
                    f"[insert] live-append sender={sender} "
                    f"children={len(list(self.messages_box))}")
        else:
            # LLM/historial: mantener inserción cronológica.
            self._insert_bubble_by_timestamp(message_widget)

        # En GTK4 el append puede actualizar el adjustment antes de que el
        # widget nuevo quede medido/pintado. Si no se invalida explícitamente,
        # XMPP queda visualmente una burbuja atrás hasta la próxima interacción.
        message_widget.queue_resize()
        self.messages_box.queue_resize()
        self.messages_box.queue_draw()
        self.message_scroll.queue_resize()
        self.message_scroll.queue_draw()
        if self.is_messaging_backend:
            self._scroll_to_bottom_messaging(force=force)
        else:
            self._scroll_to_bottom_after_layout(force=force)
        if DEBUG:
            debug_print(f"[send] display_message done sender={sender}")

        return message_widget

    def _retry_message(self, body):
        if self.backend is None or not self.is_messaging_backend:
            return
        widget = self.display_message(body, sender='user')
        widget.set_delivery_state('pending')
        self._pending_delivery_widgets.setdefault(body, []).append(widget)
        self.backend.send_message(body)

    def _on_delivery_state(self, _backend, stanza_id, state, body):
        debug_print(f"[delivery-ui] id={stanza_id} state={state} len={len(body or '')}")
        widget = self._delivery_widgets.get(stanza_id)
        if widget is None:
            pending = self._pending_delivery_widgets.get(body, [])
            if pending:
                widget = pending.pop(0)
                self._delivery_widgets[stanza_id] = widget
            if not pending:
                self._pending_delivery_widgets.pop(body, None)
        if widget is not None:
            widget.set_delivery_state(state)

    def _scroll_to_bottom_messaging(self, force=True):
        """Scroll para XMPP (mensajes discretos, sin streaming).

        Fija la intención y usa el mismo ciclo post-layout que el historial:
        el adjustment puede estar al fondo mientras el último widget todavía
        no fue medido/pintado, lo que se ve como "una burbuja atrás".
        """
        adj = self.message_scroll.get_vadjustment()
        if force:
            self._stick_to_bottom = True
        if not self._stick_to_bottom:
            return

        # Bajar ya con lo que se conoce y mantener un watcher breve hasta que
        # el layout se estabilice con la altura real del bubble nuevo.
        self._set_value_silently(adj, adj.get_upper() - adj.get_page_size())
        self._scroll_to_bottom_after_layout(force=force)

    def _clear_input_buffer_silently(self):
        """Limpia el TextBuffer sin disparar efectos colaterales de
        _on_text_changed (p.ej. notify_composing en red)."""
        buffer = self.input_text.get_buffer()
        self._suppress_text_changed = True
        try:
            if DEBUG:
                debug_print("[send] clearing input buffer silently")
            buffer.set_text("", 0)
        finally:
            self._suppress_text_changed = False

    def _update_connection_status(self, state):
        """Refleja el estado de conexión del backend en la barra XMPP."""
        labels = {
            'connecting': _("Connecting…"),
            'syncing-roster': _("Syncing contacts…"),
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
            if self._typing_row is None:
                self._typing_row = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                self._typing_row.add_css_class('typing-row')
                spinner = Gtk.Spinner()
                spinner.start()
                label = Gtk.Label(label=_("Typing…"))
                label.add_css_class('dim-label')
                self._typing_row.append(spinner)
                self._typing_row.append(label)
                self.messages_box.append(self._typing_row)
                self._scroll_to_bottom_after_layout_if_following()
        else:
            if self._typing_row is not None:
                self.messages_box.remove(self._typing_row)
                self._typing_row = None
            self._update_xmpp_title_status()

    def _on_avatar_changed(self, session, bare_jid):
        if bare_jid != getattr(self.backend, 'bare_jid', None):
            return
        path = session.avatar_paths.get(bare_jid)
        if not path:
            return
        for child in list(self.messages_box):
            message = getattr(child, 'message', None)
            if (message is not None and message.sender == 'assistant'
                    and getattr(child, '_avatar_anchor', False)):
                child.set_avatar(path)

    def _on_contact_status_changed(self, session, bare_jid):
        active_bare = getattr(self.backend, 'bare_jid', None)
        if bare_jid == active_bare:
            self._update_xmpp_title_status()
            self._update_settings_panel()

    def _on_agent_telemetry_changed(self, session, bare_jid):
        """El agente publicó telemetría nueva (PEP): refrescar la barra de
        contexto y el badge de modelo del área de entrada."""
        if bare_jid == getattr(self.backend, 'bare_jid', None):
            self._apply_agent_telemetry(session.get_agent_telemetry(bare_jid))

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
            self._is_agent_contact = False
            self._update_agent_state_chips("")
            return
        # El nombre del contacto, no su JID: get_display_name ya cae al localpart
        # capitalizado cuando el roster no trae un nombre. El JID entero sigue a
        # la vista en la barra de estado, y aquí a un hover.
        display_name = self.backend.get_display_name()
        if not self._title_is_user_renamed:
            self.title_widget.set_title(display_name)
            self.title_entry.set_text(display_name)
            self.set_title(display_name)
        self.title_widget.set_subtitle("")
        self.title_widget.set_tooltip_text(bare_jid)
        status = session.get_contact_status(bare_jid)
        presence = session.get_presence(bare_jid)
        presence_label = self._set_title_presence_state(presence)
        display_status = status or presence_label
        self.contact_status_label.set_label(bare_jid)
        self.contact_status_label.set_tooltip_text(display_status)
        # Un contacto-agente gestiona su propio modelo (comando XEP-0050); un
        # contacto XMPP normal no tiene ajustes de modelo que ofrecer.
        self._is_agent_contact = session.is_agent_contact(bare_jid)
        self._update_agent_state_chips(display_status)
        # Telemetría: pintar lo que ya tengamos, y pedir el valor actual — un
        # agente quieto no publica eventos, así que sin esta petición la barra
        # de contexto no aparecería hasta que el agente volviera a trabajar.
        self._apply_agent_telemetry(session.get_agent_telemetry(bare_jid))
        if self._is_agent_contact:
            session.fetch_agent_telemetry(bare_jid)

    def _update_agent_state_chips(self, status):
        """El <status> de la presencia: qué está haciendo el agente, y nada más.

        Los números (contexto, tokens, modelo) ya no viajan aquí — llegan por
        PEP, ver _apply_agent_telemetry. El status es texto para humanos, y
        meterle cifras hacía que cualquier otro cliente (Gajim) mostrara
        "ctx_used=42865 | tok=…" como estado del contacto."""
        if not hasattr(self, 'activity_label'):
            return
        activity = self._friendly_agent_activity(
            self._parse_agent_status(status).get('activity', ''))
        self.activity_label.set_label(activity)
        self.activity_label.set_tooltip_text(str(status or ""))

    def _set_title_presence_state(self, presence):
        """Reflect XMPP show/session state in the header status dot."""
        if not hasattr(self, 'title_presence_dot'):
            return _("Offline")
        for css_class in getattr(self, '_title_presence_css', set()):
            self.title_presence_dot.remove_css_class(css_class)
        css_classes = set()
        state = presence or XmppSession.PRESENCE_OFFLINE
        if state == XmppSession.PRESENCE_BUSY:
            label = _("Busy")
            css_classes.add("error")
            visible = True
        elif state == XmppSession.PRESENCE_AWAY:
            label = _("Away")
            css_classes.add("warning")
            visible = True
        elif state == XmppSession.PRESENCE_ONLINE:
            label = _("Online")
            css_classes.add("success")
            visible = True
        else:
            label = _("Offline")
            css_classes.add("dim-label")
            visible = False
        for css_class in css_classes:
            self.title_presence_dot.add_css_class(css_class)
        self._title_presence_css = css_classes
        self.title_presence_dot.set_tooltip_text(label)
        self.title_presence_dot.set_visible(visible)
        return label

    def _apply_agent_telemetry(self, telemetry):
        """Telemetría recibida por PEP: barra de contexto y badge de modelo."""
        if not hasattr(self, 'context_level'):
            return
        telemetry = telemetry or {}
        self._update_context_level(telemetry)
        self._update_model_badge(telemetry.get('model'))
        if telemetry and hasattr(self, 'activity_label'):
            parsed = self._normalize_agent_status_dict(telemetry)
            activity = self._friendly_agent_activity(parsed.get('activity', ''))
            if parsed.get('tool'):
                activity = _("Usando herramienta: ") + str(parsed['tool'])
            details = self._format_agent_status_details(parsed)
            self.activity_label.set_label(activity or details)
            self.activity_label.set_tooltip_text(details or activity or "")
            tool = str(parsed.get('tool') or '').strip()
            if tool:
                self.tool_output_panel.set_visible(False)
                tool_text = str(telemetry.get('tool_detail') or '').strip()
                if not tool_text:
                    tool_text = _("🛠️ Usando herramienta: ") + tool
                widget = self._telemetry_tool_widget
                if (widget is None or widget.get_parent() != self.messages_box):
                    current = self.current_message_widget
                    current_body = getattr(
                        getattr(current, 'message', None), 'content', '')
                    if (current is not None and
                            current.get_parent() == self.messages_box and
                            (self._is_progress_snapshot(current_body) or
                             self._is_progress_seed(current_body))):
                        widget = current
                        widget.update_content(tool_text)
                    else:
                        widget = self.display_message(
                            tool_text, sender='assistant')
                    self._telemetry_tool_widget = widget
                elif self._telemetry_tool_name != tool:
                    widget.update_content(tool_text)
                    self._scroll_to_bottom_after_layout_if_following()
                widget.set_streaming(True)
                self._telemetry_tool_name = tool
            else:
                # PEP can briefly report no current tool between the seed and
                # the first toolCall. It must not erase XEP-0308 progress that
                # is still active (or was just restored from history).
                if (not self._tool_output_request_ids and
                        not self._restored_active_tool_panel):
                    self.tool_output_label.set_label("")
                    self.tool_output_panel.set_visible(False)
            availability = str(telemetry.get('availability') or telemetry.get('activity') or '').lower()
            if availability in ('busy', 'processing', 'working'):
                self._set_title_presence_state(XmppSession.PRESENCE_BUSY)
            elif availability in ('away', 'paused', 'xa'):
                self._set_title_presence_state(XmppSession.PRESENCE_AWAY)
            elif availability == 'available':
                self._set_title_presence_state(XmppSession.PRESENCE_ONLINE)
                if self._telemetry_tool_widget is not None:
                    self._telemetry_tool_widget.set_streaming(False)
                self._telemetry_tool_widget = None
                self._telemetry_tool_name = None
                # PEP is authoritative for the end of a turn. A missing final
                # XEP-0308 correction must not leave “Recibido · preparando…”
                # (or the last tool name) pinned forever in the tool panel.
                self._tool_output_request_ids.clear()
                self._tool_history_request_ids.clear()
                self._restored_active_tool_panel = False
                self.tool_output_label.set_label("")
                self.tool_output_panel.set_visible(False)
                self._remove_orphaned_progress_seeds()

    def _remove_orphaned_progress_seeds(self):
        """Retira seeds y burbujas de actividad de herramienta sin corrección
        cuando PEP confirma que terminó el turno.

        Antes solo miraba _is_progress_seed ("Recibido · preparando…"), pero
        la burbuja "🛠️ Usando herramienta: X" que crea _apply_agent_telemetry
        (vía display_message cuando no hay progress seed que reusar) tiene
        otro texto y nunca calificaba — quedaba pegada en el historial para
        siempre, como mensaje del asistente, aunque solo fuera indicador de
        actividad transitoria."""
        for request_id, widget in list(self._message_widgets_by_id.items()):
            message = getattr(widget, 'message', None)
            body = getattr(message, 'content', '') if message is not None else ''
            if not (self._is_progress_seed(body)
                    or self._is_tool_activity_message(body)):
                continue
            if widget.get_parent() == self.messages_box:
                self.messages_box.remove(widget)
            self._message_widgets_by_id.pop(request_id, None)
            self._tool_output_request_ids.discard(request_id)
            self._tool_history_request_ids.discard(request_id)
            if widget is self.current_message_widget:
                self.current_message_widget = None

    def _update_context_level(self, telemetry):
        used = telemetry.get('context_used')
        total = telemetry.get('context_max')
        if used is None or not total:
            self.context_level.set_visible(False)
            return
        fraction = max(0.0, min(1.0, used / total))
        self.context_level.set_value(fraction)
        self.context_level.set_visible(True)

        tooltip = [
            _("Context: {percent}% ({used}k / {total}k tokens)").format(
                percent=round(fraction * 100),
                used=round(used / 1000),
                total=round(total / 1000)),
        ]
        # Lo acumulado no cabe en la barra, pero sí a un hover de distancia.
        if telemetry.get('tokens_total') is not None:
            tooltip.append(_("Session: {total} tokens in {requests} requests").format(
                total=f"{telemetry['tokens_total']:,}",
                requests=telemetry.get('tokens_requests', '?')))
        if telemetry.get('cost') is not None:
            tooltip.append(_("Cost: ") + self._format_cost(telemetry['cost']))
        if telemetry.get('session_cost') is not None:
            tooltip.append(_("Session cost: ") + self._format_cost(telemetry['session_cost']))
        if telemetry.get('day_cost') is not None:
            tooltip.append(_("Today: ") + self._format_cost(telemetry['day_cost']))
        self.context_level.set_tooltip_text("\n".join(tooltip))

    def _update_model_badge(self, model):
        if not model:
            self.model_badge.set_visible(False)
            return
        # El id completo (provider/modelo) es demasiado largo para un badge; el
        # nombre basta, y el id entero queda en el tooltip.
        text = str(model)
        self.model_badge.set_label(text.split('/')[-1])
        self.model_badge.set_tooltip_text(text)
        self.model_badge.set_visible(True)

    def _on_model_badge_clicked(self, _button):
        """Los ajustes del modelo son distintos según quién lo gobierne: en LLM
        los decide esta app (panel de parámetros del sidebar); con un agente los
        decide el agente, y la vía es su comando `model` (XEP-0050)."""
        if self._is_agent_contact:
            self._open_agent_model_command()
            return
        self._open_model_options()

    def _open_model_options(self, page=None):
        """Abre el panel de parámetros del modelo — ahora el sidebar derecho, no
        una página escondida dentro del roster."""
        if getattr(self, 'model_options', None) is None:
            return
        self.settings_split.set_show_sidebar(True)
        if page:
            self.model_options.stack.set_visible_child_name(page)

    def _open_agent_model_command(self):
        """Ejecuta el comando `model` del agente: el mismo formulario (selector
        de alias) que aparece en el menú de comandos, sin tener que buscarlo."""
        session = getattr(self.backend, 'session', None)
        bare_jid = getattr(self.backend, 'bare_jid', None)
        if session is None or bare_jid is None:
            return

        from .xmpp_commands import XmppCommandClient
        client = self._agent_command_client or XmppCommandClient(
            session, bare_jid)
        self._agent_command_client = client

        def on_error(message):
            self._on_llm_error(self.backend, message)

        def on_commands(commands):
            command = next((c for c in commands
                            if getattr(c, 'node', '') == 'model'), None)
            if command is None:
                on_error(_("This agent does not expose a model command."))
                return
            self._execute_agent_command(client, command)

        client.request_commands(on_commands, on_error)

    @staticmethod
    def _as_number(value):
        try:
            return float(str(value).replace(',', ''))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_agent_status(cls, status):
        text = str(status or "").strip()
        parsed = {'activity': text}
        if not text:
            return parsed
        json_text = text
        if json_text.startswith("nanoclaw:") or json_text.startswith("openclaw:"):
            json_text = json_text.split(":", 1)[1].strip()
        if json_text.startswith("{"):
            try:
                data = json.loads(json_text)
                if isinstance(data, dict):
                    return cls._normalize_agent_status_dict(data, fallback=text)
            except (TypeError, ValueError):
                pass
        parts = [part.strip() for part in re.split(r"\s*\|\s*", text) if part.strip()]
        if parts:
            parsed['activity'] = parts[0]
        for part in parts[1:]:
            cls._parse_agent_status_part(part, parsed)
        return parsed

    @classmethod
    def _normalize_agent_status_dict(cls, data, fallback=""):
        parsed = {'activity': data.get('activity') or data.get('state') or data.get('availability') or fallback}
        aliases = {
            'request': ('request', 'requests', 'requests_total', 'request_count'),
            'tokens': ('tokens', 'total_tokens', 'tokens_total'),
            'input_tokens': ('input_tokens', 'prompt_tokens', 'tokens_in'),
            'output_tokens': ('output_tokens', 'completion_tokens', 'tokens_out'),
            'cost': ('cost', 'usd', 'cost_usd'),
            'session_cost': ('session_cost', 'session_usd', 'session_cost_usd'),
            'day_cost': ('day_cost', 'today_cost', 'day_usd', 'daily_cost_usd'),
            'balance': ('balance', 'balance_usd', 'kilo_balance'),
            'availability': ('availability', 'presence'),
            'model': ('model', 'model_id'),
            'tool': ('tool', 'current_tool'),
            'bypass': ('bypass', 'approval_bypass'),
            'context_used': ('ctx_used', 'context_used'),
            'context_max': ('ctx_max', 'context_max', 'context_window'),
        }
        for key, names in aliases.items():
            for name in names:
                if data.get(name) is not None:
                    parsed[key] = data.get(name)
                    break
        return parsed

    @staticmethod
    def _parse_agent_status_part(part, parsed):
        match = re.match(r"^([A-Za-z _-]+)\s*[:=]\s*(.+)$", part)
        if not match:
            parsed.setdefault('notes', []).append(part)
            return
        key = match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        value = match.group(2).strip()
        aliases = {
            'req': 'request',
            'requests': 'request',
            'request': 'request',
            'tok': 'tokens',
            'tokens': 'tokens',
            'total_tokens': 'tokens',
            'in': 'input_tokens',
            'input': 'input_tokens',
            'input_tokens': 'input_tokens',
            'prompt_tokens': 'input_tokens',
            'out': 'output_tokens',
            'output': 'output_tokens',
            'output_tokens': 'output_tokens',
            'completion_tokens': 'output_tokens',
            'cost': 'cost',
            'usd': 'cost',
            'session_cost': 'session_cost',
            'session_usd': 'session_cost',
            'day_cost': 'day_cost',
            'today_cost': 'day_cost',
            'balance': 'balance',
            'balance_usd': 'balance',
            'kilo_balance': 'balance',
            'availability': 'availability',
            'model': 'model',
            'tool': 'tool',
            'current_tool': 'tool',
            'approval_bypass': 'bypass',
            'bypass': 'bypass',
            'ctx_used': 'context_used',
            'context_used': 'context_used',
            'ctx_max': 'context_max',
            'context_max': 'context_max',
        }
        parsed[aliases.get(key, key)] = value

    @classmethod
    def _format_agent_status_details(cls, parsed):
        details = []
        if parsed.get('tool'):
            details.append(_("Tool: ") + str(parsed['tool']))
        token_detail = cls._format_token_detail(parsed)
        if token_detail:
            details.append(token_detail)
        if parsed.get('request') not in (None, ""):
            details.append(_("Req: ") + str(parsed['request']))
        if parsed.get('cost') not in (None, ""):
            details.append(_("Cost: ") + cls._format_cost(parsed['cost']))
        if parsed.get('session_cost') not in (None, ""):
            details.append(_("Session: ") + cls._format_cost(parsed['session_cost']))
        if parsed.get('day_cost') not in (None, ""):
            details.append(_("Today: ") + cls._format_cost(parsed['day_cost']))
        if parsed.get('balance') not in (None, ""):
            details.append(_("Balance: ") + cls._format_cost(parsed['balance']))
        if parsed.get('model'):
            details.append(str(parsed['model']))
        for note in parsed.get('notes', [])[:2]:
            details.append(str(note))
        return " | ".join(details)

    @classmethod
    def _format_token_detail(cls, parsed):
        total = parsed.get('tokens')
        input_tokens = parsed.get('input_tokens')
        output_tokens = parsed.get('output_tokens')
        if total in (None, "") and input_tokens in (None, "") and output_tokens in (None, ""):
            return ""
        pieces = []
        if total not in (None, ""):
            pieces.append(_("tok ") + cls._format_count(total))
        if input_tokens not in (None, ""):
            pieces.append(_("in ") + cls._format_count(input_tokens))
        if output_tokens not in (None, ""):
            pieces.append(_("out ") + cls._format_count(output_tokens))
        return " ".join(pieces)

    @staticmethod
    def _format_count(value):
        try:
            number = int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            return str(value)
        if abs(number) >= 1_000_000:
            return f"{number / 1_000_000:.1f}M"
        if abs(number) >= 1_000:
            return f"{number / 1_000:.1f}k"
        return str(number)

    @staticmethod
    def _format_cost(value):
        try:
            number = float(str(value).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return str(value)
        return f"${number:.4f}" if number < 1 else f"${number:.2f}"

    @staticmethod
    def _friendly_agent_activity(activity):
        text = str(activity or "").strip()
        lower = text.lower()
        if lower in ("processing", "busy", "working"):
            return _("Analizando la solicitud…")
        if lower == "thinking" or lower.startswith("analizando"):
            return _("Analizando la solicitud…")
        if lower == "available":
            return _("Disponible")
        if lower in ("waiting", "queued"):
            return _("En espera")
        if lower in ("paused", "away", "xa"):
            return _("Ausente")
        if lower.startswith("tool:"):
            return _("Usando herramienta: ") + text.split(":", 1)[1].strip()
        return text

    @staticmethod
    def _as_number(value):
        try:
            return float(str(value).replace(',', ''))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_agent_status(cls, status):
        text = str(status or "").strip()
        parsed = {'activity': text}
        if not text:
            return parsed
        json_text = text
        if json_text.startswith("nanoclaw:") or json_text.startswith("openclaw:"):
            json_text = json_text.split(":", 1)[1].strip()
        if json_text.startswith("{"):
            try:
                data = json.loads(json_text)
                if isinstance(data, dict):
                    return cls._normalize_agent_status_dict(data, fallback=text)
            except (TypeError, ValueError):
                pass
        parts = [part.strip() for part in re.split(r"\s*\|\s*", text) if part.strip()]
        if parts:
            parsed['activity'] = parts[0]
        for part in parts[1:]:
            cls._parse_agent_status_part(part, parsed)
        return parsed

    @classmethod
    def _normalize_agent_status_dict(cls, data, fallback=""):
        parsed = {'activity': data.get('activity') or data.get('state') or data.get('availability') or fallback}
        aliases = {
            'request': ('request', 'requests', 'requests_total', 'request_count'),
            'tokens': ('tokens', 'total_tokens', 'tokens_total'),
            'input_tokens': ('input_tokens', 'prompt_tokens', 'tokens_in'),
            'output_tokens': ('output_tokens', 'completion_tokens', 'tokens_out'),
            'cost': ('cost', 'usd', 'cost_usd'),
            'session_cost': ('session_cost', 'session_usd', 'session_cost_usd'),
            'day_cost': ('day_cost', 'today_cost', 'day_usd', 'daily_cost_usd'),
            'balance': ('balance', 'balance_usd', 'kilo_balance'),
            'availability': ('availability', 'presence'),
            'model': ('model', 'model_id'),
            'tool': ('tool', 'current_tool'),
            'bypass': ('bypass', 'approval_bypass'),
            'context_used': ('ctx_used', 'context_used'),
            'context_max': ('ctx_max', 'context_max', 'context_window'),
        }
        for key, names in aliases.items():
            for name in names:
                if data.get(name) is not None:
                    parsed[key] = data.get(name)
                    break
        return parsed

    @staticmethod
    def _parse_agent_status_part(part, parsed):
        match = re.match(r"^([A-Za-z _-]+)\s*[:=]\s*(.+)$", part)
        if not match:
            parsed.setdefault('notes', []).append(part)
            return
        key = match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        value = match.group(2).strip()
        aliases = {
            'req': 'request',
            'requests': 'request',
            'request': 'request',
            'tok': 'tokens',
            'tokens': 'tokens',
            'total_tokens': 'tokens',
            'in': 'input_tokens',
            'input': 'input_tokens',
            'input_tokens': 'input_tokens',
            'prompt_tokens': 'input_tokens',
            'out': 'output_tokens',
            'output': 'output_tokens',
            'output_tokens': 'output_tokens',
            'completion_tokens': 'output_tokens',
            'cost': 'cost',
            'usd': 'cost',
            'session_cost': 'session_cost',
            'session_usd': 'session_cost',
            'day_cost': 'day_cost',
            'today_cost': 'day_cost',
            'balance': 'balance',
            'balance_usd': 'balance',
            'kilo_balance': 'balance',
            'availability': 'availability',
            'model': 'model',
            'tool': 'tool',
            'current_tool': 'tool',
            'approval_bypass': 'bypass',
            'bypass': 'bypass',
            'ctx_used': 'context_used',
            'context_used': 'context_used',
            'ctx_max': 'context_max',
            'context_max': 'context_max',
        }
        parsed[aliases.get(key, key)] = value

    @classmethod
    def _format_agent_status_details(cls, parsed):
        details = []
        if parsed.get('tool'):
            details.append(_("Tool: ") + str(parsed['tool']))
        token_detail = cls._format_token_detail(parsed)
        if token_detail:
            details.append(token_detail)
        if parsed.get('request') not in (None, ""):
            details.append(_("Req: ") + str(parsed['request']))
        if parsed.get('cost') not in (None, ""):
            details.append(_("Cost: ") + cls._format_cost(parsed['cost']))
        if parsed.get('session_cost') not in (None, ""):
            details.append(_("Session: ") + cls._format_cost(parsed['session_cost']))
        if parsed.get('day_cost') not in (None, ""):
            details.append(_("Today: ") + cls._format_cost(parsed['day_cost']))
        if parsed.get('balance') not in (None, ""):
            details.append(_("Balance: ") + cls._format_cost(parsed['balance']))
        if parsed.get('model'):
            details.append(str(parsed['model']))
        for note in parsed.get('notes', [])[:2]:
            details.append(str(note))
        return " | ".join(details)

    @classmethod
    def _format_token_detail(cls, parsed):
        total = parsed.get('tokens')
        input_tokens = parsed.get('input_tokens')
        output_tokens = parsed.get('output_tokens')
        if total in (None, "") and input_tokens in (None, "") and output_tokens in (None, ""):
            return ""
        pieces = []
        if total not in (None, ""):
            pieces.append(_("tok ") + cls._format_count(total))
        if input_tokens not in (None, ""):
            pieces.append(_("in ") + cls._format_count(input_tokens))
        if output_tokens not in (None, ""):
            pieces.append(_("out ") + cls._format_count(output_tokens))
        return " ".join(pieces)

    @staticmethod
    def _format_count(value):
        try:
            number = int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            return str(value)
        if abs(number) >= 1_000_000:
            return f"{number / 1_000_000:.1f}M"
        if abs(number) >= 1_000:
            return f"{number / 1_000:.1f}k"
        return str(number)

    @staticmethod
    def _format_cost(value):
        try:
            number = float(str(value).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return str(value)
        return f"${number:.4f}" if number < 1 else f"${number:.2f}"

    @staticmethod
    def _friendly_agent_activity(activity):
        text = str(activity or "").strip()
        lower = text.lower()
        if lower in ("processing", "busy", "working"):
            return _("Trabajando")
        if lower == "available":
            return _("Disponible")
        if lower in ("waiting", "queued"):
            return _("En espera")
        if lower in ("paused", "away", "xa"):
            return _("Ausente")
        if lower.startswith("tool:"):
            return _("Usando herramienta: ") + text.split(":", 1)[1].strip()
        return text

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
        # Sin encabezado: el usuario acaba de elegir el comando del menú, así
        # que repetir su nombre sobre la respuesta no aporta nada.
        from .xmpp_commands import command_result_body
        body = command_result_body(command)
        if self._approval_transport_toast(body):
            self._show_toast(self._approval_transport_toast(body))
            return
        self._show_tool_output(body)
        self.display_message(self._tool_activity_history_text(body), sender="assistant")

    def _on_backend_ready(self, backend, display_name):
        """Maneja la señal 'ready' del backend (modelo cargado / sesión lista)."""
        debug_print(f"Backend listo: {display_name}")

        if self.is_messaging_backend:
            self._update_xmpp_title_status()
            self._load_xmpp_history()
            return

        # Backend LLM: el modelo activo lo anuncia 'ready'; con un agente llega
        # por presencia (_update_agent_state_chips).
        self._update_model_badge(display_name)
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
            self._xmpp_history_latest_incoming = None
            self._xmpp_history_tool_candidate = None
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

    # Los batches son None mientras no hay una carga de historial en curso. Un
    # evento que llegue fuera de una (una sesión anterior que aún no se había
    # callado) se ignora en vez de reventar sobre un None.

    def _on_xmpp_history_message(self, backend, body, direction, timestamp):
        if self._xmpp_history_batch is None:
            return
        if direction == 'in':
            self._xmpp_history_latest_incoming = timestamp
            if self._is_progress_snapshot(body) or self._is_tool_activity_message(body):
                self._xmpp_history_tool_candidate = (body, timestamp)
        # Un toast sólo tiene sentido cuando el acuse llega en vivo. Al
        # restaurar MAM/cache se omiten estos estados efímeros por completo.
        if (self._approval_transport_toast(body) or
                self._is_progress_snapshot(body) or
                self._is_approval_transport_noise(body)):
            return
        shown_body = (self._tool_activity_history_text(body)
                      if self._is_tool_activity_message(body) else body)
        self._xmpp_history_batch.append((shown_body, direction, timestamp))

    def _on_xmpp_history_actions(self, backend, body, timestamp,
                                 quick_responses, commands, request_id=None):
        if self._xmpp_history_actions_batch is None:
            return
        self._xmpp_history_actions_batch.append(
            (body, timestamp, quick_responses, commands, request_id))

    def _on_xmpp_history_complete(self, backend, has_more):
        batch = self._xmpp_history_batch or []
        action_batch = self._xmpp_history_actions_batch or []
        approval_message_keys = {
            (Message.compact_blank_lines(body), timestamp)
            for body, timestamp, quick, commands, _request_id in action_batch
            if self._actions_look_like_approval(
                list(quick or []) + list(commands or []))
        }
        is_backfill = self._xmpp_backfill_remaining > 0
        if batch:
            # El lote se pinta por timestamp, no por su procedencia: de dónde
            # venga (carga inicial, backfill, scroll hacia arriba) no dice nada
            # sobre si es más nuevo o más viejo que lo que ya hay en pantalla.
            for body, direction, timestamp in batch:
                if (direction == 'in' and
                        (Message.compact_blank_lines(body), timestamp)
                        in approval_message_keys):
                    continue
                self._add_history_bubble(body, direction, timestamp)
            self._history_displayed = True
        for body, timestamp, quick_responses, commands, request_id in action_batch:
            self._restore_history_actions(
                body, timestamp, quick_responses, commands, request_id)
        candidate = self._xmpp_history_tool_candidate
        if (candidate is not None and
                candidate[1] == self._xmpp_history_latest_incoming):
            self._restored_active_tool_panel = True
            self._show_tool_output(candidate[0])
        if is_backfill:
            self._xmpp_backfill_remaining -= 1
        self._xmpp_history_batch = []
        self._xmpp_history_actions_batch = []
        # Bajar al fondo SIEMPRE que se hayan pintado mensajes, no sólo en el
        # backfill. La carga inicial también deja la ventana llena de burbujas
        # nuevas, y antes se quedaba donde estuviera: el usuario abría el chat y
        # no veía lo último. `load_more_history` (scroll hacia arriba) es el
        # único caso que NO debe saltar — y ése no pasa por aquí con batch,
        # porque el usuario está leyendo hacia atrás a propósito.
        if batch and not self._loading_older_history:
            self._scroll_to_bottom_after_layout()
        # Se consume aquí: si se quedara puesto, el siguiente mensaje que llegue
        # tampoco bajaría y el chat volvería a "no seguir el fondo".
        self._loading_older_history = False

    # Edad máxima para restaurar una tarjeta de acción pendiente que NO trae
    # expires_at_ms explícito. El registro de comandos del servidor caduca a
    # los 15 min (command-node-registry DEFAULT_TTL_MS), así que una tarjeta
    # más vieja ya está muerta en el servidor —presionarla no haría nada— y no
    # debe re-renderizarse al reabrir el cliente. Las que sí traen expires_at_ms
    # se filtran por ese valor exacto en _filter_unexpired_actions.
    _PENDING_ACTION_MAX_AGE_MS = 15 * 60 * 1000
    # OpenClaw mantiene waitDecision abierto durante 30 minutos. Si un gateway
    # viejo omite expires-at-ms, el cliente debe conservar la única superficie
    # desde la que el usuario puede resolverla durante ese mismo intervalo.
    # Un fallback más corto sólo oculta la card: NO cancela el pending del
    # gateway y deja la sesión bloqueada con “approval already pending”.
    _APPROVAL_ACTION_FALLBACK_MAX_AGE_MS = 30 * 60 * 1000
    # Cuánto se espera el IQ result de una decisión antes de rehabilitar la
    # card. No es un timeout de la aprobación (esa la gobierna el gateway, y
    # acortarla del lado del cliente es justo el error documentado arriba):
    # sólo cubre el caso de que la respuesta al IQ no llegue nunca, que dejaba
    # la card en “Enviada…” de forma permanente. Generoso a propósito, para no
    # rehabilitar una decisión que en realidad sí viajó.
    _APPROVAL_IQ_TIMEOUT_SECONDS = 30

    def _restore_history_actions(self, body, timestamp, quick_responses,
                                 commands, request_id=None):
        if request_id and request_id in self._rendered_response_request_ids:
            return
        quick_responses = self._filter_unexpired_actions(quick_responses)
        commands = self._filter_unexpired_actions(commands)
        # Descartar tarjetas viejas sin expiry explícito (ya caducadas en el
        # servidor). Solo aplica a las que quedaron sin expires_at_ms tras el
        # filtro anterior.
        if (quick_responses or commands) and self._pending_actions_are_stale(
                timestamp, quick_responses, commands, body):
            return
        if quick_responses and not self._history_quick_response_was_answered(
                timestamp, quick_responses):
            detail = self._action_panel_detail(body, quick_responses)
            self._add_sticky_response_card(
                quick_responses,
                lambda response: self._send_restored_quick_response(response),
                detail_text=detail,
                request_id=request_id)
        if commands and not quick_responses:
            detail = self._action_panel_detail(body, commands)
            self._add_sticky_response_card(
                commands,
                lambda command: self._execute_inline_command(command),
                detail_text=detail,
                request_id=request_id)

    def _pending_actions_are_stale(self, timestamp, quick_responses, commands,
                                   body=None):
        """True si la tarjeta pendiente es demasiado vieja para restaurar.

        Solo se considera vieja cuando NINGUNA de sus acciones trae un
        expires_at_ms explícito (esas ya se filtran por su propio valor) y el
        timestamp del mensaje supera _PENDING_ACTION_MAX_AGE_MS. Si no se puede
        parsear el timestamp, no se descarta (conservador)."""
        has_explicit_expiry = any(
            self._action_remaining_ms(a) is not None
            for a in list(quick_responses or []) + list(commands or [])
        )
        if has_explicit_expiry:
            return False
        request_dt = self._parse_history_ts(timestamp)
        if request_dt is None:
            return False
        age_ms = int(time.time() * 1000) - int(request_dt.timestamp() * 1000)
        max_age_ms = self._PENDING_ACTION_MAX_AGE_MS
        all_actions = list(quick_responses or []) + list(commands or [])
        if (self._actions_look_like_approval(all_actions)
                or self._body_looks_like_approval(body)):
            max_age_ms = self._APPROVAL_ACTION_FALLBACK_MAX_AGE_MS
        return age_ms > max_age_ms

    @staticmethod
    def _actions_look_like_approval(actions):
        labels = {
            str(action.get('label') or action.get('name') or '').strip().lower()
            for action in actions or []
            if isinstance(action, dict)
        }
        nodes = [
            str(action.get('node') or '').lower()
            for action in actions or []
            if isinstance(action, dict)
        ]
        approval_words = ('allow', 'approve', 'deny', 'reject', 'permitir',
                          'aprobar', 'denegar', 'rechazar')
        if any(any(word in label for word in approval_words)
               for label in labels):
            return True
        return any('approve' in node or 'approval' in node for node in nodes)

    @staticmethod
    def _body_looks_like_approval(body):
        text = str(body or '').lower()
        return ('approval' in text or 'aprobación' in text
                or 'aprobacion' in text or 'pending command' in text)

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
            self.display_message(label, sender="user")
            GLib.idle_add(self._scroll_to_bottom, False)
            self.backend.send_quick_response(value, label)

    @staticmethod
    def _action_remaining_ms(action):
        raw = action.get('expires_at_ms') if isinstance(action, dict) else None
        if raw in (None, ""):
            return None
        try:
            expires_at_ms = int(raw)
        except (TypeError, ValueError):
            return None
        return expires_at_ms - int(time.time() * 1000)

    @classmethod
    def _filter_unexpired_actions(cls, actions):
        filtered = []
        for action in actions or []:
            if cls._action_is_expired(action):
                continue
            filtered.append(action)
        return filtered

    @classmethod
    def _action_is_expired(cls, action):
        remaining = cls._action_remaining_ms(action)
        return remaining is not None and remaining <= 0

    def _expire_quick_responses_from_actions(self, widget, actions,
                                             approval=False):
        expiries = [
            remaining for remaining in (
                self._action_remaining_ms(action) for action in (actions or [])
            )
            if remaining is not None
        ]
        if not expiries and (approval or self._actions_look_like_approval(actions)):
            expiries = [self._APPROVAL_ACTION_FALLBACK_MAX_AGE_MS]
        if not expiries:
            return
        remaining_ms = min(expiries)
        if remaining_ms <= 0:
            widget.hide_quick_responses()
            return

        def expire_if_same_widget():
            if widget.get_parent() is not None:
                widget.hide_quick_responses()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(max(1000, remaining_ms), expire_if_same_widget)

    def _expire_sticky_response_item_from_actions(self, item_id, actions,
                                                   approval=False,
                                                   request_id=None):
        expiries = [
            remaining for remaining in (
                self._action_remaining_ms(action) for action in (actions or [])
            )
            if remaining is not None
        ]
        if not expiries and (approval or self._actions_look_like_approval(actions)):
            expiries = [self._APPROVAL_ACTION_FALLBACK_MAX_AGE_MS]
        if not expiries:
            return
        remaining_ms = min(expiries)
        if remaining_ms <= 0:
            self._remove_sticky_response_item(item_id)
            return

        def expire_if_still_pending():
            self._remove_sticky_response_item(item_id)
            if request_id and hasattr(self.backend, 'expire_pending_actions'):
                self.backend.expire_pending_actions(request_id)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(max(1000, remaining_ms), expire_if_still_pending)

    def _insert_bubble_by_timestamp(self, widget):
        """Inserta la burbuja en su sitio CRONOLÓGICO, no al final.

        Antes cada camino decidía la posición por su procedencia: la carga
        inicial hacía prepend, el backfill y los mensajes en vivo hacían append.
        Eso presupone que todo lote de backfill es más nuevo que lo ya pintado, y
        no lo es: el catch-up de MAM pide un solape hacia atrás (_overlap_timestamp,
        una semana), así que al reconectar se anexaban abajo mensajes de días
        atrás. El scroll sí llegaba al fondo — pero el fondo ya no era el mensaje
        más reciente.

        Se recorre desde el final porque el caso normal, con diferencia, es el
        mensaje que va justo al final: así es O(1) en vivo y sólo se paga el
        recorrido cuando de verdad llega algo fuera de orden.
        """
        ts = self._comparable_ts(widget.message.timestamp)

        # NO se silencia el adjustment aquí. La tentación es marcar la inserción
        # como "movimiento propio" (_restoring_scroll) para que el reajuste que
        # hace GTK no se lea como que el usuario se movió — pero eso silencia
        # también _on_vadj_value_changed, que es justo donde vive la lógica que
        # vuelve a bajar cuando el contenido CRECE. Silenciarlo se come el
        # autoscroll: la burbuja se inserta y no se ve.
        #
        # No hace falta: _on_vadj_value_changed ya distingue las dos cosas por su
        # cuenta (si el `upper` creció, no fue el usuario).
        for child in reversed(list(self.messages_box)):
            child_ts = self._comparable_ts(
                getattr(getattr(child, 'message', None), 'timestamp', None))
            # Un hijo sin timestamp (un ErrorWidget, algo que no es
            # MessageWidget) no es un ancla fiable: se salta.
            if child_ts is None:
                continue
            if child_ts <= ts:
                # El primer hijo no más nuevo que nosotros: vamos detrás.
                self.messages_box.insert_child_after(widget, child)
                self._content_added_pending = True
                GLib.idle_add(lambda: setattr(self, '_content_added_pending', False)
                              or GLib.SOURCE_REMOVE)
                if DEBUG:
                    debug_print(
                        f"[insert] after-ts ts={ts} child_ts={child_ts} "
                        f"children={len(list(self.messages_box))}")
                return
        # Más viejo que todo lo pintado (o el contenedor está vacío).
        self.messages_box.prepend(widget)

        self._content_added_pending = True
        GLib.idle_add(lambda: setattr(self, '_content_added_pending', False)
                      or GLib.SOURCE_REMOVE)
        if DEBUG:
            debug_print(
                f"[insert] prepend-ts ts={ts} children={len(list(self.messages_box))}")

    @staticmethod
    def _comparable_ts(dt):
        """Un datetime que se pueda comparar con cualquier otro de la lista.

        Los del historial vienen de MAM en UTC y _parse_history_ts los pasa a
        local con astimezone(), así que son AWARE. Los de un mensaje en vivo los
        pone Message.__init__ con datetime.now(), que es NAIVE. Compararlos
        lanza "can't compare offset-naive and offset-aware datetimes" — y como
        eso ocurría dentro de display_message, la excepción se llevaba por
        delante la burbuja: los mensajes propios no aparecían en la ventana.

        Un naive aquí siempre es hora local (lo pone datetime.now()), así que se
        le asigna la zona local en vez de descartarlo.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.astimezone()
        return dt

    def _history_bubble_key(self, body, direction, timestamp):
        """Identidad de un mensaje del historial, para no repintarlo.

        MAM no da un id estable entre la caché local y el archivo del servidor,
        así que la identidad se compone de lo que sí es estable: quién, qué y
        cuándo. El solape de una semana del catch-up reenvía mensajes que ya
        están en pantalla; sin esto se pintaban otra vez tras cada reconexión
        (el comentario de _overlap_timestamp prometía una deduplicación que en
        realidad no existía en ninguna parte).
        """
        dt = self._parse_history_ts(timestamp)
        return (direction, Message.compact_blank_lines(body),
                dt.isoformat() if dt is not None else None)

    def _add_history_bubble(self, body, direction, timestamp):
        """Pinta un mensaje del historial en su sitio, si no estaba ya."""
        key = self._history_bubble_key(body, direction, timestamp)
        # Una clave sin fecha no identifica nada (dos mensajes iguales sin
        # timestamp colisionarían), así que ésas no se deduplican.
        if key[2] is not None:
            if key in self._history_keys:
                return
            self._history_keys.add(key)

        sender = "user" if direction == 'out' else "assistant"
        if self._has_recent_matching_bubble(body, sender, timestamp):
            return
        msg = Message(body, sender, timestamp=self._parse_history_ts(timestamp))
        self._insert_bubble_by_timestamp(MessageWidget(msg))

    def _has_recent_matching_bubble(self, body, sender, timestamp,
                                    window_seconds=60):
        target_dt = self._parse_history_ts(timestamp)
        if target_dt is None:
            return False
        normalized_body = Message.compact_blank_lines(body)
        for child in list(self.messages_box):
            message = getattr(child, 'message', None)
            if message is None or message.sender != sender:
                continue
            if Message.compact_blank_lines(message.content) != normalized_body:
                continue
            child_dt = self._comparable_ts(message.timestamp)
            if child_dt is None:
                continue
            if abs((target_dt - child_dt).total_seconds()) <= window_seconds:
                return True
        return False

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
        if pos != Gtk.PositionType.TOP or self.backend is None:
            return
        # Ignorar el edge-reached de la carga inicial / backfill: el scroll
        # nace arriba (value=0) antes del salto al fondo, y eso disparaba un
        # load_more_history — con su eventual query MAM hacia atrás — en cada
        # apertura de ventana, sin que el usuario hubiera scrolleado nada.
        if (getattr(self, '_xmpp_backfill_remaining', 0) > 0
                or not self._history_displayed):
            return
        # El usuario subió a leer hacia atrás: el lote que llegue NO debe
        # saltar al fondo (ver _on_xmpp_history_complete).
        self._loading_older_history = True
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
            self._scroll_to_bottom_after_layout()
            
            return False  # Ejecutar solo una vez
        except Exception as e:
            debug_print(f"Error al cargar historial: {e}")
            import traceback
            debug_print(traceback.format_exc())
            return False  # Ejecutar solo una vez

    def _on_attach_clicked(self, _button):
        """Elige un archivo y lo manda como adjunto (XEP-0363 + OOB)."""
        if not hasattr(self.backend, 'send_file'):
            return
        dialog = Gtk.FileDialog()
        dialog.set_title(_("Attach a file"))

        # OJO: PyGObject invoca el AsyncReadyCallback con TRES argumentos
        # (source_object, result, user_data). Con dos, la llamada revienta con
        # un TypeError que el bucle de GLib se traga -> el diálogo se cierra y
        # "no pasa nada". El tercero es obligatorio aunque no se use.
        def on_open(dlg, result, _user_data=None):
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error as exc:
                # DISMISSED = el usuario canceló: no es un error que mostrar.
                if not exc.matches(Gtk.dialog_error_quark(),
                                   Gtk.DialogError.DISMISSED):
                    debug_print(f"[attach] open_finish falló: {exc}")
                    self._on_llm_error(
                        self.backend, _("Could not open the file: %s") % exc.message)
                return
            except Exception as exc:  # noqa: BLE001 - no dejarlo pasar en silencio
                debug_print(f"[attach] error inesperado: {exc}")
                self._on_llm_error(self.backend, str(exc))
                return
            if gfile is None:
                return
            path = gfile.get_path()
            if not path:
                self._on_llm_error(
                    self.backend, _("Could not read the selected file"))
                return
            debug_print(f"[attach] enviando {path}")
            # La subida es asíncrona: el backend avisa por 'finished'/'error'.
            try:
                self.backend.send_file(path)
            except Exception as exc:  # noqa: BLE001
                debug_print(f"[attach] send_file falló: {exc}")
                self._on_llm_error(self.backend, str(exc))

        dialog.open(self, None, on_open)

    def _on_send_clicked(self, button):
        buffer = self.input_text.get_buffer()
        text = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        )

        if text:
            if DEBUG:
                debug_print(f"[send] click text_len={len(text)}")
            # Ya se envía el mensaje: cancelar el aviso pendiente de 'composing'
            if self._composing_timeout_id:
                GLib.source_remove(self._composing_timeout_id)
                self._composing_timeout_id = None
                if DEBUG:
                    debug_print("[send] composing timeout cancelled")
            # El mensaje local debe verse al instante: limpiar el input sin
            # notificar composing aquí evita trabajo de red en este mismo tick.
            self._clear_input_buffer_silently()
            # Display user message
            own_widget = self.display_message(text, sender="user")
            if self.is_messaging_backend:
                own_widget.set_delivery_state('pending')
                self._pending_delivery_widgets.setdefault(text, []).append(own_widget)
                # XMPP: no bloquear la UI ni cambiar al estado busy; hacerlo
                # aquí añade relayout extra y retrasa el primer frame del
                # mensaje propio.
                # Backends de mensajería (XMPP): no hay una respuesta que
                # rellenar; los mensajes entrantes crean su propia burbuja
                # cuando llegan (_on_llm_response). No dejar un placeholder.
                self.current_message_widget = None
                # Enviar tras el próximo frame pintado (sin latencia fija):
                # prioriza que el bubble local se vea instantáneo.
                self._schedule_messaging_send_after_frame(text)
            else:
                # LLM: mantener estado busy durante generación.
                self.set_enabled(False)
                # LLM: crear ya la burbuja de respuesta que el stream irá
                # rellenando vía 'response'.
                self.current_message_widget = self.display_message("", sender="assistant")
                self._on_llm_response(self.backend, "")
                # LLM: enviar en idle de baja prioridad.
                GLib.idle_add(
                    self._start_llm_task,
                    text,
                    priority=GLib.PRIORITY_LOW,
                )

    def _cancel_pending_messaging_send(self):
        if self._pending_messaging_send_timeout_id is not None:
            GLib.source_remove(self._pending_messaging_send_timeout_id)
            self._pending_messaging_send_timeout_id = None
        if self._pending_messaging_send_tick_id is not None:
            self.remove_tick_callback(self._pending_messaging_send_tick_id)
            self._pending_messaging_send_tick_id = None
        self._pending_messaging_send_text = None
        self._pending_messaging_send_ticks_left = 0

    def _schedule_messaging_send_after_frame(self, text):
        self._pending_messaging_send_text = text
        # Dos ticks: el primero deja que se componga y pinte la burbuja local,
        # el segundo dispara el envío sin depender de un delay fijo en ms.
        self._pending_messaging_send_ticks_left = 2

        if self._pending_messaging_send_tick_id is None:
            self._pending_messaging_send_tick_id = self.add_tick_callback(
                self._on_pending_messaging_send_tick)

        # Fallback: si no hay frame próximo (ventana oculta), no bloquear envío.
        if self._pending_messaging_send_timeout_id is not None:
            GLib.source_remove(self._pending_messaging_send_timeout_id)
        self._pending_messaging_send_timeout_id = GLib.timeout_add(
            60, self._flush_pending_messaging_send)

    def _on_pending_messaging_send_tick(self, _widget, _frame_clock):
        if not self._pending_messaging_send_text:
            self._pending_messaging_send_tick_id = None
            return GLib.SOURCE_REMOVE

        if self._pending_messaging_send_ticks_left > 0:
            self._pending_messaging_send_ticks_left -= 1
            if DEBUG:
                debug_print(
                    f"[send] pending send tick, remaining={self._pending_messaging_send_ticks_left}")
            return GLib.SOURCE_CONTINUE

        self._flush_pending_messaging_send()
        return GLib.SOURCE_REMOVE

    def _flush_pending_messaging_send(self):
        text = self._pending_messaging_send_text
        if self._pending_messaging_send_tick_id is not None:
            self.remove_tick_callback(self._pending_messaging_send_tick_id)
            self._pending_messaging_send_tick_id = None
        if self._pending_messaging_send_timeout_id is not None:
            GLib.source_remove(self._pending_messaging_send_timeout_id)
            self._pending_messaging_send_timeout_id = None
        self._pending_messaging_send_text = None
        self._pending_messaging_send_ticks_left = 0

        if not text:
            return GLib.SOURCE_REMOVE

        if DEBUG:
            debug_print(f"[send] flush backend send len={len(text)}")
        # XMPP's send_text starts its encryption worker immediately. Calling
        # it here avoids a low-priority idle callback starving behind GTK
        # redraw/layout work, which left the bubble stuck at Sending….
        self._start_llm_task(text)
        return GLib.SOURCE_REMOVE

    def _start_llm_task(self, prompt_text):
        """Inicia la tarea del backend con el prompt dado."""
        started = time.monotonic()
        if DEBUG:
            debug_print(f"[send] start backend send len={len(str(prompt_text or ''))}")
        # Enviar el prompt usando el ChatBackend
        self.backend.send_message(prompt_text)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if DEBUG:
            debug_print(f"[send] backend send returned in {elapsed_ms:.1f}ms")

        # Devolver False para que idle_add no se repita
        return GLib.SOURCE_REMOVE

    def _on_llm_error(self, llm_client, message):
        """Muestra un mensaje de error en el chat"""
        debug_print(message, file=sys.stderr)
        if self.is_messaging_backend:
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
                    # La conversación LLM acaba de nacer y ya tiene cid: pasa a
                    # registrarse con su clave definitiva (spec 009).
                    llm_key = f"llm:{conversation_id}"
                    for key, win in list(app._window_by_cid.items()):
                        if win is self and key != llm_key:
                            del app._window_by_cid[key]
                    app._window_by_cid[llm_key] = self

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
        if self.is_messaging_backend:
            def apply_response_on_ui_thread():
                self.accumulated_response = ""
                toast = self._approval_transport_toast(response)
                if toast:
                    self._show_toast(toast)
                    return GLib.SOURCE_REMOVE
                if self._is_approval_transport_noise(response):
                    return GLib.SOURCE_REMOVE
                if self._is_context_unavailable_response(response):
                    self.current_message_widget = None
                    self._display_context_unavailable(response)
                else:
                    self.current_message_widget = self.display_message(
                        response, sender="assistant")
                return GLib.SOURCE_REMOVE

            GLib.idle_add(
                apply_response_on_ui_thread,
                priority=GLib.PRIORITY_HIGH_IDLE,
            )
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
                    # La conversación LLM acaba de nacer y ya tiene cid: pasa a
                    # registrarse con su clave definitiva (spec 009).
                    llm_key = f"llm:{conversation_id}"
                    for key, win in list(app._window_by_cid.items()):
                        if win is self and key != llm_key:
                            del app._window_by_cid[key]
                    app._window_by_cid[llm_key] = self

        self.accumulated_response += response
        GLib.idle_add(self.current_message_widget.update_content,
                      self.accumulated_response)
        self._scroll_to_bottom_after_layout_if_following()

    def _on_response_message(self, _backend, request_id, body, timestamp=''):
        """Mensaje discreto XMPP con identidad estable para correcciones."""
        ts = self._parse_history_ts(timestamp) if timestamp else None
        toast = self._approval_transport_toast(body)
        if toast:
            # Los acuses exitosos pueden llegar como un stanza nuevo, no como
            # corrección XEP-0308 del request original. En ese caso no existe
            # un request_id correlacionable, pero la decisión igualmente hace
            # que toda approval visible deje de ser accionable.
            if not re.search(r'(?i)failed|already pending', str(body or '')):
                if self._drop_sticky_approval_items():
                    self._rebuild_sticky_response_box()
            self._show_toast(toast)
            return
        if self._is_approval_transport_noise(body):
            return
        if self._is_progress_snapshot(body):
            widget = self.display_message(body, sender='assistant', timestamp=ts)
            widget.set_streaming(True)
            self.current_message_widget = widget
            if request_id:
                self._message_widgets_by_id[request_id] = widget
            return
        if self._is_tool_activity_message(body):
            widget = self.display_message(body, sender="assistant", timestamp=ts)
            widget.set_streaming(True)
            self.current_message_widget = widget
            if request_id:
                self._message_widgets_by_id[request_id] = widget
            return
        if request_id and self._body_looks_like_approval(body):
            self._pending_action_bodies[request_id] = body
            return
        if self._drop_sticky_approval_items():
            self._rebuild_sticky_response_box()
        self._restored_active_tool_panel = False
        if self._is_context_unavailable_response(body):
            self.current_message_widget = None
            self._display_context_unavailable(body)
            return
        widget = self.display_message(body, sender='assistant', timestamp=ts)
        self.current_message_widget = widget
        if request_id:
            self._message_widgets_by_id[request_id] = widget

    @staticmethod
    def _is_progress_seed(response):
        text = " ".join(str(response or "").strip().split())
        return bool(re.fullmatch(
            r'(?i)Recibido\s*[·.-]\s*preparando…?', text))

    @classmethod
    def _is_progress_snapshot(cls, response):
        """Seed solo o draft de tools que todavía termina en el seed.

        OpenClaw compone las líneas parciales encima de ese marcador. Esos
        drafts son una vista mutable del turno, nunca mensajes terminados.
        """
        text = str(response or '').strip()
        if cls._is_progress_seed(text):
            return True
        return bool(re.search(
            r'(?i)(?:^|\n)Recibido\s*[·.-]\s*preparando…?\s*$', text))

    @staticmethod
    def _is_tool_activity_message(response):
        return bool(re.match(
            r'^\s*(?:⚠️?|✅|❌)?\s*'
            r'(?:🔧|🛠️?|Tool(?:\s|:)|Using tool|Herramienta:|Exec failed:)',
            str(response or ''), re.IGNORECASE))

    def _show_tool_output(self, body):
        self.tool_output_label.set_label(Message.compact_blank_lines(body))
        self.tool_output_panel.set_visible(True)

    @staticmethod
    def _tool_activity_history_text(body, max_chars=280):
        """Compact, stable chat record for a tool/command panel update."""
        text = Message.compact_blank_lines(body).strip()
        first = next((line.strip() for line in text.splitlines()
                      if line.strip()), _("Tool command"))
        if len(first) > max_chars:
            first = first[:max_chars].rstrip() + "…"
        return first

    @classmethod
    def _progress_history_text(cls, body):
        """One stable chat line for a mutable progress/tool stanza."""
        lines = [line.strip() for line in str(body or '').splitlines()
                 if line.strip() and not cls._is_progress_seed(line)]
        if not lines:
            return ""
        return cls._tool_activity_history_text("\n".join(lines))

    def _approval_toast_text(self, command, request_id=None):
        decision = str(command.get('name', '')).lower()
        headline = _("🚫 Denied") if 'deny' in decision else _("✅ Approved")
        detail = ""
        for item in self._sticky_response_items:
            if item.get('request_id') == request_id:
                detail = Message.compact_blank_lines(item.get('detail_text', ''))
                break
        command_line = detail.splitlines()[0].strip() if detail else ""
        return f"{headline}\n{command_line}" if command_line else headline

    @staticmethod
    def _approval_transport_toast(response):
        """Return a concise toast for approval/XEP-0050 acknowledgements."""
        text = " ".join(str(response or "").strip().split())
        if not text:
            return None
        if re.fullmatch(r'(?i)Command (?:submitted|expired)\.?', text):
            return _("✅ Approved") if 'submitted' in text.lower() else _("⌛ Approval expired")
        if re.match(
                r'(?i)^✅\s*Approval\s+(?:allow-once|allow-always|deny)\s+submitted\b',
                text):
            return _("🚫 Denied") if re.search(r'(?i)\bdeny\b', text) else _("✅ Approved")
        if re.match(r'(?i)^✅\s*aprobado\s*[—-]', text):
            return _("✅ Approved")
        if re.match(r'(?i)^❌?\s*Failed to submit approval\b', text):
            return _("❌ Approval failed")
        if re.search(r'(?i)\bapproval already pending for session\b', text):
            return _("⚠️ Approval already pending")
        return None

    def _show_toast(self, text):
        now = time.monotonic()
        signature = (str(text), now)
        previous = self._last_toast_signature
        if previous and previous[0] == signature[0] and now - previous[1] < 2.0:
            return
        self._last_toast_signature = signature
        debug_print(f"[toast] {text}")
        toast = Adw.Toast(title=str(text))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    @staticmethod
    def _is_approval_transport_noise(response):
        """Hide protocol acknowledgements already represented by the card.

        OpenClaw may emit these as independent chat messages around the XEP-0050
        correction. They are useful in logs, but rendering each one makes a
        single approval look like several conversational turns.
        """
        text = " ".join(str(response or "").strip().split())
        if not text:
            return False
        if re.fullmatch(r'(?i)Command submitted\.?', text):
            return True
        # "Recibido · preparando…" is the seed of the single XEP-0308
        # progress bubble. It must remain visible: subsequent tool/partial
        # corrections target that stanza and update this widget in place.
        if re.fullmatch(r'(?i)Turno completado sin respuesta visible\.?', text):
            return True
        if re.match(r'(?i)^✅\s*Approval\s+(?:allow-once|allow-always|deny)\s+submitted\b', text):
            return True
        if re.match(r'(?i)^✅\s*aprobado\s*[—-]', text):
            return True
        # Some agent wrappers echo the command and “approval requested” before
        # the actual interactive stanza. The card already contains both.
        if 'Command approval requested' in text and 'Approval:' in text:
            return True
        if re.search(r'```\s*```', text) and '🔒' not in text:
            return True
        return False

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

    def _on_llm_response_correction(self, backend, request_id, body):
        """XEP-0308 correction: actualiza el texto de la pregunta original
        (localizada por request_id, no necesariamente la burbuja más
        reciente — con varias preguntas abiertas a la vez, antes esto sólo
        tocaba current_message_widget) y atenúa su card de botones si
        seguía visible. Una corrección sin widget correlacionado se ignora:
        nunca debe sobrescribir la burbuja más reciente por aproximación."""
        if request_id in self._tool_output_request_ids:
            if (self._is_progress_snapshot(body) or
                    self._is_tool_activity_message(body)):
                self._show_tool_output(body)
                history_text = self._progress_history_text(body)
                if (history_text and
                        request_id not in self._tool_history_request_ids):
                    self._tool_history_request_ids.add(request_id)
                    self.display_message(history_text, sender='assistant')
            else:
                self._tool_output_request_ids.discard(request_id)
                self._tool_history_request_ids.discard(request_id)
                self._restored_active_tool_panel = False
                self.tool_output_panel.set_visible(False)
                widget = self.display_message(body, sender='assistant')
                self.current_message_widget = widget
                self._message_widgets_by_id[request_id] = widget
            return
        resolved_a_card = self._mark_sticky_response_resolved(
            request_id, resolution_text=body)
        toast = self._approval_transport_toast(body)
        if toast:
            def show_transport_toast():
                # The corrected stanza is the ephemeral progress seed. Once
                # the command expires/fails it must disappear, leaving one
                # toast instead of becoming another permanent chat bubble.
                widget = self._message_widgets_by_id.get(request_id)
                if widget is not None and widget.get_parent() == self.messages_box:
                    self.messages_box.remove(widget)
                self._message_widgets_by_id.pop(request_id, None)
                if widget is self.current_message_widget:
                    self.current_message_widget = None
                if request_id not in self._approval_toast_request_ids:
                    self._show_toast(toast)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(show_transport_toast,
                          priority=GLib.PRIORITY_HIGH_IDLE)
            return
        # The command handler's immediate acknowledgement is transport
        # metadata, not a second question. Showing “Approval allow-once
        # submitted for <uuid>” in the former approval bubble made it look as
        # if the user now had to approve “allow-once” itself.
        if re.search(r'(?i)\bApproval\s+(?:allow-once|allow-always|deny)\s+submitted\b',
                     str(body or '')):
            body = _("Approved; running…")
        widget = self._message_widgets_by_id.get(request_id)
        if widget is None:
            debug_print(
                f"chat_window: corrección ignorada sin burbuja correlacionada "
                f"(request_id={request_id!r})")
            return
        if self._at_bottom(self.message_scroll.get_vadjustment()):
            self._stick_to_bottom = True
        widget.set_streaming(True)
        old_timeout = self._streaming_finalize_timeout_ids.pop(
            request_id, None)
        if old_timeout:
            GLib.source_remove(old_timeout)
        self._streaming_finalize_timeout_ids[request_id] = GLib.timeout_add(
            2500, self._finalize_streaming_widget, request_id, widget)
        GLib.idle_add(widget.update_content, body)
        self._scroll_to_bottom_after_layout_if_following()
        if not resolved_a_card:
            debug_print(
                f"chat_window: corrección sin card correlacionada "
                f"(request_id={request_id!r}) — sólo se actualizó la burbuja")

    def _finalize_streaming_widget(self, request_id, widget):
        self._streaming_finalize_timeout_ids.pop(request_id, None)
        widget.set_streaming(False)
        return GLib.SOURCE_REMOVE

    def _on_own_carbon_resolved(self, backend, request_id):
        """Carbon de la propia respuesta enviada desde otro dispositivo:
        atenúa la card ya (sin tocar el texto de la burbuja — a diferencia
        de _on_llm_response_correction, aquí no hay texto de corrección
        del servidor todavía, sólo la señal de que ya se respondió)."""
        self._mark_sticky_response_resolved(request_id)

    def _on_own_message(self, backend, body):
        """Un mensaje mío que esta ventana no pintó al enviarlo: un adjunto
        (su burbuja no puede existir hasta que la subida devuelve la URL) o un
        carbon de otro dispositivo, como una imagen mandada desde el móvil."""
        if not (body or '').strip():
            return
        self.display_message(body, sender="user")

    def _add_sticky_response_card(self, responses, on_selected, detail_text=None,
                                   request_id=None, remove_on_select=True):
        if not responses:
            return
        if request_id:
            if request_id in self._rendered_response_request_ids:
                return
            self._rendered_response_request_ids.add(request_id)

        # OpenClaw permits one pending exec approval per conversation. A new
        # approval panel is authoritative and replaces any older sticky one.
        if self._actions_look_like_approval(responses):
            self._drop_sticky_approval_items()

        item = {
            'id': self._sticky_response_next_id,
            'responses': list(responses),
            'on_selected': on_selected,
            'detail_text': detail_text or "",
            # request_id (stanza id de la pregunta original) permite que
            # _on_llm_response_correction encuentre y atenúe ESTA card
            # específica cuando llega la corrección XEP-0308 que la
            # resuelve — sin esto sólo podíamos tocar la burbuja más
            # reciente, rompiendo el caso de varias preguntas abiertas.
            'request_id': request_id,
            'resolved': False,
            'submitted': False,
            'remove_on_select': remove_on_select,
        }
        self._sticky_response_next_id += 1
        self._sticky_response_items.insert(0, item)
        self._expire_sticky_response_item_from_actions(
            item['id'], item['responses'],
            approval=self._body_looks_like_approval(detail_text),
            request_id=request_id)
        self._rebuild_sticky_response_box()

    def _drop_sticky_approval_items(self):
        before = len(self._sticky_response_items)
        self._sticky_response_items = [
            item for item in self._sticky_response_items
            if not self._actions_look_like_approval(item.get('responses', []))
        ]
        return before - len(self._sticky_response_items)

    @classmethod
    def _action_panel_detail(cls, body, actions):
        """Human context for a sticky action, without transport boilerplate."""
        text = Message.compact_blank_lines(body)
        if not cls._actions_look_like_approval(actions):
            return text
        command = ""
        lock_line = re.search(r'(?m)^\s*🔒\s*(.+?)\s*$', text)
        if lock_line:
            command = lock_line.group(1).strip()
        else:
            pending = re.search(
                r'(?is)Pending command:\s*```(?:\w+)?\s*\n(.*?)```', text)
            if pending:
                command = pending.group(1).strip()
        metadata = []
        warning_match = re.search(r'(?m)^\s*⚠️\s*(.+?)\s*$', text)
        if warning_match and warning_match.group(1).strip():
            metadata.append(f"⚠️ {warning_match.group(1).strip()}")
        for label in ("Host", "CWD", "Expires in"):
            match = re.search(rf'(?im)^\s*{re.escape(label)}:\s*(.+?)\s*$', text)
            if match:
                shown = _("Expires") if label == "Expires in" else label
                metadata.append(f"{shown}: {match.group(1).strip()}")
        if not metadata:
            compact_meta = re.search(
                r'(?im)^\s*cwd\s+(.+?)(?:\s*[·•]\s*caduca en\s+(.+))?$', text)
            if compact_meta:
                metadata.append(f"CWD: {compact_meta.group(1).strip()}")
                if compact_meta.group(2):
                    metadata.append(
                        f"{_('Expires')}: {compact_meta.group(2).strip()}")
        return "\n".join(part for part in (command, " · ".join(metadata)) if part)

    def _mark_sticky_response_resolved(self, request_id, resolved_timeout_ms=4000,
                                       resolution_text=None):
        """Retira la card cuyo request_id coincide con una corrección XEP-0308.

        Una aprobación resuelta ya no requiere respuesta. Mantenerla atenuada
        con sus botones deshabilitados se interpretaba como un nuevo permiso
        pendiente, especialmente junto al acuse técnico “allow-once”.
        """
        if not request_id:
            return False
        found = False
        for item in self._sticky_response_items:
            if item.get('request_id') == request_id and not item.get('resolved'):
                item['resolved'] = True
                item['resolution_text'] = Message.compact_blank_lines(
                    resolution_text or _("Resolved"))
                found = True
        if found:
            if resolved_timeout_ms > 0:
                self._rebuild_sticky_response_box()
                GLib.timeout_add(
                    resolved_timeout_ms, self._remove_sticky_response_item,
                    None, request_id)
            else:
                self._remove_sticky_response_item(None, request_id)
        return found

    def _rebuild_sticky_response_box(self):
        # La tarjeta vive DEBAJO del scroll en la misma caja vertical, así que
        # aparecer/crecer/desaparecer le cambia la altura al viewport. Al
        # encogerse, el final del último mensaje queda por debajo del área
        # visible — y ninguna señal del adjustment lo arregla sola: `upper` no
        # cambia (el contenido es el mismo), sólo `page_size`.
        #
        # Además la tarjeta llega en una señal APARTE del backend
        # (quick-responses / commands), milisegundos después de la burbuja, con
        # el scroll ya dado por terminado. Por eso se veía sólo la parte de
        # arriba de la burbuja nueva, con la tarjeta tapando el resto.
        self._scroll_to_bottom_after_layout_if_following()

        for child in list(self.sticky_response_box):
            self.sticky_response_box.remove(child)
        if not self._sticky_response_items:
            self.sticky_response_box.set_visible(False)
            return

        item = self._sticky_response_items[0]
        responses = item['responses']
        detail_text = item.get('detail_text') or ""
        count = len(self._sticky_response_items)
        resolved = bool(item.get('resolved'))
        submitted = bool(item.get('submitted'))

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        card.add_css_class("sticky-response-card")
        if resolved or submitted:
            # Otro dispositivo (o el propio agente vía corrección XEP-0308)
            # ya resolvió esta pregunta — se deja un rastro atenuado en vez
            # de retirarla al instante, útil cuando había varias abiertas.
            # set_opacity en vez de una clase CSS nueva: no hay hoja de
            # estilos propia para sticky-response-card, todo el look sale
            # de la clase "card" de Adwaita.
            card.set_opacity(0.5)
        card.set_margin_start(0)
        card.set_margin_end(0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_halign(Gtk.Align.FILL)
        is_approval = self._actions_look_like_approval(responses)
        if is_approval:
            header.append(resource_manager.create_icon_widget(
                "changes-prevent-symbolic"))
        title_text = _("Approval required") if is_approval else _("Response needed")
        if resolved:
            title_text = _("Resolved")
        elif submitted:
            title_text = _("Decision submitted…")
        if count > 1:
            title_text += f" ({count})"
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
        close_button = Gtk.Button()
        close_button.add_css_class("flat")
        close_button.set_tooltip_text(_("Dismiss"))
        close_button.set_child(
            resource_manager.create_icon_widget("window-close-symbolic"))
        close_button.connect(
            "clicked",
            lambda _button: self._remove_sticky_response_item(item['id']))
        header.append(close_button)
        card.append(header)
        if resolved and item.get('resolution_text'):
            resolution = Gtk.Label(label=item['resolution_text'])
            resolution.add_css_class('success')
            resolution.set_xalign(0)
            resolution.set_wrap(True)
            card.append(resolution)
        if detail_text:
            preview = Gtk.Label(label=self._sticky_detail_preview(
                detail_text, approval=is_approval))
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
            if self._action_is_expired(response):
                self._remove_sticky_response_item(item['id'])
                return
            for btn in buttons:
                btn.set_sensitive(False)
            if item.get('remove_on_select', True):
                self._remove_sticky_response_item(item['id'])
            else:
                item['submitted'] = True
                self._rebuild_sticky_response_box()
            item['on_selected'](response)

        for response in responses:
            label = response.get('label') or response.get('name') or response.get('value', '')
            if not label:
                continue
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
            self._apply_action_button_style(button, response)
            button.set_sensitive(not resolved and not submitted)
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
            resolved = bool(item.get('resolved'))
            submitted = bool(item.get('submitted'))
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            row.add_css_class("sticky-response-popover-row")
            if resolved or submitted:
                row.set_opacity(0.5)
            title = Gtk.Label(label=_("Pending response") + f" {index}")
            title.add_css_class("caption-heading")
            title.set_xalign(0)
            row.append(title)
            detail_text = item.get('detail_text') or ""
            if detail_text:
                preview = Gtk.Label(label=self._sticky_detail_preview(
                    detail_text, max_chars=220,
                    approval=self._actions_look_like_approval(item['responses'])))
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
                if self._action_is_expired(response):
                    self._remove_sticky_response_item(current_item['id'])
                    return
                for btn in current_buttons:
                    btn.set_sensitive(False)
                if current_item.get('remove_on_select', True):
                    self._remove_sticky_response_item(current_item['id'])
                else:
                    current_item['submitted'] = True
                    self._rebuild_sticky_response_box()
                current_item['on_selected'](response)

            for response in item['responses']:
                label = response.get('label') or response.get('name') or response.get('value', '')
                if not label:
                    continue
                button = Gtk.Button(label=label)
                button.add_css_class("pill")
                self._apply_action_button_style(button, response)
                button.set_sensitive(not resolved and not submitted)
                button.connect("clicked", handle_click, response)
                flow.append(button)
                buttons.append(button)
            if buttons:
                row.append(flow)
            box.append(row)
        return box

    @staticmethod
    def _apply_action_button_style(button, action):
        # El plugin XMPP emite un hint de color no estándar (primary|secondary|
        # success|danger) tanto en <response style=...> como en el <item> de
        # XEP-0050. Ambos parsers lo conservan y la burbuja ya lo pintaba
        # (widgets.add_quick_responses), pero la sticky card lo descartaba al
        # renderizar: las approvals salían todas del mismo color, con Deny
        # indistinguible de Allow. Mismas clases qr-* que la burbuja, definidas
        # en style_manager con background explícito para ganarle a .pill.
        style = (action.get('style') or '').strip().lower()
        css_class = {
            'primary': 'qr-primary',
            'success': 'qr-success',
            'danger': 'qr-danger',
            'secondary': 'qr-secondary',
        }.get(style)
        if css_class:
            button.add_css_class(css_class)

    @staticmethod
    def _sticky_detail_preview(detail_text, max_chars=160, approval=False):
        text = Message.compact_blank_lines(detail_text)
        if approval:
            warning = ""
            warning_match = re.search(r'(?m)^\s*⚠️\s*(.+?)\s*$', text)
            if warning_match and warning_match.group(1).strip():
                warning = f"⚠️ {warning_match.group(1).strip()} "
            lock_line = re.search(r'(?m)^\s*🔒\s*(.+?)\s*$', text)
            if lock_line:
                text = lock_line.group(1).strip()
            else:
                pending = re.search(
                    r'(?is)Pending command:\s*```(?:\w+)?\s*\n(.*?)```', text)
                if pending and pending.group(1).strip():
                    text = pending.group(1).strip()
                else:
                    text = re.sub(r'```(?:txt)?\s*```', '', text,
                                   flags=re.IGNORECASE)
            text = warning + text
        text = Message.compact_blank_lines(text).replace("\n", " ")
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}..."

    def _remove_sticky_response_item(self, item_id, request_id=None):
        """Quita una card por su id local, o por request_id (usado por el
        timeout de _mark_sticky_response_resolved — GLib.timeout_add sólo
        pasa argumentos posicionales fijos, así que item_id llega como None
        en ese camino). Devuelve False para que timeout_add no reprograme."""
        if item_id is not None:
            self._sticky_response_items = [
                item for item in self._sticky_response_items
                if item.get('id') != item_id
            ]
        elif request_id is not None:
            self._sticky_response_items = [
                item for item in self._sticky_response_items
                if item.get('request_id') != request_id
            ]
        self._rebuild_sticky_response_box()
        return GLib.SOURCE_REMOVE

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

    def _on_quick_responses(self, backend, responses, request_id=None,
                            _defer_attempt=0):
        responses = self._filter_unexpired_actions(responses)
        if not responses:
            return
        if request_id and request_id in self._rendered_response_request_ids:
            return
        if self.current_message_widget is None:
            if self.is_messaging_backend and _defer_attempt < 8:
                GLib.idle_add(
                    lambda: (
                        self._on_quick_responses(
                            backend, responses, request_id, _defer_attempt + 1),
                        GLib.SOURCE_REMOVE,
                    )[1],
                    priority=GLib.PRIORITY_DEFAULT_IDLE,
                )
            return

        # Multi-pregunta: NO ocultar los botones de preguntas anteriores al
        # llegar una nueva. NanoClaw admite varias preguntas abiertas a la
        # vez y su backend retira los botones de cada pregunta cuando se
        # responde; el cliente ya no fuerza "solo la más reciente"
        # (divergencia deliberada de XEP-0439 §6).
        def on_selected(response):
            if self._action_is_expired(response):
                if self.current_message_widget is not None:
                    self.current_message_widget.hide_quick_responses()
                return
            value = response.get('value', '')
            label = response.get('label') or value
            if not value:
                return
            self.display_message(label, sender="user")
            GLib.idle_add(self._scroll_to_bottom, False)
            if hasattr(backend, 'send_quick_response'):
                backend.send_quick_response(value, label)

        # Los botones van tanto en la burbuja del mensaje (contexto inmediato)
        # como en la sticky card (arriba, visible aunque el usuario haga
        # scroll) — antes esto último sólo pasaba al restaurar del historial
        # (_restore_history_actions), así que una pregunta EN VIVO nunca
        # quedaba fija y era fácil perderla de vista en una conversación larga.
        # _add_sticky_response_card ya marca request_id en
        # _rendered_response_request_ids, así que la comprobación de arriba
        # (línea ~3020) sigue protegiendo contra un reenvío duplicado.
        self.current_message_widget.add_quick_responses(responses, on_selected)
        self._add_sticky_response_card(
            responses,
            on_selected,
            detail_text=Message.compact_blank_lines(self.current_message_widget.message.content),
            request_id=request_id)
        self._expire_quick_responses_from_actions(
            self.current_message_widget, responses,
            approval=self._body_looks_like_approval(
                self.current_message_widget.message.content))
        self._scroll_to_bottom_after_layout_if_following()

    def _on_commands(self, backend, commands, request_id=None,
                     _defer_attempt=0):
        commands = self._filter_unexpired_actions(commands)
        if not commands:
            return
        if request_id and request_id in self._rendered_response_request_ids:
            return
        pending_body = self._pending_action_bodies.get(request_id, '')
        is_approval = self._actions_look_like_approval(commands)
        if self.current_message_widget is None and not (is_approval and pending_body):
            if self.is_messaging_backend and _defer_attempt < 8:
                GLib.idle_add(
                    lambda: (
                        self._on_commands(
                            backend, commands, request_id, _defer_attempt + 1),
                        GLib.SOURCE_REMOVE,
                    )[1],
                    priority=GLib.PRIORITY_DEFAULT_IDLE,
                )
            return

        def on_selected(command):
            self._execute_inline_command(
                command, request_id=request_id)

        # Los command-items de XEP-0050 se muestran sólo como sticky card. Si
        # también se agregan a la burbuja, una approval card aparece duplicada:
        # una vez en el flujo del mensaje y otra en la superficie fija.
        if is_approval and pending_body:
            detail_text = self._action_panel_detail(pending_body, commands)
            self._pending_action_bodies.pop(request_id, None)
        else:
            detail_text = Message.compact_blank_lines(
                self.current_message_widget.message.content)
        self._add_sticky_response_card(
            commands,
            on_selected,
            detail_text=detail_text,
            request_id=request_id,
            # No ocultar la decisión antes del IQ result. Queda deshabilitada
            # mientras está en vuelo y on_success la retira sólo después de
            # que el gateway responda "Command submitted". on_error vuelve a
            # habilitarla para reintentar.
            remove_on_select=False)
        self._scroll_to_bottom_after_layout_if_following()

    def _execute_inline_command(self, command, request_id=None):
        if self._action_is_expired(command):
            return
        name = command.get('name', '')
        node = command.get('node', '')
        jid = command.get('jid', '')
        if not name or not node or not jid:
            return
        # Los comandos inline también pasan por el flujo ad-hoc completo
        # (con formularios XEP-0004), no por el viejo send_command. Se arma
        # un AdHocCommand mínimo a partir del anuncio inline.
        backend = self.backend
        session = getattr(backend, 'session', None)
        bare_jid = getattr(backend, 'bare_jid', None)
        if session is None or bare_jid is None:
            return
        from .xmpp_commands import XmppCommandClient
        from nbxmpp.structs import AdHocCommand
        from nbxmpp.protocol import JID
        client = XmppCommandClient(session, bare_jid)
        # Mantener viva la referencia: XmppCommandClient guarda callbacks
        # pendientes y no debe recolectarse antes de que llegue la respuesta.
        self._agent_command_client = client
        adhoc = AdHocCommand(jid=JID.from_string(jid), node=node, name=name)
        # Una respuesta tardía tras el timeout no debe reabrir ni cerrar nada:
        # el estado ya se decidió. Se comparte por closure entre las tres vías
        # (éxito, error y vencimiento) para que sólo la primera gane.
        settled = {'done': False}

        def claim():
            if settled['done']:
                return False
            settled['done'] = True
            return True

        def on_error(message):
            if not claim():
                return
            for item in self._sticky_response_items:
                if item.get('request_id') == request_id:
                    item['submitted'] = False
            self._rebuild_sticky_response_box()
            self._on_llm_error(self.backend, message)

        def on_timeout():
            # Sin esto, un IQ result que nunca llega (servidor caído, sesión
            # perdida, stanza descartada) dejaba la card deshabilitada en
            # "Enviada…" hasta reiniciar la app: la decisión no se envió y el
            # usuario se quedaba sin ninguna superficie para reintentar.
            # Rehabilitar es lo seguro — la aprobación sigue viva en el
            # gateway y un reintento es idempotente, mientras que darla por
            # buena mentiría sobre algo que no se resolvió.
            if not claim():
                return False
            for item in self._sticky_response_items:
                if item.get('request_id') == request_id:
                    item['submitted'] = False
            self._rebuild_sticky_response_box()
            self._show_toast(
                _("No response from the server. Try again."))
            return False  # one-shot

        GLib.timeout_add_seconds(
            self._APPROVAL_IQ_TIMEOUT_SECONDS, on_timeout)

        def on_success(result):
            if not claim():
                return
            from .xmpp_commands import command_result_body
            body = command_result_body(result)
            if re.fullmatch(r'(?i)Command expired\.?', body.strip()):
                self._remove_sticky_response_item(None, request_id)
                if request_id and hasattr(self.backend, 'expire_pending_actions'):
                    self.backend.expire_pending_actions(request_id)
                self._show_toast(body)
                return
            if not re.fullmatch(r'(?i)Command submitted\.?', body.strip()):
                on_error(body or _("Approval command was not accepted"))
                return
            # La decisión aceptada invalida la acción local inmediatamente.
            # La corrección XEP-0308 sigue actualizando el texto después, pero
            # no es requisito para limpiar metadata ni para que la card no
            # resurja al recargar MAM/cache.
            if request_id and hasattr(self.backend, 'expire_pending_actions'):
                self.backend.expire_pending_actions(request_id)
            self._remove_sticky_response_item(None, request_id)
            if request_id not in self._approval_toast_request_ids:
                self._approval_toast_request_ids.add(request_id)
                self._show_toast(
                    self._approval_toast_text(command, request_id))

        client.execute(adhoc, on_success, on_error)

    # Margen (px) dentro del cual se considera que el usuario está "al fondo".
    # Un par de píxeles de holgura: GTK no siempre deja el valor exacto.
    _SCROLL_BOTTOM_EPSILON = 4.0

    def _log_scroll_state(self, where, adj=None, extra=""):
        """Legacy hook retained for callers; scroll tracing is intentionally off."""
        return

    def _at_bottom(self, adj):
        return (adj.get_upper() - (adj.get_value() + adj.get_page_size())
                <= self._SCROLL_BOTTOM_EPSILON)

    def _cancel_scroll_follow_for_user(self, adj=None):
        """User intent always wins over a pending layout auto-scroll."""
        if adj is None:
            adj = self.message_scroll.get_vadjustment()
        self._stick_to_bottom = False
        self._post_layout_scroll_force = False
        self._post_layout_scroll_pending = False
        if self._post_layout_scroll_watch_id is not None:
            GLib.source_remove(self._post_layout_scroll_watch_id)
            self._post_layout_scroll_watch_id = None
        if self._post_layout_scroll_settle_id is not None:
            GLib.source_remove(self._post_layout_scroll_settle_id)
            self._post_layout_scroll_settle_id = None
        self._cancel_scroll_animation()
        self._scroll_bottom_distance = max(
            0.0, adj.get_upper() - (adj.get_value() + adj.get_page_size()))
        self._log_scroll_state("cancel follow (user)", adj)

    def _on_user_scroll_intent(self, _controller, _dx, dy):
        # Negative dy is an upward wheel/touchpad gesture. Cancel before GTK
        # updates the adjustment, so the post-layout watcher cannot race it and
        # throw the viewport back to the bottom.
        if dy < 0:
            self._cancel_scroll_follow_for_user()
        return False

    def _on_vadj_value_changed(self, adj):
        """El usuario movió el scroll: decide si seguimos anclados al fondo.
        Se ignora cuando el movimiento lo provocamos nosotros, que si no cada
        auto-scroll se reafirmaría a sí mismo.

        OJO con la otra fuente de movimiento espurio: cuando una burbuja CRECE
        (los TextView con wrap sólo saben su alto real tras el layout, así que se
        estiran después de insertarse), el `upper` sube y el valor deja de estar
        al fondo — sin que el usuario haya tocado nada. Leer eso como "se fue
        hacia arriba" apagaba _stick_to_bottom justo cuando más falta hacía, y el
        scroll se quedaba A MEDIA BURBUJA. Un `upper` que crece nunca es intención
        del usuario: sólo se desancla si el contenido NO creció."""
        if self._restoring_scroll:
            self._scroll_last_value = adj.get_value()
            self._log_scroll_state("value-changed(skip restoring)", adj)
            return

        upper = adj.get_upper()
        value = adj.get_value()
        moved_up = value < self._scroll_last_value - 0.5
        self._scroll_last_value = value
        if moved_up:
            self._cancel_scroll_follow_for_user(adj)
            return
        grew = upper > self._scroll_last_upper + 0.5
        self._scroll_last_upper = upper

        if grew:
            if self._stick_to_bottom:
                self._set_value_silently(
                    adj, max(0.0, upper - adj.get_page_size()))
                self._log_scroll_state("value-changed(grew -> stick)", adj)
            else:
                self._log_scroll_state("value-changed(grew no-stick)", adj)
            return

        # Si estamos en medio de una inserción de burbuja (content_added flag),
        # no recalcular _stick_to_bottom — GTK mueve el value automáticamente
        # y _at_bottom daría False hasta que termine el layout.
        if self._content_added_pending:
            self._log_scroll_state("value-changed(skip content_added_pending)", adj)
            return

        self._stick_to_bottom = self._at_bottom(adj)
        self._scroll_bottom_distance = max(
            0.0, upper - (adj.get_value() + adj.get_page_size()))
        self._log_scroll_state(
            "value-changed(update intent)",
            adj,
            extra=f"bottom_distance={self._scroll_bottom_distance:.1f}")

    def _on_vadj_changed(self, adj):
        """Cambió el rango: contenido nuevo o ya medido, o un redimensionado.
        Este es el único punto donde `upper` es de fiar, así que aquí es donde
        se hace el auto-scroll de verdad."""
        page_size = adj.get_page_size()
        resized = page_size != self._scroll_last_page_size
        self._scroll_last_page_size = page_size
        self._log_scroll_state("changed(entry)", adj, extra=f"resized={resized}")

        if self._stick_to_bottom:
            # Contenido nuevo (o el widget que acaba de crecer al renderizar):
            # pegarse al fondo con el alto ya definitivo.
            self._animate_value_silently(adj, adj.get_upper() - page_size)
            self._log_scroll_state("changed(apply stick)", adj)
            return

        if resized:
            # El usuario está leyendo más arriba y cambió el alto del viewport:
            # mantener anclado lo que estaba viendo, no saltar.
            target = max(
                0.0,
                adj.get_upper() - page_size - self._scroll_bottom_distance)
            if abs(target - adj.get_value()) >= 1.0:
                self._set_value_silently(adj, target)
                self._log_scroll_state(
                    "changed(restore anchor)", adj, extra=f"target={target:.1f}")
            else:
                self._log_scroll_state(
                    "changed(anchor no-op)", adj, extra=f"target={target:.1f}")

    def _on_vadj_range_notify(self, adj, _pspec):
        """En GTK4 hay casos donde `changed` llega tarde; al notificar rango
        (upper/page-size) aplicamos la misma lógica de seguimiento al fondo."""
        self._log_scroll_state("notify(range)", adj)
        self._on_vadj_changed(adj)

    def _set_value_silently(self, adj, value):
        """Mover el scroll sin que _on_vadj_value_changed lo lea como que el
        usuario cambió de intención."""
        self._cancel_scroll_animation()
        self._jump_to_value_silently(adj, value)

    def _jump_to_value_silently(self, adj, value):
        target = max(0.0, value)
        self._restoring_scroll = True
        try:
            # GTK puede aceptar el nuevo value durante notify::upper/changed,
            # pero dejar el transform visual del viewport en el value anterior
            # hasta una interacción real. Si ya estamos numéricamente en el
            # target, emitir un cambio mínimo fuerza al ScrolledWindow a
            # reaplicar su desplazamiento interno.
            if abs(adj.get_value() - target) < 0.5 and target > 0.5:
                adj.set_value(target - 0.5)
            adj.set_value(target)
        finally:
            self._restoring_scroll = False
        self._log_scroll_state(
            "set_value_silently", adj, extra=f"requested={value:.1f}")

    def _animate_value_silently(self, adj, value, duration_ms=140):
        target = max(0.0, value)
        start = adj.get_value()
        if abs(target - start) < 24.0:
            self._set_value_silently(adj, target)
            return

        self._cancel_scroll_animation()
        self._scroll_animation_adj = adj
        self._scroll_animation_start_value = start
        self._scroll_animation_target = target
        self._scroll_animation_started_at = time.monotonic()
        self._scroll_animation_duration = max(0.001, duration_ms / 1000.0)
        self._scroll_animation_tick_id = self.add_tick_callback(
            self._on_scroll_animation_tick)

    def _cancel_scroll_animation(self):
        if getattr(self, '_scroll_animation_tick_id', None) is not None:
            self.remove_tick_callback(self._scroll_animation_tick_id)
            self._scroll_animation_tick_id = None
        self._scroll_animation_adj = None

    def _on_scroll_animation_tick(self, _widget, _frame_clock):
        adj = self._scroll_animation_adj
        if adj is None:
            self._scroll_animation_tick_id = None
            return GLib.SOURCE_REMOVE

        elapsed = time.monotonic() - self._scroll_animation_started_at
        progress = min(1.0, elapsed / self._scroll_animation_duration)
        # Ease-out cubic: quick response, soft landing.
        eased = 1.0 - pow(1.0 - progress, 3)
        value = (
            self._scroll_animation_start_value +
            (self._scroll_animation_target - self._scroll_animation_start_value) * eased
        )

        if progress >= 1.0:
            target = self._scroll_animation_target
            self._scroll_animation_tick_id = None
            self._scroll_animation_adj = None
            self._jump_to_value_silently(adj, target)
            return GLib.SOURCE_REMOVE

        self._restoring_scroll = True
        try:
            adj.set_value(max(0.0, value))
        finally:
            self._restoring_scroll = False
        return GLib.SOURCE_CONTINUE

    def _scroll_to_bottom(self, force=True, animate=False):
        """Reanuda el seguimiento del fondo. `force` lo reanuda aunque el
        usuario se hubiera ido hacia arriba (p. ej. porque él mismo acaba de
        enviar un mensaje); si no, respeta que esté leyendo el historial.

        El scroll efectivo lo hace _on_vadj_changed tras el layout — aquí sólo
        se fija la intención y se baja con lo que ya se conoce."""
        adj = self.message_scroll.get_vadjustment()
        if force:
            self._stick_to_bottom = True
        self._content_added_pending = False
        if self._stick_to_bottom:
            target = adj.get_upper() - adj.get_page_size()
            if animate:
                self._animate_value_silently(adj, target)
            else:
                self._set_value_silently(adj, target)
        self._log_scroll_state("scroll_to_bottom", adj, extra=f"force={force}")

    def _scroll_to_bottom_after_layout_if_following(self):
        """Como _scroll_to_bottom_after_layout, pero RESPETA al que está leyendo.

        Para cambios de layout que no son contenido nuevo (la tarjeta sticky
        apareciendo o yéndose): si el usuario seguía el fondo, hay que volver a
        pegarlo ahí con el viewport ya redimensionado; si estaba leyendo más
        arriba, no se le mueve la vista."""
        if not self._stick_to_bottom:
            return
        self._scroll_to_bottom_after_layout(force=False)

    def _arm_post_layout_scroll_settle(self):
        if self._post_layout_scroll_settle_id is not None:
            GLib.source_remove(self._post_layout_scroll_settle_id)
        self._post_layout_scroll_settle_id = GLib.timeout_add(
            200, self._finish_post_layout_scroll)
        self._log_scroll_state("arm_settle", extra="timeout_ms=200")

    def _finish_post_layout_scroll(self):
        if self._post_layout_scroll_watch_id is not None:
            GLib.source_remove(self._post_layout_scroll_watch_id)
            self._post_layout_scroll_watch_id = None
        self._cancel_scroll_animation()
        self._post_layout_scroll_settle_id = None
        self._post_layout_scroll_pending = False
        self._post_layout_scroll_force = False
        self._log_scroll_state("finish_post_layout_scroll")
        return GLib.SOURCE_REMOVE

    def _get_messages_box_height(self):
        """Altura asignada actual de messages_box, compatible con distintas
        versiones de bindings Gtk4."""
        if hasattr(self.messages_box, 'get_height'):
            return self.messages_box.get_height()
        if hasattr(self.messages_box, 'get_allocated_height'):
            return self.messages_box.get_allocated_height()
        return 0

    def _watch_post_layout_scroll(self):
        if not self._post_layout_scroll_pending:
            self._post_layout_scroll_watch_id = None
            self._log_scroll_state("watch(stop no pending)")
            return GLib.SOURCE_REMOVE

        should_follow = self._post_layout_scroll_force or self._stick_to_bottom
        if not should_follow:
            self._finish_post_layout_scroll()
            self._log_scroll_state("watch(stop no follow)")
            return GLib.SOURCE_REMOVE

        height = self._get_messages_box_height()
        height_changed = height != self._messages_box_last_height
        self._messages_box_last_height = height

        if height_changed:
            # El bubble todavía está creciendo (wrap/markdown): bajar de nuevo
            # con el alto real del layout actual.
            self._scroll_to_bottom(
                force=self._post_layout_scroll_force,
                animate=True)
            self._arm_post_layout_scroll_settle()
            self._log_scroll_state("watch(height changed)", extra=f"height={height}")
        else:
            self._log_scroll_state("watch(height stable)", extra=f"height={height}")

        return GLib.SOURCE_CONTINUE

    def _ensure_post_layout_scroll_watch(self):
        if self._post_layout_scroll_watch_id is None:
            self._post_layout_scroll_watch_id = GLib.timeout_add(
                33, self._watch_post_layout_scroll)
            self._log_scroll_state("watch(start)", extra="interval_ms=33")

    def _scroll_to_bottom_after_layout(self, force=True):
        """Baja del todo cuando el alto aún no es definitivo (carga de
        historial, un bubble que renderiza markdown después)."""
        if force:
            self._stick_to_bottom = True
        self._post_layout_scroll_pending = True
        self._post_layout_scroll_force = self._post_layout_scroll_force or force
        self._messages_box_last_height = self._get_messages_box_height()
        self._ensure_post_layout_scroll_watch()
        self._arm_post_layout_scroll_settle()
        self._log_scroll_state(
            "scroll_to_bottom_after_layout",
            extra=f"force={force} box_h={self._messages_box_last_height}")

        def scroll_once():
            self._scroll_to_bottom(force, animate=True)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(scroll_once)

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
        self._scroll_to_bottom_after_layout()

    def _on_focus_enter(self, controller):
        """Set focus to the input text when the window gains focus."""
        # Solo poner el foco si el sidebar no está visible
        if not self.split_view.get_show_sidebar():
            self.input_text.grab_focus()

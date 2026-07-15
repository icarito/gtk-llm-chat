import json
import os
import re
import signal
import sys
import subprocess
import threading
import gettext
import locale

from gi import require_versions
require_versions({"Gtk": "4.0", "Adw": "1"})

from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext
import llm

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from .db_operations import ChatHistory

_ = gettext.gettext

DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


# Reemplazar la definición de la interfaz D-Bus con XML
DBUS_INTERFACE_XML = """
<node>
  <interface name='org.fuentelibre.gtk_llm_Chat'>
    <method name='OpenConversation'>
      <arg type='s' name='cid' direction='in'/>
    </method>
  </interface>
</node>
"""

class LLMChatApplication(Adw.Application):
    """Class for a chat instance"""

    def __init__(self, config=None):
        super().__init__(
            application_id="org.fuentelibre.gtk_llm_Chat",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )

        self._shutting_down = False  # Bandera para controlar proceso de cierre
        self._window_by_cid = {}  # Mapa de CID -> ventana
        # La restauración de la sesión de ventanas se hace una sola vez, en el
        # primer arranque; las reinvocaciones single-instance no re-restauran.
        self._session_restored = False
        
        debug_print("LLMChatApplication.__init__: Verificando si se necesita configuración inicial...")
        self._needs_initial_setup = self._check_initial_setup_needed()
        debug_print(f"LLMChatApplication.__init__: _needs_initial_setup = {self._needs_initial_setup}")

        # Add signal handler
        signal.signal(signal.SIGINT, self._handle_sigint)
        self.connect('shutdown', self.on_shutdown)  # Conectar señal shutdown



        # Force dark mode until we've tested / liked light mode (issue #25)
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

    def _handle_sigint(self, signum, frame):
        """Handles SIGINT signal to close the application"""
        debug_print(_("\nClosing application..."))
        self.quit()

    def _register_dbus_interface(self):
        # Solo ejecutar en Linux y evitar timeouts
        if sys.platform != 'linux':
            return
        try:
            from gi.repository import Gio
            # Agregar timeout para evitar bloqueos
            import threading
            
            def register_with_timeout():
                try:
                    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                    node_info = Gio.DBusNodeInfo.new_for_xml(DBUS_INTERFACE_XML)
                    interface_info = node_info.interfaces[0]
                    
                    def method_call_handler(connection, sender, object_path, interface_name, method_name, parameters, invocation):
                        if method_name == "OpenConversation":
                            try:
                                cid = parameters.unpack()[0]
                                debug_print(f"D-Bus: Recibida solicitud para abrir conversación CID: '{cid}'")
                                # Usar GLib.idle_add para manejar la llamada en el hilo principal de GTK
                                GLib.idle_add(lambda: self.OpenConversation(cid))
                                invocation.return_value(None)
                            except Exception as e:
                                debug_print(f"D-Bus: Error al procesar OpenConversation: {e}")
                                invocation.return_dbus_error("org.fuentelibre.Error.Failed", str(e))
                        else:
                            invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Método desconocido")
                    
                    reg_id = connection.register_object(
                        '/org/fuentelibre/gtk_llm_Chat',
                        interface_info,
                        method_call_handler,
                        None,  # get_property_handler
                        None   # set_property_handler
                    )
                    if reg_id > 0:
                        self.dbus_registration_id = reg_id
                        debug_print("Interfaz D-Bus registrada correctamente")
                    else:
                        debug_print("Error al registrar la interfaz D-Bus")
                except Exception as e:
                    debug_print(f"Error registrando D-Bus: {e}")
            
            # Ejecutar registro en thread separado con timeout
            thread = threading.Thread(target=register_with_timeout, daemon=True)
            thread.start()
            # No esperar - continuar sin D-Bus si hay problemas
            
        except Exception as e:
            debug_print(f"Error al configurar D-Bus (solo debe ocurrir en Linux): {e}")

    def do_startup(self):
        Adw.Application.do_startup(self)
        
        # Configurar recursos básicos de forma segura (solo en hilo principal)
        try:
            # Cargar estilos CSS y configurar tema de iconos en el hilo principal
            from .style_manager import style_manager
            from .resource_manager import resource_manager
            
            # Configurar sin threading para evitar conflictos
            style_manager.load_styles()
            if not resource_manager._icon_theme_configured:
                resource_manager.setup_icon_theme()
            debug_print("Recursos básicos configurados en do_startup")
            
        except Exception as e:
            debug_print(f"Error configurando recursos en startup: {e}")
        
        # Solo registrar D-Bus en Linux
        if sys.platform=='linux':
            self._register_dbus_interface()

        self.hold()  # Asegura que la aplicación no termine prematuramente

        APP_NAME = "gtk-llm-chat"
        if getattr(sys, 'frozen', False):
            base_path = os.path.join(
                    sys._MEIPASS)
        else:
            base_path = os.path.join(os.path.dirname(__file__), "..")

        LOCALE_DIR = os.path.abspath(os.path.join(base_path, 'po'))

        lang = locale.getdefaultlocale()[0]  # Ej: 'es_ES'
        if lang:
            gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
            gettext.textdomain(APP_NAME)
            lang_trans = gettext.translation(APP_NAME, LOCALE_DIR, languages=[lang], fallback=True)
            lang_trans.install()
            global _
            _ = lang_trans.gettext

        self._setup_icon()

        # Configure actions
        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self.on_rename_activate)
        self.add_action(rename_action)

        delete_action = Gio.SimpleAction.new("delete", None)
        delete_action.connect("activate", self.on_delete_activate)
        self.add_action(delete_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

        new_conversation_action = Gio.SimpleAction.new("new-conversation", None)
        new_conversation_action.connect(
            "activate", lambda a, p: self.open_conversation_window({}))
        self.add_action(new_conversation_action)

        new_xmpp_action = Gio.SimpleAction.new("new-xmpp-conversation", None)
        new_xmpp_action.connect("activate", self.on_new_xmpp_conversation_activate)
        self.add_action(new_xmpp_action)

        xmpp_account_action = Gio.SimpleAction.new("xmpp-account", None)
        xmpp_account_action.connect("activate", self.on_xmpp_account_activate)
        self.add_action(xmpp_account_action)

        xmpp_reconnect_action = Gio.SimpleAction.new("xmpp-reconnect", None)
        xmpp_reconnect_action.connect("activate", self.on_xmpp_reconnect_activate)
        self.add_action(xmpp_reconnect_action)

        xmpp_disconnect_action = Gio.SimpleAction.new("xmpp-disconnect", None)
        xmpp_disconnect_action.connect("activate", self.on_xmpp_disconnect_activate)
        self.add_action(xmpp_disconnect_action)

        xmpp_remove_action = Gio.SimpleAction.new("xmpp-remove-account", None)
        xmpp_remove_action.connect("activate", self.on_xmpp_remove_account_activate)
        self.add_action(xmpp_remove_action)

        # Acciones parametrizadas por bare JID, invocadas desde las
        # notificaciones XMPP (spec 002 T5/T6).
        open_xmpp_action = Gio.SimpleAction.new(
            "open-xmpp", GLib.VariantType.new('s'))
        open_xmpp_action.connect("activate", self._on_open_xmpp_action)
        self.add_action(open_xmpp_action)

        accept_sub_action = Gio.SimpleAction.new(
            "accept-xmpp-sub", GLib.VariantType.new('s'))
        accept_sub_action.connect("activate", self._on_accept_xmpp_sub)
        self.add_action(accept_sub_action)

        deny_sub_action = Gio.SimpleAction.new(
            "deny-xmpp-sub", GLib.VariantType.new('s'))
        deny_sub_action.connect("activate", self._on_deny_xmpp_sub)
        self.add_action(deny_sub_action)

    def OpenConversation(self, cid):
        """Abrir (o enfocar) una conversación dado un CID.

        El focus-or-open lo hace open_conversation (spec 009); aquí ya no se
        toca el registro a mano."""
        debug_print(f"D-Bus: OpenConversation recibido con CID: {cid}")
        self.open_conversation({'kind': 'llm', 'cid': cid or None})

    def create_chat_window(self, cid):
        """Crear una nueva ventana de chat"""
        # Implementación para crear una ventana de chat
        pass

    def on_shutdown(self, app):
        """Handles application shutdown and unregisters D-Bus."""
        self._shutting_down = True
        # Guardar el estado de las ventanas abiertas para restaurarlo al
        # próximo arranque (misma sesión de ventanas que al salir).
        self._save_session_state()
        if hasattr(self, 'dbus_registration_id'):
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.unregister_object(self.dbus_registration_id)

    # --- Persistencia del estado de ventanas ---

    def _session_state_path(self):
        """Ruta del archivo JSON con el estado de ventanas de la última salida."""
        try:
            from .platform_utils import ensure_user_dir_exists
            user_dir = ensure_user_dir_exists()
            if not user_dir:
                return None
            return os.path.join(user_dir, "window_session.json")
        except Exception as e:
            debug_print(f"No se pudo resolver la ruta de window_session.json: {e}")
            return None

    def _window_descriptor(self, window):
        """Descriptor serializable de una ventana con contenido, o None.

        Solo devuelve algo para ventanas que valga la pena restaurar:
        conversaciones LLM con CID, o conversaciones XMPP con un contacto.
        Las ventanas vacías / borrador (sin CID ni contacto, o el picker de
        roster) devuelven None y no se persisten.
        """
        backend = getattr(window, 'backend', None)
        bare_jid = getattr(backend, 'bare_jid', None)
        session = getattr(backend, 'session', None)
        geometry = self._window_geometry(window)
        if bare_jid and session is not None:
            descriptor = {'type': 'xmpp', 'bare_jid': bare_jid}
            if geometry:
                descriptor['geometry'] = geometry
            return descriptor
        cid = getattr(window, 'cid', None) or (window.config.get('cid')
                                               if hasattr(window, 'config') else None)
        if cid:
            descriptor = {'type': 'llm', 'cid': cid}
            if geometry:
                descriptor['geometry'] = geometry
            return descriptor
        return None

    def _window_geometry(self, window):
        width = window.get_width() if hasattr(window, 'get_width') else 0
        height = window.get_height() if hasattr(window, 'get_height') else 0
        if width <= 0 or height <= 0:
            try:
                width, height = window.get_default_size()
            except Exception:
                width, height = 0, 0
        if width <= 0 or height <= 0:
            return None
        return {'width': width, 'height': height}

    def _window_descriptor_key(self, descriptor):
        dtype = descriptor.get('type')
        if dtype == 'xmpp':
            return dtype, descriptor.get('bare_jid')
        if dtype == 'llm':
            return dtype, descriptor.get('cid')
        return tuple(sorted(descriptor.items()))

    def _save_session_state(self):
        """Escribe los descriptores de las ventanas abiertas a disco."""
        path = self._session_state_path()
        if path is None:
            return
        descriptors = []
        seen = set()
        for window in self.get_windows():
            try:
                descriptor = self._window_descriptor(window)
            except Exception as e:
                debug_print(f"Error describiendo ventana para guardar sesión: {e}")
                continue
            if descriptor is None:
                continue
            key = self._window_descriptor_key(descriptor)
            if key in seen:
                continue
            seen.add(key)
            descriptors.append(descriptor)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'windows': descriptors}, f)
            debug_print(f"Estado de sesión guardado: {len(descriptors)} ventana(s)")
        except Exception as e:
            debug_print(f"Error guardando estado de sesión: {e}")

    def _load_session_descriptors(self):
        """Lee los descriptores guardados; lista vacía si no hay o hay error."""
        path = self._session_state_path()
        if path is None or not os.path.exists(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            windows = data.get('windows', []) if isinstance(data, dict) else []
            return [w for w in windows if isinstance(w, dict)]
        except Exception as e:
            debug_print(f"Error leyendo estado de sesión: {e}")
            return []

    def _restore_session_state(self):
        """Reabre las ventanas guardadas al salir. Devuelve True si abrió
        al menos una."""
        descriptors = self._load_session_descriptors()
        if not descriptors:
            return False
        # La sesión XMPP se crea de forma perezosa; solo si hay algún
        # contacto XMPP que restaurar.
        xmpp_session = None
        restored = 0
        for descriptor in descriptors:
            dtype = descriptor.get('type')
            try:
                if dtype == 'llm':
                    cid = descriptor.get('cid')
                    if cid:
                        self.open_conversation_window({
                            'cid': cid,
                            '_window_geometry': descriptor.get('geometry'),
                        })
                        restored += 1
                elif dtype == 'xmpp':
                    bare_jid = descriptor.get('bare_jid')
                    if not bare_jid:
                        continue
                    if xmpp_session is None:
                        xmpp_session = self.get_xmpp_session_for_roster()
                    if xmpp_session is None:
                        debug_print(
                            "No hay cuenta XMPP: no se restaura la conversación "
                            f"con {bare_jid}")
                        continue
                    self.open_xmpp_conversation(
                        xmpp_session, bare_jid,
                        window_geometry=descriptor.get('geometry'))
                    restored += 1
            except Exception as e:
                debug_print(f"Error restaurando ventana {descriptor}: {e}")
        return restored > 0

    def _open_default_window(self):
        """Abre la ventana por defecto: siempre el roster (en una ventana
        vacía). Si hay cuenta XMPP se conecta la sesión; si no, el sidebar
        muestra la acción de configurar cuenta sin bifurcar la UI."""
        session = self.get_xmpp_session_for_roster()
        self._create_new_window_with_config({}, xmpp_session=session)

    def get_application_version(self):
        """
        Gets the application version from _version.py.
        """
        try:
            from . import _version
            return _version.__version__
        except ImportError:
            debug_print(_("Error: _version.py not found"))
            return "Unknown"
        return "Unknown"

    def _setup_icon(self):
        """Configures the application icon"""
        # Set search directory
        if getattr(sys, 'frozen', False):
            base_path = os.path.join(sys._MEIPASS, 'gtk_llm_chat')
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(base_path)

    def do_command_line(self, command_line):
        """Procesa los argumentos de la línea de comandos."""
        debug_print("do_command_line invocado")

        # Extraer configuración de los argumentos
        args = command_line.get_arguments()
        debug_print(f"Argumentos recibidos: {args}")

        config = {}
        has_args = False  # Flag para saber si se recibieron argumentos relevantes

        for arg in args:
            # Skip the executable path (first argument)
            if arg == args[0] and arg.endswith(("gtk-llm-chat", "gtk-llm-chat.exe", "python", "python.exe")):
                continue

            has_args = True  # Se recibió al menos un argumento válido

            if arg.startswith("--cid="):
                config['cid'] = arg.split("=", 1)[1]
                debug_print(f"CID encontrado en argumentos: {config['cid']}")
            elif arg.startswith("--model="):
                config['model'] = arg.split("=", 1)[1]
            elif arg.startswith("--template="):
                config['template'] = arg.split("=", 1)[1]

        # Guardar esta configuración para usarla
        debug_print(f"Configuración preparada: {config}")

        if has_args:
            # Intención explícita (--cid, --model, --template): abrir
            # directo, sin picker. Este es el único camino que asume LLM,
            # y solo porque el usuario ya lo pidió explícitamente.
            if self._needs_initial_setup:
                debug_print("Mostrando asistente de configuración inicial desde command_line")
                self._show_welcome_window()
            else:
                self.open_conversation_window(config)
        else:
            if self._needs_initial_setup:
                self._show_welcome_window()
            elif not self._session_restored:
                # Primer arranque sin argumentos: restaurar la sesión de
                # ventanas de la última salida (o abrir el roster por defecto).
                self._session_restored = True
                self._restore_or_open_default()
            else:
                # Reinvocación de la instancia ya viva (single-instance):
                # abrir una ventana nueva sin re-restaurar toda la sesión.
                self._open_default_window()

        return 0

    def _check_initial_setup_needed(self):
        """
        Verifica si se necesita mostrar el asistente de configuración inicial.
        
        Returns:
            bool: True si se necesita mostrar el asistente, False si ya hay configuración
        """
        try:
            # Obtener la ruta de la base de datos usando ensure_user_dir_exists()
            from .platform_utils import ensure_user_dir_exists
            user_dir = ensure_user_dir_exists()
            if not user_dir: # Si ensure_user_dir_exists falla
                debug_print("_check_initial_setup_needed: Error obteniendo user_dir, asumiendo que se necesita setup.")
                return True # Si no podemos obtener el dir, mejor mostrar el welcome.
            user_dir = ensure_user_dir_exists()
            db_path = os.path.join(user_dir, "logs.db")
            
            debug_print(f"_check_initial_setup_needed: user_dir = {user_dir}")
            debug_print(f"_check_initial_setup_needed: db_path = {db_path}")
            debug_print(f"_check_initial_setup_needed: user_dir exists = {os.path.exists(user_dir)}")
            debug_print(f"_check_initial_setup_needed: db_path exists = {os.path.exists(db_path)}")
            
            # Si no existe el archivo logs.db, es la primera vez
            if not os.path.exists(db_path):
                debug_print("_check_initial_setup_needed: Configuración inicial necesaria: logs.db no existe")
                return True
            
            debug_print("_check_initial_setup_needed: Configuración inicial no necesaria: ya existe configuración")
            return False
            
        except Exception as e:
            debug_print(f"_check_initial_setup_needed: Error verificando configuración inicial: {e}")
            # En caso de error, proceder normalmente sin el asistente
            return False

    def do_activate(self):
        """Activa la aplicación y crea una nueva ventana utilizando la configuración actual."""
        Adw.Application.do_activate(self)
        debug_print("do_activate invocado")
        debug_print(f"do_activate: self._needs_initial_setup = {self._needs_initial_setup}")

        if self._needs_initial_setup:
            self._show_welcome_window()
        elif not self._session_restored:
            self._session_restored = True
            self._restore_or_open_default()
        else:
            self._open_default_window()

    def _restore_or_open_default(self):
        """Restaura las ventanas de la última salida; si no había estado
        guardado (o no se pudo restaurar nada), abre el roster en una
        ventana vacía."""
        if not self._restore_session_state():
            self._open_default_window()

    def _show_welcome_window(self):
        """Muestra el asistente de configuración inicial."""
        try:
            from .welcome import WelcomeWindow
            
            # Definimos un método que se llamará cuando el usuario termine el asistente
            def on_welcome_finished(config_data=None):
                """Callback que se ejecuta cuando el usuario completa el asistente."""
                debug_print("Asistente de configuración completado")
                
                # Continuar con la apertura de la ventana de chat
                self.open_conversation_window()
            
            welcome_window = WelcomeWindow(self, on_welcome_finished=on_welcome_finished)
            welcome_window.present()
            
        except Exception as e:
            debug_print(f"Error mostrando ventana de bienvenida: {e}")
            # Si hay error con el asistente, proceder con la ventana normal
            self.open_conversation_window()

    # --- Apertura de conversaciones (spec 009) ---
    #
    # Una conversación se identifica por un descriptor, y un descriptor da
    # exactamente una clave de registro y un backend. LLM y XMPP siguen el mismo
    # camino: antes una conversación LLM transformaba la ventana actual en vez de
    # abrir la suya, lo que obligaba a reescribir claves del registro a mano cada
    # vez que una ventana cambiaba de identidad.

    @staticmethod
    def conversation_key(descriptor):
        """Clave de registro (focus-or-open) para un descriptor."""
        if descriptor.get('kind') == 'xmpp':
            return f"xmpp:{descriptor['account']}:{descriptor['jid']}"
        cid = descriptor.get('cid')
        # Una conversación LLM nueva aún no tiene cid: no se registra hasta que
        # el backend le dé uno (ver _register_llm_window).
        return f"llm:{cid}" if cid else None

    def build_backend(self, descriptor, chat_history):
        """Construye el ChatBackend de un descriptor. La ventana ya no construye
        ninguno: sólo habla con el contrato ChatBackend."""
        if descriptor.get('kind') == 'xmpp':
            session = descriptor['session']
            return session.get_conversation(descriptor['jid'])

        from .llm_client import LLMClient
        from llm import get_default_model
        config = dict(self.config or {})
        config.update(descriptor.get('config') or {})
        cid = descriptor.get('cid')
        if cid:
            config['cid'] = cid
        else:
            # Conversación nueva: sin cid del que deducir el modelo, se usa el
            # predeterminado. (Con cid, el LLMClient resuelve el de esa
            # conversación al cargarlo.)
            default_model_id = get_default_model()
            if default_model_id:
                config['model'] = default_model_id
        return LLMClient(config, chat_history)

    def open_conversation(self, descriptor):
        """Abre —o enfoca, si ya está abierta— la ventana de una conversación.

        Único punto de entrada: lo usan el roster, D-Bus y la restauración de
        sesión, tanto para LLM como para XMPP."""
        key = self.conversation_key(descriptor)
        if key is not None:
            existing = self._window_by_cid.get(key)
            if existing is not None:
                existing.present()
                return existing

        chat_history = ChatHistory()
        try:
            backend = self.build_backend(descriptor, chat_history)
        except Exception as err:
            debug_print(f"open_conversation: no se pudo crear el backend: {err}")
            return None

        config = dict(descriptor.get('config') or {})
        if descriptor.get('cid'):
            config['cid'] = descriptor['cid']

        window = self._create_new_window_with_config(
            config, backend=backend,
            xmpp_session=descriptor.get('session'),
            chat_history=chat_history)

        if key is not None:
            self._window_by_cid[key] = window
        elif descriptor.get('kind') != 'xmpp':
            # LLM nueva: se registra cuando el backend anuncie su cid.
            self._register_llm_window_when_ready(window, backend)
        return window

    def _register_llm_window_when_ready(self, window, backend):
        """Una conversación LLM nueva no tiene cid hasta que el backend lo crea;
        en ese momento se registra, para que un segundo clic la enfoque en vez de
        abrir otra ventana."""
        def on_ready(_backend, _display_name):
            cid = backend.get_conversation_id()
            if cid:
                self._window_by_cid[f"llm:{cid}"] = window
        backend.connect('ready', on_ready)

    def _create_new_window_with_config(self, config, backend=None,
                                       xmpp_session=None, chat_history=None):
        """Crea una nueva ventana con la configuración dada.

        Args:
            backend: ChatBackend ya construido (p.ej. XmppConversation) a
                inyectar en la ventana en vez del LLMClient por defecto.
            xmpp_session: sesión XMPP sin contacto elegido aún (spec 003):
                la ventana muestra el roster y espera selección.
        """
        debug_print(f"Creando nueva ventana con configuración: {config}")

        from .chat_window import LLMChatWindow
        from .resource_manager import resource_manager
        if chat_history is None:
            chat_history = ChatHistory()

        # Crear la nueva ventana con la configuración
        window = LLMChatWindow(application=self, config=config, chat_history=chat_history,
                                backend=backend, xmpp_session=xmpp_session)
        self._apply_window_geometry(window, config.get('_window_geometry'))
        resource_manager.set_widget_icon_name(window, "org.fuentelibre.gtk_llm_Chat")

        # Configurar el manejador de eventos de teclado
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        window.add_controller(key_controller)

        # Registrar la ventana por CID si existe
        if 'cid' in config and config['cid']:
            cid = config['cid']
            self._window_by_cid[cid] = window
            debug_print(f"Ventana registrada para CID: {cid}")

        # Presentar la ventana con logs de diagnóstico
        debug_print("Presentando ventana de chat...")
        try:
            window.present()
            debug_print("Ventana de chat presentada correctamente.")
        except Exception as e:
            debug_print(f"[ERROR] Fallo al presentar la ventana: {e}")
        return window

    def _apply_window_geometry(self, window, geometry):
        if not isinstance(geometry, dict):
            return
        width = geometry.get('width')
        height = geometry.get('height')
        if not isinstance(width, int) or not isinstance(height, int):
            return
        if width < 320 or height < 240:
            return
        window.set_default_size(width, height)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Maneja eventos de teclado a nivel de aplicación."""
        window = self.get_active_window()

        # F10: Toggle del sidebar
        if keyval == Gdk.KEY_F10:
            if window and hasattr(window, 'split_view'):
                is_visible = window.split_view.get_show_sidebar()
                window.split_view.set_show_sidebar(not is_visible)
                return True

        # F2: Renombrar conversación
        if keyval == Gdk.KEY_F2:
            if window:
                self.on_rename_activate(None, None)
                return True

        # Escape: Cerrar ventana solo si el input tiene el foco
        if keyval == Gdk.KEY_Escape:
            if window:
                # Verificar si el foco está en el input_text
                if hasattr(window, 'input_text') and window.input_text.has_focus():
                    window.close()
                    return True

        # Permitir que otros controles procesen otros eventos de teclado
        return False

    def on_rename_activate(self, action, param):
        """Renames the current conversation"""
        window = self.get_active_window()
        if hasattr(window, 'begin_title_edit'):
            window.begin_title_edit()
        else:
            window.header.set_title_widget(window.title_entry)
            window.title_entry.grab_focus()

    def on_delete_activate(self, action, param):
        """Elimina la conversación actual solo si tiene historial, si no cierra la ventana directamente."""
        window = self.get_active_window()

        # Verificar que tenemos una ventana y acceder a su configuración
        if not window or not hasattr(window, 'config'):
            debug_print("No se puede eliminar: ventana inválida o sin configuración")
            return

        cid = window.config.get('cid')
        chat_history = getattr(window, 'chat_history', None)
        has_history = False
        if cid and chat_history:
            try:
                history_entries = chat_history.get_conversation_history(cid)
                has_history = bool(history_entries)
            except Exception as e:
                debug_print(f"Error consultando historial para CID {cid}: {e}")

        if not has_history:
            debug_print("No hay historial, cerrando ventana directamente (Ctrl+W)")
            window.close()
            return

        # Usar Adw.MessageDialog en vez de Gtk.MessageDialog
        dialog = Adw.MessageDialog(
            transient_for=window,
            modal=True,
            heading=_("Delete Conversation"),
            body=_("Are you sure you want to delete the conversation?")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_delete_response(dialog, response):
            if response == "delete" and hasattr(window, 'chat_history'):
                cid = window.config.get('cid')
                debug_print(f"Eliminando conversación con CID: {cid}")
                if cid:
                    window.chat_history.delete_conversation(cid)
                    # Cerrar solo la ventana actual en lugar de toda la aplicación
                    window.close()
            dialog.destroy()

        dialog.connect("response", on_delete_response)
        dialog.present()

    def on_about_activate(self, action, param):
        """Shows the 'About' dialog"""
        about_dialog = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            # Keep "Gtk LLM Chat" as the application name
            application_name=_("Gtk LLM Chat"),
            application_icon="org.fuentelibre.gtk_llm_Chat",
            website="https://github.com/icarito/gtk_llm_chat",
            comments=_("A frontend for LLM"),
            license_type=Gtk.License.GPL_3_0,
            developer_name="Sebastian Silva",
            version=self.get_application_version(),
            developers=["Sebastian Silva <sebastian@fuentelibre.org>"],
            copyright="© 2024 Sebastian Silva"
        )
        about_dialog.present()

    def on_new_xmpp_conversation_activate(self, action, param):
        """Abre el flujo de conversación XMPP (spec 001): cuenta -> roster -> ventana.

        Punto de entrada deliberadamente separado del selector de modelos
        LLM (ver specs/001-xmpp-backend/design.md) para no arriesgar el
        flujo LLM existente.
        """
        from .xmpp_account import load_account
        account = load_account()
        if account is None:
            # Sin cuenta configurada: abrir el setup y reintentar al terminar
            self._open_xmpp_account_dialog(
                on_ready=lambda jid: self.on_new_xmpp_conversation_activate(None, None))
            return

        jid, password = account
        session = self._ensure_xmpp_session(jid, password)
        self._open_xmpp_roster_picker(session)

    def on_xmpp_account_activate(self, action, param):
        """Abre el diálogo de configuración de cuenta XMPP (siempre, no solo
        la primera vez): permite configurar o cambiar la cuenta."""
        self._open_xmpp_account_dialog()

    def on_xmpp_reconnect_activate(self, action, param):
        """Reconecta la sesión XMPP activa sin recrear ventanas."""
        session = getattr(self, '_xmpp_session', None)
        if session is not None:
            session.reconnect_now()

    def on_xmpp_disconnect_activate(self, action, param):
        """Desconecta la sesión XMPP activa y cancela reconexiones pendientes."""
        session = getattr(self, '_xmpp_session', None)
        if session is not None:
            session.disconnect_from_server()

    def on_xmpp_remove_account_activate(self, action, param):
        """Elimina credenciales XMPP guardadas y cierra la sesión activa."""
        window = self.get_active_window()
        dialog = Adw.MessageDialog(
            transient_for=window,
            modal=True,
            heading=_("Remove XMPP Account"),
            body=_("Remove the saved XMPP account from this device?"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_dialog, response):
            if response != "remove":
                return
            from .xmpp_account import delete_account
            session = getattr(self, '_xmpp_session', None)
            if session is not None:
                session.shutdown()
                self._xmpp_session = None
            delete_account()

        dialog.connect("response", on_response)
        dialog.present()

    def _open_xmpp_account_dialog(self, on_ready=None):
        from .xmpp_account_dialog import XmppAccountDialog

        def _on_ready(jid):
            # Una cuenta nueva/cambiada invalida la sesión previa
            old = getattr(self, '_xmpp_session', None)
            if old is not None:
                old.shutdown()
                self._xmpp_session = None
            if on_ready is not None:
                on_ready(jid)

        dialog = XmppAccountDialog(
            parent=self.get_active_window(), on_account_ready=_on_ready)
        dialog.present()

    def _ensure_xmpp_session(self, jid, password):
        """Devuelve la sesión XMPP de la app, creándola (y cableando sus
        notificaciones) la primera vez."""
        session = getattr(self, '_xmpp_session', None)
        if session is not None and session.bare_jid != jid:
            session.shutdown()
            self._xmpp_session = None
            session = None
        if session is None:
            from .xmpp_client import XmppSession
            session = XmppSession(jid, password)
            self._xmpp_session = session
            session.connect('message-received', self._on_xmpp_message_received)
            session.connect('subscription-request', self._on_xmpp_subscription_request)
            session.connect_to_server()
        elif not session.is_connected:
            session.reconnect_now()
        return session

    def _on_xmpp_message_received(self, session, bare_jid, body):
        """Notifica un mensaje XMPP entrante si su ventana no está activa
        (spec 002 T5). Si la ventana está enfocada, no molesta."""
        key = f"xmpp:{session.bare_jid}:{bare_jid}"
        window = self._window_by_cid.get(key)
        if window is not None and window.is_active():
            return  # la ve el usuario ahora mismo; no notificar
        notification = Gio.Notification.new(session.get_contact_name(bare_jid))
        notification.set_body(body)
        # 'default' action → abrir/enfocar esa conversación al hacer clic
        notification.set_default_action_and_target(
            "app.open-xmpp", GLib.Variant('s', bare_jid))
        # id = bare JID: mensajes repetidos reemplazan, no se apilan
        self.send_notification(f"xmpp-msg:{bare_jid}", notification)

    def _on_xmpp_subscription_request(self, session, bare_jid):
        """Alguien pide vernos: notificación con Aceptar/Rechazar (T6)."""
        notification = Gio.Notification.new(_("Contact request"))
        notification.set_body(
            _("{jid} wants to add you as a contact.").format(jid=bare_jid))
        notification.add_button(
            _("Accept"), "app.accept-xmpp-sub::" + bare_jid)
        notification.add_button(
            _("Deny"), "app.deny-xmpp-sub::" + bare_jid)
        self.send_notification(f"xmpp-sub:{bare_jid}", notification)

    def _open_xmpp_roster_picker(self, session):
        """Abre una ventana XMPP sin contacto elegido: muestra el roster
        normal (spec 003) en vez de un diálogo modal aparte."""
        self._create_new_window_with_config({}, xmpp_session=session)

    def get_xmpp_session_for_roster(self):
        """Devuelve la sesión XMPP compartida para el roster unificado.

        Si hay cuenta guardada, conecta o reutiliza la sesión. Si no hay
        cuenta, devuelve None para que el roster muestre la acción de
        configuración sin bifurcar la UI.
        """
        from .xmpp_account import load_account
        account = load_account()
        if account is None:
            return None
        jid, password = account
        return self._ensure_xmpp_session(jid, password)

    def open_xmpp_conversation(self, session, bare_jid, window_geometry=None):
        """Abre (o enfoca, si ya existe) la ventana de conversación con un
        contacto XMPP. Spec 002: usado tanto por el picker modal como por
        el roster sidebar."""
        # La conversación se está abriendo/enfocando: retirar cualquier
        # notificación de mensaje pendiente de ese contacto (fix review #1).
        self.withdraw_notification(f"xmpp-msg:{bare_jid}")
        # Envoltorio del camino único (spec 009); el focus-or-open ya lo hace él.
        return self.open_conversation({
            'kind': 'xmpp',
            'session': session,
            'account': session.bare_jid,
            'jid': bare_jid,
            'config': {'_window_geometry': window_geometry},
        })

    def _on_open_xmpp_action(self, action, param):
        """Notificación XMPP clicada: abre/enfoca la conversación con el JID."""
        bare_jid = param.get_string()
        session = getattr(self, '_xmpp_session', None)
        if session is None:
            return
        # Buscar ventana existente para este JID en cualquier sesión.
        # La notificación puede llegar cuando la sesión se reconectó
        # (cambiando resource y, si se usara, account en la key).
        for key, window in list(self._window_by_cid.items()):
            if key.endswith(f":{bare_jid}") and key.startswith("xmpp:"):
                window.present()
                self.withdraw_notification(f"xmpp-msg:{bare_jid}")
                return
        self.open_xmpp_conversation(session, bare_jid)

    def _on_accept_xmpp_sub(self, action, param):
        """Botón 'Aceptar' de una notificación de solicitud de suscripción."""
        session = getattr(self, '_xmpp_session', None)
        if session is not None:
            session.accept_subscription(param.get_string())
        self.withdraw_notification(f"xmpp-sub:{param.get_string()}")

    def _on_deny_xmpp_sub(self, action, param):
        """Botón 'Rechazar' de una notificación de solicitud de suscripción."""
        session = getattr(self, '_xmpp_session', None)
        if session is not None:
            session.deny_subscription(param.get_string())
        self.withdraw_notification(f"xmpp-sub:{param.get_string()}")

    def open_conversation_window(self, config=None):
        """
        Abre una ventana de conversación con la configuración dada.

        Args:
            config (dict, optional): Configuración para la ventana de conversación. 
                                    Puede incluir 'cid', 'model', etc.

        Returns:
            LLMChatWindow: La ventana creada o enfocada
        """
        # Envoltorio del camino único (spec 009): una conversación LLM es un
        # descriptor más, y se abre/enfoca como cualquier otra.
        config = dict(config or {})
        cid = config.pop('cid', None)
        return self.open_conversation({'kind': 'llm', 'cid': cid, 'config': config})

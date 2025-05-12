import json
import os
import re
import signal
import sys
import subprocess

from gi import require_versions
require_versions({"Gtk": "4.0", "Adw": "1"})

from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import locale
import gettext

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from db_operations import ChatHistory

_ = gettext.gettext

DEBUG = os.environ.get('DEBUG') or False

TRAY_PROCESS = None

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


class LLMChatApplication(Adw.Application):
    """Class for a chat instance"""

    def __init__(self, config=None):
        super().__init__(
            application_id="org.fuentelibre.gtk_llm_Chat",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE  # Cambiar para permitir procesar argumentos
        )

        self.tray_process = None  # Subproceso del tray applet

        # Inicializar un registro de ventanas por CID
        self._window_by_cid = {}  # Mapa de CID -> ventana

        # Configuración de inicio
        if config:
            # Verificar si debemos iniciar el applet
            self._applet_mode = dict(config).pop('applet', False)
            debug_print(f"Modo applet: {self._applet_mode}")
        else:
            self._applet_mode = False
            debug_print("Inicializando aplicación sin configuración")

        # Add signal handler
        signal.signal(signal.SIGINT, self._handle_sigint)
        self.connect('shutdown', self.on_shutdown)  # Conectar señal shutdown

        # Windows-specific adjustments
        if sys.platform == "win32":
            settings = Gtk.Settings.get_default()
            if settings:
                settings.set_property('gtk-font-name', 'Segoe UI')


    def _handle_sigint(self, signum, frame):
        """Handles SIGINT signal to close the application"""
        debug_print(_("\nClosing application..."))
        self.quit()

    def do_startup(self):
        Adw.Application.do_startup(self)

        # Manejar instancias múltiples
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

        # Configure the application icon
        self._setup_icon()

        # Configure actions
        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self.on_rename_activate)
        self.add_action(rename_action)

        delete_action = Gio.SimpleAction.new("delete", None)  # Corrected: parameter_type should be None
        delete_action.connect("activate", self.on_delete_activate)
        self.add_action(delete_action)

        about_action = Gio.SimpleAction.new("about", None)  # Corrected: parameter_type should be None
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

    def _start_tray_applet(self):
        """
        Inicia el tray applet en un subproceso si no está ya en ejecución.
        """
        if self.tray_process is not None and self.tray_process.poll() is None:
            debug_print("El applet ya está en ejecución, no se inicia otro")
            return False
            
        try:
            debug_print("Iniciando tray applet...")
            self.tray_process = subprocess.Popen(
                [sys.executable, "gtk_llm_chat/tk_llm_applet.py"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            debug_print(f"Tray applet iniciado con PID: {self.tray_process.pid}")
            return True
        except Exception as e:
            debug_print(f"Error al iniciar el tray applet: {e}")
            self.tray_process = None
            return False

    def _handle_tray_exit(self):
        """
        Monitorea el estado del tray applet y lo reinicia si ha terminado
        inesperadamente.
        """
        if self.tray_process is None:
            return True
            
        # Verificar si el proceso del applet ha terminado
        if self.tray_process.poll() is not None:
            debug_print(f"El tray applet terminó con código: {self.tray_process.returncode}")
            
            # Opcional: Reiniciar el applet si terminó inesperadamente
            if self._applet_mode:
                debug_print("Reiniciando tray applet...")
                self._start_tray_applet()
                
        return True  # Mantener el timer activo

    def on_shutdown(self, app):
        """Handles application shutdown and terminates the tray process."""
        if self.tray_process:
            debug_print("Terminando proceso del applet...")
            self.tray_process.terminate()
            try:
                self.tray_process.wait(timeout=5)
                debug_print("Proceso terminado correctamente.")
            except subprocess.TimeoutExpired:
                debug_print("Proceso no terminó a tiempo, matando a la fuerza.")
                self.tray_process.kill()
                self.tray_process.wait()

    def get_application_version(self):
        """
        Gets the application version from _version.py.
        """
        try:
            from gtk_llm_chat import _version
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
        for arg in args:
            if arg.startswith("--cid="):
                config['cid'] = arg.split("=", 1)[1]
                debug_print(f"CID encontrado en argumentos: {config['cid']}")
            elif arg.startswith("--model="):
                config['model'] = arg.split("=", 1)[1]
            elif arg.startswith("--template="):
                config['template'] = arg.split("=", 1)[1]
        
        # Guardar esta configuración para usarla en do_activate
        self._last_window_config = config
        debug_print(f"Configuración preparada para do_activate: {config}")
        
        # Abrir ventana de conversación con la configuración extraída
        self.open_conversation_window(config)
        
        return 0

    def do_activate(self):
        """Activa la aplicación y crea una nueva ventana utilizando la configuración actual."""
        Adw.Application.do_activate(self)
        debug_print("do_activate invocado")

        # Supervisar el tray applet
        GLib.timeout_add_seconds(1, self._handle_tray_exit)

        # Si estamos en modo applet, solo iniciar el applet sin abrir ventana
        if self._applet_mode:
            debug_print("Ejecutando en modo applet, iniciando el tray applet...")
            self._start_tray_applet()
            self.hold()  # Mantener la aplicación en ejecución
            return

        # Abrir ventana de conversación con la configuración actual
        self.open_conversation_window()

    def _create_new_window_with_config(self, config):
        """Crea una nueva ventana con la configuración dada."""
        debug_print(f"Creando nueva ventana con configuración: {config}")
        
        try:
            from chat_window import LLMChatWindow
            chat_history = ChatHistory()
            
            # Crear la nueva ventana con la configuración
            window = LLMChatWindow(application=self, config=config, chat_history=chat_history)
            window.set_icon_name("org.fuentelibre.gtk_llm_Chat")
            
            # Configurar el manejador de eventos de teclado
            key_controller = Gtk.EventControllerKey()
            key_controller.connect("key-pressed", self._on_key_pressed)
            window.add_controller(key_controller)
            
            # Registrar la ventana por CID si existe
            if 'cid' in config and config['cid']:
                cid = config['cid']
                self._window_by_cid[cid] = window
                debug_print(f"Ventana registrada para CID: {cid}")
                
                # Conectar señal de cierre para eliminar del registro
                def on_window_close(window):
                    if cid in self._window_by_cid:
                        debug_print(f"Eliminando ventana del registro para CID: {cid}")
                        del self._window_by_cid[cid]
                    # Permitir el cierre de la ventana
                    return False
                
                # Conectar después del manejador existente
                window.connect_after("close-request", on_window_close)
            
            # Presentar la ventana
            window.present()
            
            return window
        except Exception as e:
            debug_print(f"Error al crear nueva ventana: {e}")
            import traceback
            debug_print(traceback.format_exc())
            
            # En caso de error, activar la ventana normalmente
            self.activate()
            return None

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
        window.header.set_title_widget(window.title_entry)
        window.title_entry.grab_focus()

    def on_delete_activate(self, action, param):
        """Deletes the current conversation"""
        window = self.get_active_window()
        
        # Verificar que tenemos una ventana y acceder a su configuración
        if not window or not hasattr(window, 'config'):
            debug_print("No se puede eliminar: ventana inválida o sin configuración")
            return
            
        dialog = Gtk.MessageDialog(
            transient_for=window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Are you sure you want to delete the conversation?")
        )

        def on_delete_response(dialog, response):
            if response == Gtk.ResponseType.YES and hasattr(window, 'chat_history'):
                cid = window.config.get('cid')
                debug_print(f"Eliminando conversación con CID: {cid}")
                if cid:
                    window.chat_history.delete_conversation(cid)
                    
                    # Verificar si hay más ventanas abiertas
                    other_windows = [w for w in self.get_windows() if w != window]
                    
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

    def open_conversation_window(self, config=None):
        """
        Abre una ventana de conversación con la configuración dada.
        Si no se proporciona configuración, usa la última configuración conocida.
        
        Args:
            config (dict, optional): Configuración para la ventana de conversación. 
                                    Puede incluir 'cid', 'model', etc.
        
        Returns:
            LLMChatWindow: La ventana creada o enfocada
        """
        # Asegurar que tenemos una configuración
        config = config or {}
        
        # Evitar que se abra una ventana de applet
        conversation_config = dict(config)
        if 'applet' in conversation_config:
            conversation_config.pop('applet')
        
        # Si hay un CID específico en la configuración
        if 'cid' in conversation_config:
            cid = conversation_config['cid']
            debug_print(f"Abriendo ventana con CID específico: {cid}")
            
            # Verificar si ya existe una ventana registrada para este CID
            if cid in self._window_by_cid:
                window = self._window_by_cid[cid]
                if window.is_visible():
                    debug_print(f"Se encontró ventana registrada para CID {cid}, activándola")
                    window.present()
                    return window
                else:
                    # Si la ventana existe pero no es visible, eliminarla del registro
                    debug_print(f"La ventana para CID {cid} no es visible, eliminando del registro")
                    del self._window_by_cid[cid]
            
            # Si no existe una ventana para este CID o no es visible, crear una nueva
            debug_print(f"Creando nueva ventana para CID: {cid}")
            return self._create_new_window_with_config(conversation_config)
            
        else:
            # Si no hay CID específico, verificar si hay ventanas abiertas
            active_window = self.get_active_window()
            if active_window and active_window.is_visible():
                debug_print("Presentando ventana activa existente (sin CID específico)")
                active_window.present()
                return active_window
            else:
                # Crear una nueva ventana sin CID específico
                debug_print("Creando nueva ventana sin CID específico")
                return self._create_new_window_with_config(conversation_config)


import json
import os
import re
import signal
import sys
import subprocess
import threading

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


# Reemplazar la definición de la interfaz D-Bus con XML
DBUS_INTERFACE_XML = """
<node>
  <interface name='org.fuentelibre.ChatApplication'>
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

        self.tray_process = None  # Subproceso del tray applet
        self._shutting_down = False  # Bandera para controlar proceso de cierre

        # Inicializar un registro de ventanas por CID
        self._window_by_cid = {}  # Mapa de CID -> ventana

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

    # Simplificar el registro D-Bus con un enfoque más directo
    def do_startup(self):
        Adw.Application.do_startup(self)

        # Configurar D-Bus usando Gio
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # Obtener la información de la interfaz
        node_info = Gio.DBusNodeInfo.new_for_xml(DBUS_INTERFACE_XML)
        interface_info = node_info.interfaces[0]
        
        # Crear una función manejadora para métodos D-Bus
        def method_call_handler(connection, sender, object_path, interface_name, method_name, parameters, invocation):
            if method_name == "OpenConversation":
                cid = parameters.unpack()[0]
                self.OpenConversation(cid)
                invocation.return_value(None)
            else:
                invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Método desconocido")
        
        # Registrar la interfaz D-Bus
        reg_id = connection.register_object(
            '/org/fuentelibre/ChatApplication',
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

        # Setup system tray applet
        GLib.idle_add(self._start_tray_applet)

        # Supervisar el tray applet
        GLib.timeout_add_seconds(1, self._handle_tray_exit)

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

    def OpenConversation(self, cid):
        """Abrir una nueva conversación dado un CID"""
        if cid not in self._window_by_cid:
            # Crear y registrar una nueva ventana
            window = self.create_chat_window(cid)
            self._window_by_cid[cid] = window
            window.show()
        else:
            # Enfocar la ventana existente
            self._window_by_cid[cid].present()

    def create_chat_window(self, cid):
        """Crear una nueva ventana de chat"""
        # Implementación para crear una ventana de chat
        pass

    def _start_tray_applet(self):
        """
        Inicia el tray applet en un subproceso si no está ya en ejecución.
        """
        if self.tray_process is not None and self.tray_process.poll() is None:
            debug_print("El applet ya está en ejecución, no se inicia otro")
            return False
            
        debug_print("Iniciando tray applet...")

        try:
            from gtk_llm_applet import main
            # Usamos el adaptador para tener un hilo con API de proceso
            self.tray_process = ThreadToProcessAdapter(target_func=main)
            self.tray_process.start()
            debug_print(f"Tray applet iniciado como hilo adaptado con PID simulado: {self.tray_process.pid}")
            return False
        except Exception as e:
            debug_print(f"Error al iniciar el tray applet como hilo: {e}")
            # Si falla, continuamos con el método de proceso


        args = []
        if getattr(sys, 'frozen', False):
                executable = "gtk-llm-applet"
                if sys.platform == "win32":
                    executable += ".exe"
                elif sys.platform == "linux" and os.environ.get('_PYI_ARCHIVE_FILE'):
                    if os.environ.get('APPIMAGE'):
                        debug_print('Error fatal, imposible hacer el icono')
                        executable = os.environ.get('APPIMAGE')
                        args = ['--legacy-applet']
        else:
            executable = sys.executable
            args += [os.path.join("gtk_llm_chat", "gtk_llm_applet.py")]

        try:
            self.tray_process = subprocess.Popen(
                [executable] + args,
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            debug_print(f"Tray applet iniciado con PID: {self.tray_process.pid}")
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
            
        # Verificar si el proceso/hilo del applet ha terminado
        poll_result = self.tray_process.poll()
        if poll_result is not None:
            debug_print(f"El tray applet terminó con código: {self.tray_process.returncode}")
            # Reiniciar solo si el código no es 0 y no estamos en proceso de cierre
            if self.tray_process.returncode != 0 and not getattr(self, '_shutting_down', False):
                debug_print("Reiniciando el tray applet...")
                GLib.idle_add(self._start_tray_applet)
            else:
                debug_print("El tray applet terminó normalmente o estamos en proceso de cierre.")
                
        return True  # Mantener el timer activo

    def on_shutdown(self, app):
        """Handles application shutdown and unregisters D-Bus."""
        # Establecer bandera para evitar que se reinicie el applet durante el cierre
        self._shutting_down = True
        
        if self.tray_process:
            debug_print("Terminando proceso/hilo del applet...")
            try:
                self.tray_process.terminate()
                try:
                    self.tray_process.wait(timeout=5)
                    debug_print("Applet terminado correctamente.")
                except subprocess.TimeoutExpired:
                    debug_print("Applet no terminó a tiempo, intentando con kill().")
                    self.tray_process.kill()
                    self.tray_process.wait()
            except Exception as e:
                debug_print(f"Excepción al terminar el applet: {e}")

        if hasattr(self, 'dbus_registration_id'):
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.unregister_object(self.dbus_registration_id)

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
        only_applet = False
        legacy_applet = False
        for arg in args:
            if arg.startswith("--cid="):
                config['cid'] = arg.split("=", 1)[1]
                debug_print(f"CID encontrado en argumentos: {config['cid']}")
            elif arg.startswith("--model="):
                config['model'] = arg.split("=", 1)[1]
            elif arg.startswith("--template="):
                config['template'] = arg.split("=", 1)[1]
            elif arg.startswith("--applet"):
                only_applet = True
            elif arg.startswith("--legacy-applet"):
                legacy_applet = True
        
        # Guardar esta configuración para usarla en do_activate
        debug_print(f"Configuración preparada para do_activate: {config}")
        
        # Abrir ventana de conversación con la configuración extraída
        if not only_applet:
            self.open_conversation_window(config)
        if legacy_applet:
            self._applet_loaded = True
        
        return 0

    def do_activate(self):
        """Activa la aplicación y crea una nueva ventana utilizando la configuración actual."""
        Adw.Application.do_activate(self)
        debug_print("do_activate invocado")

        if not hasattr(self, '_applet_loaded'):
            # Setup system tray applet
            GLib.idle_add(self._start_tray_applet)

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


class ThreadToProcessAdapter:
    """
    Adapta un objeto Thread para que exponga una API similar a un objeto Process.
    Esto permite usar hilos con un código que espera interactuar con procesos.
    """
    def __init__(self, target_func, daemon=True, **kwargs):
        """
        Inicializa el adaptador creando un Thread interno.
        
        Args:
            target_func: La función que debe ejecutar el hilo
            daemon: Si el hilo debe ser daemon (termina cuando el programa principal termina)
            **kwargs: Argumentos adicionales para el constructor del Thread
        """
        self._thread = threading.Thread(target=target_func, daemon=daemon, **kwargs)
        self._is_running = False
        self._returncode = None
        self.pid = hash(self._thread)  # Simular un ID de proceso
    
    def start(self):
        """Inicia el hilo y actualiza el estado interno."""
        self._thread.start()
        self._is_running = True
    
    def poll(self):
        """
        Simula el comportamiento de poll() de un proceso.
        
        Returns:
            None si el hilo está en ejecución, o un código de retorno si ha terminado.
        """
        if self._is_running and not self._thread.is_alive():
            self._is_running = False
            self._returncode = 0  # Asume que el hilo terminó normalmente
            return self._returncode
        
        return None if self._is_running else self._returncode
    
    def terminate(self):
        """
        Simula el comportamiento de terminate() de un proceso.
        
        Como los hilos en Python no se pueden terminar de manera forzada,
        esto simplemente registra la intención (los hilos daemon terminarán
        cuando el programa principal termine).
        """
        debug_print("Thread no puede ser terminado directamente. Se marca para terminar.")
        self._is_running = False
        self._returncode = 0  # Simula una terminación "exitosa"
    
    def kill(self):
        """Simula el comportamiento de kill() de un proceso. Similar a terminate()."""
        self.terminate()
    
    def wait(self, timeout=None):
        """
        Simula el comportamiento de wait() de un proceso.
        
        Args:
            timeout: Tiempo máximo de espera en segundos
        
        Returns:
            El código de retorno del hilo
        
        Raises:
            subprocess.TimeoutExpired: Si el timeout se alcanza
        """
        self._thread.join(timeout)
        
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired("Thread", timeout)
        
        self._is_running = False
        self._returncode = 0  # Asume que el hilo terminó normalmente
        return self._returncode
    
    @property
    def returncode(self):
        """Simula la propiedad returncode de un proceso."""
        if self._is_running and not self._thread.is_alive():
            self._is_running = False
            self._returncode = 0
        
        return self._returncode
    
    def is_alive(self):
        """Comprueba si el hilo está en ejecución."""
        return self._thread.is_alive()


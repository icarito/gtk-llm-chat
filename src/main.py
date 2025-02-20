import sys
import gi
from datetime import datetime

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib

class Message:
    def __init__(self, content, sender="user", timestamp=None):
        self.content = content
        self.sender = sender
        self.timestamp = timestamp or datetime.now()

class MessageWidget(Gtk.Box):
    """Widget para mostrar un mensaje individual"""
    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        
        # Configurar el estilo según el remitente
        is_user = message.sender == "user"
        self.add_css_class('message')
        self.add_css_class('user-message' if is_user else 'assistant-message')
        
        # Configurar alineación
        self.set_halign(Gtk.Align.END if is_user else Gtk.Align.START)
        self.set_margin_start(50 if is_user else 6)
        self.set_margin_end(6 if is_user else 50)
        self.set_margin_top(3)
        self.set_margin_bottom(3)
        
        # Crear el contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('message-content')
        
        # Agregar el texto del mensaje
        label = Gtk.Label(label=message.content)
        label.set_wrap(True)
        label.set_selectable(True)
        label.set_xalign(0)
        message_box.append(label)
        
        # Agregar timestamp
        time_label = Gtk.Label(
            label=message.timestamp.strftime("%H:%M"),
            css_classes=['timestamp']
        )
        time_label.set_halign(Gtk.Align.END)
        message_box.append(time_label)
        
        self.append(message_box)

class LLMChatApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.gnome.LLMChat",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        
    def do_activate(self):
        # Crear una nueva ventana para esta instancia
        window = LLMChatWindow(application=self)
        window.present()

class LLMChatWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Configurar la ventana principal
        self.set_title("LLM Chat")
        self.set_default_size(600, 700)
        
        # Contenedor principal
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        # ScrolledWindow para el historial de mensajes
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Contenedor para mensajes
        self.messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
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
        send_button = Gtk.Button(label="Enviar")
        send_button.connect('clicked', self._on_send_clicked)
        send_button.add_css_class('suggested-action')
        
        # Ensamblar la interfaz
        input_box.append(self.input_text)
        input_box.append(send_button)
        
        main_box.append(scroll)
        main_box.append(input_box)
        
        self.set_content(main_box)
        
        # Agregar cola de mensajes
        self.message_queue = []
        
        # Agregar CSS provider
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data("""
            .message { padding: 8px; }
            .message-content { padding: 6px; }
            
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
        """.encode())
        
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
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
            
            # Crear y mostrar el widget del mensaje
            message_widget = MessageWidget(message)
            self.messages_box.append(message_widget)
            
            # Auto-scroll al último mensaje
            self._scroll_to_bottom()
            
            print(f"[{message.timestamp}] {message.sender}: {message.content}")
            return True
        return False
    
    def _on_send_clicked(self, button):
        buffer = self.input_text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        
        if self._add_message_to_queue(text):
            # Limpiar el buffer de entrada
            buffer.set_text("")
    
    def _scroll_to_bottom(self):
        """Desplaza la vista al último mensaje"""
        def scroll_after():
            adj = self.messages_box.get_parent().get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
        # Programar el scroll para después de que se actualice el layout
        GLib.idle_add(scroll_after)

def main():
    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main()) 
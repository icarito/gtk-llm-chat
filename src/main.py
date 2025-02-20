import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk

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
    
    def _on_send_clicked(self, button):
        buffer = self.input_text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        if text.strip():
            # TODO: Implementar el envío del mensaje
            buffer.set_text("")

def main():
    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main()) 
import sys
from gi.repository import Gtk, Adw, Gio

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
        
        # Configurar el contenido inicial (vacío por ahora)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(content)

def main():
    # Inicializar Libadwaita
    Adw.init()
    
    # Crear y ejecutar la aplicación
    app = LLMChatApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main()) 
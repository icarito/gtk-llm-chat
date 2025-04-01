import gi
import os
import sys
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from markdownview import MarkdownView


class Message:
    """
    Representa un mensaje
    """

    def __init__(self, content, sender="user", timestamp=None):
        self.content = content
        self.sender = sender
        self.timestamp = timestamp or datetime.now()


class ErrorWidget(Gtk.Box):
    """Widget para mostrar mensajes de error"""

    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.get_style_context().add_class('error-message')
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(3)
        self.set_margin_bottom(3)

        # Icono de advertencia
        icon = Gtk.Image()
        icon.set_from_icon_name("dialog-warning", Gtk.IconSize.MENU)
        icon_style = icon.get_style_context()
        icon_style.add_class("error-icon")
        self.add(icon)

        # Contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box_style = message_box.get_style_context()
        message_box_style.add_class("error-content")

        # Texto del error
        label = Gtk.Label(label=message)
        label.set_xalign(0)
        message_box.add(label)

        self.add(message_box)


class MessageWidget(Gtk.Box):
    """Widget para mostrar un mensaje individual"""

    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        # Configurar el estilo según el remitente
        is_user = message.sender == "user"
        self.get_style_context().add_class('message')
        self.get_style_context().add_class(
            'user-message' if is_user else 'assistant-message'
        )

        # Crear un contenedor con margen para centrar el contenido
        margin_box = Gtk.HBox()
        margin_box.set_hexpand(True)

        # Crear el contenedor del mensaje
        message_box = Gtk.VBox(spacing=3)
        message_box_style = message_box.get_style_context()
        message_box_style.add_class("message-content")
        message_box.set_hexpand(True)

        # Agregar espaciadores flexibles a los lados
        if is_user:
            left_spacer = Gtk.Box()
            left_spacer.set_hexpand(True)
            margin_box.add(left_spacer)  # Espaciador izquierdo
            margin_box.add(message_box)
            # Espaciador derecho pequeño
            margin_box.add(Gtk.Box(hexpand=False))
        else:
            # Espaciador izquierdo pequeño
            margin_box.add(Gtk.Box(hexpand=False))
            margin_box.add(message_box)
            margin_box.add(Gtk.Box(hexpand=True))  # Espaciador derecho

        # Quitar el prefijo "user:" si existe
        content = message.content
        if is_user and content.startswith("user:"):
            content = content[5:].strip()

        # Usar MarkdownView para el contenido
        self.content_view = MarkdownView()
        self.content_view.set_size_request(200, -1)  # Asegurar tamaño mínimo en GTK3
        self.content_view.set_hexpand(True)
        self.content_view.set_markdown(content)
        message_box.add(self.content_view)

        # Agregar timestamp
        time_label = Gtk.Label(
            label=message.timestamp.strftime("%H:%M"))
        time_label.set_halign(Gtk.Align.END)
        message_box.add(time_label)

        self.add(margin_box)

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.content_view.set_markdown(new_content)


if __name__ == "__main__":
    import gi
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk

    css_provider = Gtk.CssProvider()
    css_path = os.path.join(os.path.dirname(__file__), "styles", "gtk-llm.css")
    css_provider.load_from_path(css_path)
    screen = Gdk.Screen.get_default()
    Gtk.StyleContext.add_provider_for_screen(
        screen,
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    win = Gtk.Window(title="Ejemplo de Widgets")
    win.set_default_size(400, 300)

    box = Gtk.VBox()
    win.add(box)

    ejemplo_msg_user = Message("Hola, soy el usuario", "user")
    ejemplo_msg_assistant = Message("Hola, soy el asistente", "assistant")

    box.pack_start(MessageWidget(ejemplo_msg_user), False, False, 0)
    box.pack_start(MessageWidget(ejemplo_msg_assistant), False, False, 0)

    box.pack_start(ErrorWidget("Este es un mensaje de error"), False, False, 0)

    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


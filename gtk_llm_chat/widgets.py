import gi
import os
import sys
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


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

        self.add_css_class('error-message')
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(3)
        self.set_margin_bottom(3)

        # Icono de advertencia
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.add_css_class('error-icon')
        self.append(icon)

        # Contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('error-content')

        # Texto del error
        label = Gtk.Label(label=message)
        label.set_wrap(True)
        label.set_xalign(0)
        message_box.append(label)

        self.append(message_box)


class MessageWidget(Gtk.Box):
    """Widget para mostrar un mensaje individual"""

    def __init__(self, message):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        # Import MarkdownView here
        from markdownview import MarkdownView

        # Configurar el estilo según el remitente
        is_user = message.sender == "user"
        self.add_css_class('message')
        self.add_css_class('user-message' if is_user else 'assistant-message')

        # Crear un contenedor con margen para centrar el contenido
        margin_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        margin_box.set_hexpand(True)

        # Crear el contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('message-content')
        message_box.set_hexpand(True)

        # Agregar espaciadores flexibles a los lados
        if is_user:
            margin_box.append(Gtk.Box(hexpand=True))  # Espaciador izquierdo
            margin_box.append(message_box)
            # Espaciador derecho pequeño
            margin_box.append(Gtk.Box(hexpand=False))
        else:
            # Espaciador izquierdo pequeño
            margin_box.append(Gtk.Box(hexpand=False))
            margin_box.append(message_box)
            margin_box.append(Gtk.Box(hexpand=True))  # Espaciador derecho

        # Quitar el prefijo "user:" si existe
        content = message.content
        if is_user and content.startswith("user:"):
            content = content[5:].strip()

        # Usar MarkdownView para el contenido
        self.content_view = MarkdownView()
        self.content_view.set_hexpand(True)
        self.content_view.set_markdown(content)
        message_box.append(self.content_view)

        # Agregar timestamp
        time_label = Gtk.Label(
            label=message.timestamp.strftime("%H:%M"),
            css_classes=['timestamp']
        )
        time_label.set_halign(Gtk.Align.END)
        message_box.append(time_label)

        self.append(margin_box)

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.content_view.set_markdown(new_content)

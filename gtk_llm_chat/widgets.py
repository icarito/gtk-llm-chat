import gi
import os
import sys
import re
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Pango
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from .resource_manager import resource_manager

DEBUG = os.environ.get('DEBUG') or False


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

class Message:
    """
    Representa un mensaje
    """

    def __init__(self, content, sender="user", timestamp=None):
        self.content = self.compact_blank_lines(content)
        self.sender = sender
        self.timestamp = timestamp or datetime.now()

    @staticmethod
    def compact_blank_lines(content):
        text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r'\n[ \t]+\n', '\n\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


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
        icon = resource_manager.create_icon_widget("dialog-warning-symbolic")
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

    def __init__(self, message, use_markdown=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.message = message
        self.use_markdown = use_markdown

        # Import MarkdownView here
        from .markdownview import MarkdownView

        # Configurar el estilo según el remitente
        is_user = message.sender == "user"
        self.add_css_class('message')
        self.add_css_class('user-message' if is_user else 'assistant-message')

        # Crear un contenedor con margen para centrar el contenido
        margin_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        margin_box.set_hexpand(True)
        margin_box.set_size_request(180, -1)

        # Crear el contenedor del mensaje
        message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        message_box.add_css_class('message-content')
        message_box.set_hexpand(True)
        message_box.set_size_request(180, -1)

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

        self.content_view = None
        self.content_label = None
        if self.use_markdown:
            # Usar MarkdownView para el contenido
            self.content_view = MarkdownView()
            self.content_view.set_hexpand(True)
            self.content_view.set_size_request(167, -1)  # El warning pedía al menos 167
            self.content_view.set_markdown(content)
            message_box.append(self.content_view)
        else:
            # En XMPP las burbujas son mayormente texto plano; Label evita
            # costes de relayout de TextView y mejora la aparición inmediata.
            self.content_label = Gtk.Label()
            self.content_label.set_wrap(True)
            self.content_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.content_label.set_xalign(0.0)
            self.content_label.set_selectable(True)
            self.content_label.set_hexpand(True)
            self.content_label.set_label(content)
            message_box.append(self.content_label)

        # Agregar timestamp
        time_label = Gtk.Label(
            label=message.timestamp.strftime("%H:%M"),
            css_classes=['timestamp']
        )
        time_label.set_halign(Gtk.Align.END)
        time_label.set_size_request(60, -1)
        message_box.append(time_label)
        self.message_box = message_box
        self._quick_response_row = None

        self.append(margin_box)

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.message.content = Message.compact_blank_lines(new_content)
        debug_print(
            f"[widget] update_content sender={self.message.sender} "
            f"len={len(self.message.content)}")
        if self.content_view is not None:
            self.content_view.set_markdown(self.message.content)
        elif self.content_label is not None:
            self.content_label.set_label(self.message.content)
        # El TextView puede crecer en varios pasos (wrap + markdown). Sin pedir
        # relayout explícito, el ScrolledWindow a veces deja `upper` viejo hasta
        # la próxima interacción del usuario.
        if self.content_view is not None:
            self.content_view.queue_resize()
        if self.content_label is not None:
            self.content_label.queue_resize()
        self.message_box.queue_resize()
        self.queue_resize()
        parent = self.get_parent()
        if parent is not None:
            parent.queue_resize()
            debug_print("[widget] queued parent resize")
            # Subir hasta la raíz para asegurar que el ScrolledWindow
            # recalcule el rango aunque no haya interacción del usuario.
            ancestor = parent
            while ancestor is not None:
                ancestor.queue_resize()
                ancestor = ancestor.get_parent()

    def add_quick_responses(self, responses, on_selected):
        """Adjunta botones de respuesta rápida a esta burbuja."""
        if not responses:
            return
        flow = Gtk.FlowBox()
        flow.set_margin_top(6)
        flow.set_max_children_per_line(99)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_halign(Gtk.Align.FILL)
        flow.set_valign(Gtk.Align.START)
        flow.add_css_class("quick-responses")

        buttons = []

        def handle_click(_button, response):
            for btn in buttons:
                btn.set_sensitive(False)
            on_selected(response)

        for response in responses:
            label = response.get('label') or response.get('name') or response.get('value', '')
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
            button.connect("clicked", handle_click, response)
            flow.append(button)
            buttons.append(button)

        self.message_box.append(flow)
        self._quick_response_row = flow

    def hide_quick_responses(self):
        if self._quick_response_row is not None:
            self.message_box.remove(self._quick_response_row)
            self._quick_response_row = None

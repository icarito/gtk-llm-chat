import gi
import os
import sys
import re
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GLib, Gtk, Pango
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from .resource_manager import resource_manager

DEBUG = os.environ.get('DEBUG') or False


def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


# URL suelta en el texto (para autoenlazar y para detectar adjuntos).
URL_RE = re.compile(r'https?://[^\s<>"\']+')
IMAGE_EXT_RE = re.compile(
    r'\.(png|jpe?g|gif|webp|bmp|heic|heif|avif)(\?|#|$)', re.IGNORECASE)


def _first_image_url(content):
    """Primera URL del texto que apunte a una imagen, o None.

    Los adjuntos de XEP-0363 llegan como una URL (en el body y en el OOB);
    si es una imagen, la burbuja muestra un preview además del link."""
    for match in URL_RE.finditer(content or ''):
        url = match.group(0)
        if IMAGE_EXT_RE.search(url):
            return url
    return None


def _load_picture_async(picture, url):
    """Descarga la imagen en un hilo y la pinta cuando llega.

    En un hilo porque urlopen bloquea; el widget se toca sólo desde el hilo
    principal vía GLib.idle_add. Si falla, se deja el preview vacío y el link
    del cuerpo sigue sirviendo."""
    import threading
    import urllib.request

    def work():
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
        except Exception as exc:
            debug_print(f"[widget] no se pudo descargar {url}: {exc}")
            GLib.idle_add(lambda: (picture.set_visible(False),
                                   GLib.SOURCE_REMOVE)[1])
            return

        def apply():
            try:
                from gi.repository import Gdk, Gio
                stream = Gio.MemoryInputStream.new_from_bytes(
                    GLib.Bytes.new(data))
                texture = Gdk.Texture.new_from_stream(stream)
                picture.set_paintable(texture)
            except Exception as exc:
                debug_print(f"[widget] imagen inválida {url}: {exc}")
                picture.set_visible(False)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(apply)

    threading.Thread(target=work, daemon=True).start()


def _on_activate_link(_label, uri):
    """Abre el link en el navegador/visor del sistema."""
    try:
        Gtk.UriLauncher.new(uri).launch(None, None, None, None)
    except Exception as exc:
        debug_print(f"[widget] no se pudo abrir {uri}: {exc}")
    return True  # consumido: no dejar que GTK lo intente otra vez


def _autolink(markup):
    """Convierte URLs sueltas en <a href> dentro de un markup de Pango.

    Se aplica DESPUÉS de generar el markup, saltándose lo que ya está dentro
    de un <a ...>...</a> para no anidar enlaces (Pango lo rechaza)."""
    out = []
    last = 0
    # Tramos que ya son un enlace: no tocarlos.
    linked = [(m.start(), m.end())
              for m in re.finditer(r'<a\s[^>]*>.*?</a>', markup, re.DOTALL)]

    def inside_link(pos):
        return any(start <= pos < end for start, end in linked)

    for match in URL_RE.finditer(markup):
        if inside_link(match.start()):
            continue
        url = match.group(0)
        out.append(markup[last:match.start()])
        out.append(f'<a href="{url}">{url}</a>')
        last = match.end()
    out.append(markup[last:])
    return ''.join(out)


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

        # Un único Gtk.Label para markdown (vía Pango markup) y texto plano.
        # Un Label mide su alto real de forma síncrona; el GtkTextView del
        # viejo MarkdownView reportaba una altura basura hasta validar su
        # layout en un idle posterior (a veces 0 -> burbuja colapsada que
        # sólo aparecía con el próximo relayout; a veces varias veces la
        # real -> burbujón de espacio vacío que dejaba el mensaje fuera del
        # viewport). Toda la "tormenta" de queue_draw/queue_resize y el
        # scroll que se quedaba corto venían de ahí.
        self.content_view = None
        self.content_plain_view = None
        # Adjunto de imagen: preview encima del texto. El link sigue estando
        # en el cuerpo (clicable), así que si la descarga falla no se pierde.
        self._attachment_picture = None
        image_url = _first_image_url(content)
        if image_url:
            self._attachment_picture = Gtk.Picture()
            self._attachment_picture.set_can_shrink(True)
            self._attachment_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self._attachment_picture.set_size_request(-1, 180)
            self._attachment_picture.add_css_class('attachment-image')
            message_box.append(self._attachment_picture)
            _load_picture_async(self._attachment_picture, image_url)

        self.content_label = Gtk.Label()
        self.content_label.set_wrap(True)
        self.content_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.content_label.set_xalign(0.0)
        self.content_label.set_selectable(True)
        self.content_label.set_hexpand(True)
        # Abrir links (markdown y URLs sueltas autoenlazadas) en el navegador.
        self.content_label.connect('activate-link', _on_activate_link)
        self._set_label_content(content)
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

    def _set_label_content(self, content):
        """Pinta `content` en el label — markdown como Pango markup, o texto
        plano. El markup generado es balanceado por construcción, pero ante
        cualquier sorpresa se degrada a texto plano en vez de a un label
        vacío (set_markup inválido no pinta nada)."""
        if self.use_markdown:
            from .pango_markdown import markdown_to_pango
            markup = _autolink(markdown_to_pango(content))
            try:
                Pango.parse_markup(markup, -1, '\x00')
                self.content_label.set_markup(markup)
                return
            except GLib.Error:
                debug_print("[widget] markup inválido; fallback a texto plano")
        # Texto plano: aun así autoenlazar las URLs (los adjuntos llegan como
        # una URL suelta). Se escapa primero para que el markup sea válido.
        escaped = GLib.markup_escape_text(content or '')
        markup = _autolink(escaped)
        try:
            Pango.parse_markup(markup, -1, '\x00')
            self.content_label.set_markup(markup)
            return
        except GLib.Error:
            debug_print("[widget] autolink inválido; texto plano tal cual")
        self.content_label.set_text(content)

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.message.content = Message.compact_blank_lines(new_content)
        debug_print(
            f"[widget] update_content sender={self.message.sender} "
            f"len={len(self.message.content)}")
        self._set_label_content(self.message.content)
        # Cambiar el label ya invalida el layout del widget; no hace falta
        # propagar queue_resize a mano (GTK4 lo hace hacia arriba).

    def add_quick_responses(self, responses, on_selected):
        """Adjunta botones de respuesta rápida a esta burbuja."""
        if not responses:
            return
        self.hide_quick_responses()
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

        # Mapea el hint de estilo del servidor (primary|secondary|success|
        # danger, igual que los botones de Telegram) a clases CSS propias
        # (qr-*), definidas en style_manager con background explícito para que
        # pinten de forma fiable sobre el botón .pill. Sin style => "pill".
        style_classes = {
            'primary': 'qr-primary',
            'danger': 'qr-danger',
            'success': 'qr-success',
            'secondary': 'qr-secondary',
        }
        for response in responses:
            label = response.get('label') or response.get('name') or response.get('value', '')
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
            style = response.get('style')
            extra_class = style_classes.get(style) if style else None
            if extra_class:
                button.add_css_class(extra_class)
            button.connect("clicked", handle_click, response)
            flow.append(button)
            buttons.append(button)

        self.message_box.append(flow)
        self._quick_response_row = flow

    def hide_quick_responses(self):
        if self._quick_response_row is not None:
            self.message_box.remove(self._quick_response_row)
            self._quick_response_row = None

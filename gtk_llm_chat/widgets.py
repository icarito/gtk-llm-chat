import gi
import os
import sys
import re
import urllib.parse
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Adw', '1')
from gi.repository import Gdk, GLib, Gtk, Pango
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
TRAILING_URL_PUNCT = '.,;:!?)]]}'


def _first_image_url(content):
    """Primera URL del texto que apunte a una imagen, o None.

    Los adjuntos de XEP-0363 llegan como una URL (en el body y en el OOB);
    si es una imagen, la burbuja muestra un preview además del link."""
    for match in URL_RE.finditer(content or ''):
        url = match.group(0).rstrip(TRAILING_URL_PUNCT)
        if IMAGE_EXT_RE.search(url):
            return url
    return None


def _attachment_filename(url):
    path = urllib.parse.urlparse(url or '').path
    name = urllib.parse.unquote(os.path.basename(path))
    return name or 'image'


def _content_without_attachment_url(content, image_url):
    """Quita del texto la URL que ya se muestra como preview."""
    if not image_url:
        return content
    text = content or ''
    for match in URL_RE.finditer(text):
        url = match.group(0)
        clean_url = url.rstrip(TRAILING_URL_PUNCT)
        if clean_url != image_url:
            continue
        stripped = f"{text[:match.start()]}{text[match.end():]}"
        stripped = re.sub(r'[ \t]+([,.;:!?])', r'\1', stripped)
        stripped = re.sub(r'\s+[)\]}]+(?=\s|$)', '', stripped)
        stripped = re.sub(r'(?m)^[ \t]+|[ \t]+$', '', stripped)
        stripped = re.sub(r'\n{3,}', '\n\n', stripped).strip()
        return _remove_attachment_label(stripped)
    return text


def _remove_attachment_label(content):
    """Quita etiquetas genéricas de adjunto cuando ya hay preview."""
    return re.sub(r'^\[Photo\]\s*[^:\n]*:\s*$', '', content or '',
                  flags=re.IGNORECASE).strip()


CODE_FENCE_RE = re.compile(r'```([^\n`]*)\n?([\s\S]*?)```')


def _split_code_fences(content):
    """Devuelve fragmentos ('text'|'code', language, content) preservando orden."""
    parts = []
    pos = 0
    for match in CODE_FENCE_RE.finditer(content or ''):
        if match.start() > pos:
            parts.append(('text', '', content[pos:match.start()]))
        # El info-string puede venir vacío (``` sin lenguaje): split() da []
        # y [0] reventaba. Tomamos el primer token si lo hay, si no ''.
        language_tokens = (match.group(1) or '').strip().split()
        language = language_tokens[0] if language_tokens else ''
        code = match.group(2) or ''
        parts.append(('code', language, code.rstrip('\n')))
        pos = match.end()
    if pos < len(content or ''):
        parts.append(('text', '', (content or '')[pos:]))
    return parts or [('text', '', content or '')]


def _texture_from_bytes(data):
    """Crea una Gdk.Texture desde bytes de imagen descargados."""
    from gi.repository import Gdk, GdkPixbuf

    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        raise ValueError("image data did not produce a pixbuf")
    return Gdk.Texture.new_for_pixbuf(pixbuf)


def _load_picture_async(picture, url, on_loaded=None):
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
                texture = _texture_from_bytes(data)
                picture.set_paintable(texture)
                picture.set_visible(True)
                if on_loaded:
                    on_loaded(texture, data)
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


class ImagePreviewDialog(Gtk.Window):
    """Popup simple de imagen con fit por defecto, zoom y pan."""

    MIN_ZOOM = 0.1
    MAX_ZOOM = 8.0

    def __init__(self, parent, texture, url=None, data=None):
        super().__init__(title="Image preview")
        if isinstance(parent, Gtk.Window):
            self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(900, 700)
        self.texture = texture
        self.url = url
        self.data = data
        self.zoom = 1.0
        self.fit_mode = True

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)

        header = Gtk.HeaderBar()
        root.append(header)

        zoom_out = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        zoom_out.set_tooltip_text("Zoom out")
        zoom_out.connect("clicked", lambda *_: self._set_zoom(self.zoom / 1.25))
        header.pack_start(zoom_out)

        zoom_in = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        zoom_in.set_tooltip_text("Zoom in")
        zoom_in.connect("clicked", lambda *_: self._set_zoom(self.zoom * 1.25))
        header.pack_start(zoom_in)

        fit = Gtk.Button.new_from_icon_name("zoom-fit-best-symbolic")
        fit.set_tooltip_text("Fit to window")
        fit.connect("clicked", lambda *_: self._fit_to_window())
        header.pack_start(fit)

        if data:
            save_button = Gtk.Button.new_from_icon_name("document-save-symbolic")
            save_button.set_tooltip_text("Save image")
            save_button.connect("clicked", self._on_save_clicked)
            header.pack_end(save_button)

        if url:
            open_button = Gtk.Button.new_from_icon_name("document-open-symbolic")
            open_button.set_tooltip_text("Open link")
            open_button.connect("clicked", lambda *_: _on_activate_link(None, url))
            header.pack_end(open_button)

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)
        root.append(self.scrolled)

        self.picture = Gtk.Picture.new_for_paintable(texture)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_can_shrink(True)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.add_css_class("image-preview-picture")
        self.scrolled.set_child(self.picture)

        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_click)
        self.picture.add_controller(click)

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.picture.add_controller(drag)
        self._drag_start_h = 0.0
        self._drag_start_v = 0.0

    def _on_click(self, _gesture, n_press, _x, _y):
        if n_press == 2:
            if self.fit_mode:
                self._set_zoom(1.0)
            else:
                self._fit_to_window()

    def _on_drag_begin(self, *_args):
        hadj = self.scrolled.get_hadjustment()
        vadj = self.scrolled.get_vadjustment()
        self._drag_start_h = hadj.get_value() if hadj else 0.0
        self._drag_start_v = vadj.get_value() if vadj else 0.0

    def _on_drag_update(self, _gesture, offset_x, offset_y):
        if self.fit_mode:
            return
        hadj = self.scrolled.get_hadjustment()
        vadj = self.scrolled.get_vadjustment()
        if hadj:
            self._set_adjustment_value(hadj, self._drag_start_h - offset_x)
        if vadj:
            self._set_adjustment_value(vadj, self._drag_start_v - offset_y)

    @staticmethod
    def _set_adjustment_value(adj, value):
        lower = adj.get_lower()
        upper = adj.get_upper() - adj.get_page_size()
        adj.set_value(max(lower, min(value, upper)))

    def _fit_to_window(self):
        self.fit_mode = True
        self.zoom = 1.0
        self.picture.set_can_shrink(True)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.set_size_request(-1, -1)

    def _set_zoom(self, zoom):
        self.fit_mode = False
        self.zoom = max(self.MIN_ZOOM, min(float(zoom), self.MAX_ZOOM))
        width = max(1, int(self.texture.get_width() * self.zoom))
        height = max(1, int(self.texture.get_height() * self.zoom))
        self.picture.set_hexpand(False)
        self.picture.set_vexpand(False)
        self.picture.set_can_shrink(False)
        self.picture.set_size_request(width, height)

    def _on_save_clicked(self, _button):
        if not self.data:
            return
        dialog = Gtk.FileDialog()
        dialog.set_title("Save image")
        dialog.set_initial_name(_attachment_filename(self.url))

        def on_save(dlg, result, _user_data=None):
            try:
                gfile = dlg.save_finish(result)
            except GLib.Error as exc:
                if not exc.matches(Gtk.dialog_error_quark(),
                                   Gtk.DialogError.DISMISSED):
                    debug_print(f"[widget] save_finish falló: {exc}")
                return
            except Exception as exc:
                debug_print(f"[widget] error inesperado al guardar: {exc}")
                return
            if gfile is None:
                return
            try:
                gfile.replace_contents(self.data, None, False, 0, None)
            except Exception as exc:
                debug_print(f"[widget] no se pudo guardar imagen: {exc}")

        dialog.save(self, None, on_save, None)


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

        # Texto normal sigue en Gtk.Label/Pango por estabilidad de layout; los
        # fences se montan como widgets separados para copiar sólo el bloque.
        self.content_view = None
        self.content_plain_view = None
        # Adjunto de imagen: preview encima del texto. El link sigue estando
        # en el cuerpo (clicable), así que si la descarga falla no se pierde.
        self._attachment_picture = None
        self._attachment_texture = None
        self._attachment_data = None
        self._attachment_url = None
        image_url = _first_image_url(content)
        if image_url:
            self._ensure_attachment_preview(message_box, image_url)
        visible_content = _content_without_attachment_url(content, image_url)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.content_box.set_hexpand(True)
        self._set_message_content(visible_content)
        message_box.append(self.content_box)

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

    def _ensure_attachment_preview(self, message_box, image_url):
        if self._attachment_url == image_url and self._attachment_picture is not None:
            return
        self._attachment_url = image_url
        self._attachment_texture = None
        self._attachment_data = None
        if self._attachment_picture is None:
            self._attachment_picture = Gtk.Picture()
            self._attachment_picture.set_visible(False)
            self._attachment_picture.set_can_shrink(True)
            self._attachment_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self._attachment_picture.set_size_request(-1, 240)
            self._attachment_picture.set_hexpand(True)
            self._attachment_picture.add_css_class('attachment-image')

            click = Gtk.GestureClick.new()
            click.connect("released", self._on_attachment_clicked)
            self._attachment_picture.add_controller(click)
            message_box.prepend(self._attachment_picture)

        def on_loaded(texture, data):
            self._attachment_texture = texture
            self._attachment_data = data

        _load_picture_async(self._attachment_picture, image_url, on_loaded=on_loaded)

    def _on_attachment_clicked(self, *_args):
        if self._attachment_texture is None:
            return
        root = self.get_root()
        dialog = ImagePreviewDialog(
            root, self._attachment_texture, self._attachment_url,
            data=self._attachment_data)
        dialog.present()

    def _clear_content_box(self):
        for child in list(self.content_box):
            self.content_box.remove(child)

    def _build_text_label(self, content):
        label = Gtk.Label()
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0.0)
        label.set_selectable(True)
        label.set_hexpand(True)
        label.connect('activate-link', _on_activate_link)
        self._set_label_content(label, content)
        return label

    def _set_label_content(self, label, content):
        """Pinta `content` en `label` — markdown como Pango markup, o texto
        plano. El markup generado es balanceado por construcción, pero ante
        cualquier sorpresa se degrada a texto plano en vez de a un label
        vacío (set_markup inválido no pinta nada)."""
        if not (content or '').strip():
            label.set_text('')
            label.set_visible(False)
            return
        label.set_visible(True)
        if self.use_markdown:
            from .pango_markdown import markdown_to_pango
            markup = _autolink(markdown_to_pango(content))
            try:
                Pango.parse_markup(markup, -1, '\x00')
                label.set_markup(markup)
                return
            except GLib.Error:
                debug_print("[widget] markup inválido; fallback a texto plano")
        # Texto plano: aun así autoenlazar las URLs (los adjuntos llegan como
        # una URL suelta). Se escapa primero para que el markup sea válido.
        escaped = GLib.markup_escape_text(content or '')
        markup = _autolink(escaped)
        try:
            Pango.parse_markup(markup, -1, '\x00')
            label.set_markup(markup)
            return
        except GLib.Error:
            debug_print("[widget] autolink inválido; texto plano tal cual")
        label.set_text(content)

    def _build_code_block(self, code, language):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class('code-block')
        card.set_hexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.add_css_class('code-block-header')
        label = Gtk.Label(label=language or 'code')
        label.add_css_class('code-block-language')
        label.set_xalign(0.0)
        label.set_hexpand(True)
        header.append(label)

        copy_button = Gtk.Button(icon_name='edit-copy-symbolic')
        copy_button.add_css_class('flat')
        copy_button.add_css_class('code-copy-button')
        copy_button.set_tooltip_text('Copiar código')

        def on_copy(_button):
            display = Gdk.Display.get_default()
            if display:
                display.get_clipboard().set(code or '')

        copy_button.connect('clicked', on_copy)
        header.append(copy_button)
        card.append(header)

        view = Gtk.TextView()
        view.add_css_class('code-block-text')
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.NONE)
        view.set_monospace(True)
        view.set_hexpand(True)
        view.get_buffer().set_text(code or '')

        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class('code-block-scroll')
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scrolled.set_min_content_height(42)
        scrolled.set_max_content_height(260)
        scrolled.set_child(view)
        card.append(scrolled)
        return card

    def _set_message_content(self, content):
        self._clear_content_box()
        if not (content or '').strip():
            return
        for kind, language, value in _split_code_fences(content):
            if kind == 'code':
                self.content_box.append(self._build_code_block(value, language))
            elif (value or '').strip():
                self.content_box.append(self._build_text_label(value))

    def update_content(self, new_content):
        """Actualiza el contenido del mensaje"""
        self.message.content = Message.compact_blank_lines(new_content)
        debug_print(
            f"[widget] update_content sender={self.message.sender} "
            f"len={len(self.message.content)}")
        image_url = _first_image_url(self.message.content)
        if image_url:
            self._ensure_attachment_preview(self.message_box, image_url)
        visible_content = _content_without_attachment_url(
            self.message.content, image_url)
        self._set_message_content(visible_content)
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

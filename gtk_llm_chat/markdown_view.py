import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Pango

class MarkdownView(Gtk.TextView):
    """TextView personalizado que renderiza texto con formato markdown básico"""
    
    def __init__(self):
        super().__init__()
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_editable(False)
        self.set_cursor_visible(False)
        
        # Configurar tags para formato
        self.buffer = self.get_buffer()
        self.buffer.create_tag("bold", weight=Pango.Weight.BOLD)
        self.buffer.create_tag("italic", style=Pango.Style.ITALIC)
        self.buffer.create_tag("code", family="monospace", background="rgba(0,0,0,0.1)")
        self.buffer.create_tag("link", underline=Pango.Underline.SINGLE, foreground="blue")
        self.buffer.create_tag("h1", weight=Pango.Weight.BOLD, size=24 * Pango.SCALE)
        self.buffer.create_tag("h2", weight=Pango.Weight.BOLD, size=20 * Pango.SCALE)
        self.buffer.create_tag("h3", weight=Pango.Weight.BOLD, size=16 * Pango.SCALE)
        self.buffer.create_tag("h4", weight=Pango.Weight.BOLD, size=12 * Pango.SCALE)
        self.buffer.create_tag("bold_italic", weight=Pango.Weight.BOLD, style=Pango.Style.ITALIC)
        self.buffer.create_tag("ul", left_margin=20)
        self.buffer.create_tag("ol", left_margin=20)
        self.buffer.create_tag("strikethrough", strikethrough=True)
        
        # Controlador para links
        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", self._on_click)
        self.add_controller(click_controller)
        
        # Almacenar links
        self.links = {}

    def _on_click(self, gesture, n_press, x, y):
        """Maneja clicks en links"""
        buffer_x, buffer_y = self.window_to_buffer_coords(Gtk.TextWindowType.TEXT, x, y)
        iter_at_click = self.get_iter_at_location(buffer_x, buffer_y)[1]

        for url, (start_mark, end_mark) in self.links.items():
            start_iter = self.buffer.get_iter_at_mark(start_mark)
            end_iter = self.buffer.get_iter_at_mark(end_mark)
            if start_iter.get_offset() <= iter_at_click.get_offset() <= end_iter.get_offset():
                # Abrir URL usando el launcher por defecto
                Gtk.show_uri(None, url, Gdk.CURRENT_TIME)
                break

    def set_markdown(self, text):
        """Renderiza texto markdown"""
        self.buffer.set_text("")
        self.links.clear()
        
        # Procesar el texto línea por línea
        current_pos = self.buffer.get_start_iter()
        
        lines = text.split('\n')
        in_code_block = False
        code_block_text = []
        
        for line in lines:
            if line.startswith('```'):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                self.buffer.insert(current_pos, line + '\n')
                continue

            # Headers
            if line.startswith('# '):
                self.buffer.insert_with_tags_by_name(current_pos, line[2:], "h1")
                self.buffer.insert(current_pos, '\n')
                continue
            elif line.startswith('## '):
                self.buffer.insert_with_tags_by_name(current_pos, line[3:], "h2")
                self.buffer.insert(current_pos, '\n')
                continue
            elif line.startswith('### '):
                self.buffer.insert_with_tags_by_name(current_pos, line[4:], "h3")
                self.buffer.insert(current_pos, '\n')
                continue
            elif line.startswith('#### '):
                self.buffer.insert_with_tags_by_name(current_pos, line[5:], "h4")
                self.buffer.insert(current_pos, '\n')
                continue

            # Lists
            if line.startswith('* ') or line.startswith('- '):
                self.buffer.insert_with_tags_by_name(current_pos, line, "ul")
                self.buffer.insert(current_pos, '\n')
                continue
            elif line.startswith(('1. ', '2. ', '3. ', '4. ', '5. ', '6. ', '7. ', '8. ', '9. ')):
                self.buffer.insert_with_tags_by_name(current_pos, line, "ol")
                self.buffer.insert(current_pos, '\n')
                continue

            # Procesar línea normal
            remaining_text = line
            while remaining_text:
                # Buscar el próximo marcador de formato
                markers = {
                    '**': ('bold', 2),
                    '*': ('italic', 1),
                    '`': ('code', 1),
                    '[': ('link', 1),
                    '***': ('bold_italic', 3),
                    '~~': ('strikethrough', 2)
                }

                next_marker_pos = float('inf')
                next_marker = None

                for marker, (tag, length) in markers.items():
                    pos = remaining_text.find(marker)
                    if pos != -1 and pos < next_marker_pos:
                        next_marker_pos = pos
                        next_marker = (marker, tag, length)

                if next_marker is None or next_marker_pos == float('inf'):
                    # No hay más marcadores, insertar el texto restante
                    self.buffer.insert(current_pos, remaining_text)
                    break

                # Insertar texto antes del marcador
                if next_marker_pos > 0:
                    self.buffer.insert(current_pos, remaining_text[:next_marker_pos])

                marker, tag, length = next_marker
                remaining_text = remaining_text[next_marker_pos + length:]

                # Procesar el formato
                if marker == '[':
                    # Procesar link [texto](url)
                    link_end = remaining_text.find(']')
                    if link_end != -1 and remaining_text[link_end:].startswith(']('):
                        url_start = link_end + 2
                        url_end = remaining_text.find(')', url_start)
                        if url_end != -1:
                            link_text = remaining_text[:link_end]
                            url = remaining_text[url_start:url_end]

                            start_mark = self.buffer.create_mark(None, current_pos, True)
                            self.buffer.insert_with_tags_by_name(current_pos, link_text, "link")
                            end_mark = self.buffer.create_mark(None, current_pos, True)

                            self.links[url] = (start_mark, end_mark)

                            remaining_text = remaining_text[url_end + 1:]
                            continue

                # Buscar el cierre del formato
                end_pos = remaining_text.find(marker)
                if end_pos != -1:
                    formatted_text = remaining_text[:end_pos]
                    self.buffer.insert_with_tags_by_name(current_pos, formatted_text, tag)
                    remaining_text = remaining_text[end_pos + length:]
                else:
                    # No se encontró el cierre, tratar como texto normal
                    self.buffer.insert(current_pos, marker)

            # Agregar salto de línea al final de cada línea
            self.buffer.insert(current_pos, '\n')
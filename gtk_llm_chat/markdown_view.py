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
        
        for start, end, url in self.links.values():
            if start.get_offset() <= iter_at_click.get_offset() <= end.get_offset():
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
                if not in_code_block and code_block_text:
                    # Insertar bloque de código acumulado
                    code_text = '\n'.join(code_block_text)
                    self.buffer.insert_with_tags_by_name(current_pos, code_text, "code")
                    self.buffer.insert(current_pos, '\n')
                    code_block_text = []
                continue
                
            if in_code_block:
                code_block_text.append(line)
                continue
                
            # Procesar línea normal
            remaining_text = line
            while remaining_text:
                # Buscar el próximo marcador de formato
                markers = {
                    '**': ('bold', 2),
                    '*': ('italic', 1),
                    '`': ('code', 1),
                    '[': ('link', 1)
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
                            
                            start_iter = self.buffer.get_iter_at_mark(start_mark)
                            end_iter = self.buffer.get_iter_at_mark(end_mark)
                            
                            self.links[url] = (start_iter, end_iter, url)
                            
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
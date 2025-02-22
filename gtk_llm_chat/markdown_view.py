import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Pango
import markdown_it

class MarkdownView(Gtk.TextView):
    """TextView personalizado que renderiza texto con formato markdown básico"""
    
    def __init__(self):
        super().__init__()
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_editable(False)
        self.set_cursor_visible(False)
        
        # Configurar tags para formato
        self.buffer = Gtk.TextBuffer()
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
        self.set_buffer(self.buffer)
        
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

    def set_markdown(self, text, tag_name):
        """Renderiza texto markdown"""
        self.links.clear()
        
        md = markdown_it.MarkdownIt()
        tokens = md.parse(text)
        
        start_mark = None
        
        for token in tokens:
            print(f"Token type: {token.type}, content: {token.content}")
            
            if token.type == 'paragraph_open':
                pass
            elif token.type == 'paragraph_close':
                self.buffer.insert_at_cursor('\n', -1)
            elif token.type == 'inline':
                self.buffer.insert_at_cursor(token.content, -1)
            elif token.type == 'strong_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
            elif token.type == 'strong_close':
                if start_mark:
                    end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    self.buffer.apply_tag_by_name("bold", start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    start_mark = None
            elif token.type == 'em_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
            elif token.type == 'em_close':
                if start_mark:
                    end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    self.buffer.apply_tag_by_name("italic", start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    start_mark = None
            elif token.type == 'code_inline':
                start_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                self.buffer.insert_at_cursor(token.content, -1)
                end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                self.buffer.apply_tag_by_name("code", start_iter, end_iter)
            elif token.type == 'link_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
                self.links[token.attrs['href']] = start_mark
            elif token.type == 'link_close':
                url = next((url for url, start in self.links.items() if start == start_mark), None)
                if url:
                    end_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    end_iter = self.buffer.get_iter_at_mark(end_mark)
                    self.buffer.apply_tag_by_name("link", start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    del self.links[url]
                    start_mark = None
            elif token.type == 'heading_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
            elif token.type == 'heading_close':
                if start_mark:
                    end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    level = token.tag[1]  # Extract heading level (1-6)
                    tag_name = f"h{level}"
                    self.buffer.apply_tag_by_name(tag_name, start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    start_mark = None
            elif token.type == 'list_item_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
            elif token.type == 'list_item_close':
                if start_mark:
                    end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    if token.tag == 'ul':
                        self.buffer.apply_tag_by_name("ul", start_iter, end_iter)
                    elif token.tag == 'ol':
                        self.buffer.apply_tag_by_name("ol", start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    start_mark = None
            elif token.type == 's_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
            elif token.type == 's_close':
                if start_mark:
                    end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    self.buffer.apply_tag_by_name("strikethrough", start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    start_mark = None
            elif token.type == 'strong_em_open' or token.type == 'em_strong_open':
                start_mark = self.buffer.create_mark(None, self.buffer.get_iter_at_mark(self.buffer.get_insert()), True)
            elif token.type == 'strong_em_close' or token.type == 'em_strong_close':
                if start_mark:
                    end_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
                    start_iter = self.buffer.get_iter_at_mark(start_mark)
                    self.buffer.apply_tag_by_name("bold_italic", start_iter, end_iter)
                    self.buffer.delete_mark(start_mark)
                    start_mark = None
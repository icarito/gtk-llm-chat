import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango, Gdk
from markdown_it import MarkdownIt
from markdown_it.token import Token

class MarkdownView(Gtk.TextView):
    def __init__(self):
        super().__init__()
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.buffer = self.get_buffer()
        self.md = MarkdownIt()
        self.bold_tag = self.buffer.create_tag("bold", weight=Pango.Weight.BOLD)
        self.italic_tag = self.buffer.create_tag("italic", style=Pango.Style.ITALIC)
        self.current_tags = []

    def set_markdown(self, text):
        return self.render_markdown(text)

    def render_markdown(self, text):
        # Parsear Markdown con markdown-it-py
        tokens = self.md.parse(text)
        
        # Limpiar el buffer
        self.buffer.set_text("", -1)
        
        # Aplicar formato
        self.apply_pango_format(tokens)

    def apply_pango_format(self, tokens):
        # Iterar sobre los tokens y aplicar formato
        for token in tokens:
            if token.type == 'strong_open':
                self.apply_tag(self.bold_tag)
            elif token.type == 'strong_close':
                self.remove_tag(self.bold_tag)
            elif token.type == 'em_open':
                self.apply_tag(self.italic_tag)
            elif token.type == 'em_close':
                self.remove_tag(self.italic_tag)
            elif token.type == 'text':
                self.insert_text(token.content)
            elif token.type == 'paragraph_open':
                pass
            elif token.type == 'paragraph_close':
                self.insert_text("\n")
            elif token.type == 'heading_open':
                pass # ignore the title formatting
            elif token.type == 'heading_close':
                self.insert_text("\n")
            elif token.type == 'inline':
                for child in token.children:
                    if child.type == 'text':
                        self.insert_text(child.content)
                    elif child.type == 'em_open':
                        self.apply_tag(self.italic_tag)
                    elif child.type == 'em_close':
                        self.remove_tag(self.italic_tag)
                    elif child.type == 'strong_open':
                        self.apply_tag(self.bold_tag)
                    elif child.type == 'strong_close':
                        self.remove_tag(self.bold_tag)
    
    def insert_text(self, text):
        # Insertar texto con las etiquetas actuales
        iter = self.buffer.get_end_iter()
        tags = self.current_tags.copy()
        if tags:
            self.buffer.insert_with_tags(iter, text, *tags)
        else:
            self.buffer.insert(iter, text)

    def apply_tag(self, tag):
        # Aplicar una etiqueta al texto actual
        if tag not in self.current_tags:
            self.current_tags.append(tag)

    def remove_tag(self, tag):
        # Eliminar una etiqueta del texto actual
        if tag in self.current_tags:
            self.current_tags.remove(tag)


# Ejemplo de uso
if __name__ == "__main__":
    app = Gtk.Application(application_id='com.example.MarkdownApp')
    
    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app)
        win.set_title("Markdown TextView")
        win.set_default_size(400, 300)

        markdown_text = "# Título\nEste es un **texto en negrita** y _cursiva_."
        
        markdown_view = MarkdownView()
        markdown_view.render_markdown(markdown_text)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_child(markdown_view)
        win.set_child(scrolled_window)

        win.present()

    app.connect('activate', on_activate)
    app.run()


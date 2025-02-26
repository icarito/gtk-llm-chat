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
        self.heading_tags = {
            '1': self.buffer.create_tag("h1", weight=Pango.Weight.BOLD, size=24 * Pango.SCALE),
            '2': self.buffer.create_tag("h2", weight=Pango.Weight.BOLD, size=20 * Pango.SCALE),
            '3': self.buffer.create_tag("h3", weight=Pango.Weight.BOLD, size=16 * Pango.SCALE),
            '4': self.buffer.create_tag("h4", weight=Pango.Weight.BOLD, size=12 * Pango.SCALE),
            '5': self.buffer.create_tag("h5", weight=Pango.Weight.BOLD, size=10 * Pango.SCALE),
        }
        self.code_tag = self.buffer.create_tag("code", family="monospace", background="gray")
        
        # Tags para listas (con soporte para anidación)
        self.list_tags = {
            1: self.buffer.create_tag("list_1", left_margin=30),
            2: self.buffer.create_tag("list_2", left_margin=50),
            3: self.buffer.create_tag("list_3", left_margin=70),
        }
        
        # Variable para rastrear si estamos dentro de un elemento de lista
        self.in_list_item = False
        self.in_ordered_list = False

        self.current_tags = []
        self.list_level = 0  # Para controlar la anidación de listas

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
                level = token.tag[1]
                if level in self.heading_tags:
                    self.apply_tag(self.heading_tags[level])
            elif token.type == 'heading_close':
                level = token.tag[1]

                self.remove_tag(self.heading_tags[level])
                self.insert_text("\n")
            elif token.type == 'fence':
                self.insert_text("\n")
                self.apply_tag(self.code_tag)
                self.insert_text(token.content)
                self.remove_tag(self.code_tag)
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
            # Manejo de listas con viñetas
            elif token.type == 'bullet_list_open':
                # Incrementamos el nivel de lista y aplicamos el tag de lista
                self.list_level += 1
                # Agregamos un pequeño margen antes de comenzar la lista
                if self.list_level == 1:
                    self.insert_text("\n")
                self.apply_tag(self.list_tags[min(self.list_level, 3)])
            elif token.type == 'bullet_list_close':
                # Decrementamos el nivel de lista y quitamos el tag
                self.list_level -= 1
                # Quitamos el tag del nivel que estamos cerrando
                current_level = min(self.list_level + 1, 3)
                self.remove_tag(self.list_tags[current_level])
                if self.list_level == 0:
                    self.insert_text("\n")
            # Soporte para listas ordenadas (numeradas)
            elif token.type == 'ordered_list_open':
                self.list_level += 1
                self.in_ordered_list = True
                if self.list_level == 1:
                    self.insert_text("\n")
                self.apply_tag(self.list_tags[min(self.list_level, 3)])
            elif token.type == 'ordered_list_close':
                self.list_level -= 1
                self.in_ordered_list = False
                # Quitamos el tag del nivel que estamos cerrando
                current_level = min(self.list_level + 1, 3)
                self.remove_tag(self.list_tags[current_level])
                if self.list_level == 0:
                    self.insert_text("\n")
            elif token.type == 'list_item_open':
                self.in_list_item = True
                # Agregamos la viñeta o número según el tipo de lista
                if self.in_ordered_list:
                    # Para listas ordenadas, usamos el atributo info que contiene el número
                    item_number = token.info
                    self.insert_text(f"{item_number}. ")
                else:
                    # Para listas con viñetas, usamos diferentes símbolos según el nivel
                    if self.list_level == 1:
                        self.insert_text("• ")
                    elif self.list_level == 2:
                        self.insert_text("◦ ")
                    else:
                        self.insert_text("▪ ")
            elif token.type == 'list_item_close':
                self.in_list_item = False
            else:
                print ("Unknown markdown token:", token)

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

        markdown_text = "# Título 1\n## Título 2\n### Título 3\nEste es un **texto en negrita** y _cursiva_."
        markdown_text += "\n```\n"
        markdown_text += "Este es un bloque de código.\n"
        markdown_text += "```\n"
        markdown_text += "\nLista de ejemplo:\n"
        markdown_text += "* Elemento 1\n  * Subelemento 1.1\n  * Subelemento 1.2\n* Elemento 2\n* Elemento 3\n"
        markdown_text += "\nLista numerada:\n"
        markdown_text += "1. Primer elemento\n"
        markdown_text += "2. Segundo elemento\n"
        markdown_text += "   1. Subelemento 2.1\n"

        
        markdown_view = MarkdownView()
        markdown_view.render_markdown(markdown_text)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_child(markdown_view)
        win.set_child(scrolled_window)

        win.present()

    app.connect('activate', on_activate)
    app.run()

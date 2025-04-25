from markdown_it import MarkdownIt
import re
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango  # noqa: E402


class MarkdownView(Gtk.TextView):
    def __init__(self):
        super().__init__()
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.buffer = self.get_buffer()
        self.md = MarkdownIt().enable('strikethrough')

        # Get the TextTagTable from the buffer
        self.tag_table = self.buffer.get_tag_table()  # Corrected line

        # Create TextTags and add them to the table
        self.bold_tag = Gtk.TextTag(name="bold")
        self.bold_tag.set_property("weight", Pango.Weight.BOLD)
        self.tag_table.add(self.bold_tag)

        self.italic_tag = Gtk.TextTag(name="italic")
        self.italic_tag.set_property("style", Pango.Style.ITALIC)
        self.tag_table.add(self.italic_tag)

        self.strike_tag = Gtk.TextTag(name="strike")
        self.strike_tag.set_property("strikethrough", True)
        self.tag_table.add(self.strike_tag)

        self.hr_tag = Gtk.TextTag(name="hr_line")
        self.hr_tag.set_property("foreground", "#666666")
        self.hr_tag.set_property("scale", 0.3)
        self.hr_tag.set_property("rise", -500)
        self.hr_tag.set_property("justification", Gtk.Justification.CENTER)
        self.tag_table.add(self.hr_tag)

        self.heading_tags = {
            '1': Gtk.TextTag(name="h1"),
            '2': Gtk.TextTag(name="h2"),
            '3': Gtk.TextTag(name="h3"),
            '4': Gtk.TextTag(name="h4"),
            '5': Gtk.TextTag(name="h5"),
        }
        self.heading_tags['1'].set_property("weight", Pango.Weight.BOLD)
        self.heading_tags['1'].set_property("size", 24 * Pango.SCALE)
        self.heading_tags['2'].set_property("weight", Pango.Weight.BOLD)
        self.heading_tags['2'].set_property("size", 20 * Pango.SCALE)
        self.heading_tags['3'].set_property("weight", Pango.Weight.BOLD)
        self.heading_tags['3'].set_property("size", 16 * Pango.SCALE)
        self.heading_tags['4'].set_property("weight", Pango.Weight.BOLD)
        self.heading_tags['4'].set_property("size", 12 * Pango.SCALE)
        self.heading_tags['5'].set_property("weight", Pango.Weight.BOLD)
        self.heading_tags['5'].set_property("size", 10 * Pango.SCALE)
        for tag in self.heading_tags.values():
            self.tag_table.add(tag)

        self.code_tag = Gtk.TextTag(name="code")
        self.code_tag.set_property("family", "monospace")
        self.code_tag.set_property("background", "gray")
        self.tag_table.add(self.code_tag)

        self.code_inline_tag = Gtk.TextTag(name="code_inline")
        self.code_inline_tag.set_property("family", "monospace")
        self.code_inline_tag.set_property("background", "#444444")
        self.tag_table.add(self.code_inline_tag)

        self.thinking_tag = Gtk.TextTag(name="thinking")
        self.thinking_tag.set_property("style", Pango.Style.ITALIC)
        self.thinking_tag.set_property("scale", 0.8)
        self.thinking_tag.set_property("left-margin", 20)
        self.thinking_tag.set_property("right-margin", 20)
        self.tag_table.add(self.thinking_tag)

        self.blockquote_tag = Gtk.TextTag(name="blockquote")
        self.blockquote_tag.set_property("left-margin", 30)
        self.blockquote_tag.set_property("style", Pango.Style.ITALIC)
        self.blockquote_tag.set_property("background", "gray")
        self.tag_table.add(self.blockquote_tag)

        self.list_tags = {
            1: Gtk.TextTag(name="list_1"),
            2: Gtk.TextTag(name="list_2"),
            3: Gtk.TextTag(name="list_3"),
        }
        self.list_tags[1].set_property("left-margin", 30)
        self.list_tags[2].set_property("left-margin", 50)
        self.list_tags[3].set_property("left-margin", 70)
        for tag in self.list_tags.values():
            self.tag_table.add(tag)

        self.in_list_item = False
        self.in_ordered_list = False
        self.current_tags = []
        self.list_level = 0

    def set_markdown(self, text):
        return self.render_markdown(text)

    def process_thinking_tags(self, text):
        """
        Procesa las etiquetas <think> o <thinking> en el texto.
        Devuelve una lista de fragmentos alternando texto normal y pensamiento.
        Cada fragmento es una tupla (texto, es_pensamiento).
        """
        fragments = []
        think_pattern = re.compile(r'<think>(.*?)</think>', re.DOTALL)
        thinking_pattern = re.compile(r'<thinking>(.*?)</thinking>', re.DOTALL)

        all_matches = []
        for pattern in [think_pattern, thinking_pattern]:
            for match in pattern.finditer(text):
                all_matches.append(
                    (match.start(), match.end(), match.group(1)))

        all_matches.sort(key=lambda x: x[0])

        last_end = 0
        for start, end, content in all_matches:
            if start > last_end:
                fragments.append((text[last_end:start], False))
            fragments.append((content, True))
            last_end = end

        if last_end < len(text):
            fragments.append((text[last_end:], False))

        return fragments

    def render_markdown(self, text):
        self.buffer.set_text("", 0)
        fragments = self.process_thinking_tags(text)

        for fragment_text, is_thinking in fragments:
            if is_thinking:
                self.insert_thinking(fragment_text)
            else:
                self.render_markdown_fragment(fragment_text)

    def render_markdown_fragment(self, text):
        tokens = self.md.parse(text)
        self.apply_pango_format(tokens)

    def apply_pango_format(self, tokens):
        for token in tokens:
            if token.type == 'strong_open':
                self.apply_tag(self.bold_tag)
            elif token.type == 'strong_close':
                self.remove_tag(self.bold_tag)
            elif token.type == 'em_open':
                self.apply_tag(self.italic_tag)
            elif token.type == 'em_close':
                self.remove_tag(self.italic_tag)
            elif token.type == 's_open':
                self.apply_tag(self.strike_tag)
            elif token.type == 's_close':
                self.remove_tag(self.strike_tag)

            elif token.type == 'text':
                self.insert_text(token.content)
            elif token.type == 'paragraph_open':
                pass
            elif token.type == 'paragraph_close':
                self.insert_text("\n\n")

            elif token.type == 'heading_open':
                level = token.tag[1]
                if level in self.heading_tags:
                    self.apply_tag(self.heading_tags[level])
            elif token.type == 'heading_close':
                level = token.tag[1]
                self.remove_tag(self.heading_tags[level])
                self.insert_text("\n\n")
            elif token.type == 'fence':
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
                    elif child.type == 'code_inline':
                        self.apply_tag(self.code_inline_tag)
                        self.insert_text(child.content)
                        self.remove_tag(self.code_inline_tag)
                    # Manejar tachado en elementos inline
                    elif child.type == 's_open':
                        self.apply_tag(self.strike_tag)
                    elif child.type == 's_close':
                        self.remove_tag(self.strike_tag)
            elif token.type == 'blockquote_open':
                self.insert_text("\n")
                self.apply_tag(self.blockquote_tag)
            elif token.type == 'blockquote_close':
                self.remove_tag(self.blockquote_tag)
                self.insert_text("\n")
            elif token.type == 'bullet_list_open':
                self.list_level += 1
                self.apply_tag(self.list_tags[min(self.list_level, 3)])
            elif token.type == 'bullet_list_close':
                self.list_level -= 1
                current_level = min(self.list_level + 1, 3)
                self.remove_tag(self.list_tags[current_level])
            elif token.type == 'ordered_list_open':
                self.list_level += 1
                self.in_ordered_list = True
                self.apply_tag(self.list_tags[min(self.list_level, 3)])
            elif token.type == 'ordered_list_close':
                self.list_level -= 1
                self.in_ordered_list = False
                current_level = min(self.list_level + 1, 3)
                self.remove_tag(self.list_tags[current_level])
            elif token.type == 'list_item_open':
                self.in_list_item = True
                if self.in_ordered_list:
                    item_number = token.info
                    self.insert_text(f"{item_number}. ")
                else:
                    if self.list_level == 1:
                        self.insert_text("• ")
                    elif self.list_level == 2:
                        self.insert_text("◦ ")
                    else:
                        self.insert_text("▪ ")
            elif token.type == 'list_item_close':
                self.in_list_item = False
            elif token.type == 'hr':
                self.insert_text("\n")
                self.apply_tag(self.hr_tag)
                self.insert_text("-" * 35)
                self.remove_tag(self.hr_tag)
                self.insert_text("\n\n")
            elif token.type == 'html_block':
                pass
            elif token.type == 'code_block':
                self.insert_text("\n")
                self.insert_text(token.content)
                self.insert_text("\n")
            else:
                print("Unknown markdown token:", token.type, flush=True)


    def insert_text(self, text):
        buf = self.buffer
        buf.create_mark("insert_start", buf.get_end_iter(), left_gravity=True)
        buf.insert(buf.get_end_iter(), text, -1)
        start = buf.get_iter_at_mark(buf.get_mark("insert_start"))
        end = start.copy()
        end.forward_chars(len(text))
        for tag in self.current_tags:
            buf.apply_tag(tag, start, end)
        buf.delete_mark(buf.get_mark("insert_start"))

    def insert_thinking(self, text):
        buf = self.buffer
        buf.create_mark("think_start", buf.get_end_iter(), left_gravity=True)
        buf.insert(buf.get_end_iter(), text, -1)
        start = buf.get_iter_at_mark(buf.get_mark("think_start"))
        end = start.copy()
        end.forward_chars(len(text))
        buf.apply_tag(self.thinking_tag, start, end)
        buf.delete_mark(buf.get_mark("think_start"))
        buf.insert(buf.get_end_iter(), "\n", -1)

    def apply_tag(self, tag):
        if tag not in self.current_tags:
            self.current_tags.append(tag)
        start, end = self.buffer.get_bounds()
        if not start.equal(end):
            self.buffer.apply_tag(tag, end, self.buffer.get_end_iter())

    def remove_tag(self, tag):
        if tag in self.current_tags:
            self.current_tags.remove(tag)
        start, end = self.buffer.get_bounds()
        self.buffer.remove_tag(tag, end, self.buffer.get_end_iter())


if __name__ == "__main__":
    app = Gtk.Application(application_id='org.fuentelibre.MarkdownDemo')

    def on_activate(app):
        win = Gtk.ApplicationWindow(application=app)
        win.set_title("Markdown TextView")
        win.set_default_size(400, 300)

        markdown_text = """# Título 1\n## Título 2\n### Título 3\nEste es un
        **texto en negrita** y _cursiva_.
        \n```\n"
        Este es un bloque de código.\n"
        var x = 10;\n"
        ```\n"
        \nLista de ejemplo:\n"
        * Elemento 1\n  * Subelemento 1.1\n  * Subelemento 1.2\n* Elemento 2
        * Elemento 3\n"
        \nLista numerada:\n"
        1. Primer elemento\n"
        2. Segundo elemento\n"
           1. Subelemento 2.1\n"
        \nTexto con `código en línea` y emoji 😊\n"
        hola `amigo` 😊\n"""

        markdown_view = MarkdownView()
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_child(markdown_view)
        win.set_child(scrolled_window)

        markdown_view.render_markdown(markdown_text)
        win.present()

    app.connect('activate', on_activate)
    app.run()

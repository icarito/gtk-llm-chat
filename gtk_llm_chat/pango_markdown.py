"""Markdown -> Pango markup, para renderizar burbujas con Gtk.Label.

Por qué no GtkTextView (el enfoque anterior, MarkdownView): un TextView
no-scrollable valida su layout en un idle *posterior* al measure, así que
en el momento de insertarlo reporta una altura basura — a veces 0 (burbuja
colapsada que "aparece" recién con el próximo relayout), a veces varias
veces la real (burbujón de espacio vacío que deja el mensaje fuera del
viewport). Un Gtk.Label con markup mide síncrono y exacto.

Cubre el mismo subconjunto de markdown que MarkdownView: negrita, cursiva,
tachado, código inline y en bloque, headings, listas (anidadas y ordenadas),
blockquote, hr y las etiquetas <think>/<thinking>.
"""
import re

from gi.repository import GLib
from markdown_it import MarkdownIt

_md = MarkdownIt().enable(['strikethrough', 'table'])

_HEADING_PT = {'1': 24, '2': 20, '3': 16, '4': 12, '5': 10, '6': 10}

_THINK_RE = re.compile(r'<think(?:ing)?>(.*?)</think(?:ing)?>', re.DOTALL)


def _esc(text):
    return GLib.markup_escape_text(text)


def _split_thinking(text):
    """[(fragmento, es_pensamiento), ...] — igual que process_thinking_tags."""
    fragments = []
    last_end = 0
    for match in _THINK_RE.finditer(text):
        if match.start() > last_end:
            fragments.append((text[last_end:match.start()], False))
        fragments.append((match.group(1), True))
        last_end = match.end()
    if last_end < len(text):
        fragments.append((text[last_end:], False))
    return fragments


def _render_inline(children):
    out = []
    for child in children:
        ctype = child.type
        if ctype == 'text':
            out.append(_esc(child.content))
        elif ctype in ('softbreak', 'hardbreak'):
            out.append('\n')
        elif ctype == 'strong_open':
            out.append('<b>')
        elif ctype == 'strong_close':
            out.append('</b>')
        elif ctype == 'em_open':
            out.append('<i>')
        elif ctype == 'em_close':
            out.append('</i>')
        elif ctype == 's_open':
            out.append('<s>')
        elif ctype == 's_close':
            out.append('</s>')
        elif ctype == 'code_inline':
            out.append('<span font_family="monospace" bgcolor="#808080" '
                       'bgalpha="25%">' + _esc(child.content) + '</span>')
        elif ctype == 'image':
            out.append(_esc(child.attrs.get('alt', '') or child.content))
        elif ctype == 'link_open':
            out.append('<u>')
        elif ctype == 'link_close':
            out.append('</u>')
        elif child.content:
            out.append(_esc(child.content))
    return ''.join(out)


def _render_fragment(text):
    tokens = _md.parse(text)
    out = []
    list_stack = []  # 'bullet' | número siguiente de lista ordenada
    quote_depth = 0

    def bullet_prefix():
        depth = len(list_stack)
        indent = '  ' * max(depth - 1, 0)
        if list_stack and list_stack[-1] != 'bullet':
            n = list_stack[-1]
            list_stack[-1] += 1
            return f"{indent}{n}. "
        marker = {1: '•', 2: '◦'}.get(depth, '▪')
        return f"{indent}{marker} "

    for token in tokens:
        ttype = token.type
        if ttype == 'inline':
            out.append(_render_inline(token.children or []))
        elif ttype == 'paragraph_open':
            if quote_depth:
                out.append('<i>')
        elif ttype == 'paragraph_close':
            if quote_depth:
                out.append('</i>')
            # Dentro de una lista el salto de línea lo pone list_item_close.
            out.append('\n' if list_stack else '\n\n')
        elif ttype == 'heading_open':
            pt = _HEADING_PT.get(token.tag[1:], 12)
            out.append(f'<span weight="bold" size="{pt * 1024}">')
        elif ttype == 'heading_close':
            out.append('</span>\n\n')
        elif ttype in ('fence', 'code_block'):
            out.append('<span font_family="monospace" bgcolor="#808080" '
                       'bgalpha="18%">'
                       + _esc(token.content.rstrip('\n')) + '</span>\n\n')
        elif ttype == 'blockquote_open':
            quote_depth += 1
        elif ttype == 'blockquote_close':
            quote_depth -= 1
        elif ttype in ('bullet_list_open',):
            list_stack.append('bullet')
        elif ttype == 'ordered_list_open':
            list_stack.append(int(token.attrs.get('start', 1)))
        elif ttype in ('bullet_list_close', 'ordered_list_close'):
            if list_stack:
                list_stack.pop()
            if not list_stack:
                out.append('\n')
        elif ttype == 'list_item_open':
            out.append(bullet_prefix())
        elif ttype == 'list_item_close':
            pass  # el \n lo puso paragraph_close (modo lista)
        elif ttype == 'hr':
            out.append('<span fgalpha="40%">' + '─' * 32 + '</span>\n\n')
        elif ttype == 'html_block':
            pass
        elif token.content:
            out.append(_esc(token.content))
    return ''.join(out)


def markdown_to_pango(text):
    """Convierte markdown a Pango markup listo para Gtk.Label.set_markup."""
    parts = []
    for fragment, is_thinking in _split_thinking(text or ''):
        if is_thinking:
            body = _esc(fragment.strip())
            if body:
                parts.append('<i><small>' + body + '</small></i>\n\n')
        else:
            parts.append(_render_fragment(fragment))
    out = ''.join(parts)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip('\n')


def extract_tables(text):
    tokens = _md.parse(text)
    tables = []
    current_table = None
    current_row = None
    in_header = False

    for token in tokens:
        ttype = token.type
        if ttype == 'table_open':
            current_table = {'headers': [], 'rows': [], 'align': []}
        elif ttype == 'thead_open':
            in_header = True
        elif ttype == 'tbody_open':
            in_header = False
        elif ttype == 'tr_open':
            current_row = []
        elif ttype == 'tr_close' and current_table and current_row:
            if in_header:
                current_table['headers'] = current_row
            else:
                current_table['rows'].append(current_row)
            current_row = None
        elif ttype in ('th_open', 'td_open'):
            style = token.attrs.get('style', '')
            if 'text-align:right' in style:
                current_table['align'].append(1.0)
            elif 'text-align:center' in style:
                current_table['align'].append(0.5)
            else:
                current_table['align'].append(0.0)
        elif ttype == 'inline' and current_row is not None:
            current_row.append(_render_inline(token.children or []))
        elif ttype == 'table_close' and current_table:
            tables.append(current_table)
            current_table = None

    return tables


def has_table(text):
    tokens = _md.parse(text)
    for token in tokens:
        if token.type == 'table_open':
            return True
    return False

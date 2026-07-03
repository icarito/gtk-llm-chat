"""
llm_conversation_sidebar.py - panel de conversaciones LLM persistente (spec 003).

Espejo de xmpp_roster_sidebar.py para el lado LLM: nivel principal lista
las conversaciones recientes (reemplaza al menú del tray eliminado);
un botón navega a un segundo nivel con las opciones existentes
(ChatSidebar: modelo, parámetros, system prompt).
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .chat_application import _
from .chat_sidebar import ChatSidebar
from .db_operations import ChatHistory
from .resource_manager import resource_manager


class LLMConversationSidebar(Gtk.Box):
    """Lista de conversaciones LLM recientes, con las opciones existentes
    (ChatSidebar) como segundo nivel navegable."""

    def __init__(self, config, llm_client, chat_history=None, on_conversation_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.config = config or {}
        self.llm_client = llm_client
        self.chat_history = chat_history or ChatHistory()
        self._on_conversation_selected = on_conversation_selected

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        self.stack.add_named(self._build_list_page(), "list")

        self.options_sidebar = ChatSidebar(config=self.config, llm_client=self.llm_client)
        self.stack.add_named(self.options_sidebar, "options")

        self.append(self.stack)
        self._populate()

    def _build_list_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.add_css_class("flat")
        header.set_title_widget(Gtk.Label(label=_("Conversations")))

        options_button = Gtk.Button()
        resource_manager.set_widget_icon_name(options_button, "emblem-system-symbolic")
        options_button.set_tooltip_text(_("Model Settings"))
        options_button.connect(
            "clicked", lambda _b: self.stack.set_visible_child_name("options"))
        header.pack_end(options_button)
        page.append(header)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('navigation-sidebar')
        self.list_box.connect('row-activated', self._on_row_activated)
        scroll.set_child(self.list_box)
        page.append(scroll)
        return page

    def _populate(self):
        child = self.list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list_box.remove(child)
            child = nxt

        conversations = self.chat_history.get_conversations(limit=50, offset=0)
        if not conversations:
            row = Adw.ActionRow(title=_("No conversations yet"))
            row.set_selectable(False)
            self.list_box.append(row)
            return

        for conv in conversations:
            title = conv.get('name') or conv.get('title') or conv.get('id')
            row = Adw.ActionRow(title=title)
            if conv.get('model'):
                row.set_subtitle(conv['model'])
            row.set_activatable(True)
            row.cid = conv.get('id')
            self.list_box.append(row)

    def _on_row_activated(self, _list_box, row):
        cid = getattr(row, 'cid', None)
        if cid and self._on_conversation_selected:
            self._on_conversation_selected(cid)

    def refresh(self):
        """Vuelve a poblar la lista (p.ej. tras crear/renombrar una conversación)."""
        self._populate()

    def show_options(self):
        self.stack.set_visible_child_name("options")

    def show_list(self):
        self.stack.set_visible_child_name("list")

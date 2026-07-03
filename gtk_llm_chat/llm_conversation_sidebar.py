import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .chat_application import _
from .db_operations import ChatHistory
from .chat_sidebar import ChatSidebar

class LLMConversationSidebar(Gtk.Box):
    def __init__(self, config, llm_client, on_conversation_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.config = config
        self.llm_client = llm_client
        self.on_conversation_selected = on_conversation_selected
        self.chat_history = ChatHistory()

        # Stack to switch between conversation list and settings
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        # 1. Conversation List Page
        self.list_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.add_css_class("flat")
        header.set_title_widget(Gtk.Label(label=_("Conversations")))

        # Button to go to settings
        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.connect("clicked", lambda x: self.stack.set_visible_child_name("settings"))
        header.pack_end(settings_btn)

        self.list_page.append(header)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('navigation-sidebar')
        self.list_box.connect('row-activated', self._on_row_activated)
        scroll.set_child(self.list_box)
        self.list_page.append(scroll)

        self.stack.add_named(self.list_page, "list")

        # 2. Settings Page (Reusing ChatSidebar)
        self.settings_sidebar = ChatSidebar(config=self.config, llm_client=self.llm_client)

        # Override the back button in settings if it exists or add one
        settings_header = self.settings_sidebar.get_first_child() # Usually Adw.HeaderBar
        if isinstance(settings_header, Adw.HeaderBar):
            back_btn = Gtk.Button(icon_name="go-previous-symbolic")
            back_btn.connect("clicked", lambda x: self.stack.set_visible_child_name("list"))
            settings_header.pack_start(back_btn)

        self.stack.add_named(self.settings_sidebar, "settings")

        self.append(self.stack)
        self._populate()

    def _populate(self):
        # Clear existing
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
            row = Adw.ActionRow(title=conv.get('name') or conv.get('title') or conv.get('id'))
            row.set_subtitle(conv.get('model') or "")
            row.set_activatable(True)
            row.cid = conv.get('id')
            self.list_box.append(row)

    def _on_row_activated(self, list_box, row):
        cid = getattr(row, 'cid', None)
        if cid and self.on_conversation_selected:
            self.on_conversation_selected(cid)

    def refresh(self):
        self._populate()

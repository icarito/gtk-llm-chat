import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, GObject, Gdk
import time
import os
import threading
import gettext

from .chat_application import _, debug_print
from .llm_client import LLMClient
from .db_operations import ChatHistory
from .style_manager import style_manager
from .resource_manager import resource_manager
from .widgets import MessageWidget, Message
from .llm_conversation_sidebar import LLMConversationSidebar

class LLMChatWindow(Adw.Window):
    def __init__(self, application, config=None, backend=None):
        super().__init__(application=application)
        self.config = config or {}
        self.cid = self.config.get('cid')
        self.benchmark_startup = self.config.get('benchmark_startup', False)
        self.start_time = self.config.get('start_time')
        self.chat_history = ChatHistory()
        self._injected_backend = backend is not None
        self.backend = backend
        self.current_message_widget = None
        self.accumulated_response = ""
        self._composing_timeout_id = None
        self.roster_sidebar = None
        self.model_sidebar = None

        title = _("New Chat")
        self.set_title(title)

        # Toolbar View with two rows
        self.toolbar_view = Adw.ToolbarView()

        # Row 1: Primary actions
        self.header_row1 = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle.new(title, "")
        self.header_row1.set_title_widget(self.title_widget)

        # Sidebar Toggle Button
        self.sidebar_button = Gtk.ToggleButton()
        resource_manager.set_widget_icon_name(self.sidebar_button, "sidebar-show-symbolic")
        self.sidebar_button.set_tooltip_text(_("Show Sidebar"))
        self.header_row1.pack_start(self.sidebar_button)

        # Menu Button
        primary_menu = Gio.Menu()
        primary_menu.append(_("New Conversation"), "app.new-conversation")
        self.menu_button = Gtk.MenuButton()
        resource_manager.set_widget_icon_name(self.menu_button, "view-more-symbolic")
        self.menu_button.set_menu_model(primary_menu)
        self.header_row1.pack_end(self.menu_button)

        self.toolbar_view.add_top_bar(self.header_row1)

        # Row 2: Contextual info
        self.header_row2 = Adw.HeaderBar()
        self.header_row2.add_css_class("flat")
        self.subtitle_label = Gtk.Label()
        self.subtitle_label.add_css_class("dim-label")
        self.subtitle_label.add_css_class("caption")
        self.header_row2.set_title_widget(self.subtitle_label)
        self.toolbar_view.add_top_bar(self.header_row2)

        # Split View
        self.split_view = Adw.OverlaySplitView()
        self.split_view.set_sidebar_position(Gtk.PackType.START)
        self.split_view.bind_property("show-sidebar", self.sidebar_button, "active",
                                      GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        
        # Main Chat Content
        chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.messages_box.set_margin_all(12)
        scroll.set_child(self.messages_box)
        chat_box.append(scroll)
        
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.set_margin_all(6)
        input_box.add_css_class("card")
        self.input_text = Gtk.TextView()
        self.input_text.set_hexpand(True)
        self.input_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        input_box.append(self.input_text)
        self.send_button = Gtk.Button(label=_("Send"))
        self.send_button.add_css_class("suggested-action")
        self.send_button.connect("clicked", self._on_send_clicked)
        input_box.append(self.send_button)
        chat_box.append(input_box)

        self.split_view.set_content(chat_box)
        self.toolbar_view.set_content(self.split_view)
        self.set_content(self.toolbar_view)

        # Initialize Backend
        if self._injected_backend:
            # XMPP
            self.title_widget.set_subtitle(self.backend.get_display_name())
            self.subtitle_label.set_label(_("Connected"))
            from .xmpp_roster_sidebar import XmppRosterSidebar
            self.roster_sidebar = XmppRosterSidebar(self.backend.session,
                                                   on_contact_selected=self._on_roster_contact_selected)
            self.split_view.set_sidebar(self.roster_sidebar)
        else:
            # LLM
            self.backend = LLMClient(self.config, self.chat_history)
            self.backend.connect('ready', self._on_backend_ready)
            self.backend.connect('response', self._on_llm_response)
            self.backend.connect('finished', self._on_llm_finished)
            
            self.model_sidebar = LLMConversationSidebar(config=self.config,
                                                        llm_client=self.backend,
                                                        on_conversation_selected=self._on_llm_conv_selected)
            self.split_view.set_sidebar(self.model_sidebar)
            self.subtitle_label.set_label(self.backend.get_model_id() or "")

        self.connect('close-request', self._on_close_request)
        self.connect('show', self._on_window_show)

    def _on_send_clicked(self, button):
        buffer = self.input_text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if text:
            self.display_message(text, sender="user")
            buffer.set_text("")
            self.backend.send_prompt(text)

    def display_message(self, text, sender="user"):
        msg = Message(text, sender=sender)
        widget = MessageWidget(msg)
        self.messages_box.append(widget)
        GLib.idle_add(self._scroll_to_bottom)
        return widget

    def _on_backend_ready(self, client, model_id):
        self.subtitle_label.set_label(model_id)

    def _on_llm_response(self, client, response):
        if not self.current_message_widget or self.accumulated_response == "":
             self.current_message_widget = self.display_message(response, sender="assistant")
             self.accumulated_response = response
        else:
             self.accumulated_response += response
             self.current_message_widget.update_content(self.accumulated_response)
        GLib.idle_add(self._scroll_to_bottom)

    def _on_llm_finished(self, client, response_id):
        self.current_message_widget = None
        self.accumulated_response = ""
        if self.model_sidebar:
            self.model_sidebar.refresh()

    def _on_roster_contact_selected(self, bare_jid):
        app = self.get_application()
        app.open_xmpp_conversation(self.backend.session, bare_jid)
        self.split_view.set_show_sidebar(False)

    def _on_llm_conv_selected(self, cid):
        app = self.get_application()
        app.open_conversation_window({'cid': cid})
        self.split_view.set_show_sidebar(False)

    def _scroll_to_bottom(self):
        adj = self.messages_box.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _on_close_request(self, window):
        if self.backend:
            self.backend.shutdown()
        if self.roster_sidebar:
            self.roster_sidebar.shutdown()

        app = self.get_application()
        app._on_window_closed(self)
        return False

    def _on_window_show(self, window):
        self.input_text.grab_focus()

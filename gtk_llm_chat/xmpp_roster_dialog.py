"""
xmpp_roster_dialog.py - selector de contacto XMPP (spec 001, T6).

Punto de entrada separado del selector de modelos LLM (ver
specs/001-xmpp-backend/design.md, "Selector integration"): una lista
simple del roster de la sesión ya conectada. Elegir un contacto invoca
el callback con su bare JID.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .chat_application import _
from .style_manager import style_manager
from .xmpp_client import XmppSession


class XmppRosterDialog(Adw.Window):
    """Lista los contactos de una XmppSession ya conectada."""

    def __init__(self, session: XmppSession, parent=None, on_contact_selected=None):
        super().__init__(modal=True, transient_for=parent)
        self.session = session
        self._on_contact_selected = on_contact_selected

        self.set_title(_("Select XMPP Contact"))
        self.set_default_size(360, 480)
        style_manager.apply_to_widget(self, "main-container")

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('navigation-sidebar')
        self.list_box.connect('row-activated', self._on_row_activated)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self.list_box)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(scroll)
        self.set_content(toolbar_view)

        self._populate()
        session.connect('roster-updated', lambda _s: self._populate())

    def _populate(self):
        child = self.list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child

        if not self.session.roster_items:
            row = Adw.ActionRow(title=_("No contacts in your roster yet"))
            row.set_selectable(False)
            self.list_box.append(row)
            return

        for bare_jid, item in sorted(self.session.roster_items.items()):
            row = Adw.ActionRow(title=item.get('name') or bare_jid)
            if item.get('name'):
                row.set_subtitle(bare_jid)
            row.set_activatable(True)
            row.bare_jid = bare_jid
            self.list_box.append(row)

    def _on_row_activated(self, _list_box, row):
        bare_jid = getattr(row, 'bare_jid', None)
        if bare_jid and self._on_contact_selected:
            self._on_contact_selected(bare_jid)
            self.close()

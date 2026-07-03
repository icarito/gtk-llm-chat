"""
xmpp_roster_sidebar.py - panel de contactos persistente (spec 002, T3).

A diferencia de xmpp_roster_dialog.py (modal, de un solo uso), este es un
widget que vive dentro de la ventana de chat XMPP: lista los contactos
del roster con su presencia en vivo y notifica la selección de un
contacto vía callback.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .chat_application import _
from .xmpp_client import XmppSession


class XmppRosterSidebar(Gtk.Box):
    """Lista de contactos con presencia en vivo, para dockear en la ventana."""

    def __init__(self, session: XmppSession, on_contact_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.session = session
        self._on_contact_selected = on_contact_selected
        # bare_jid -> (row, presence_dot) para actualizar presencia sin recrear
        self._rows = {}

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.add_css_class("flat")
        header.set_title_widget(Gtk.Label(label=_("Contacts")))
        self.append(header)

        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class('navigation-sidebar')
        self.list_box.connect('row-activated', self._on_row_activated)
        scroll.set_child(self.list_box)
        self.append(scroll)

        self._populate()
        self._roster_handler = session.connect(
            'roster-updated', lambda _s: self._populate())
        self._presence_handler = session.connect(
            'presence-changed', self._on_presence_changed)

    def _presence_dot(self, state):
        dot = Gtk.Image.new_from_icon_name("media-record-symbolic")
        dot.add_css_class("success" if state == XmppSession.PRESENCE_ONLINE
                          else "dim-label")
        dot.set_tooltip_text(_("Online") if state == XmppSession.PRESENCE_ONLINE
                             else _("Offline"))
        return dot

    def _populate(self):
        child = self.list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list_box.remove(child)
            child = nxt
        self._rows = {}

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
            dot = self._presence_dot(item.get('presence', XmppSession.PRESENCE_OFFLINE))
            row.add_prefix(dot)
            self.list_box.append(row)
            self._rows[bare_jid] = (row, dot)

    def _on_presence_changed(self, _session, bare_jid, state):
        entry = self._rows.get(bare_jid)
        if entry is None:
            return
        row, old_dot = entry
        new_dot = self._presence_dot(state)
        row.remove(old_dot)
        row.add_prefix(new_dot)
        self._rows[bare_jid] = (row, new_dot)

    def _on_row_activated(self, _list_box, row):
        bare_jid = getattr(row, 'bare_jid', None)
        if bare_jid and self._on_contact_selected:
            self._on_contact_selected(bare_jid)

    def shutdown(self):
        """Suelta los handlers de la sesión compartida."""
        self.session.disconnect(self._roster_handler)
        self.session.disconnect(self._presence_handler)

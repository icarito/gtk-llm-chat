"""
xmpp_roster_sidebar.py - panel de contactos persistente (spec 002/003).

Widget que vive dentro de la ventana de chat XMPP: lista los contactos
del roster con su presencia en vivo y notifica la selección de un
contacto vía callback. Es el único selector de contacto de la app — no
hay un diálogo modal aparte; una ventana sin conversación elegida
todavía simplemente muestra este mismo panel (spec 003).
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .chat_application import _
from .resource_manager import resource_manager
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
            self._append_add_contact_row()
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

        self._append_add_contact_row()

    def _append_add_contact_row(self):
        row = Adw.ActionRow(title=_("Add Contact…"))
        row.add_css_class("dim-label")
        row.add_prefix(resource_manager.create_icon_widget("list-add-symbolic"))
        row.set_activatable(True)
        row.bare_jid = None  # marca especial: no es un contacto
        row.connect("activated", lambda _r: self._show_add_contact_dialog())
        self.list_box.append(row)

    def _show_add_contact_dialog(self):
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading=_("Add Contact"),
            body=_("Enter the JID of the contact you want to add (e.g. user@example.org):"),
        )
        entry = Gtk.Entry(placeholder_text="user@example.org")
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("add", _("Add"))
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")

        def on_response(_dialog, response):
            if response == "add":
                jid = entry.get_text().strip()
                if jid:
                    self.session.add_contact(jid)

        dialog.connect("response", on_response)
        dialog.present()

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

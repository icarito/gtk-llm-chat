"""
chat_roster_sidebar.py - roster unificado de chats.

Lista conversaciones LLM y contactos XMPP en el mismo panel lateral. El
roster es la superficie primaria para cambiar de conversación, sin separar
visualmente "modo LLM" y "modo XMPP".
"""
import gi
import json
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib

from .chat_application import _
from .chat_sidebar import ChatSidebar
from .db_operations import ChatHistory
from .debug_utils import debug_print
from .resource_manager import resource_manager
from .xmpp_client import XmppSession


def _display_name(bare_jid, name=None):
    """Nombre legible de un contacto: el del roster, o la parte local del JID
    ("rolando@hablar.fuentelibre.org" -> "rolando"), que dice más que el JID
    entero en una fila estrecha."""
    if name and name.strip():
        return name.strip()
    local = bare_jid.split('@')[0]
    return local or bare_jid


class ChatRosterSidebar(Gtk.Box):
    """Roster único: conversaciones LLM + contactos XMPP."""

    def __init__(
        self, config, llm_client=None, chat_history=None, xmpp_session=None,
        on_llm_conversation_selected=None, on_xmpp_contact_selected=None,
        on_xmpp_account=None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.config = config or {}
        self.llm_client = llm_client
        self.chat_history = chat_history or ChatHistory()
        self.xmpp_session = xmpp_session
        self._on_llm_conversation_selected = on_llm_conversation_selected
        self._on_xmpp_contact_selected = on_xmpp_contact_selected
        self._on_xmpp_account = on_xmpp_account
        self._rows = {}
        self._handler_ids = []

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.add_named(self._build_list_page(), "list")

        # Los parámetros del modelo ya no viven aquí dentro. Compartían stack con
        # la lista de contactos, así que abrir los ajustes tapaba el roster;
        # ahora son el sidebar derecho de la ventana (spec 009), y el roster se
        # queda con lo suyo: la lista.
        self.options_sidebar = None
        if self.llm_client is not None:
            self.options_sidebar = ChatSidebar(
                config=self.config, llm_client=self.llm_client)

        self.append(self.stack)
        self._populate()

        if self.xmpp_session is not None:
            self._handler_ids = [
                self.xmpp_session.connect('roster-updated', lambda _s: self._populate()),
                # Un avatar recién descargado tiene que aparecer sin reabrir.
                self.xmpp_session.connect('avatar-changed', lambda _s, _jid: self._populate()),
                self.xmpp_session.connect('presence-changed', self._on_presence_changed),
                self.xmpp_session.connect(
                    'contact-status-changed', self._on_contact_status_changed),
            ]

    def _build_list_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.add_css_class("flat")
        header.set_title_widget(Gtk.Label(label=_("Roster")))

        if self.llm_client is not None:
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

    def _section_label(self, text):
        label = Gtk.Label(label=text)
        label.add_css_class("heading")
        label.add_css_class("dim-label")
        label.set_xalign(0)
        label.set_margin_top(12)
        label.set_margin_bottom(6)
        label.set_margin_start(12)
        label.set_margin_end(12)
        return label

    def _clear(self):
        child = self.list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list_box.remove(child)
            child = nxt
        self._rows = {}

    def _populate(self):
        self._clear()
        self._append_llm_conversations()
        self._append_xmpp_contacts()

    def _append_llm_conversations(self):
        self.list_box.append(self._section_label(_("Conversations")))
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
            row.chat_kind = "llm"
            row.cid = conv.get('id')
            self.list_box.append(row)

    def _contacts_by_activity(self):
        """Contactos por actividad reciente: la conversación que se acaba de
        mover, arriba. Los que no tienen historial van al final por nombre, en
        vez de intercalarse entre las conversaciones vivas."""
        items = self.xmpp_session.roster_items.items()
        history = getattr(self.xmpp_session, 'history', None)
        latest = {}
        if history is not None:
            try:
                latest = history.get_latest_timestamps()
            except Exception:
                # El orden del roster nunca debe tumbar la barra lateral.
                latest = {}

        # Dos pasadas, aprovechando que sorted() es estable: primero por nombre
        # (el desempate), y encima por actividad descendente. Los timestamps son
        # ISO-8601, así que comparan bien como texto.
        by_name = sorted(items, key=lambda e: _display_name(e[0], e[1].get('name')).lower())
        with_activity = [e for e in by_name if latest.get(e[0])]
        without_activity = [e for e in by_name if not latest.get(e[0])]
        with_activity.sort(key=lambda e: latest[e[0]], reverse=True)
        return with_activity + without_activity

    def _append_xmpp_contacts(self):
        self.list_box.append(self._section_label(_("Contacts")))
        if self.xmpp_session is None:
            row = Adw.ActionRow(title=_("Set Up XMPP Account…"))
            row.set_activatable(True)
            row.chat_kind = "xmpp-account"
            self.list_box.append(row)
            return

        if not self.xmpp_session.roster_items:
            row = Adw.ActionRow(title=_("No contacts in your roster yet"))
            row.set_selectable(False)
            self.list_box.append(row)
        else:
            for bare_jid, item in self._contacts_by_activity():
                row = Adw.ActionRow(title=_display_name(bare_jid, item.get('name')))
                subtitle = self._display_status(item, bare_jid)
                if subtitle:
                    row.set_subtitle(subtitle)
                row.set_activatable(True)
                row.chat_kind = "xmpp"
                row.bare_jid = bare_jid
                avatar = self._contact_avatar(bare_jid, item)
                if avatar is not None:
                    row.add_prefix(avatar)
                dot = self._presence_dot(
                    item.get('presence', XmppSession.PRESENCE_OFFLINE))
                row.add_prefix(dot)
                self.list_box.append(row)
                self._rows[bare_jid] = (row, dot)

        self._append_add_contact_row()

    def _contact_avatar(self, bare_jid, item):
        """Avatar del contacto (XEP-0084) si lo publicó; si no, Adw.Avatar cae
        solo en las iniciales del nombre, que ya es mejor que un icono igual
        para todos."""
        name = _display_name(bare_jid, item.get('name'))
        avatar = Adw.Avatar(size=32, text=name, show_initials=True)
        path = None
        if self.xmpp_session is not None:
            path = (getattr(self.xmpp_session, 'avatar_paths', {}) or {}).get(bare_jid)
            if path is None:
                # Aún no lo tenemos: los eventos PEP sólo llegan cuando el
                # contacto publica, así que hay que preguntar por el actual.
                # Si llega, 'avatar-changed' repuebla el roster.
                try:
                    self.xmpp_session.fetch_avatar(bare_jid)
                except Exception as exc:  # noqa: BLE001
                    debug_print(f"[avatar] no se pudo pedir el de {bare_jid}: {exc}")
        if path:
            try:
                avatar.set_custom_image(Gdk.Texture.new_from_filename(path))
            except GLib.Error as exc:
                debug_print(f"[avatar] no se pudo pintar el de {bare_jid}: {exc}")
        return avatar

    def _display_status(self, item, bare_jid):
        status = item.get('status') or ''
        parsed = self._parse_agent_status(status)
        if parsed:
            activity = parsed.get('activity') or ''
            tool = parsed.get('tool') or ''
            if tool:
                return _("Usando herramienta: ") + str(tool)
            label = self._friendly_activity(activity)
            if label:
                return label
        return bare_jid if item.get('name') else ''

    @staticmethod
    def _parse_agent_status(status):
        text = str(status or '').strip()
        if not text:
            return {}
        json_text = text
        if json_text.startswith('nanoclaw:') or json_text.startswith('openclaw:'):
            json_text = json_text.split(':', 1)[1].strip()
        if not json_text.startswith('{'):
            if text.lower().startswith('tool:'):
                return {'activity': 'processing', 'tool': text.split(':', 1)[1].strip()}
            return {'activity': text}
        try:
            data = json.loads(json_text)
        except (TypeError, ValueError):
            return {'activity': text}
        if not isinstance(data, dict):
            return {'activity': text}
        return {
            'activity': data.get('activity') or data.get('state') or data.get('availability') or '',
            'availability': data.get('availability') or '',
            'tool': data.get('tool') or data.get('current_tool') or '',
        }

    @staticmethod
    def _friendly_activity(activity):
        lower = str(activity or '').strip().lower()
        if lower in ('processing', 'busy', 'working'):
            return _("Trabajando")
        if lower == 'available':
            return _("Disponible")
        if lower in ('waiting', 'queued'):
            return _("En espera")
        if lower in ('paused', 'away', 'xa'):
            return _("Ausente")
        return str(activity or '').strip()

    def _append_add_contact_row(self):
        add_button = Gtk.Button()
        add_button.set_child(resource_manager.create_icon_widget("list-add-symbolic"))
        add_button.add_css_class("circular")
        add_button.add_css_class("flat")
        add_button.set_size_request(32, 32)
        add_button.set_tooltip_text(_("Add Contact…"))
        add_button.set_halign(Gtk.Align.CENTER)
        add_button.connect("clicked", lambda _b: self._show_add_contact_dialog())

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.chat_kind = "add-contact"
        row.set_child(add_button)
        self.list_box.append(row)

    def _presence_dot(self, state):
        dot = Gtk.Image.new_from_icon_name("media-record-symbolic")
        if state == XmppSession.PRESENCE_ONLINE:
            dot.add_css_class("success")
            dot.set_tooltip_text(_("Online"))
        elif state == XmppSession.PRESENCE_BUSY:
            dot.add_css_class("error")
            dot.set_tooltip_text(_("Busy"))
        elif state == XmppSession.PRESENCE_AWAY:
            dot.add_css_class("warning")
            dot.set_tooltip_text(_("Away"))
        else:
            dot.add_css_class("dim-label")
            dot.set_tooltip_text(_("Offline"))
        return dot

    def _show_add_contact_dialog(self):
        if self.xmpp_session is None:
            if self._on_xmpp_account is not None:
                self._on_xmpp_account()
            return

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
                    self.xmpp_session.add_contact(jid)

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

    def _on_contact_status_changed(self, session, bare_jid):
        entry = self._rows.get(bare_jid)
        if entry is None:
            return
        row, _dot = entry
        item = session.roster_items.get(bare_jid, {})
        subtitle = self._display_status(item, bare_jid)
        row.set_subtitle(subtitle)

    def _on_row_activated(self, _list_box, row):
        kind = getattr(row, 'chat_kind', None)
        if kind == "llm" and self._on_llm_conversation_selected is not None:
            cid = getattr(row, 'cid', None)
            if cid:
                self._on_llm_conversation_selected(cid)
        elif kind == "xmpp" and self._on_xmpp_contact_selected is not None:
            bare_jid = getattr(row, 'bare_jid', None)
            if bare_jid:
                self._on_xmpp_contact_selected(bare_jid)
        elif kind == "xmpp-account" and self._on_xmpp_account is not None:
            self._on_xmpp_account()

    def refresh(self):
        self._populate()

    def show_list(self):
        self.stack.set_visible_child_name("list")

    def shutdown(self):
        if self.xmpp_session is not None:
            for handler_id in self._handler_ids:
                self.xmpp_session.disconnect(handler_id)
        self._handler_ids = []

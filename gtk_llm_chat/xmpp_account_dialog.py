"""
xmpp_account_dialog.py - diálogo de cuenta XMPP (spec 001, T4; edición
de la cuenta ya conectada añadida después).

Ventana simple: JID + contraseña, botón Connect. En éxito persiste la
cuenta (xmpp_account.save_account) y notifica vía callback para que el
selector pueda abrir el roster; en fallo muestra el error y deja
reintentar sin perder lo escrito.

Si ya hay una cuenta configurada (xmpp_account.load_account), el diálogo
se abre en modo edición: título "XMPP Account", JID precargado (editable)
y el campo de contraseña vacío con un placeholder que indica que dejarlo
vacío conserva la contraseña actual — así no hay que leer ni mostrar la
contraseña guardada solo para reabrir el diálogo.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from .chat_application import _
from .debug_utils import debug_print
from .style_manager import style_manager
from .xmpp_account import load_account, save_account, is_omemo_enabled
from .xmpp_client import XmppSession, STATE_CONNECTED, STATE_DISCONNECTED


class XmppAccountDialog(Adw.Window):
    """Pide JID + contraseña, valida conectando de verdad, y persiste."""

    def __init__(self, parent=None, on_account_ready=None):
        super().__init__(modal=True, transient_for=parent)
        self._on_account_ready = on_account_ready
        self._probe_session = None

        existing = load_account()
        self._existing_jid, self._existing_password = existing or (None, None)

        self.set_title(_("XMPP Account") if existing else _("Add XMPP Account"))
        self.set_default_size(380, -1)
        style_manager.apply_to_widget(self, "main-container")

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        self.jid_row = Adw.EntryRow(title=_("JID (e.g. user@yax.im)"))
        if self._existing_jid:
            self.jid_row.set_text(self._existing_jid)
        self.password_row = Adw.PasswordEntryRow(title=_("Password"))
        if self._existing_jid:
            self.password_row.set_title(_("Password (leave empty to keep current)"))

        self.omemo_row = Adw.SwitchRow(title=_("Enable OMEMO encryption (XEP-0384)"))
        self.omemo_row.set_active(is_omemo_enabled())

        group = Adw.PreferencesGroup()
        group.add(self.jid_row)
        group.add(self.password_row)
        group.add(self.omemo_row)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_wrap(True)
        self.status_label.add_css_class("error")
        self.status_label.set_visible(False)

        self.connect_button = Gtk.Button(
            label=_("Save") if self._existing_jid else _("Connect"))
        self.connect_button.add_css_class("suggested-action")
        self.connect_button.connect('clicked', self._on_connect_clicked)

        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.append(group)
        content.append(self.status_label)

        button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.END)
        button_box.append(self.spinner)
        button_box.append(self.connect_button)
        content.append(button_box)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(content)
        self.set_content(toolbar_view)

        self.password_row.connect('entry-activated', self._on_connect_clicked)

    def _set_busy(self, busy: bool):
        self.connect_button.set_sensitive(not busy)
        self.jid_row.set_sensitive(not busy)
        self.password_row.set_sensitive(not busy)
        # El usuario debe poder desactivar OMEMO incluso mientras la prueba
        # de credenciales está en curso; el valor se persiste al confirmar.
        self.omemo_row.set_sensitive(True)
        self.spinner.set_visible(busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

    def _show_error(self, message: str):
        self.status_label.set_label(message)
        self.status_label.set_visible(True)

    def _on_connect_clicked(self, _widget):
        jid = self.jid_row.get_text().strip()
        password = self.password_row.get_text()
        if not password and jid == self._existing_jid and self._existing_password:
            # Modo edición, campo dejado vacío a propósito: mantener la
            # contraseña ya guardada en vez de exigir volver a escribirla.
            password = self._existing_password
        if not jid or not password:
            self._show_error(_("Enter both a JID and a password."))
            return

        self.status_label.set_visible(False)
        self._set_busy(True)

        # Sesión de prueba: solo valida credenciales, no se reutiliza.
        # send_message() no aplica aquí (aún no hay UI de conversación).
        self._probe_session = XmppSession(jid, password, auto_reconnect=False)

        def on_state(_session, state):
            self._on_probe_state(jid, password, state)

        self._probe_session.connect('state-changed', on_state)
        self._probe_session.connect('session-error', self._on_probe_error)
        self._probe_session.connect_to_server()

        def on_timeout():
            if self._probe_session is not None:
                self._show_error(_("Connection timed out."))
                self._cleanup_probe()
            return GLib.SOURCE_REMOVE
        GLib.timeout_add_seconds(20, on_timeout)

    def _on_probe_state(self, jid, password, state):
        if state == STATE_CONNECTED:
            debug_print(f"XmppAccountDialog: credenciales válidas para {jid}")
            try:
                omemo_enabled = self.omemo_row.get_active()
                save_account(jid, password, omemo_enabled=omemo_enabled)
            except RuntimeError as err:
                self._show_error(str(err))
                self._cleanup_probe()
                return
            self._cleanup_probe()
            self._set_busy(False)
            if self._on_account_ready:
                self._on_account_ready(jid)
            self.close()
        elif state == STATE_DISCONNECTED and self._probe_session is not None:
            # Se desconectó antes de confirmar 'connected': el error ya
            # llegó (o llegará) por 'session-error'.
            self._cleanup_probe()

    def _on_probe_error(self, _session, message):
        self._show_error(_("Could not connect: {error}").format(error=message))
        self._set_busy(False)

    def _cleanup_probe(self):
        if self._probe_session is not None:
            session, self._probe_session = self._probe_session, None
            session.shutdown()
            self._set_busy(False)

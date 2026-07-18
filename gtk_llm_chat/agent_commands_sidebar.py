"""
agent_commands_sidebar.py - los comandos ad-hoc del agente (XEP-0050) como
panel lateral, no como popover.

El popover del header no daba para más: los comandos llegan agrupados
(sesión / skills / administración), traen descripción, y algunos piden un
formulario (XEP-0004) que hasta ahora se abría en un diálogo aparte. Aquí caben
los tres.

Es el `get_settings_panel()` del backend XMPP — el equivalente al panel de
parámetros del modelo que ofrece el backend LLM.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .chat_application import _
from .debug_utils import debug_print
from .xmpp_commands import (
    XmppCommandClient,
    command_result_body,
    is_completed,
    next_action_for,
)

# Secciones del menú, en orden. Cada comando cae en la suya por el prefijo de su
# nodo; lo que no encaje en ninguna va al final, de modo que un comando nuevo del
# servidor aparece sin tocar este archivo.
SECTIONS = (
    (_("Session"), ('context', 'compact', 'clear', 'model',
                    'session-status', 'session-reset')),
    (_("Skills"), ('skill:',)),
    (_("Administration"), ('agent-', 'approval-bypass')),
)
OTHER_SECTION = _("Other")

# Comandos irreversibles: se confirman antes de lanzarlos. No llevan formulario,
# así que sin esto un clic despistado bastaría para borrar el contexto.
DESTRUCTIVE_NODES = ('clear', 'session-reset')


def section_for(node):
    for index, (_name, prefixes) in enumerate(SECTIONS):
        for prefix in prefixes:
            # Nodo exacto ('clear') o espacio de nombres ('skill:', 'agent-').
            if node == prefix or (prefix[-1] in ':-' and node.startswith(prefix)):
                return index
    return len(SECTIONS)


def section_name(index):
    return SECTIONS[index][0] if index < len(SECTIONS) else OTHER_SECTION


class AgentCommandsSidebar(Gtk.Box):
    """Lista los comandos del agente y ejecuta el que se elija, mostrando el
    formulario o el resultado en el propio panel."""

    def __init__(self, session, bare_jid, on_error=None, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self.session = session
        self.bare_jid = bare_jid
        self._on_error = on_error
        self._client = XmppCommandClient(session, bare_jid)
        self._pending_command = None

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title=_("Agent Commands")))
        refresh = Gtk.Button()
        refresh.set_icon_name("view-refresh-symbolic")
        refresh.add_css_class("flat")
        refresh.set_tooltip_text(_("Reload commands"))
        refresh.connect("clicked", lambda _b: self.refresh())
        header.pack_end(refresh)
        self.append(header)

        # Dos páginas: la lista, y el formulario/resultado de un comando.
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_vexpand(True)
        self.append(self.stack)

        self._list_page = Gtk.ScrolledWindow()
        self._list_page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._list_box.set_margin_top(12)
        self._list_box.set_margin_bottom(12)
        self._list_box.set_margin_start(12)
        self._list_box.set_margin_end(12)
        self._list_page.set_child(self._list_box)
        self.stack.add_named(self._list_page, "list")

        self._detail_page = Gtk.ScrolledWindow()
        self._detail_page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.stack.add_named(self._detail_page, "detail")

        self._set_placeholder(_("Loading commands…"))
        self.refresh()

    # --- Lista de comandos ---

    def refresh(self):
        if not self.session.is_connected:
            self._set_placeholder(_("Not connected"))
            return
        self._client.request_commands(self._on_commands, self._on_request_error)

    def _on_commands(self, commands):
        self._build_list(commands)
        self.stack.set_visible_child_name("list")

    def _on_request_error(self, message):
        debug_print(f"AgentCommandsSidebar: {message}")
        self._set_placeholder(_("Could not load commands"))

    def _clear_list(self):
        child = self._list_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

    def _set_placeholder(self, text):
        self._clear_list()
        label = Gtk.Label(label=text)
        label.add_css_class("dim-label")
        label.set_margin_top(24)
        self._list_box.append(label)
        self.stack.set_visible_child_name("list")

    def _build_list(self, commands):
        self._clear_list()
        if not commands:
            self._set_placeholder(_("This agent exposes no commands"))
            return

        grouped = {}
        for command in commands:
            grouped.setdefault(section_for(command.node), []).append(command)

        for index in sorted(grouped):
            group = Adw.PreferencesGroup(title=section_name(index))
            for command in grouped[index]:
                row = Adw.ActionRow(title=command.name or command.node)
                row.set_activatable(True)
                row.connect("activated", self._on_row_activated, command)
                if command.node in DESTRUCTIVE_NODES:
                    row.add_css_class("error")
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                group.add(row)
            self._list_box.append(group)

    # --- Ejecución ---

    def _on_row_activated(self, _row, command):
        if command.node in DESTRUCTIVE_NODES:
            self._confirm(command)
            return
        self._execute(command)

    def _confirm(self, command):
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            heading=command.name or command.node,
            body=_("This cannot be undone. Run it anyway?"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("run", _("Run"))
        dialog.set_response_appearance("run", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect(
            "response",
            lambda _d, response: self._execute(command) if response == "run" else None)
        dialog.present()

    def _execute(self, command, dataform=None, action=None):
        self._show_detail(Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER,
                                      valign=Gtk.Align.CENTER, vexpand=True))
        self._client.execute(
            command, self._on_result, self._on_exec_error,
            action=action, dataform=dataform)

    def _on_exec_error(self, message):
        if self._on_error:
            self._on_error(message)
        self._show_result_text(_("Error: ") + str(message))

    def _on_result(self, result):
        """Un comando puede terminar de una (nota de texto) o pedir un
        formulario; en el segundo caso se muestra aquí, no en un diálogo
        aparte."""
        if is_completed(result) or result.data is None:
            self._show_result_text(command_result_body(result))
            return
        self._show_form(result)

    def _show_form(self, command):
        from .xmpp_commands import XmppCommandFormDialog
        # Reutiliza el mismo renderizador de XEP-0004 que el diálogo, pero
        # embebido: el usuario no pierde de vista dónde estaba.
        dialog = XmppCommandFormDialog(
            self.get_root(), command,
            lambda dataform: self._execute(
                command, dataform=dataform, action=next_action_for(command)),
            on_cancel=lambda: self.stack.set_visible_child_name("list"))
        dialog.present()

    def _show_result_text(self, text):
        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_xalign(0)
        label.set_selectable(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.append(label)
        back = Gtk.Button(label=_("Back to commands"))
        back.add_css_class("flat")
        back.set_halign(Gtk.Align.START)
        back.connect("clicked", lambda _b: self.stack.set_visible_child_name("list"))
        box.append(back)
        self._show_detail(box)

    def _show_detail(self, child):
        self._detail_page.set_child(child)
        self.stack.set_visible_child_name("detail")

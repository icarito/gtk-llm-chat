"""
xmpp_commands.py - cliente XEP-0050/XEP-0004 para agentes NanoClaw.

Mantiene la ejecución de comandos ad-hoc fuera de xmpp_client.py, que se
queda como transporte/sesión. Usa los módulos nbxmpp existentes.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from nbxmpp.const import AdHocAction, AdHocStatus
from nbxmpp.modules.dataforms import SimpleDataForm, create_field, extend_form

from .chat_application import _
from .debug_utils import debug_print


class XmppCommandClient:
    def __init__(self, session, bare_jid: str):
        self.session = session
        self.bare_jid = bare_jid
        self._pending_callbacks = []

    @property
    def target_jid(self):
        return self.session.get_agent_full_jid(self.bare_jid) or self.bare_jid

    def _done_callback(self, on_success, on_error):
        def cb(task):
            self._pending_callbacks.remove(cb)
            self._finish_task(task, on_success, on_error)
        self._pending_callbacks.append(cb)
        return cb

    def request_commands(self, on_success, on_error):
        if not self.session.is_connected:
            on_error(_("Not connected to the XMPP server"))
            return
        task = self.session._client.get_module('AdHoc').request_command_list(
            self.target_jid)
        task.add_done_callback(self._done_callback(on_success, on_error))

    def execute(self, command, on_success, on_error, action=None, dataform=None):
        if not self.session.is_connected:
            on_error(_("Not connected to the XMPP server"))
            return
        effective_action = action or AdHocAction.EXECUTE
        debug_print(
            "XmppCommandClient: execute "
            f"jid={command.jid} node={command.node} "
            f"action={effective_action.value}")
        task = self.session._client.get_module('AdHoc').execute_command(
            command, action=effective_action, dataform=dataform)
        task.add_done_callback(self._done_callback(on_success, on_error))

    def _finish_task(self, task, on_success, on_error):
        try:
            on_success(task.finish())
        except Exception as err:
            debug_print(f"XmppCommandClient: {err}")
            on_error(str(err))


class XmppCommandFormDialog(Adw.Window):
    def __init__(self, parent, command, on_submit, on_cancel=None):
        super().__init__(modal=True, transient_for=parent)
        self.command = command
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._submitted = False
        self._field_widgets = {}
        self._fixed_fields = []
        self._hidden_fields = []

        form = extend_form(command.data)
        title = form.title or command.name or _("Agent Command")
        self.set_title(title)
        self.set_default_size(420, -1)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        group = Adw.PreferencesGroup(title=title)
        if form.instructions:
            group.set_description(form.instructions)

        for field in form.iter_fields():
            self._add_field(group, field)

        cancel_button = Gtk.Button(label=_("Cancel"))
        cancel_button.connect("clicked", self._cancel)
        submit_button = Gtk.Button(label=_("Submit"))
        submit_button.add_css_class("suggested-action")
        submit_button.connect("clicked", self._submit)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        buttons.append(cancel_button)
        buttons.append(submit_button)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.append(group)
        content.append(buttons)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(content)
        self.set_content(toolbar_view)
        self.connect("close-request", self._on_close_request)

    def _cancel(self, _button=None):
        self.close()

    def _on_close_request(self, _window):
        if not self._submitted and self._on_cancel is not None:
            callback, self._on_cancel = self._on_cancel, None
            callback()
        return False

    def _add_field(self, group, field):
        typ = field.type_
        if typ == 'hidden':
            self._hidden_fields.append(field)
            return
        if typ == 'fixed':
            # Fila de solo texto (sin var), usada para instrucciones sueltas.
            # field.value puede venir vacío; no dejar el título en None.
            row = Adw.ActionRow(title=field.value or '')
            row.set_selectable(False)
            group.add(row)
            self._fixed_fields.append(field)
            return
        if typ == 'boolean':
            row = Adw.SwitchRow(title=field.label)
            row.set_active(bool(field.value))
            group.add(row)
            self._field_widgets[field.var] = (field, row)
            return
        if typ == 'list-single':
            # ComboRow es el control Adwaita idiomático para list-single.
            # iter_options() de nbxmpp yield (value, label) en ese orden.
            options = list(field.iter_options())
            labels = [label for _value, label in options]
            row = Adw.ComboRow(title=field.label)
            row.set_model(Gtk.StringList.new(labels))
            active = 0
            for index, (value, _label) in enumerate(options):
                if value == field.value:
                    active = index
                    break
            row.set_selected(active)
            group.add(row)
            self._field_widgets[field.var] = (field, row, options)
            return
        if typ == 'text-multi':
            # Un TextView no cabe en el suffix de un ActionRow (se ve
            # apretado): va en su propia fila de ancho completo, con label
            # encima y el área de texto dentro de un ScrolledWindow con
            # borde. field.value nunca es None en nbxmpp, pero se normaliza
            # por si el tipo real difiere.
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            label = Gtk.Label(label=field.label, xalign=0)
            label.add_css_class("caption-heading")
            box.append(label)
            text_view = Gtk.TextView()
            text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            text_view.set_top_margin(6)
            text_view.set_bottom_margin(6)
            text_view.set_left_margin(6)
            text_view.set_right_margin(6)
            text_view.get_buffer().set_text(field.value or '', -1)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_min_content_height(96)
            scrolled.set_child(text_view)
            frame = Gtk.Frame()
            frame.set_child(scrolled)
            box.append(frame)
            group.add(box)
            self._field_widgets[field.var] = (field, text_view)
            return

        row_cls = Adw.PasswordEntryRow if typ == 'text-private' else Adw.EntryRow
        row = row_cls(title=field.label)
        row.set_text(field.value or '')
        group.add(row)
        self._field_widgets[field.var] = (field, row)

    def _submit(self, _button):
        fields = []
        for field in self._hidden_fields:
            fields.append(create_field('hidden', var=field.var, value=field.value))
        for var, entry in self._field_widgets.items():
            field = entry[0]
            typ = field.type_
            if typ == 'boolean':
                value = entry[1].get_active()
            elif typ == 'list-single':
                dropdown, options = entry[1], entry[2]
                selected = dropdown.get_selected()
                value = options[selected][0] if selected < len(options) else ''
            elif typ == 'text-multi':
                buffer = entry[1].get_buffer()
                value = buffer.get_text(
                    buffer.get_start_iter(), buffer.get_end_iter(), True)
            else:
                value = entry[1].get_text()
            fields.append(create_field(typ, var=var, value=value))

        self._submitted = True
        self._on_submit(SimpleDataForm(type_='submit', fields=fields))
        self.close()


def command_result_body(command):
    parts = []
    for note in command.notes or []:
        if note.text:
            parts.append(note.text)
    if command.data is not None:
        try:
            form = extend_form(command.data)
            for field in form.iter_fields():
                value = getattr(field, 'value', '')
                if value:
                    parts.append(f"{field.label}: {value}")
        except Exception as err:
            debug_print(f"show_command_result: {err}")
    return "\n".join(parts) or _("Command completed.")


def show_command_result(parent, command):
    body = command_result_body(command)
    dialog = Adw.MessageDialog(
        transient_for=parent,
        modal=True,
        heading=command.name or _("Agent Command"),
        body=body,
    )
    dialog.add_response("ok", _("OK"))
    dialog.present()


def next_action_for(command):
    if command.default in (AdHocAction.NEXT, AdHocAction.COMPLETE):
        return command.default
    if command.actions and AdHocAction.NEXT in command.actions:
        return AdHocAction.NEXT
    return AdHocAction.COMPLETE


def is_completed(command):
    return command.status == AdHocStatus.COMPLETED

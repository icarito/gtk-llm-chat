"""
chat_type_picker.py - ventana inicial: elegir LLM o XMPP (spec 003).

Se muestra al abrir la app sin un tipo de conversación explícito (sin
CID, sin contacto): ni LLM ni XMPP se asumen por defecto. El usuario
elige con qué quiere hablar antes de que se abra nada interactuable.
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw

from .chat_application import _
from .resource_manager import resource_manager
from .style_manager import style_manager


class ChatTypePickerWindow(Adw.ApplicationWindow):
    """Pantalla '¿con quién quieres hablar?': LLM o XMPP."""

    def __init__(self, application, on_pick_llm=None, on_pick_xmpp=None):
        super().__init__(application=application)
        self._on_pick_llm = on_pick_llm
        self._on_pick_xmpp = on_pick_xmpp

        style_manager.apply_to_widget(self, "main-container")
        self.set_title(_("Gtk LLM Chat"))
        self.set_default_size(480, 420)
        self.set_size_request(400, 320)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        status_page = Adw.StatusPage()
        status_page.set_title(_("New Chat"))

        button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=18,
            halign=Gtk.Align.CENTER)

        button_box.append(self._make_choice_button(
            "brain-symbolic", _("LLM"), self._on_llm_clicked))
        button_box.append(self._make_choice_button(
            "system-users-symbolic", _("XMPP"), self._on_xmpp_clicked))

        status_page.set_child(button_box)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(status_page)
        self.set_content(toolbar_view)

    def _make_choice_button(self, icon_name, label_text, callback):
        icon = resource_manager.create_icon_widget(icon_name)
        icon.set_pixel_size(48)

        label = Gtk.Label(label=label_text)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.append(icon)
        content.append(label)

        button = Gtk.Button()
        button.set_child(content)
        button.add_css_class("card")
        button.add_css_class("choice-card")
        button.connect("clicked", callback)
        return button

    def _on_llm_clicked(self, _button):
        if self._on_pick_llm:
            self._on_pick_llm()
        self.close()

    def _on_xmpp_clicked(self, _button):
        if self._on_pick_xmpp:
            self._on_pick_xmpp()
        self.close()

import os
import sys
import threading
import gettext
from gi.repository import Gtk, Adw, Gio, Gdk, GLib

from .debug_utils import debug_print
from .style_manager import style_manager
from .resource_manager import resource_manager

_ = gettext.gettext

class WelcomeWindow(Adw.Window):
    def __init__(self, app, on_welcome_finished=None):
        super().__init__(application=app)
        self.app = app
        self.on_welcome_finished = on_welcome_finished
        self.config_data = {}
        self._model_selector_created = False
        self._models_loaded = False

        self.set_default_size(800, 600)
        self.set_title(_("Welcome to Gtk LLM Chat"))

        self.main_stack = Adw.ViewStack()
        
        self.carousel = Adw.Carousel()
        self.carousel.connect('page-changed', self._on_page_changed)
        
        # Panel 1: Welcome
        page1 = Adw.StatusPage(
            title=_("Welcome"),
            description=_("Gtk LLM Chat is a modern interface for Large Language Models.")
        )
        vbox1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.start_button = Gtk.Button(label=_("Start"))
        self.start_button.add_css_class("suggested-action")
        self.start_button.set_halign(Gtk.Align.CENTER)
        self.start_button.connect('clicked', self.on_start_clicked)
        vbox1.append(self.start_button)
        page1.set_child(vbox1)
        self.carousel.append(page1)

        # Panel 2: Model Selection
        page2_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page2_container.set_margin_all(24)
        self.panel2_placeholder = Gtk.Label(label=_("Loading models..."))
        page2_container.append(self.panel2_placeholder)
        self.carousel.append(page2_container)

        # Panel 3: Finish
        page3 = Adw.StatusPage(
            title=_("Ready!"),
            description=_("You are now ready to start chatting with AI models.")
        )
        self.finish_button = Gtk.Button(label=_("Finish"))
        self.finish_button.add_css_class("suggested-action")
        self.finish_button.set_halign(Gtk.Align.CENTER)
        self.finish_button.connect('clicked', self.on_finish_clicked)
        page3.set_child(self.finish_button)
        self.carousel.append(page3)

        self.set_content(self.carousel)
        self.connect('show', self._on_window_show)

    def _on_page_changed(self, carousel, index):
        if index == 1 and not self._model_selector_created:
            self.start_lazy_loading()

    def on_start_clicked(self, button):
        self.carousel.scroll_to(self.carousel.get_nth_page(1), True)

    def on_finish_clicked(self, button):
        if self.on_welcome_finished:
            self.on_welcome_finished(self.config_data)
        self.close()

    def start_lazy_loading(self):
        def load_modules():
            try:
                from .model_selector import WideModelSelector
                from .model_selection import ModelSelectionManager
                GLib.idle_add(self._create_model_selector, WideModelSelector, ModelSelectionManager)
            except Exception as e:
                debug_print(f"Error loading model selector modules: {e}")

        threading.Thread(target=load_modules, daemon=True).start()

    def _create_model_selector(self, WideModelSelector, ModelSelectionManager):
        self.model_manager = ModelSelectionManager(self.config_data)
        self.model_selector = WideModelSelector(manager=self.model_manager)
        
        parent = self.panel2_placeholder.get_parent()
        parent.remove(self.panel2_placeholder)
        parent.append(self.model_selector)
        
        self._model_selector_created = True
        self.model_selector.load_providers_and_models()
        self.model_selector.connect('model-selected', self._on_model_selected)

    def _on_model_selected(self, selector, model_id):
        self.config_data['model'] = model_id
        # Scroll to next page automatically?
        # self.carousel.scroll_to(self.carousel.get_nth_page(2), True)

    def _on_window_show(self, window):
        if not hasattr(self, '_resources_configured'):
            try:
                style_manager.load_styles()
                resource_manager.setup_icon_theme()
                self._resources_configured = True
            except Exception as e:
                debug_print(f"Welcome: Error configuring resources: {e}")

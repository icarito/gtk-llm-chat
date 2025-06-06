import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import time
from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import os
import threading
from .debug_utils import debug_print
from .resource_manager import resource_manager
from .style_manager import style_manager
from .chat_application import _


class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, app, on_welcome_finished=None):
        super().__init__(application=app)
        self._on_welcome_finished = on_welcome_finished
        self.set_default_size(900, 700)
        self.set_size_request(700, 500)  # Tamaño mínimo razonable para evitar colapsos
        self.panel_titles = ["", _("Tray applet"), _("Default Model"), ""]
        self.config_data = {}
        self._finish_clicked = False # Bandera para controlar el flujo de cierre

        # Cargar estilos globales y aplicar clase principal
        style_manager.load_styles()
        style_manager.apply_to_widget(self, "main-container")

        # Configurar recursos (solo iconos, sin estilos CSS personalizados)
        resource_manager.setup_icon_theme()

        import sys
        self.header_bar = Adw.HeaderBar()
        self.header_bar.set_show_end_title_buttons(True)
        if sys.platform == 'darwin':
            def _apply_native_controls():
                style_manager.apply_macos_native_window_controls(self.header_bar)
                return False  # Ejecutar solo una vez
            GLib.idle_add(_apply_native_controls)

        # Conectar la señal realize para iniciar la carga de modelos automáticamente
        self.connect('realize', self._on_realize)
        
        root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root_vbox.set_hexpand(True)
        root_vbox.set_vexpand(True)
        root_vbox.set_size_request(700, 500)
        self.prev_button = Gtk.Button()
        self.prev_button.set_icon_name("go-previous-symbolic")
        self.prev_button.add_css_class("flat")
        self.prev_button.set_size_request(100, 40)
        self.prev_button.connect('clicked', self.on_prev_clicked)
        self.header_bar.pack_start(self.prev_button)

        self.next_button = Gtk.Button(label=_("Next"))
        self.next_button.add_css_class("suggested-action")
        self.next_button.set_size_request(100, 40)
        self.next_button.connect('clicked', self.on_next_clicked)
        self.header_bar.pack_end(self.next_button)

        self.start_chatting_button = Gtk.Button(label=_("New Conversation"))
        self.start_chatting_button.add_css_class("suggested-action")
        self.start_chatting_button.set_halign(Gtk.Align.CENTER)
        self.start_chatting_button.set_size_request(160, 40)
        self.start_chatting_button.connect('clicked', self.on_finish_clicked)

        self.api_key_button = Gtk.Button()
        self.api_key_button.set_size_request(120, 40)  # Tamaño mínimo fijo
        self.api_key_button.connect('clicked', self._on_api_key_button_clicked)
        self.api_key_button_packed = False

        self.loading_spinner = Adw.Spinner()
        self.loading_spinner.set_size_request(32, 32)  # Spinner más grande para visibilidad
        self.loading_spinner_packed = False

        root_vbox.append(self.header_bar)
        self.set_content(root_vbox)

        self.carousel = Adw.Carousel()
        self.carousel.set_vexpand(True)
        self.carousel.set_hexpand(True)
        self.carousel.set_halign(Gtk.Align.FILL)
        self.carousel.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.carousel.set_interactive(False)
        self.carousel.set_size_request(700, 450)

        def make_clamped(child, fill_vertical=False, halign=Gtk.Align.CENTER):
            clamp = Adw.Clamp()
            clamp.set_maximum_size(800)
            clamp.set_tightening_threshold(400)
            clamp.set_hexpand(True)
            clamp.set_halign(halign)
            clamp.set_vexpand(True)
            clamp.set_valign(Gtk.Align.FILL if fill_vertical else Gtk.Align.CENTER)
            clamp.set_child(child)
            return clamp

        # Panel 1: Bienvenida
        page1 = Adw.StatusPage()
        page1.set_hexpand(True)
        page1.set_halign(Gtk.Align.FILL)
        page1.set_size_request(700, 450)
        
        # Usar resource_manager para cargar la imagen
        vbox1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        vbox1.set_valign(Gtk.Align.CENTER)
        vbox1.set_halign(Gtk.Align.CENTER)
        vbox1.set_hexpand(False)
        vbox1.set_vexpand(False)
        # No forzar size_request aquí, dejar que el clamp lo limite
        
        # Usar resource_manager para cargar el icono de la aplicación con tamaño grande
        app_image = resource_manager.create_icon_widget("org.fuentelibre.gtk_llm_Chat", 256)
        app_image.set_valign(Gtk.Align.CENTER)
        app_image.set_halign(Gtk.Align.CENTER)
        app_image.set_size_request(256, 256)
        vbox1.append(app_image)
        
        page1.set_title(_("Own the conversation."))
        page1.set_description(_("Use any model you want. Your conversations are stored locally."))
        panel1_desc_label2 = Gtk.Label(label=_("This wizard will guide you through the initial setup"))
        panel1_desc_label2.set_wrap(True)
        panel1_desc_label2.set_justify(Gtk.Justification.CENTER)
        panel1_desc_label2.set_halign(Gtk.Align.CENTER)
        panel1_desc_label2.set_max_width_chars(50)
        vbox1.append(panel1_desc_label2)
        self.start_button = Gtk.Button(label=_("Start"))
        self.start_button.add_css_class("suggested-action")
        self.start_button.set_halign(Gtk.Align.CENTER)
        self.start_button.set_valign(Gtk.Align.CENTER)
        self.start_button.set_hexpand(True)
        self.start_button.connect('clicked', self.on_start_clicked)
        vbox1.append(self.start_button)
        # Usar un Gtk.Box vertical expandible para centrar vbox1 verticalmente
        centering_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        centering_box.set_hexpand(True)
        centering_box.set_vexpand(True)
        centering_box.append(Gtk.Box(vexpand=True))  # Espaciador arriba
        centering_box.append(vbox1)
        centering_box.append(Gtk.Box(vexpand=True))  # Espaciador abajo
        page1.set_child(make_clamped(centering_box))

        # Panel 2: Applet de bandeja
        page2_vbox_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page2_vbox_content.set_valign(Gtk.Align.CENTER)
        page2_vbox_content.set_halign(Gtk.Align.CENTER)
        page2_vbox_content.set_hexpand(False)
        page2_vbox_content.set_vexpand(False)
        # No forzar size_request aquí, dejar que el clamp lo limite
        
        self.panel2_app_icon_target_size = 64
        # Usar resource_manager para crear el icono
        self.panel2_app_icon = resource_manager.create_icon_widget("org.fuentelibre.gtk_llm_Chat-symbolic", 1)
        self.panel2_app_icon.set_opacity(0.0)
        self.panel2_app_icon.set_size_request(1, 1)
        self.panel2_app_icon.set_halign(Gtk.Align.CENTER)
        self.panel2_app_icon.set_margin_bottom(12)
        page2_vbox_content.append(self.panel2_app_icon)
        panel2_desc_label = Gtk.Label(label=_("Access conversations from the convenience of your system tray"))
        panel2_desc_label.set_wrap(True)
        panel2_desc_label.set_justify(Gtk.Justification.CENTER)
        panel2_desc_label.set_halign(Gtk.Align.CENTER)
        panel2_desc_label.set_max_width_chars(50)
        page2_vbox_content.append(panel2_desc_label)
        panel2_desc_label2 = Gtk.Label(label=_("Would you like to start the applet with your session?"))
        panel2_desc_label2.set_wrap(True)
        panel2_desc_label2.set_justify(Gtk.Justification.CENTER)
        panel2_desc_label2.set_halign(Gtk.Align.CENTER)
        panel2_desc_label2.set_max_width_chars(50)
        page2_vbox_content.append(panel2_desc_label2)
        self.tray_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.tray_group.set_hexpand(True)
        self.tray_group.set_halign(Gtk.Align.CENTER)
        self.tray_group.set_margin_top(12)
        self.tray_radio1 = Gtk.CheckButton(label=_("Yes, with my session"))
        self.tray_radio2 = Gtk.CheckButton(label=_("No, only when I start the app"))
        self.tray_radio1.set_group(self.tray_radio2)
        self._initialize_tray_options()
        self.tray_radio1.connect('toggled', self._on_tray_option_changed)
        self.tray_radio2.connect('toggled', self._on_tray_option_changed)
        self.tray_group.append(self.tray_radio1)
        self.tray_group.append(self.tray_radio2)
        page2_vbox_content.append(self.tray_group)
        panel2_app_animation_target = Adw.CallbackAnimationTarget.new(self._animate_panel2_app_icon_callback)
        self.panel2_app_animation = Adw.TimedAnimation.new(self.panel2_app_icon, 0.0, 1.0, 700, panel2_app_animation_target)
        self.panel2_app_animation.set_easing(Adw.Easing.EASE_OUT_EXPO)
        self.panel2_app_animation_played = False

        # Panel 3: Selección de modelo y API key
        page3_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page3_container.set_hexpand(True)
        page3_container.set_halign(Gtk.Align.FILL)
        page3_container.set_vexpand(True)
        page3_container.set_valign(Gtk.Align.FILL)
        page3_container.set_size_request(700, 450)
        panel3_inner_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel3_inner_vbox.set_valign(Gtk.Align.FILL)
        panel3_inner_vbox.set_halign(Gtk.Align.FILL)
        panel3_inner_vbox.set_hexpand(True)
        panel3_inner_vbox.set_vexpand(True)
        self.model_manager = None
        self.model_selector = None
        self._models_loaded = False
        self._model_selector_created = False
        self.app = app
        self.panel3_placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.panel3_placeholder.set_vexpand(True)
        self.panel3_placeholder.set_hexpand(True)
        self.panel3_placeholder.set_valign(Gtk.Align.CENTER)
        self.panel3_placeholder.set_halign(Gtk.Align.CENTER)
        placeholder_label = Gtk.Label(label=_("Loading model selection..."))
        placeholder_label.add_css_class("dim-label")
        self.panel3_placeholder.append(placeholder_label)
        panel3_inner_vbox.append(self.panel3_placeholder)
        page3_container.append(make_clamped(panel3_inner_vbox, fill_vertical=True, halign=Gtk.Align.FILL))

        # Panel 4: Listo para comenzar
        page4 = Adw.StatusPage()
        page4.set_hexpand(True)
        page4.set_halign(Gtk.Align.FILL)
        page4.set_title(_("Ready to start!"))
        page4.set_size_request(700, 450)
        page4_vbox_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page4_vbox_content.set_valign(Gtk.Align.CENTER)
        page4_vbox_content.set_halign(Gtk.Align.CENTER)
        page4_vbox_content.set_hexpand(True)
        checkmark_icon = Gtk.Image.new_from_icon_name("checkmark-symbolic")
        checkmark_icon.set_pixel_size(128)
        checkmark_icon.set_halign(Gtk.Align.CENTER)
        checkmark_icon.set_margin_bottom(24)
        checkmark_icon.add_css_class("success")
        page4_vbox_content.append(checkmark_icon)
        page4.set_child(make_clamped(page4_vbox_content))

        # Centrado vertical para el panel 2
        centering_box2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        centering_box2.set_hexpand(True)
        centering_box2.set_vexpand(True)
        centering_box2.append(Gtk.Box(vexpand=True))  # Espaciador arriba
        centering_box2.append(page2_vbox_content)
        centering_box2.append(Gtk.Box(vexpand=True))  # Espaciador abajo

        self.carousel.append(page1)
        self.carousel.append(make_clamped(centering_box2, fill_vertical=False))
        self.carousel.append(make_clamped(page3_container, fill_vertical=True))
        self.carousel.append(page4)
        self.indicator_dots = Adw.CarouselIndicatorDots(carousel=self.carousel)
        self.indicator_dots.set_halign(Gtk.Align.CENTER)
        self.indicator_dots.set_valign(Gtk.Align.END)
        self.indicator_dots.set_margin_top(6)
        self.indicator_dots.set_margin_bottom(18)
        self.carousel.set_hexpand(True)
        self.carousel.set_halign(Gtk.Align.FILL)
        root_vbox.append(self.carousel)
        root_vbox.append(self.indicator_dots)
        self.carousel.connect("page-changed", self.on_page_changed)
        self.update_navigation_buttons()
        self.on_page_changed(self.carousel, self.carousel.get_position())
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)
        
        # Conectar señal de cierre de ventana para terminar la aplicación si se cierra sin completar
        self.connect('close-request', self._on_window_close_request)

    def on_start_clicked(self, button):
        page_to_scroll_to = self.carousel.get_nth_page(1)
        if page_to_scroll_to:
            self.carousel.scroll_to(page_to_scroll_to, True)

    def on_prev_clicked(self, button):
        current_page_idx = int(round(self.carousel.get_position()))
        if current_page_idx > 0:
            prev_page_widget = self.carousel.get_nth_page(current_page_idx - 1)
            if prev_page_widget:
                self.carousel.scroll_to(prev_page_widget, True)

    def on_next_clicked(self, button):
        current_page_idx = int(round(self.carousel.get_position()))
        n_pages = self.carousel.get_n_pages()
        if current_page_idx == 2:
            if self.model_selector:
                status = self.model_selector.get_current_model_selection_status()
                if not status["is_valid_for_next_step"]:
                    debug_print("DEBUG: Cannot proceed, model/API key selection is not valid.")
                    return
            else:
                debug_print("DEBUG: Model selector not ready yet.")
                return
        if current_page_idx < n_pages - 1:
            next_page_widget = self.carousel.get_nth_page(current_page_idx + 1)
            if next_page_widget:
                self.carousel.scroll_to(next_page_widget, True)

    def on_page_changed(self, carousel, page_index):
        self.update_navigation_buttons()
        current_page_as_int = int(round(page_index))
        if 0 <= current_page_as_int < len(self.panel_titles):
            self.set_title(self.panel_titles[current_page_as_int])
        else:
            self.set_title("")
        if current_page_as_int == 1 and not self.panel2_app_animation_played:
            if hasattr(self, 'panel2_app_animation'):
                self.panel2_app_animation.play()
                self.panel2_app_animation_played = True
        if current_page_as_int == 2:
            self.prev_button.set_can_focus(False)
            if self.model_selector and hasattr(self.model_selector, 'provider_sidebar') and self.model_selector.provider_sidebar:
                def attempt_focus_and_reenable_prev_button():
                    if int(round(self.carousel.get_position())) == 2:
                        if self.model_selector.provider_sidebar.get_realized() and self.model_selector.provider_sidebar.get_mapped():
                            self.model_selector.provider_sidebar.grab_focus()
                    if self.prev_button.is_sensitive():
                        self.prev_button.set_can_focus(True)
                    return GLib.SOURCE_REMOVE
                GLib.timeout_add(100, attempt_focus_and_reenable_prev_button)
        else:
            if self.prev_button.is_sensitive():
                self.prev_button.set_can_focus(True)
            else:
                self.prev_button.set_can_focus(False)


    def on_key_pressed(self, controller, keyval, keycode, state):
        if not (keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter):
            return False
        current_page_idx = int(round(self.carousel.get_position()))
        n_pages = self.carousel.get_n_pages()
        if current_page_idx == 0:
            self.on_start_clicked(None)
            return True
        elif current_page_idx == n_pages - 1:
            self.on_finish_clicked(None)
            return True
        else:
            self.on_next_clicked(None)
            return True

    def update_navigation_buttons(self):
        idx = self.carousel.get_position()
        current_page_idx = int(round(idx))
        n = self.carousel.get_n_pages()
        self.prev_button.set_sensitive(current_page_idx > 0)

        # Página 0: Bienvenida
        if current_page_idx == 0:
            self.prev_button.set_visible(False)
            self.next_button.set_visible(False)
            self._ensure_api_key_button_removed()
            return

        # Última página: Listo para comenzar
        if current_page_idx == n - 1:
            self.prev_button.set_visible(True)
            self.next_button.set_visible(False)
            if self.start_chatting_button.get_parent() != self.header_bar:
                self.header_bar.pack_end(self.start_chatting_button)
            self.start_chatting_button.set_visible(True)
            self._ensure_api_key_button_removed()
            return

        # Otras páginas
        self.prev_button.set_visible(True)
        self.next_button.set_visible(True)
        self.start_chatting_button.set_visible(False)

        # Página de selección de modelo
        if current_page_idx == 2:
            if not self._models_loaded or not self._model_selector_created:
                if not self.loading_spinner_packed:
                    self.header_bar.pack_start(self.loading_spinner)
                    self.loading_spinner_packed = True
                self.loading_spinner.set_visible(True)
                self.next_button.set_sensitive(False)
                self._ensure_api_key_button_removed()
                return
            else:
                self._ensure_loading_spinner_removed()

            # Si hay selector de modelo, usar su status
            if self.model_selector:
                status = self.model_selector.get_current_model_selection_status()
                current_provider = self.model_selector.get_current_provider_key()
                debug_print(f"Debug update_navigation_buttons: current_provider={current_provider}")

                # Mostrar u ocultar botón de API key según status
                self._update_api_key_button(current_provider)
                # El botón Next se habilita si hay un modelo seleccionado válido
                self.next_button.set_sensitive(status["is_valid_for_next_step"])
            else:
                self.next_button.set_sensitive(False)
                self._ensure_api_key_button_removed()
        else:
            self.next_button.set_sensitive(True)
            self._ensure_api_key_button_removed()
            self._ensure_loading_spinner_removed()

    def _update_api_key_button(self, current_provider):
        """Muestra u oculta el botón de API key según el estado del proveedor actual."""
        provider_needs_key = False
        provider_has_key = False
        models_count = 0
        if current_provider and current_provider != "no_selection" and hasattr(self.model_manager, 'check_api_key_status'):
            key_status = self.model_manager.check_api_key_status(current_provider)
            provider_needs_key = key_status.get('needs_key', False)
            provider_has_key = key_status.get('has_key', False)
            if hasattr(self.model_manager, 'models_by_provider') and current_provider in self.model_manager.models_by_provider:
                models_count = len(self.model_manager.models_by_provider[current_provider])
            # Heurística extra: si está en el mapeo de needs_key pero no lo reporta, forzar needs_key
            if not provider_needs_key and hasattr(self.model_manager, '_provider_to_needs_key'):
                if current_provider in self.model_manager._provider_to_needs_key:
                    needs_key_name = self.model_manager._provider_to_needs_key[current_provider]
                    if needs_key_name and needs_key_name != "":
                        provider_needs_key = True
                        try:
                            import llm
                            key_value = llm.get_key(needs_key_name)
                            key_exists = key_value is not None and key_value.strip() != ""
                            provider_has_key = key_exists and models_count > 0
                        except Exception:
                            provider_has_key = False
        if provider_needs_key:
            debug_print(f"Debug: Mostrando botón API key para {current_provider}")
            if not self.api_key_button_packed:
                if self.api_key_button.get_parent() is not None:
                    self.api_key_button.get_parent().remove(self.api_key_button)
                self.api_key_button.set_visible(False)
                self.header_bar.pack_start(self.api_key_button)
                self.api_key_button_packed = True
            button_text = _("Set API Key") if not provider_has_key else _("Change API Key")
            self.api_key_button.set_label(button_text)
            self.api_key_button.get_style_context().remove_class("suggested-action")
            self.api_key_button.get_style_context().remove_class("destructive-action")
            if not provider_has_key:
                self.api_key_button.get_style_context().add_class("suggested-action")
            else:
                self.api_key_button.get_style_context().add_class("destructive-action")
            self.api_key_button.set_visible(True)
        else:
            debug_print(f"Debug: Ocultando botón API key para {current_provider}")
            self._ensure_api_key_button_removed()

    def _ensure_api_key_button_removed(self):
        if self.api_key_button_packed:
            try:
                if self.api_key_button.get_parent() == self.header_bar:
                    self.header_bar.remove(self.api_key_button)
                self.api_key_button_packed = False
            except Exception as e:
                debug_print(f"Error removiendo botón API key: {e}")
                self.api_key_button_packed = False
        self.api_key_button.set_visible(False)

    def _ensure_loading_spinner_removed(self):
        if self.loading_spinner_packed:
            try:
                if self.loading_spinner.get_parent() == self.header_bar:
                    self.header_bar.remove(self.loading_spinner)
                self.loading_spinner_packed = False
            except Exception as e:
                debug_print(f"Error removiendo spinner: {e}")
                self.loading_spinner_packed = False
        self.loading_spinner.set_visible(False)

    def on_finish_clicked(self, button):
        self._finish_clicked = True # Marcar que el flujo se completó
        self.close()
        if self._on_welcome_finished:
            self._on_welcome_finished(self.get_configuration())

    def _on_window_close_request(self, window):
        """Maneja el cierre de la ventana de bienvenida."""
        if not self._finish_clicked:
            debug_print("Ventana de bienvenida cerrada ANTES de completar el asistente, terminando aplicación")
            self.app.quit() # Terminar la aplicación si el flujo no se completó
        else:
            debug_print("Ventana de bienvenida cerrada DESPUÉS de completar el asistente (por self.close()). La app continúa.")
        return False # Permitir que la ventana se cierre en cualquier caso


    def _on_model_selected(self, selector, model_id):
        self.config_data['model'] = model_id
        provider_key = None
        # Intentar obtener el provider_key usando llm_client si está disponible
        llm_client = getattr(self.app, 'llm_client', None)
        if llm_client and hasattr(llm_client, 'get_provider_for_model'):
            provider_key = llm_client.get_provider_for_model(model_id)
        else:
            # Fallback: buscar en los modelos cargados
            try:
                import llm
                all_models = llm.get_models()
                for m in all_models:
                    if getattr(m, 'model_id', None) == model_id:
                        provider_key = getattr(m, 'needs_key', None)
                        break
            except Exception:
                provider_key = None
        # Consultar el estado de la API key
        needs_key = False
        has_key = False
        if provider_key is not None and self.model_manager and hasattr(self.model_manager, 'check_api_key_status'):
            key_status = self.model_manager.check_api_key_status(provider_key)
            needs_key = key_status.get('needs_key', False)
            has_key = key_status.get('has_key', False)
        # Solo setear modelo por defecto si no requiere clave o si la clave está presente
        if not needs_key or has_key:
            try:
                import llm
                llm.set_default_model(model_id)

                # Forzar la creación de logs.db para evitar ejecuciones repetidas del asistente
                try:
                    # Usamos la lógica ya implementada en ChatHistory
                    from .db_operations import ChatHistory
                    
                    # Solo necesitamos inicializar ChatHistory y llamar a _ensure_db_exists()
                    temp_history = ChatHistory()
                    temp_history._ensure_db_exists()  # Esto aplica las migraciones si el archivo no existe
                    self.app._needs_initial_setup = False
                    debug_print("Base de datos logs.db creada correctamente")
                except Exception as db_err:
                    debug_print(f"Error forzando creación de BD: {db_err}")
                
                debug_print(f"Modelo por defecto configurado: {model_id}")
            except Exception as e:
                debug_print(f"Error configurando modelo por defecto: {e}")
            
            from .platform_utils import spawn_tray_applet
            spawn_tray_applet({})
        self.update_navigation_buttons()

    def save_configuration(self):
        if self.tray_radio1.get_active():
            self.config_data['tray_startup'] = 'session'
        elif self.tray_radio2.get_active():
            self.config_data['tray_startup'] = 'application'
        else:
            self.config_data['tray_startup'] = 'never'
        debug_print(f"Configuration saved: {self.config_data}")

    def get_configuration(self):
        return self.config_data.copy()

    def _on_api_key_button_clicked(self, button):
        if self.model_selector:
            self.model_selector.trigger_api_key_dialog_for_current_provider()

    def _on_api_key_status_changed(self, selector, provider_key, needs_key, has_key):
        debug_print(f"Debug: API key status changed - provider: {provider_key}, needs: {needs_key}, has: {has_key}")

        # Si se configuró una API key (needs_key=True y has_key=True), recargar solo los modelos dinámicos
        # sin cambiar el stack para evitar bucles infinitos
        if needs_key and has_key and self.model_selector:
            debug_print(f"Debug: API key configurada para {provider_key}, recargando solo modelos dinámicos...")
            try:
                # Recargar modelos dinámicos directamente sin tocar la UI del stack
                self.model_selector.manager.reload_dynamic_models_only()
                
                # Actualizar solo la página del proveedor que cambió
                if provider_key in self.model_selector._provider_pages_cache:
                    page_ui = self.model_selector._provider_pages_cache[provider_key]
                    self.model_selector._populate_model_list_for_page(provider_key, page_ui)
                    debug_print(f"Debug: Lista de modelos actualizada para proveedor {provider_key}")
                
            except Exception as e:
                debug_print(f"Error recargando modelos dinámicos: {e}")

        # Actualizar botones en cualquier caso
        if int(round(self.carousel.get_position())) == 2:
            self.update_navigation_buttons()

    def _animate_panel2_app_icon_callback(self, value):
        self.panel2_app_icon.set_opacity(value)
        end_size = self.panel2_app_icon_target_size
        current_size = int(end_size * value)
        self.panel2_app_icon.set_size_request(current_size, current_size)
        self.panel2_app_icon.set_pixel_size(current_size)

    def start_lazy_loading(self):
        if not self._models_loaded:
            if int(round(self.carousel.get_position())) == 2:
                if not self.loading_spinner_packed:
                    self.header_bar.pack_start(self.loading_spinner)
                    self.loading_spinner_packed = True
                self.loading_spinner.set_visible(True)
            GLib.timeout_add(200, self._start_background_loading)

    def _start_background_loading(self):
        threading.Thread(
            target=self._load_models_in_thread,
            daemon=True,
            name="ModelLoader"
        ).start()
        return False

    def _load_models_in_thread(self):
        try:
            from .wide_model_selector import WideModelSelector, NO_SELECTION_KEY
            from .model_selection import ModelSelectionManager
            GLib.idle_add(self._create_model_selector_and_replace_placeholder, WideModelSelector, ModelSelectionManager)
        except Exception as e:
            debug_print(f"Error importing/creating model selector in background: {e}")
            GLib.idle_add(self._on_models_loaded_error, str(e))

    def _create_model_selector_and_replace_placeholder(self, WideModelSelector, ModelSelectionManager):
        try:
            self._create_model_selector_if_needed(WideModelSelector, ModelSelectionManager)
            panel3_inner_vbox = self.panel3_placeholder.get_parent()
            if panel3_inner_vbox:
                panel3_inner_vbox.remove(self.panel3_placeholder)
                panel3_inner_vbox.append(self.model_selector)
            threading.Thread(
                target=self._load_models_data_in_thread,
                daemon=True,
                name="ModelDataLoader"
            ).start()
        except Exception as e:
            debug_print(f"Error creating model selector: {e}")
            GLib.idle_add(self._on_models_loaded_error, str(e))
        return False

    def _load_models_data_in_thread(self):
        try:
            # Cargar proveedores y modelos usando el manager del selector
            self.model_selector.load_providers_and_models()
            
            # Obtener el modelo por defecto
            try:
                import llm
                modelid = llm.get_default_model()
                debug_print(f"Debug: Modelo por defecto obtenido: {modelid}")
            except Exception as e:
                debug_print(f"Error obteniendo modelo por defecto: {e}")
                modelid = None
            
            GLib.idle_add(self._on_models_loaded_completed, modelid)
        except Exception as e:
            debug_print(f"Error loading model data in background: {e}")
            import traceback
            debug_print(traceback.format_exc())
            GLib.idle_add(self._on_models_loaded_error, str(e))

    def _on_models_loaded_completed(self, modelid=None):
        self._models_loaded = True
        self._ensure_loading_spinner_removed()
        if int(round(self.carousel.get_position())) == 2:
            self.update_navigation_buttons()
        
        if self.model_selector and modelid:
            debug_print(f"Debug: Intentando seleccionar modelo por defecto: {modelid}")
            # Verificar si el modelo requiere API key y si está configurada
            provider_key = None
            
            # Obtener el provider_key del modelo usando el manager
            if hasattr(self.model_selector, 'manager') and self.model_selector.manager:
                manager = self.model_selector.manager
                # Buscar el modelo en todos los proveedores
                for prov_key, models in manager.models_by_provider.items():
                    for model in models:
                        if getattr(model, 'model_id', None) == modelid:
                            provider_key = manager._provider_to_needs_key.get(prov_key)
                            debug_print(f"Debug: Encontrado modelo {modelid} en proveedor {prov_key}, needs_key: {provider_key}")
                            break
                    if provider_key is not None:
                        break
            
            # Si no se encontró, intentar obtener directamente del modelo
            if provider_key is None:
                try:
                    import llm
                    all_models = llm.get_models()
                    for m in all_models:
                        if getattr(m, 'model_id', None) == modelid:
                            provider_key = getattr(m, 'needs_key', None)
                            debug_print(f"Debug: Encontrado modelo {modelid} directamente, needs_key: {provider_key}")
                            break
                except Exception as e:
                    debug_print(f"Error buscando modelo en llm.get_models(): {e}")
                    provider_key = None
            
            # Consultar el estado de la API key si es necesario
            should_select = True
            if provider_key is not None and hasattr(self.model_manager, 'check_api_key_status'):
                key_status = self.model_manager.check_api_key_status(provider_key)
                needs_key = key_status.get('needs_key', False)
                has_key = key_status.get('has_key', False)
                debug_print(f"Debug: Estado de API key para {provider_key}: needs_key={needs_key}, has_key={has_key}")
                
                if needs_key and not has_key:
                    should_select = False
                    debug_print(f"Debug: No seleccionando modelo {modelid} porque falta API key para {provider_key}")
            
            # Seleccionar el modelo si es apropiado
            if should_select:
                debug_print(f"Debug: Seleccionando modelo por defecto: {modelid}")
                self.model_selector.pick_model(modelid)
        else:
            debug_print("Debug: No hay modelo por defecto para seleccionar")
            # Intentar seleccionar un modelo disponible
        
        return False

    def _on_models_loaded_error(self, error_message):
        debug_print(f"Background model loading failed: {error_message}")
        return False

    def _create_model_selector_if_needed(self, WideModelSelector, ModelSelectionManager):
        if not self._model_selector_created:
            self._model_selector_created = True
            self.model_manager = ModelSelectionManager(self.config_data, self.app.llm_client if hasattr(self.app, 'llm_client') else None)
            self.model_selector = WideModelSelector(manager=self.model_manager)
            self.model_selector.set_vexpand(True)
            self.model_selector.set_hexpand(True)
            self.model_selector.set_valign(Gtk.Align.FILL)
            self.model_selector.set_halign(Gtk.Align.FILL)
            self.model_selector.connect('model-selected', self._on_model_selected)
            self.model_selector.connect('api-key-status-changed', self._on_api_key_status_changed)
            # También conectar al stack interno para detectar cambios de proveedor
            if hasattr(self.model_selector, 'content_stack'):
                self.model_selector.content_stack.connect('notify::visible-child-name', self._on_provider_changed)

    def _on_tray_option_changed(self, checkbutton):
        if not checkbutton.get_active():
            return
        try:
            from .platform_utils import ensure_load_on_session_startup
            if self.tray_radio1.get_active():
                success = ensure_load_on_session_startup(True)
                if success:
                    debug_print("Autostart habilitado para inicio de sesión")
                    self.config_data['tray_startup'] = 'session'
                else:
                    debug_print("Error habilitando autostart")
            else:
                success = ensure_load_on_session_startup(False)
                if success:
                    debug_print("Autostart deshabilitado")
                    self.config_data['tray_startup'] = 'application'
                else:
                    debug_print("Error deshabilitando autostart")
        except Exception as e:
            debug_print(f"Error configurando autostart: {e}")

    def _initialize_tray_options(self):
        try:
            from .platform_utils import is_loading_on_session_startup
            autostart_enabled = is_loading_on_session_startup()
            if autostart_enabled:
                self.tray_radio1.set_active(True)
                self.config_data['tray_startup'] = 'session'
                debug_print("Autostart detectado como habilitado")
            else:
                self.tray_radio2.set_active(True)
                self.config_data['tray_startup'] = 'application'
                debug_print("Autostart detectado como deshabilitado")
        except Exception as e:
            debug_print(f"Error verificando estado de autostart: {e}")
            self.tray_radio2.set_active(True)
            self.config_data['tray_startup'] = 'application'

    def _on_provider_changed(self, stack, pspec):
        """Actualiza los botones cuando se cambia de proveedor."""
        current_provider = stack.get_visible_child_name()
        debug_print(f"Debug: Proveedor cambiado a: {current_provider}")
        if int(round(self.carousel.get_position())) == 2:
            # Usar un timeout pequeño para que el cambio se complete
            GLib.timeout_add(50, self.update_navigation_buttons)

    def _on_realize(self, widget):
        """Callback cuando la ventana se realiza - inicia la carga de modelos."""
        self.start_lazy_loading()

if __name__ == "__main__":
    import sys
    import signal
    app = Adw.Application(application_id="org.fuentelibre.GtkLLMChatWelcome", flags=Gio.ApplicationFlags.FLAGS_NONE)
    icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    project_root = os.path.dirname(os.path.abspath(__file__))
    icon_theme.add_search_path(project_root)
    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property("gtk-icon-theme-name", "Adwaita")
    def on_activate(app):
        def welcome_finished_callback(config):
            debug_print("Welcome flow finished. Config:", config)
            app.quit()
        win = WelcomeWindow(app, on_welcome_finished=welcome_finished_callback)
        win.present()
        signal.signal(signal.SIGINT, lambda s, f: app.quit())
    app.connect('activate', on_activate)
    app.run(sys.argv)
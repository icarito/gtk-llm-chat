import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib
import os

# from gtk_llm_chat.model_selector import ModelSelectorWidget # Ya no se usa
from gtk_llm_chat.wide_model_selector import CompactModelSelector, NO_SELECTION_KEY # Importar el nuevo widget
from gtk_llm_chat.model_selection import ModelSelectionManager

class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, app, on_start_callback=None):
        super().__init__(application=app)
        self.set_default_size(800, 600)
        # self.set_title("")  # El título se manejará dinámicamente

        # Títulos para cada panel
        self.panel_titles = [
            "",
            "Tray applet",  # Panel 2 - Título original
            "Default Model", # Panel 3
            "" # Panel 4
        ]

        self.on_start_callback = on_start_callback
        self.config_data = {}  # Para almacenar la configuración

        # --- Contenedor Principal ---
        root_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # HeaderBar con botones de navegación
        self.header_bar = Adw.HeaderBar()
        self.header_bar.set_show_end_title_buttons(True)
        
        # Botón Anterior en el lado izquierdo
        self.prev_button = Gtk.Button()
        self.prev_button.set_icon_name("go-previous-symbolic")
        self.prev_button.add_css_class("flat")
        self.prev_button.connect('clicked', self.on_prev_clicked)
        self.header_bar.pack_start(self.prev_button)
        
        # Botón Siguiente en el lado derecho (textual)
        self.next_button = Gtk.Button(label="Next")
        self.next_button.add_css_class("suggested-action")
        self.next_button.connect('clicked', self.on_next_clicked)
        self.header_bar.pack_end(self.next_button)

        # Botón Start Chatting (solo visible en el último panel)
        self.start_chatting_button = Gtk.Button(label="Ready")
        self.start_chatting_button.add_css_class("suggested-action")
        self.start_chatting_button.set_halign(Gtk.Align.CENTER) # Centrar el botón
        self.start_chatting_button.connect('clicked', self.on_finish_clicked)

        # Botón para configurar API Key (solo visible en panel de modelo)
        self.api_key_button = Gtk.Button() # Label se setea dinámicamente
        self.api_key_button.connect('clicked', self._on_api_key_button_clicked)
        # Se añadirá/quitará del header_bar dinámicamente
        self.api_key_button_packed = False
        
        root_vbox.append(self.header_bar)
        self.set_content(root_vbox)

        # --- Carrusel ---
        self.carousel = Adw.Carousel()
        self.carousel.set_vexpand(True)
        self.carousel.set_hexpand(True)
        self.carousel.set_halign(Gtk.Align.FILL)
        self.carousel.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.carousel.set_interactive(False)

        # Clamp para centrar contenido horizontalmente y opcionalmente llenar verticalmente
        def make_clamped(child, fill_vertical=False, halign=Gtk.Align.CENTER):
            clamp = Adw.Clamp()
            clamp.set_maximum_size(800)  # Increased from 600 to 800
            clamp.set_tightening_threshold(400)
            clamp.set_hexpand(True)
            clamp.set_halign(halign)

            clamp.set_vexpand(True) # Clamp itself should take available vertical space
            if fill_vertical:
                clamp.set_valign(Gtk.Align.FILL) # Clamp fills vertically, allowing child to fill
            else:
                clamp.set_valign(Gtk.Align.CENTER) # Clamp centers its child vertically
            
            clamp.set_child(child)
            return clamp

        # Panel 1: Own the conversation
        page1 = Adw.StatusPage()
        page1.set_hexpand(True)
        page1.set_halign(Gtk.Align.FILL)
        # Icono centrado - usar imagen de windows/
        img_path = os.path.join(os.path.dirname(__file__), "windows/org.fuentelibre.gtk_llm_Chat.png")
        vbox1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        vbox1.set_valign(Gtk.Align.CENTER)
        vbox1.set_halign(Gtk.Align.CENTER)
        vbox1.set_hexpand(True)
        if os.path.exists(img_path):
            image = Gtk.Picture.new_for_filename(img_path)
            image.set_valign(Gtk.Align.CENTER)
            image.set_halign(Gtk.Align.CENTER)
            image.set_content_fit(Gtk.ContentFit.CONTAIN)
            image.set_size_request(128, 128)
            image.set_hexpand(True)
            vbox1.append(image)
        page1.set_title("Own the conversation")
        page1.set_description("Your private, native AI assistant. Chat with advanced models while staying in full control of your data.")
        # Botón Start centrado
        self.start_button = Gtk.Button(label="Start")
        self.start_button.add_css_class("suggested-action")
        self.start_button.set_halign(Gtk.Align.CENTER)
        self.start_button.set_valign(Gtk.Align.CENTER)
        self.start_button.set_hexpand(True)
        self.start_button.connect('clicked', self.on_start_clicked)
        vbox1.append(self.start_button)
        page1.set_child(make_clamped(vbox1))

        # Panel 2: Applet de bandeja con icono animado
        page2_vbox_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page2_vbox_content.set_valign(Gtk.Align.CENTER) # Centrar todo el contenido verticalmente
        page2_vbox_content.set_halign(Gtk.Align.CENTER)
        page2_vbox_content.set_hexpand(True)

        self.panel2_app_icon_target_size = 64 # Tamaño final del icono de la aplicación
        # Usar el nombre del icono para que respete el color simbólico del tema
        self.panel2_app_icon = Gtk.Image.new_from_icon_name("org.fuentelibre.gtk_llm_Chat")
        self.panel2_app_icon.set_opacity(0.0) # Empezar invisible
        self.panel2_app_icon.add_css_class("icon-dropshadow")
        self.panel2_app_icon.set_size_request(1, 1) # Empezar muy pequeño para la animación
        self.panel2_app_icon.set_pixel_size(1) # Tamaño inicial
        self.panel2_app_icon.set_halign(Gtk.Align.CENTER)
        self.panel2_app_icon.set_margin_bottom(12) # Espacio entre icono y título
        page2_vbox_content.append(self.panel2_app_icon)

        # Título del panel 2
        # Descripción del panel 2
        panel2_desc_label = Gtk.Label(label="Access conversations from the convenience of your system tray")
        panel2_desc_label.add_css_class("title-2") # Estilo de título grande
        panel2_desc_label.set_wrap(True)
        panel2_desc_label.set_justify(Gtk.Justification.CENTER)
        panel2_desc_label.set_halign(Gtk.Align.CENTER)
        panel2_desc_label.set_max_width_chars(50) # Limitar ancho para mejor lectura
        page2_vbox_content.append(panel2_desc_label)

        panel2_desc_label2 = Gtk.Label(label="Would you like to start the applet with your session?")
        panel2_desc_label2.set_wrap(True)
        panel2_desc_label2.set_justify(Gtk.Justification.CENTER)
        panel2_desc_label2.set_halign(Gtk.Align.CENTER)
        panel2_desc_label2.set_max_width_chars(50) # Limitar ancho para mejor lectura
        page2_vbox_content.append(panel2_desc_label2)
        
        # Opciones de arranque para el applet de bandeja
        self.tray_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.tray_group.set_hexpand(True)
        self.tray_group.set_halign(Gtk.Align.CENTER) # Centrar el grupo de botones
        self.tray_group.set_margin_top(12) # Espacio antes de los botones
        self.tray_radio1 = Gtk.CheckButton(label="Yes, with my session")
        self.tray_radio1.add_css_class("selection-mode")
        self.tray_radio2 = Gtk.CheckButton(label="No, only when I start the app")
        self.tray_radio2.add_css_class("selection-mode")
        self.tray_radio1.set_group(self.tray_radio2) # Agrupar para que sean mutuamente excluyentes
        self.tray_radio2.set_active(True) # Opción por defecto
        self.tray_group.append(self.tray_radio1)
        self.tray_group.append(self.tray_radio2)
        page2_vbox_content.append(self.tray_group)

        # Animación para el icono del Panel 2
        panel2_app_animation_target = Adw.CallbackAnimationTarget.new(self._animate_panel2_app_icon_callback)
        self.panel2_app_animation = Adw.TimedAnimation.new(self.panel2_app_icon, 0.0, 1.0, 700, panel2_app_animation_target)
        self.panel2_app_animation.set_easing(Adw.Easing.EASE_OUT_EXPO)
        self.panel2_app_animation_played = False

        # Panel 3: Configuración de modelo y API key
        # Replace Adw.StatusPage with a Gtk.Box for more direct layout control
        page3_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page3_container.set_hexpand(True)
        page3_container.set_halign(Gtk.Align.FILL)
        page3_container.set_vexpand(True)
        page3_container.set_valign(Gtk.Align.FILL)

        # Contenedor interno para el icono y el selector de modelo
        panel3_inner_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel3_inner_vbox.set_valign(Gtk.Align.FILL) # Para que el model_selector pueda expandirse
        panel3_inner_vbox.set_halign(Gtk.Align.FILL) # Usar todo el ancho disponible
        panel3_inner_vbox.set_hexpand(True)
        panel3_inner_vbox.set_vexpand(True)

        # El icono animado se elimina del panel 3.
        # El CompactModelSelector ya tiene su propio icono "brain-augmented-symbolic"
        # en su estado inicial (página "No Selection").

        self.model_manager = ModelSelectionManager(self.config_data, app.llm_client if hasattr(app, 'llm_client') else None)
        # Crear y configurar widget de selección
        self.model_selector = CompactModelSelector(manager=self.model_manager) # Usar CompactModelSelector
        self.model_selector.set_vexpand(True) # Hacer que el selector ocupe el espacio vertical
        self.model_selector.set_hexpand(True) # Hacer que el selector ocupe el espacio horizontal
        self.model_selector.set_valign(Gtk.Align.FILL)
        self.model_selector.set_halign(Gtk.Align.FILL)

        self.model_selector.connect('model-selected', self._on_model_selected)
        self.model_selector.connect('api-key-status-changed', self._on_api_key_status_changed)
        
        # Cargar lista de proveedores
        self.model_selector.load_providers_and_models() # Usar el nuevo método de carga
        panel3_inner_vbox.append(self.model_selector) # model_selector ya se expande

        page3_container.append(make_clamped(panel3_inner_vbox, 
                                            fill_vertical=True, 
                                            halign=Gtk.Align.FILL))

        # Panel 4: Links y cierre
        page4 = Adw.StatusPage()
        page4.set_hexpand(True)
        page4.set_halign(Gtk.Align.FILL)
        page4.set_title("Ready to start!")
        # page4.set_description("Discover more, report issues, or contribute on our website.") # Se reemplaza por el icono animado

        # Contenido del Panel 4: Icono checkmark y luego el link
        page4_vbox_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page4_vbox_content.set_valign(Gtk.Align.CENTER)
        page4_vbox_content.set_halign(Gtk.Align.CENTER)
        page4_vbox_content.set_hexpand(True)

        # Icono checkmark para indicar que está listo
        checkmark_icon = Gtk.Image.new_from_icon_name("checkmark-symbolic")
        checkmark_icon.set_pixel_size(128)
        checkmark_icon.set_halign(Gtk.Align.CENTER)
        checkmark_icon.set_margin_bottom(24)
        checkmark_icon.add_css_class("success")
        page4_vbox_content.append(checkmark_icon)

        link_button = Gtk.LinkButton(uri="https://gtk-llm-chat.fuentelibre.org/", label="gtk-llm-chat.fuentelibre.org")
        link_button.set_halign(Gtk.Align.CENTER)
        page4_vbox_content.append(link_button)

        page4.set_child(make_clamped(page4_vbox_content))

        # Añadir páginas al carrusel
        self.carousel.append(page1)
        self.carousel.append(make_clamped(page2_vbox_content, fill_vertical=False)) # Añadir el Gtk.Box del panel 2
        self.carousel.append(make_clamped(page3_container, fill_vertical=True)) # Panel 3 uses full space
        self.carousel.append(page4)

        # --- Indicadores de puntos ---
        self.indicator_dots = Adw.CarouselIndicatorDots(carousel=self.carousel)
        self.indicator_dots.set_halign(Gtk.Align.CENTER)
        self.indicator_dots.set_valign(Gtk.Align.END)
        self.indicator_dots.set_margin_top(6)
        self.indicator_dots.set_margin_bottom(18)

        # --- Ensamblar todo ---
        self.carousel.set_hexpand(True)
        self.carousel.set_halign(Gtk.Align.FILL)
        root_vbox.append(self.carousel)
        root_vbox.append(self.indicator_dots)

        self.carousel.connect("page-changed", self.on_page_changed)
        self.update_navigation_buttons()
        self.on_page_changed(self.carousel, self.carousel.get_position()) # Establecer título inicial
        
        # Agregar soporte para tecla Enter
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE) # Process key events in capture phase
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

    def on_start_clicked(self, button):
        # Avanza al siguiente panel
        page_to_scroll_to = self.carousel.get_nth_page(1)
        if page_to_scroll_to:
            self.carousel.scroll_to(page_to_scroll_to, True)
        if self.on_start_callback:
            self.on_start_callback()

    def on_prev_clicked(self, button):
        current_page_idx = int(round(self.carousel.get_position()))
        if current_page_idx > 0:
            prev_page_widget = self.carousel.get_nth_page(current_page_idx - 1)
            if prev_page_widget:
                self.carousel.scroll_to(prev_page_widget, True)

    def on_next_clicked(self, button):
        current_page_idx = int(round(self.carousel.get_position()))
        n_pages = self.carousel.get_n_pages()

        if current_page_idx == 2: # Panel de selección de modelo (índice 2)
            status = self.model_selector.get_current_model_selection_status()
            if not status["is_valid_for_next_step"]:
                # Podríamos mostrar un Adw.Toast aquí para indicar el problema
                print("DEBUG: Cannot proceed, model/API key selection is not valid.")
                return

        if current_page_idx < n_pages - 1:
            next_page_widget = self.carousel.get_nth_page(current_page_idx + 1)
            if next_page_widget:
                 self.carousel.scroll_to(next_page_widget, True)

    def on_page_changed(self, carousel, page_index):
        self.update_navigation_buttons()
        # Convert float page_index to int, rounding to the nearest whole number.
        # page_index can be a float during transitions.
        current_page_as_int = int(round(page_index))

        if 0 <= current_page_as_int < len(self.panel_titles):
            self.set_title(self.panel_titles[current_page_as_int])
        else:
            self.set_title("") # Título por defecto si el índice está fuera de rango

        # Disparar animación del icono de la app para Panel 2
        if current_page_as_int == 1 and not self.panel2_app_animation_played: # Panel 2 es índice 1
            if hasattr(self, 'panel2_app_animation'):
                self.panel2_app_animation.play()
                self.panel2_app_animation_played = True
        
        # Manage focusability of the 'Previous' button
        if current_page_as_int == 2: # Special handling for arriving at Panel 3
            # Explicitly make prev_button non-focusable immediately upon arrival at Panel 3
            # This is to prevent it from grabbing focus during the transition from Panel 2.
            self.prev_button.set_can_focus(False)
            
            # Schedule an attempt to focus the main content of Panel 3 (sidebar)
            # and then re-enable focus on the 'Previous' button.
            if self.model_selector and hasattr(self.model_selector, 'provider_sidebar') and \
               self.model_selector.provider_sidebar:
                def attempt_focus_and_reenable_prev_button():
                    # Check if we are still on Panel 3 before trying to focus its content
                    if int(round(self.carousel.get_position())) == 2:
                        if self.model_selector.provider_sidebar.get_realized() and \
                           self.model_selector.provider_sidebar.get_mapped():
                            self.model_selector.provider_sidebar.grab_focus()
                    
                    # Always re-enable focus on prev_button if it's sensitive,
                    # regardless of whether focus grab succeeded or if we are still on panel 3.
                    # This prevents it from getting stuck in a non-focusable state.
                    if self.prev_button.is_sensitive():
                        self.prev_button.set_can_focus(True)

                    return GLib.SOURCE_REMOVE # Run only once
                GLib.timeout_add(100, attempt_focus_and_reenable_prev_button) # Increased delay
        else: # For all other panels (not Panel 3)
            # Set 'Previous' button focusability based on its sensitivity.
            # update_navigation_buttons (called earlier) determines sensitivity.
            if self.prev_button.is_sensitive():
                self.prev_button.set_can_focus(True)
            else: # If not sensitive (e.g., on the first panel), it shouldn't be focusable.
                self.prev_button.set_can_focus(False)


    def on_key_pressed(self, controller, keyval, keycode, state):
        """Maneja la tecla Enter para avanzar páginas"""
        if not (keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter):
            return False # No es la tecla Enter, permitir propagación por defecto.

        current_page_idx = int(round(self.carousel.get_position()))
        n_pages = self.carousel.get_n_pages()

        if current_page_idx == 0: # Primer panel: simula el botón "Start"
            self.on_start_clicked(None)
            return True # Consumir Enter
        #elif current_page_idx == 1: # Panel 2 (Applet de Bandeja): simula "Next" pero permite toggle de CheckButton
        #    if current_page_idx < n_pages - 1: # Asegurar que no es la última página
        #        self.on_next_clicked(None)
            # Permitir que Enter propague al CheckButton enfocado si está en el panel 2.
            # Esto es porque el EventControllerKey está en fase de CAPTURE.
            # Si retornamos False, el evento continúa hacia el widget enfocado.
        #    return False
        elif current_page_idx == n_pages - 1: # Último panel: simula el botón "Ready"
            self.on_finish_clicked(None)
            return True # Consumir Enter
        else: # Paneles intermedios (actualmente solo Panel 3 / índice 2)
              # Simula el botón "Next". on_next_clicked() ya maneja la validación.
            self.on_next_clicked(None)
            # Consumir Enter, incluso si la validación en on_next_clicked falla (simulando un botón inactivo)
            return True

    def update_navigation_buttons(self):
        idx = self.carousel.get_position()
        current_page_idx = int(round(idx))
        n = self.carousel.get_n_pages()

        self.prev_button.set_sensitive(current_page_idx > 0)

        # Mostrar/ocultar Next y Start Chatting según el panel
        if current_page_idx == 0: # Primer panel
            self.prev_button.set_visible(False)
            self.next_button.set_visible(False)
            # El botón "Ready" (start_chatting_button) está en el contenido del panel 4, no en el header.
            # No es necesario quitarlo del header aquí.
            self._ensure_api_key_button_removed()
        elif current_page_idx == n - 1: # Último panel
            self.prev_button.set_visible(True)
            self.next_button.set_visible(False)
            # Añadir el botón "Ready" al header bar en el último panel
            if self.start_chatting_button.get_parent() != self.header_bar:
                self.header_bar.pack_end(self.start_chatting_button)
            self.start_chatting_button.set_visible(True)
            self._ensure_api_key_button_removed()
        else: # Paneles intermedios
            self.prev_button.set_visible(True)
            self.next_button.set_visible(True)
            # El botón "Ready" (start_chatting_button) está en el contenido del panel 4, no en el header.
            # No es necesario quitarlo del header aquí.
            self.start_chatting_button.set_visible(False) # Ocultar en paneles intermedios
            
            # Lógica específica para el panel de selección de modelo (índice 2)
            if current_page_idx == 2:
                status = self.model_selector.get_current_model_selection_status()
                self.next_button.set_sensitive(status["is_valid_for_next_step"])
                
                if status["needs_api_key"]:
                    if not self.api_key_button_packed:
                        self.header_bar.pack_start(self.api_key_button)
                        self.api_key_button_packed = True
                    self.api_key_button.set_visible(True)
                    self.api_key_button.set_label("Set API Key" if not status["api_key_set"] else "Change API Key")
                    self.api_key_button.get_style_context().remove_class("suggested-action")
                    self.api_key_button.get_style_context().remove_class("destructive-action")
                    if not status["api_key_set"]:
                        self.api_key_button.get_style_context().add_class("destructive-action")
                    else:
                        self.api_key_button.get_style_context().add_class("suggested-action")
                else:
                    self._ensure_api_key_button_removed()
            else: # Otros paneles intermedios
                self.next_button.set_sensitive(True) # Por defecto sensible
                self._ensure_api_key_button_removed()

    def _ensure_api_key_button_removed(self):
        if self.api_key_button_packed and self.api_key_button.get_parent():
            if self.api_key_button.get_parent() == self.header_bar: # Comprobar explícitamente
                self.header_bar.remove(self.api_key_button)
        self.api_key_button_packed = False
        self.api_key_button.set_visible(False)

    def on_finish_clicked(self, button):
        """Guarda la configuración y cierra la ventana de bienvenida"""
        self.save_configuration()
        # if self.on_start_callback: # El callback original se llamaba en on_start_clicked
        #     self.on_start_callback() # Este callback es para cuando la app principal debe iniciar
        self.close()
        # Si hay un callback para indicar que el welcome flow ha terminado y la app puede proceder:
        if hasattr(self.get_application(), 'on_welcome_finished'):
             self.get_application().on_welcome_finished(self.get_configuration())


    def _on_model_selected(self, selector, model_id):
        """Callback cuando se selecciona un modelo."""
        # Guardar el modelo seleccionado en la configuración
        self.config_data['model'] = model_id
        self.update_navigation_buttons() # Re-evaluar la validez para "Next"

    def save_configuration(self):
        """Guarda la configuración seleccionada."""
        # Restaurar guardado de configuración de bandeja
        if self.tray_radio1.get_active():
            self.config_data['tray_startup'] = 'session'
        elif self.tray_radio2.get_active():
            self.config_data['tray_startup'] = 'application'
        else:
            # Aunque no debería pasar si uno está activo por defecto
            self.config_data['tray_startup'] = 'never' 
        # La configuración del modelo y API key ya está guardada a través de
        # ModelSelectionManager y las señales 'model-selected' y 'api-key-changed'
        print(f"Configuration saved: {self.config_data}")

    def get_configuration(self):
        """Retorna la configuración guardada."""
        return self.config_data.copy()

    def _on_api_key_button_clicked(self, button):
        self.model_selector.trigger_api_key_dialog_for_current_provider()

    def _on_api_key_status_changed(self, selector, provider_key, needs_key, has_key):
        # Esta señal es principalmente para que CompactModelSelector informe de cambios.
        # WelcomeWindow reacciona a estos cambios actualizando sus botones de navegación.
        if int(round(self.carousel.get_position())) == 2: # Si estamos en el panel de modelos
            self.update_navigation_buttons()

    def _animate_panel2_app_icon_callback(self, value):
        self.panel2_app_icon.set_opacity(value)
        start_size = 1
        end_size = self.panel2_app_icon_target_size
        current_size = int(end_size * value)
        self.panel2_app_icon.set_size_request(current_size, current_size)
        self.panel2_app_icon.set_pixel_size(current_size)


if __name__ == "__main__":
    import sys
    import signal
    app = Adw.Application(application_id="org.fuentelibre.GtkLLMChatWelcome", flags=Gio.ApplicationFlags.FLAGS_NONE)

    # Configurar la ruta de búsqueda para iconos personalizados
    # Esto es similar a lo que ChatApplication hace en _setup_icon()
    icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    # welcome.py está en la raíz del proyecto, los iconos están en gtk_llm_chat/
    project_root = os.path.dirname(os.path.abspath(__file__))
    custom_icon_path = os.path.join(project_root, "gtk_llm_chat")
    icon_theme.add_search_path(custom_icon_path)

    # Asegurar que el tema de iconos Adwaita esté activo
    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property("gtk-icon-theme-name", "Adwaita")

    def on_activate(app):
        # Simular un callback para cuando la bienvenida termina
        def welcome_finished_callback(config):
            print("Welcome flow finished. Config:", config)
            app.quit()
        app.on_welcome_finished = welcome_finished_callback # Añadir el callback a la app
        win = WelcomeWindow(app) # on_start_callback ya no se pasa aquí
        win.present()
        # Permitir Ctrl+C para cerrar
        signal.signal(signal.SIGINT, lambda s, f: app.quit())

    app.connect('activate', on_activate)
    app.run(sys.argv)
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib, Gdk
import os

from .chat_application import _
from .model_selector import ModelSelectorWidget
from .model_selection import ModelSelectionManager

def debug_print(*args):
    if DEBUG:
        print(*args)
    

PROVIDER_LIST_NAME = "providers"
MODEL_LIST_NAME = "models"
DEBUG = os.environ.get('DEBUG') or False

class ChatSidebar(Gtk.Box):
    """
    Sidebar widget for model selection using a two-step navigation
    (Providers -> Models) with Adw.ViewStack and API key management via Adw.Banner.
    """

    def __init__(self, config=None, llm_client=None, **kwargs):
        self.config = config or {}
        self.llm_client = llm_client
        
        # Crear el manager para el selector de modelos
        self.model_manager = ModelSelectionManager(config, llm_client)

        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs) # Sin espacio entre header y stack

        self.set_margin_top(0) # Sin margen superior, el header lo maneja
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Crear Gtk.Stack con transición rotate-left-right
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.ROTATE_LEFT_RIGHT)
        self.stack.set_vexpand(True)

        # --- Página 1: Acciones principales (diseño similar al info_panel) ---
        actions_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Contenedor principal con espaciado como en info_panel
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        main_vbox.set_valign(Gtk.Align.START)
        main_vbox.set_halign(Gtk.Align.FILL)
        main_vbox.set_margin_top(24)
        main_vbox.set_margin_start(12)
        main_vbox.set_margin_end(12)
        main_vbox.set_margin_bottom(12)

        # Avatar con icono brain-symbolic (como en info_panel)
        avatar = Adw.Avatar(size=64)
        avatar.set_icon_name("brain-symbolic")
        avatar.set_halign(Gtk.Align.CENTER)
        avatar.set_margin_bottom(12)
        main_vbox.append(avatar)

        # Grupo del Modelo
        model_group = Adw.PreferencesGroup(title=_("Model"))
        
        # Fila de Modelo - uso de ícono "brain-symbolic"
        model_id = self.config.get('model') or self.llm_client.get_model_id() if self.llm_client else None
        self.model_row = Adw.ActionRow(title=_("Change Model"),
                                       subtitle=f"{_('Provider')}: " + llm_client.get_provider_for_model(model_id) if llm_client else None)
        self.model_row.set_icon_name("brain-symbolic")
        # NO establecer subtítulo aquí, lo hará model-loaded
        self.model_row.set_activatable(True)  # Hacerla accionable
        self.model_row.connect("activated", self._on_model_button_clicked)
        
        # Añadir botón "Set as Default Model" al row del modelo
        self.default_model_button = Gtk.Button()
        self.default_model_button.set_icon_name("starred-symbolic")
        self.default_model_button.set_tooltip_text(_("Set as Default Model"))
        self.default_model_button.add_css_class("flat")
        self.default_model_button.add_css_class("warning")  # Estrella amarilla
        self.default_model_button.connect("clicked", self._on_set_default_model_clicked)
        self.model_row.add_suffix(self.default_model_button)
        
        model_group.add(self.model_row)

        # Fila para Parámetros del Modelo
        parameters_action_row = Adw.ActionRow(title=_("Model Parameters"))
        parameters_action_row.set_icon_name("brain-augmented-symbolic")
        parameters_action_row.set_activatable(True)
        parameters_action_row.connect("activated", self._on_model_parameters_button_clicked)
        model_group.add(parameters_action_row)
        
        main_vbox.append(model_group)

        # Grupo de la Conversación
        conversation_group = Adw.PreferencesGroup(title=_("Conversation"))
        
        # Delete Conversation - uso de ícono "user-trash-symbolic"
        delete_row = Adw.ActionRow(title=_("Delete Conversation"))
        delete_row.add_css_class("destructive")
        delete_row.set_icon_name("user-trash-symbolic")
        delete_row.set_activatable(True)  # Hacerla accionable
        delete_row.connect("activated", lambda x: self.get_root().get_application().on_delete_activate(None, None))
        conversation_group.add(delete_row)
        
        main_vbox.append(conversation_group)
        
        # Grupo About
        about_group = Adw.PreferencesGroup(title=_("Information"))
        # About - uso de ícono "help-about-symbolic"
        about_row = Adw.ActionRow(title=_("About"))
        about_row.set_icon_name("help-about-symbolic")
        about_row.set_activatable(True)  # Hacerla accionable
        about_row.connect("activated", lambda x: self.get_root().get_application().on_about_activate(None, None))
        about_group.add(about_row)
        
        main_vbox.append(about_group)
        
        actions_page.append(main_vbox)
        self.stack.add_titled(actions_page, "actions", _("Actions"))

        # --- Página 2: Selector de Modelos usando ModelSelectorWidget ---
        # Solo el widget selector de modelos (usa sus propios headers)
        self.model_selector = ModelSelectorWidget(manager=self.model_manager)
        self.model_selector.connect('model-selected', self._on_model_selected)
        self.model_selector.connect('api-key-status-changed', self._on_api_key_status_changed)
        
        self.stack.add_titled(self.model_selector, "model_selector", _("Model Selector"))        
        # --- Página 3: Parámetros del Modelo ---
        parameters_page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        parameters_header = Adw.HeaderBar()
        parameters_header.set_show_end_title_buttons(False)
        parameters_header.add_css_class("flat")
        param_back_button = Gtk.Button(icon_name="go-previous-symbolic")
        param_back_button.connect("clicked", lambda x: self.stack.set_visible_child_name("actions"))
        parameters_header.pack_start(param_back_button)
        parameters_header.set_title_widget(Gtk.Label(label=_("Model Parameters")))
        parameters_page_box.append(parameters_header)

        parameters_group = Adw.PreferencesGroup() # No necesita título si el header ya lo tiene
        parameters_page_box.append(parameters_group)

        # Mover la Fila de Temperatura aquí
        self.temperature_row = Adw.ActionRow(title=_("Temperature"))
        self.temperature_row.set_icon_name("temperature-symbolic") # O un ícono más adecuado
        initial_temp = self.config.get('temperature', 0.7)
        self.adjustment = Gtk.Adjustment(value=initial_temp, lower=0.0, upper=1.0, step_increment=0.05, page_increment=0.1) # Ajustado upper y step
        self.adjustment.connect("value-changed", self._on_temperature_changed)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.adjustment, digits=2, value_pos=Gtk.PositionType.RIGHT) # digits a 2
        scale.set_hexpand(True)
        self.temperature_row.add_suffix(scale)
        self.temperature_row.set_activatable_widget(scale)
        parameters_group.add(self.temperature_row)
        self._update_temperature_subtitle() # Actualizar subtítulo inicial de temperatura

        # Nueva Fila para System Prompt
        self.system_prompt_row = Adw.ActionRow(title=_("System Prompt"))
        self.system_prompt_row.set_icon_name("open-book-symbolic") # O un ícono más adecuado
        self.system_prompt_row.set_activatable(True)
        self.system_prompt_row.connect("activated", self._on_system_prompt_button_clicked)
        parameters_group.add(self.system_prompt_row)
        self._update_system_prompt_row_subtitle() # Actualizar subtítulo inicial

        self.stack.add_titled(parameters_page_box, "parameters", _("Parameters"))

        # Añadir el stack al sidebar
        self.append(self.stack)

        # Cargar proveedores en el selector de modelos
        GLib.timeout_add(500, self._delayed_model_load)

        # Si ya tenemos llm_client, programar la actualización del modelo
        if self.llm_client:
            self.llm_client.connect('model-loaded', self._on_model_loaded)
            # Programar la actualización con el modelo actual
            GLib.idle_add(self.update_model_button)
            # Configurar visibilidad inicial del botón de modelo por defecto
            GLib.idle_add(self._update_default_model_button_visibility)

        # Volver a la primera pantalla al colapsar el sidebar
        def _on_sidebar_toggled(self, toggled):
            if not toggled:
                self.stack.set_visible_child_name("actions")

        # Conectar el evento de colapsar el sidebar
        self.connect("notify::visible", lambda obj, pspec: self._on_sidebar_toggled(self.get_visible()))
        
    def _delayed_model_load(self):
        """Carga los modelos después de un breve retraso para no bloquear la UI durante el arranque."""
        debug_print("ChatSidebar: Cargando modelos en segundo plano...")
        self.model_selector.load_providers()
        return False  # No repetir el timeout

    def _on_model_selected(self, selector, model_id):
        """Manejador cuando se selecciona un modelo desde el ModelSelectorWidget."""
        debug_print(f"ChatSidebar: Model selected: {model_id}")
        
        # Intentar cambiar el modelo
        success = True
        if self.llm_client:
            success = self.llm_client.set_model(model_id)
        
        if success:
            self.config['model'] = model_id
            # Volver a la página de acciones
            self.stack.set_visible_child_name("actions")
            
            # Actualizar el modelo en la base de datos si hay una conversación actual
            if self.llm_client:
                cid = self.llm_client.get_conversation_id()
                if cid:
                    self.llm_client.chat_history.update_conversation_model(cid, model_id)
            
            # Ocultar el sidebar después de un breve retraso
            window = self.get_root()
            if window and hasattr(window, 'split_view'):
                GLib.timeout_add(100, lambda: window.split_view.set_show_sidebar(False))

    def _on_api_key_status_changed(self, selector, provider_key, needs_key, has_key):
        """Manejador cuando cambia el estado de la API key."""
        debug_print(f"ChatSidebar: API key status changed for {provider_key}: needs_key={needs_key}, has_key={has_key}")

    def _on_model_button_clicked(self, row):
        """Handler para cuando se activa la fila del modelo."""
        # Mostrar el selector de modelos
        self.stack.set_visible_child_name("model_selector")

    def _on_set_default_model_clicked(self, button):
        """Manejador para el botón 'Set as Default Model'."""
        if not self.llm_client:
            debug_print("ChatSidebar: No hay llm_client disponible para establecer modelo por defecto")
            return
            
        current_model_id = self.llm_client.get_model_id()
        if not current_model_id:
            debug_print("ChatSidebar: No hay modelo actual para establecer como defecto")
            return
            
        # Obtener el nombre del proveedor para mostrar en el diálogo
        provider_name = self.llm_client.get_provider_for_model(current_model_id) or _("Unknown Provider")
        
        root_window = self.get_root()
        dialog = Adw.MessageDialog(
            transient_for=root_window,
            modal=True,
            heading=_("Set Default Model"),
            body=f"{_('Do you want to set')} '{current_model_id}' {_('from')} {provider_name} {_('as the default model for new conversations?')}"
        )
        
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("set_default", _("Set as Default"))
        dialog.set_response_appearance("set_default", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("set_default")
        
        dialog.connect("response", self._on_set_default_model_dialog_response, current_model_id)
        dialog.present()
    
    def _on_set_default_model_dialog_response(self, dialog, response_id, model_id):
        """Manejador de la respuesta del diálogo 'Set as Default Model'."""
        if response_id == "set_default":
            # Guardar el modelo como defecto en la configuración
            self.config['default_model'] = model_id
            debug_print(f"ChatSidebar: Modelo '{model_id}' establecido como defecto")

            # Forzar recarga del modelo por defecto desde llm y refrescar el estado visual
            try:
                import llm
                llm.set_default_model(model_id)
            except Exception as e:
                debug_print(f"ChatSidebar: Error al establecer modelo por defecto en llm: {e}")
            # Llamar update_model_button para refrescar TODO el panel
            self.update_model_button()

            # Mostrar toast de confirmación si es posible
            window = self.get_root()
            if window and hasattr(window, 'add_toast'):
                toast = Adw.Toast(title=f"{_('Model')} '{model_id}' {_('set as default')}")
                toast.set_timeout(3)
                window.add_toast(toast)

        dialog.destroy()

    def _on_temperature_changed(self, adjustment):
        """Manejador para cuando cambia el valor de la temperatura."""
        temperature = adjustment.get_value()
        self.config['temperature'] = temperature
        if self.llm_client and hasattr(self.llm_client, 'set_temperature'):
             try:
                  self.llm_client.set_temperature(temperature)
             except Exception as e:
                  debug_print(f"Error setting temperature in LLM client: {e}")
        self._update_temperature_subtitle() # Actualizar subtítulo de temperatura

    def _update_temperature_subtitle(self):
        """Actualiza el subtítulo de la fila de temperatura con el valor actual."""
        if hasattr(self, 'adjustment') and hasattr(self, 'temperature_row'):
            temp_value = self.adjustment.get_value()
            self.temperature_row.set_subtitle(f"{temp_value:.2f}")
        else:
            debug_print("ChatSidebar: Saltando actualización de subtítulo de temperatura (adjustment o temperature_row no inicializados).")

    def _on_model_loaded(self, client, model_id):
        """Callback para la señal model-loaded del LLMClient."""
        debug_print(f"ChatSidebar: Model loaded: {model_id}")

        # Obtener el proveedor del modelo cargado
        provider_name = _("Unknown Provider")
        if self.llm_client:
            provider_name = self.llm_client.get_provider_for_model(model_id) or _("Unknown Provider")
        
        self.model_row.set_subtitle(f"{_('Provider')}: {provider_name}")
        debug_print(f"ChatSidebar: _on_model_loaded calling _update_default_model_button_visibility")
        self._update_default_model_button_visibility()

    def _on_model_parameters_button_clicked(self, row):
        self.stack.set_visible_child_name("parameters")

    def _on_system_prompt_button_clicked(self, row):
        debug_print("ChatSidebar: _on_system_prompt_button_clicked llamado.")
        root_window = self.get_root()
        debug_print(f"ChatSidebar: Ventana raíz para el diálogo: {root_window}")

        dialog = Adw.MessageDialog(
            transient_for=root_window,
            modal=True,
            heading=_("Set System Prompt"),
            body=_("Enter the system prompt for the AI model:"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("set", _("Set"))
        dialog.set_response_appearance("set", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("set")

        text_view = Gtk.TextView(
            editable=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            vexpand=True,
            hexpand=True,
            left_margin=6, right_margin=6, top_margin=6, bottom_margin=6
        )
        text_view.get_buffer().set_text(self.config.get('system', '') or '')
        text_view.add_css_class("card")
        
        scrolled_window = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            min_content_height=150 # Altura mínima para el text view
        )
        scrolled_window.set_child(text_view)

        clamp = Adw.Clamp(maximum_size=600) # Ancho máximo del diálogo
        clamp.set_child(scrolled_window)
        dialog.set_extra_child(clamp)

        dialog.connect("response", self._on_system_prompt_dialog_response, text_view)
        GLib.idle_add(dialog.present)
        GLib.idle_add(lambda: text_view.grab_focus())

    def _on_system_prompt_dialog_response(self, dialog, response_id, text_view):
        if response_id == "set":
            buffer = text_view.get_buffer()
            new_system_prompt = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
            self.config['system'] = new_system_prompt.strip() # Guardar como 'system'
            self._update_system_prompt_row_subtitle()
            # No es necesario notificar a LLMClient explícitamente si lee de self.config['system']
            debug_print(f"System prompt actualizado a: {self.config['system'][:100]}")
        dialog.destroy()

    def _update_system_prompt_row_subtitle(self):
        current_prompt = self.config.get('system', '')
        if current_prompt:
            # Tomar las primeras N palabras o M caracteres
            words = current_prompt.split()
            if len(words) > 7:
                subtitle_text = ' '.join(words[:7]) + "..."
            elif len(current_prompt) > 40:
                subtitle_text = current_prompt[:37] + "..."
            else:
                subtitle_text = current_prompt
            self.system_prompt_row.set_subtitle(f"{_('Current')}: {subtitle_text}")
        else:
            self.system_prompt_row.set_subtitle(_("Not set"))

    def _update_default_model_button_visibility(self):
        """Actualiza el estilo y estado del botón de estrella según si el modelo actual es el modelo por defecto."""
        debug_print(f"ChatSidebar: _update_default_model_button_visibility called")
        if not self.llm_client or not hasattr(self, 'default_model_button'):
            debug_print("ChatSidebar: Cannot update button visibility - missing llm_client or button")
            return

        current_model_id = self.llm_client.get_model_id()
        try:
            import llm
            default_model_id = llm.get_default_model()
        except Exception as e:
            debug_print(f"ChatSidebar: Error obteniendo modelo por defecto del sistema: {e}")
            default_model_id = None

        is_default = (current_model_id is not None and default_model_id is not None and current_model_id == default_model_id)

        # El botón de estrella siempre debe ser visible
        self.default_model_button.set_visible(True)

        # Limpiar clases previas
        self.default_model_button.remove_css_class("warning")
        self.default_model_button.remove_css_class("suggested-action")

        if is_default:
            # Estilo de advertencia y deshabilitado
            self.default_model_button.add_css_class("warning")
            self.default_model_button.set_sensitive(False)
            self.default_model_button.set_tooltip_text(_("This is the current default model"))
        else:
            # Estilo normal y habilitado
            self.default_model_button.set_sensitive(True)
            self.default_model_button.set_tooltip_text(_("Set as default model"))
            self.default_model_button.add_css_class("suggested-action")
        debug_print(f"ChatSidebar: Default model button updated. is_default={is_default}")

    def update_model_button(self):
        """Actualiza la información del modelo seleccionado en la interfaz."""
        if not self.llm_client:
            return
            
        current_model_id = self.llm_client.get_model_id()
            
        # Actualizar la configuración con el modelo actual
        self.config['model'] = current_model_id
        
        # Actualizar subtítulo del modelo con el proveedor
        self.model_row.set_subtitle(f"{_('Provider')}: {self.llm_client.get_provider_for_model(current_model_id) or _('Unknown Provider')}")
        self._update_system_prompt_row_subtitle() # Asegurar que el subtítulo del system prompt también se actualice
        self._update_default_model_button_visibility() # Actualizar visibilidad del botón de modelo por defecto

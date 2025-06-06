import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib

from .chat_application import _
from .model_selection import ModelSelectionManager
from .debug_utils import debug_print

NO_SELECTION_KEY = "_internal_no_selection_"

class WideModelSelector(Gtk.Box):
    """
    Un widget de selección de modelo compacto usando Gtk.StackSidebar.
    Maneja la selección de proveedor, modelo y la configuración de API keys.
    No tiene títulos ni banners propios, diseñado para ser integrado.
    La gestión del botón de API key y el diálogo se delega al contenedor.
    """
    __gsignals__ = {
        'model-selected': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Señal: (provider_key, needs_key, has_key)
        'api-key-status-changed': (GObject.SignalFlags.RUN_LAST, None, (str, bool, bool))
    }

    def __init__(self, manager: ModelSelectionManager = None, config=None, llm_client=None, **kwargs):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, **kwargs)

        self.manager = manager or ModelSelectionManager(config, llm_client)
        self._current_provider_key_for_api_dialog = None

        # Stack principal para el contenido (listas de modelos y tarjetas de API key)
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.content_stack.set_vexpand(True)
        self.content_stack.set_hexpand(True)

        # Sidebar para navegar el stack de contenido (proveedores)
        self.provider_sidebar = Gtk.StackSidebar()
        self.provider_sidebar.set_stack(self.content_stack)
        self.provider_sidebar.set_vexpand(True)
        listbox = self.provider_sidebar.get_last_child().get_child().get_child()
        listbox.set_valign(Gtk.Align.CENTER)

        self.append(self.provider_sidebar)
        self.append(self.content_stack)

        self.content_stack.connect("notify::visible-child", self._on_stack_page_changed)

        # Cache para las UI de cada proveedor para no recrearlas constantemente
        self._provider_pages_cache = {} # provider_key -> { "page": Gtk.Box, "model_list": Gtk.ListBox }

        # Icono para la página "No Selection"
        self.no_selection_icon = None
        self.no_selection_icon_target_size = 128

        self.manager.connect('api-key-changed', self._on_external_api_key_change)

    def pick_model(self, modelid):
        """
        Selecciona el modelo dado su modelid, sin importar el proveedor.
        Cambia el sidebar al proveedor correspondiente y selecciona el modelo en la lista.
        Además, emite las señales necesarias para que el contenedor actualice el UI.
        """
        for provider_key in self.manager.models_by_provider:
            models = self.manager.get_models_for_provider(provider_key)
            for model in models:
                if getattr(model, 'model_id', None) == modelid:
                    # Normalizar None a un nombre válido para el stack
                    stack_key = provider_key if provider_key is not None else "local"
                    self.content_stack.set_visible_child_name(stack_key)
                    page_ui = self._provider_pages_cache.get(provider_key)
                    if page_ui:
                        model_list = page_ui["model_list"]
                        for row in model_list:
                            if getattr(row, 'model_id', None) == modelid:
                                GLib.idle_add(model_list.select_row, row)
                                break
                    self._update_model_info_panel(provider_key, modelid)
                    # Emitir señal para que el contenedor actualice el headerbar
                    self.emit('model-selected', modelid)
                    self._update_and_emit_api_key_status(provider_key)
                    return True
        return False

    def _add_no_selection_page(self):
        """Añade la página inicial de 'Sin Selección'."""
        page_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                               valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER,
                               margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        page_content.set_vexpand(True)

        info_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                               label=_("Please select a provider from the list on the left.\nThen, choose a model from the list that appears here."))
        info_label.set_margin_bottom(12)
        page_content.append(info_label)

        # Añadir el icono "brain-augmented-symbolic"
        self.no_selection_icon = Gtk.Image.new_from_icon_name("brain-augmented-symbolic")
        self.no_selection_icon.set_pixel_size(self.no_selection_icon_target_size)
        page_content.append(self.no_selection_icon)


        # Warning panel about API keys
        warning_bin = Adw.Bin()
        warning_bin.add_css_class("card")
        warning_bin.set_margin_top(12)
        warning_bin.set_margin_bottom(12)
        warning_bin.set_margin_start(12)
        warning_bin.set_margin_end(12)
        
        # Content inside the bin
        warning_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        warning_content.add_css_class("warning")
        warning_content.set_margin_top(12)
        warning_content.set_margin_bottom(12)
        warning_content.set_margin_start(12)
        warning_content.set_margin_end(12)
        
        # Icon and title row
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_halign(Gtk.Align.CENTER)
        
        warning_icon = Gtk.Image.new_from_icon_name("dialog-information")
        warning_icon.set_pixel_size(16)
        header_box.append(warning_icon)
        
        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{_('Most AI models require an API key')}</b>")
        title_label.set_halign(Gtk.Align.CENTER)
        header_box.append(title_label)
        
        warning_content.append(header_box)
        
        # Description text
        desc_label = Gtk.Label(label=_("You'll need to register with each provider to obtain these authentication tokens."))
        desc_label.set_halign(Gtk.Align.CENTER)
        desc_label.set_wrap(True)
        desc_label.set_xalign(0.0)
        warning_content.append(desc_label)
        
        warning_bin.set_child(warning_content)
        
        # Wrap warning card in a clamp to reduce its size
        warning_clamp = Adw.Clamp(maximum_size=400)
        warning_clamp.set_child(warning_bin)
        page_content.append(warning_clamp)

        self.content_stack.add_titled(page_content, NO_SELECTION_KEY, _("No Selection"))

    def load_providers_and_models(self):
        """Carga los proveedores y prepara las páginas en el stack."""
        # Limpiar completamente el stack
        while self.content_stack.get_first_child():
            child = self.content_stack.get_first_child()
            self.content_stack.remove(child)
        self._provider_pages_cache.clear()
        self._add_no_selection_page()

        if not self.manager.populate_providers_and_group_models():
            placeholder_page_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            placeholder_page_content.set_valign(Gtk.Align.CENTER)
            placeholder_page_content.set_halign(Gtk.Align.CENTER)
            placeholder_page_content.append(Gtk.Label(label=_("No models or providers found.")))
            self.content_stack.add_titled(placeholder_page_content, "no_providers_page", _("Error"))
            #GLib.idle_add(lambda: self.content_stack.set_visible_child_name(NO_SELECTION_KEY))
            #self._update_and_emit_api_key_status(NO_SELECTION_KEY)
            return

        sorted_providers = sorted(
            self.manager.models_by_provider.keys(),
            key=lambda p_key: self.manager.get_provider_display_name(p_key).lower()
        )
        
        for provider_key in sorted_providers:
            # Normalizar None a un nombre válido para el stack
            stack_key = provider_key if provider_key is not None else "local"
            debug_print(f"DEBUG: Agregando proveedor al stack - provider_key: '{provider_key}', stack_key: '{stack_key}', display_name: '{self.manager.get_provider_display_name(provider_key)}'")
            page_ui = self._create_page_for_provider(provider_key)
            self.content_stack.add_titled(page_ui["page"], stack_key, self.manager.get_provider_display_name(provider_key))
            self._provider_pages_cache[provider_key] = page_ui
            self._populate_model_list_for_page(provider_key, page_ui)
            # No actualizamos la tarjeta de API aquí, se hará al cambiar de página o seleccionar modelo

        # Solo forzar "No selection" si NO hay ningún modelo disponible en ningún proveedor
        any_model_available = any(
            any(getattr(model, 'model_id', None) for model in self.manager.get_models_for_provider(provider_key))
            for provider_key in self.manager.models_by_provider
        )

        #if not any_model_available:
        #    debug_print(f"DEBUG: No hay ningún modelo disponible en ningún proveedor, forzando página 'No Selection'")
            #GLib.idle_add(lambda: self.content_stack.set_visible_child_name(NO_SELECTION_KEY))
            #self._update_and_emit_api_key_status(NO_SELECTION_KEY)
        #else:
        #    debug_print(f"DEBUG: Hay al menos un modelo disponible, no se fuerza 'No Selection'")

    # --- Métodos de creación de UI para cada proveedor ---

    def _create_page_for_provider(self, provider_key: str) -> dict:
        """Crea la estructura de la página para un proveedor (API card + lista de modelos)."""
        page_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        page_box.set_margin_top(6)
        page_box.set_margin_bottom(6)
        page_box.set_margin_start(6)
        page_box.set_margin_end(6)
        page_box.set_vexpand(True)
        page_box.set_hexpand(True)

        # --- Model List ---
        model_list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                               vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        model_list_scroll.set_vexpand(True)
        model_list_scroll.set_hexpand(False)
        model_list_scroll.set_size_request(250, -1)  # Fixed width for model list
        model_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        model_list.set_valign(Gtk.Align.CENTER)
        model_list.add_css_class('navigation-sidebar') 
        model_list.connect("row-activated", self._on_model_row_activated, provider_key)
        model_list_scroll.set_child(model_list)
        page_box.append(model_list_scroll)

        # --- Info Panel for selected model ---
        info_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info_panel.set_vexpand(True)
        info_panel.set_hexpand(False)
        info_panel.set_size_request(350, -1)
        info_panel.set_valign(Gtk.Align.CENTER)
        
        # Placeholder icon 
        placeholder_icon = Gtk.Image.new_from_icon_name("brain-symbolic")
        placeholder_icon.set_pixel_size(64)
        placeholder_icon.set_halign(Gtk.Align.CENTER)
        placeholder_icon.set_valign(Gtk.Align.CENTER)
        placeholder_icon.add_css_class("dim-label")  # Atenuated color
        placeholder_icon.set_opacity(0.5)  # Static dim opacity
        info_panel.append(placeholder_icon)

        page_box.append(info_panel)

        return {"page": page_box, "model_list": model_list, "info_panel": info_panel}

    def _populate_model_list_for_page(self, provider_key: str, page_ui: dict):
        """Puebla la lista de modelos para la UI de página dada."""
        model_list_widget = page_ui["model_list"]
        self._clear_list_box(model_list_widget)

        models = self.manager.get_models_for_provider(provider_key)
        # Siempre deselecciona todo antes de poblar
        GLib.idle_add(model_list_widget.unselect_all)

        if not models:
            row = Adw.ActionRow(title=_("No models found for this provider"))
            row.set_selectable(False)
            model_list_widget.append(row)
            return

        current_model_id = self.manager.config.get('model')
        active_row = None
        for model_obj in models:
            model_id = getattr(model_obj, 'model_id', None)
            model_name = getattr(model_obj, 'name', None) or model_id
            if model_id:
                row = Adw.ActionRow(title=model_name)
                row.set_activatable(True)
                row.model_id = model_id 
                model_list_widget.append(row)
                if model_id == current_model_id:
                    active_row = row

        # Solo selecciona si hay un modelo válido
        if active_row:
            GLib.idle_add(model_list_widget.select_row, active_row)

    # --- Callbacks y manejo de estado ---

    def _on_model_row_activated(self, list_box, row, provider_key: str):
        model_id = getattr(row, 'model_id', None)
        if model_id:
            self.manager.config['model'] = model_id
            self.manager.emit('model-selected', model_id) 
            self.emit('model-selected', model_id)
            debug_print(f"WideModelSelector: Model '{model_id}' for provider '{provider_key}' selected.")
            self._update_and_emit_api_key_status(provider_key)
            self._update_model_info_panel(provider_key, model_id)

    def _on_stack_page_changed(self, stack, param):
        current_provider_key = stack.get_visible_child_name()
        debug_print(f"DEBUG: _on_stack_page_changed called - stack page changed to: '{current_provider_key}'")
        
        # Log the mapping from stack key to actual provider key
        if current_provider_key == "local":
            actual_provider = None
            debug_print(f"DEBUG: Stack key 'local' maps to provider key: None")
        elif current_provider_key == NO_SELECTION_KEY:
            actual_provider = NO_SELECTION_KEY
            debug_print(f"DEBUG: Stack key '{NO_SELECTION_KEY}' maps to provider key: {NO_SELECTION_KEY}")
        else:
            actual_provider = current_provider_key
            debug_print(f"DEBUG: Stack key '{current_provider_key}' maps to provider key: {actual_provider}")
        
        debug_print(f"DEBUG: Proveedor cambiado a: {actual_provider}")
        self._update_and_emit_api_key_status(actual_provider)

    def _show_api_key_dialog(self, provider_key: str):
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            heading=_("Enter API Key"),
            body=f"{_('Enter the API key for')} {self.manager.get_provider_display_name(provider_key)}:",
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("set", _("Set Key"))
        dialog.set_response_appearance("set", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("set")

        key_entry = Gtk.Entry(
            hexpand=True,
            placeholder_text=_("Paste your API key here")
        )
        key_entry.connect("activate", lambda entry: dialog.response("set"))
        
        content_clamp = Adw.Clamp(maximum_size=400)
        content_clamp.set_child(key_entry)
        dialog.set_extra_child(content_clamp)

        dialog.connect("response", self._on_api_key_dialog_response, key_entry)
        dialog.present()

    def _on_api_key_dialog_response(self, dialog, response_id, key_entry):
        provider_key = self._current_provider_key_for_api_dialog
        if not provider_key:
            dialog.destroy()
            return

        if response_id == "set":
            api_key = key_entry.get_text()
            if api_key: 
                self.manager.set_api_key(provider_key, api_key)
                # El _on_external_api_key_change se encargará de emitir api-key-status-changed
        dialog.destroy()
        self._current_provider_key_for_api_dialog = None

    def _on_external_api_key_change(self, manager_instance, provider_key_changed: str):
        debug_print(f"WideModelSelector: API key changed externally for provider '{provider_key_changed}', reloading models and updating UI.")
        
        # Save current selection to restore after reload
        current_provider = self.get_current_provider_key()
        current_stack_key = self.content_stack.get_visible_child_name()
        debug_print(f"WideModelSelector: Saving current selection - provider: '{current_provider}', stack_key: '{current_stack_key}'")
        
        # First reload dynamic models to get newly available models with the API key
        try:
            self.manager.reload_dynamic_models_only()
            debug_print(f"WideModelSelector: Dynamic models reloaded after API key change for '{provider_key_changed}'")
        except Exception as e:
            debug_print(f"WideModelSelector: Error reloading dynamic models: {e}")
        
        # Then update the UI
        if provider_key_changed in self._provider_pages_cache:
            page_ui = self._provider_pages_cache[provider_key_changed]
            self._populate_model_list_for_page(provider_key_changed, page_ui)
            
            # Update info panel if this provider is currently selected and a model is selected
            selected_model = self.get_selected_model_id()
            if current_provider == provider_key_changed and selected_model:
                self._update_model_info_panel(provider_key_changed, selected_model)
        
        # Restore the selection if it was the provider that changed
        if current_provider == provider_key_changed and current_stack_key != NO_SELECTION_KEY:
            debug_print(f"WideModelSelector: Restoring selection to stack_key: '{current_stack_key}'")
            GLib.idle_add(lambda: self.content_stack.set_visible_child_name(current_stack_key))
                
        self._update_and_emit_api_key_status(provider_key_changed)

    def _update_and_emit_api_key_status(self, provider_key: str):
        debug_print(f"DEBUG: _update_and_emit_api_key_status called with provider_key: '{provider_key}'")
        
        #if provider_key == NO_SELECTION_KEY or not provider_key:
        #    debug_print(f"DEBUG: Ocultando botón API key para {provider_key}")
        #    self.emit('api-key-status-changed', NO_SELECTION_KEY, False, False)
        #    return

        debug_print(f"DEBUG: Verificando status API key para proveedor: {provider_key}")
        key_status = self.manager.check_api_key_status(provider_key)
        needs_key = key_status.get('needs_key', False)
        has_key = key_status.get('has_key', False)
        debug_print(f"DEBUG: Status API key - needs_key: {needs_key}, has_key: {has_key}")
        
        if needs_key:
            debug_print(f"DEBUG: Mostrando botón API key para {provider_key}")
        else:
            debug_print(f"DEBUG: No se necesita API key para {provider_key}")
            
        self.emit('api-key-status-changed', provider_key, needs_key, has_key)

    def _clear_list_box(self, list_box: Gtk.ListBox):
        child = list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            list_box.remove(child)
            child = next_child

    def _update_model_info_panel(self, provider_key: str, model_id: str):
        """Actualiza el panel de información con los detalles del modelo seleccionado."""
        if provider_key not in self._provider_pages_cache:
            return
        
        page_ui = self._provider_pages_cache[provider_key]
        info_panel = page_ui["info_panel"]
        
        # Limpiar contenido actual
        child = info_panel.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            info_panel.remove(child)
            child = next_child
        
        # Contenedor principal con spacing
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        main_vbox.set_valign(Gtk.Align.START)
        main_vbox.set_halign(Gtk.Align.FILL)
        main_vbox.set_margin_top(24)
        main_vbox.set_margin_start(12)
        main_vbox.set_margin_end(12)
        
        # Avatar con icono brain-symbolic
        avatar = Adw.Avatar(size=64)
        avatar.set_icon_name("brain-symbolic")
        avatar.set_halign(Gtk.Align.CENTER)
        avatar.set_margin_bottom(12)
        main_vbox.append(avatar)
        
        # Obtener información del modelo
        models = self.manager.get_models_for_provider(provider_key)
        model_obj = None
        for model in models:
            if getattr(model, 'model_id', None) == model_id:
                model_obj = model
                break
        
        if not model_obj:
            error_row = Adw.ActionRow()
            error_row.set_title(_("Model information not available"))
            error_row.set_subtitle(_("Unable to retrieve model details"))
            main_vbox.append(error_row)
        else:
            # ListBox para las ActionRows
            details_listbox = Gtk.ListBox()
            details_listbox.add_css_class("boxed-list")
            details_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            
            # Model ID/Name Row
            model_name = getattr(model_obj, 'name', model_id) or model_id
            model_row = Adw.ActionRow()
            model_row.set_title(_("Model"))
            if model_name != model_id:
                model_row.set_subtitle(f"{model_name} ({model_id})")
            else:
                model_row.set_subtitle(model_id)
            model_row.set_icon_name("brain-symbolic")
            details_listbox.append(model_row)
            
            # Aliases Row (solo si existen)
            aliases = getattr(model_obj, 'aliases', None)
            if aliases and len(aliases) > 0:
                aliases_text = ", ".join(aliases)
                aliases_row = Adw.ActionRow()
                aliases_row.set_title(_("Aliases"))
                aliases_row.set_subtitle(aliases_text)
                aliases_row.set_icon_name("tag-symbolic")
                details_listbox.append(aliases_row)
            
            # API Key Row
            key_status = self.manager.check_api_key_status(provider_key)
            needs_key = key_status.get('needs_key', False)
            has_key = key_status.get('has_key', False)
            
            api_key_row = Adw.ActionRow()
            api_key_row.set_title(_("API Key"))
            api_key_row.set_icon_name("dialog-password-symbolic")
            api_key_row.set_activatable(True)  # Make it clickable
            
            # Connect to show API key dialog when clicked
            api_key_row.connect("activated", lambda row: self._on_api_key_row_activated(provider_key))
            
            if needs_key:
                if has_key:
                    api_key_row.set_subtitle(_("Required • Set"))
                    # Icono de éxito
                    check_icon = Gtk.Image.new_from_icon_name("padlock2-open-symbolic")
                    check_icon.add_css_class("success")
                    api_key_row.add_suffix(check_icon)
                else:
                    api_key_row.set_subtitle(_("Required • Not set"))
                    # Icono de advertencia
                    warning_icon = Gtk.Image.new_from_icon_name("padlock2-symbolic")
                    warning_icon.add_css_class("error")
                    api_key_row.add_suffix(warning_icon)
            else:
                api_key_row.set_subtitle(_("Not required"))
                api_key_row.set_activatable(False)  # Not clickable if not needed
            
            details_listbox.append(api_key_row)
            
            # Plugin/Provider Row
            plugin_info = getattr(model_obj, 'plugin_info', None)
            provider_row = Adw.ActionRow()
            provider_row.set_icon_name("application-x-addon-symbolic")
            
            if plugin_info:
                plugin_name = plugin_info.get('name', _('Unknown'))
                plugin_version = plugin_info.get('version', _('Unknown'))
                provider_row.set_title(_("Plugin"))
                provider_row.set_subtitle(f"{plugin_name} v{plugin_version}")
            else:
                provider_display_name = self.manager.get_provider_display_name(provider_key)
                provider_row.set_title(_("Provider"))
                provider_row.set_subtitle(provider_display_name)
            
            details_listbox.append(provider_row)
            main_vbox.append(details_listbox)
        
        info_panel.append(main_vbox)

    def _on_api_key_row_activated(self, provider_key: str):
        """Maneja el clic en la ActionRow de API Key para mostrar el diálogo."""
        self._current_provider_key_for_api_dialog = provider_key
        self._show_api_key_dialog(provider_key)

    # --- Métodos públicos para el contenedor ---

    def get_selected_model_id(self) -> str | None:
        return self.manager.config.get('model')

    def get_current_provider_key(self) -> str | None:
        stack_key = self.content_stack.get_visible_child_name()
        # Mapear "local" de vuelta a None para compatibilidad
        return None if stack_key == "local" else stack_key

    def trigger_api_key_dialog_for_current_provider(self):
        current_provider = self.get_current_provider_key()
        if (current_provider and current_provider != NO_SELECTION_KEY):
            self._current_provider_key_for_api_dialog = current_provider
            self._show_api_key_dialog(current_provider)
        else:
            debug_print("WideModelSelector: Cannot trigger API key dialog, no valid provider selected.")

    def get_current_model_selection_status(self) -> dict:
        """
        Retorna el estado actual de la selección para validación.
        {"model_selected": bool, "needs_api_key": bool, "api_key_set": bool, "is_valid_for_next_step": bool}
        """
        provider_key = self.get_current_provider_key()
        selected_model_id = self.get_selected_model_id()

        if provider_key == NO_SELECTION_KEY or not selected_model_id:
            return {"model_selected": False, "needs_api_key": False, "api_key_set": False, "is_valid_for_next_step": False}

        key_status = self.manager.check_api_key_status(provider_key)
        needs_key = key_status.get('needs_key', False)
        has_key = key_status.get('has_key', False)

        is_valid = True if not needs_key else has_key
        return {"model_selected": True, "needs_api_key": needs_key, "api_key_set": has_key, "is_valid_for_next_step": is_valid}

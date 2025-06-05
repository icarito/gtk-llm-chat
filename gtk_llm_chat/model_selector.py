import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib

from .chat_application import _
from .model_selection import ModelSelectionManager
from .debug_utils import debug_print

class ModelSelectorWidget(Gtk.Box):
    """
    Widget reutilizable que implementa una UI de selección de modelo con navegación
    en dos pasos (Proveedores -> Modelos) usando Adw.ViewStack.
    Ahora usa la misma lógica que WideModelSelector pero en formato vertical.
    """

    __gsignals__ = {
        'model-selected': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'api-key-status-changed': (GObject.SignalFlags.RUN_LAST, None, (str, bool, bool))
    }

    def __init__(self, manager=None, config=None, llm_client=None, show_headers=True):
        """
        Inicializa el selector de modelos.
        
        Args:
            manager: ModelSelectionManager opcional a usar. Si no se proporciona,
                   se creará uno nuevo usando config y llm_client.
            config: Configuración opcional si no se proporciona manager.
            llm_client: Cliente LLM opcional si no se proporciona manager.
            show_headers: Si mostrar los headers en las páginas (por defecto True).
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Inicializar manager
        self.manager = manager or ModelSelectionManager(config, llm_client)
        self._selected_provider_key = None
        self.show_headers = show_headers

        # Contenedor principal para apilar paneles
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_vexpand(True)

        # --- Lista de Proveedores ---
        provider_page = self._create_provider_page()
        self.stack.add_titled(provider_page, "providers", _("Providers"))

        # --- Lista de Modelos ---
        model_page = self._create_model_page()
        self.stack.add_titled(model_page, "models", _("Models"))

        # Añadir stack al widget
        self.append(self.stack)

        # Conectar señales del manager
        self.manager.connect('api-key-changed', self._on_api_key_changed)

    def _create_provider_page(self):
        """Crea la página de selección de proveedor."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_vexpand(True)

        # Header con título (solo si show_headers es True)
        if self.show_headers:
            header = Adw.HeaderBar()
            header.set_show_end_title_buttons(False)
            header.add_css_class("flat")
            header.set_title_widget(Gtk.Label(label=_("Select Provider")))
            page.append(header)

        # Lista de proveedores en una sola columna
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        self.provider_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.provider_list.add_css_class('navigation-sidebar')
        self.provider_list.connect("row-activated", self._on_provider_row_activated)
        scroll.set_child(self.provider_list)
        page.append(scroll)
        return page

    def _create_model_page(self):
        """Crea la página de selección de modelo."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_vexpand(True)

        # Header con botón atrás y título
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.add_css_class("flat")
        back_button = Gtk.Button(icon_name="go-previous-symbolic")
        back_button.connect("clicked", lambda x: self.stack.set_visible_child_name("providers"))
        header.pack_start(back_button)
        header.set_title_widget(Gtk.Label(label=_("Select Model")))
        page.append(header)

        # Banner para API key (inicialmente oculto)
        self.api_key_banner = Adw.Banner(revealed=False)
        gizmo = self.api_key_banner.get_first_child().get_first_child()
        gizmo.set_css_classes(['card'])
        self.api_button = gizmo.get_last_child()
        self.api_key_banner.connect("button-clicked", self._on_banner_button_clicked)
        page.append(self.api_key_banner)

        # Lista de modelos en una sola columna
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                     vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        self.model_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.model_list.add_css_class('navigation-sidebar')
        self.model_list.connect("row-activated", self._on_model_row_activated)
        scroll.set_child(self.model_list)
        page.append(scroll)
        return page

    def load_providers(self):
        """Carga y muestra la lista de proveedores."""
        self._clear_list_box(self.provider_list)
        
        if not self.manager.populate_providers_and_group_models():
            # Error al cargar proveedores
            row = Adw.ActionRow(title=_("No models found"))
            row.set_selectable(False)
            self.provider_list.append(row)
            return

        # Ordenar proveedores por nombre
        providers = sorted(
            self.manager.models_by_provider.keys(),
            key=lambda p: self.manager.get_provider_display_name(p).lower() if p else "local/other"
        )

        for provider_key in providers:
            display_name = self.manager.get_provider_display_name(provider_key)
            
            # Pre-cargar modelos para obtener el conteo
            models = self.manager.get_models_for_provider(provider_key)
            model_count = len(models) if models else 0
            
            # Crear fila con subtítulo mostrando el número de modelos
            row = Adw.ActionRow(title=display_name)
            if model_count > 0:
                row.set_subtitle(f"{model_count} {_('models')}")
            else:
                # Verificar si necesita API key para mostrar mensaje apropiado
                key_status = self.manager.check_api_key_status(provider_key)
                if key_status.get('needs_key', False) and not key_status.get('has_key', False):
                    row.set_subtitle(_("API key required"))
                else:
                    row.set_subtitle(_("No models"))
            
            row.set_activatable(True)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.provider_key = provider_key
            debug_print(f"DEBUG: Created row for provider '{provider_key}' (type: {type(provider_key)}) with {model_count} models")
            self.provider_list.append(row)

    def _clear_list_box(self, list_box):
        """Elimina todas las filas de un Gtk.ListBox."""
        child = list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            list_box.remove(child)
            child = next_child

    def _on_provider_row_activated(self, list_box, row):
        """Manejador cuando se selecciona un proveedor."""
        # Usar hasattr para distinguir entre "no tiene atributo" vs "atributo es None"
        if hasattr(row, 'provider_key'):
            provider_key = row.provider_key
            debug_print(f"DEBUG: Row activated - provider_key: {provider_key} (type: {type(provider_key)})")
            debug_print(f"DEBUG: Calling _populate_model_list for {provider_key}")
            self._populate_model_list(provider_key)
            debug_print(f"DEBUG: Setting stack to 'models' page")
            self.stack.set_visible_child_name("models")
        else:
            debug_print(f"DEBUG: Row does not have provider_key attribute, no action taken")

    def _populate_model_list(self, provider_key):
        """Puebla la lista de modelos para el proveedor seleccionado."""
        debug_print(f"DEBUG: _populate_model_list called with provider_key: {provider_key} (type: {type(provider_key)})")
        self._clear_list_box(self.model_list)
        self._selected_provider_key = provider_key
        
        # DEBUG: Imprimir información del proveedor
        debug_print(f"DEBUG: Proveedor seleccionado: {provider_key}")
        
        # Obtener modelos primero para determinar si necesita API key
        models = self.manager.get_models_for_provider(provider_key)
        debug_print(f"DEBUG: Modelos encontrados para {provider_key}: {len(models) if models else 0}")
        if models:
            debug_print(f"DEBUG: Primeros 3 modelos: {[getattr(m, 'model_id', 'NO_ID') for m in models[:3]]}")
        
        # Actualizar banner de API key
        key_status = self.manager.check_api_key_status(provider_key)
        debug_print(f"DEBUG: Key status para {provider_key}: {key_status}")
        
        # Si no hay modelos y el proveedor no es "local/other", asumir que necesita API key
        needs_api_key = key_status.get('needs_key', False)
        if not models and provider_key not in [None, '', 'local', 'local/other', 'ollama']:
            debug_print(f"DEBUG: No hay modelos para {provider_key}, asumiendo que necesita API key")
            needs_api_key = True
        
        if needs_api_key:
            debug_print(f"DEBUG: Proveedor {provider_key} necesita API key")
            if key_status.get('has_key', False):
                debug_print(f"DEBUG: API key ya configurada para {provider_key}")
                self.api_key_banner.set_title(_("API Key is configured"))
                self.api_key_banner.set_button_label(_("Change Key"))
                self.api_button.remove_css_class("error")
                self.api_button.add_css_class("success")
            else:
                debug_print(f"DEBUG: API key NO configurada para {provider_key}")
                self.api_key_banner.set_title(_("API Key Required"))
                self.api_key_banner.set_button_label(_("Set Key"))
                self.api_button.remove_css_class("success")
                self.api_button.add_css_class("error")
            debug_print(f"DEBUG: Mostrando banner para {provider_key}")
            self.api_key_banner.set_revealed(True)
        else:
            debug_print(f"DEBUG: Proveedor {provider_key} NO necesita API key, ocultando banner")
            self.api_key_banner.set_revealed(False)

        # Emitir señal de cambio de estado de API key
        has_key = key_status.get('has_key', False)
        self.emit('api-key-status-changed', provider_key, needs_api_key, has_key)

        if not models:
            # Si no hay modelos pero el proveedor requiere API key, mostrar el banner
            if needs_api_key and not has_key:
                # El banner ya está configurado arriba, solo añadir mensaje explicativo
                debug_print(f"DEBUG: Mostrando mensaje de API key requerida")
                row = Adw.ActionRow(title=_("No models available"))
                row.set_subtitle(_("Configure an API key to access models from this provider"))
                row.set_selectable(False)
                self.model_list.append(row)
            else:
                debug_print(f"DEBUG: Mostrando mensaje genérico de no modelos")
                row = Adw.ActionRow(title=_("No models found for this provider"))
                row.set_selectable(False)
                self.model_list.append(row)
            return

        current_model_id = None
        if self.manager.llm_client:
            current_model_id = self.manager.llm_client.get_model_id()
        if not current_model_id:
            current_model_id = self.manager.config.get('model')

        active_row = None
        for model_obj in models:
            model_id = getattr(model_obj, 'model_id', None)
            model_name = getattr(model_obj, 'name', None) or model_id
            if model_id:
                row = Adw.ActionRow(title=model_name)
                row.set_activatable(True)
                row.model_id = model_id
                self.model_list.append(row)
                if model_id == current_model_id:
                    active_row = row

        if active_row:
            self.model_list.select_row(active_row)

    def _on_model_row_activated(self, list_box, row):
        """Manejador cuando se selecciona un modelo."""
        model_id = getattr(row, 'model_id', None)
        if model_id:
            success = True
            if self.manager.llm_client:
                success = self.manager.llm_client.set_model(model_id)
            if success:
                self.manager.config['model'] = model_id
                self.emit('model-selected', model_id)
                debug_print(f"ModelSelector: Model '{model_id}' selected.")

    def _on_banner_button_clicked(self, banner):
        """Manejador para el clic del botón en el banner de API key."""
        provider_key = getattr(self, '_selected_provider_key', None)
        if not provider_key:
            return

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

        dialog.set_extra_child(key_entry)
        dialog.connect("response", self._on_api_key_dialog_response, provider_key, key_entry)
        dialog.present()

    def _on_api_key_dialog_response(self, dialog, response_id, provider_key, key_entry):
        """Manejador de la respuesta del diálogo de API key."""
        if response_id == "set":
            api_key = key_entry.get_text()
            if api_key:
                self.manager.set_api_key(provider_key, api_key)
        dialog.destroy()

    def _on_api_key_changed(self, manager, provider_key):
        """Manejador cuando cambia una API key."""
        debug_print(f"ModelSelector: API key changed for provider '{provider_key}', updating UI.")
        
        # Save current selection to restore after reload
        current_provider = self._selected_provider_key
        
        # Reload dynamic models for new API key
        try:
            self.manager.reload_dynamic_models_only()
            debug_print(f"ModelSelector: Dynamic models reloaded after API key change for '{provider_key}'")
        except Exception as e:
            debug_print(f"ModelSelector: Error reloading dynamic models: {e}")
        
        # Update UI if this provider is currently selected
        if current_provider == provider_key:
            self._populate_model_list(provider_key)
        
        # Update API key status
        key_status = manager.check_api_key_status(provider_key)
        if key_status.get('has_key', False):
            self.api_key_banner.set_title(_("API Key is configured"))
            self.api_key_banner.set_button_label(_("Change Key"))
            self.api_button.remove_css_class("error")
            self.api_button.add_css_class("success")
        else:
            self.api_key_banner.set_title(_("API Key Required"))
            self.api_key_banner.set_button_label(_("Set Key"))
            self.api_button.remove_css_class("success")
            self.api_button.add_css_class("error")

if __name__ == '__main__':
    import sys
    from .model_selection import ModelSelectionManager
    
    class TestApp(Adw.Application):
        def __init__(self):
            super().__init__(application_id="org.example.ModelSelectorTest")
            
        def do_activate(self):
            # Crear ventana principal
            window = Adw.ApplicationWindow(application=self)
            window.set_title(_("Model Selector Test"))
            window.set_default_size(600, 500)
            
            # Crear configuración mock
            mock_config = {}
            
            # Crear el widget selector
            selector = ModelSelectorWidget(config=mock_config)
            
            # Cargar proveedores
            selector.load_providers()
            
            # Conectar señal de modelo seleccionado
            def on_model_selected(widget, model_id):
                debug_print(f"Modelo seleccionado: {model_id}")
            
            selector.connect('model-selected', on_model_selected)
            
            # Agregar a la ventana
            window.set_content(selector)
            window.present()
    
    app = TestApp()
    app.run(sys.argv)

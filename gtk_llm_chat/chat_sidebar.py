import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib, Gdk
import llm
from collections import defaultdict
import os
import pathlib
import json

from chat_application import _

def debug_print(*args):
    if DEBUG:
        print(*args)
    

# Usaremos None para representar la ausencia de 'needs_key'
LOCAL_PROVIDER_KEY = None
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
        self.models_by_provider = defaultdict(list)
        self._selected_provider_key = LOCAL_PROVIDER_KEY
        self._models_loaded = False  # Flag para saber si los modelos ya se cargaron

        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs) # Sin espacio entre header y stack

        self.set_margin_top(0) # Sin margen superior, el header lo maneja
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Crear Gtk.Stack con transición rotate-left-right
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.ROTATE_LEFT_RIGHT)
        self.stack.set_vexpand(True)

        # --- Página 1: Grupo de acciones ---
        actions_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        actions_group = Adw.PreferencesGroup(title=_("Actions"))

        # Añadir un header con título centrado para la página de acciones
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        header.add_css_class("flat")
        header.set_title_widget(Gtk.Label(label=_("Settings")))
        actions_page.append(header)

        # Filas de acciones con íconos simbólicos
        # Delete Conversation - uso de ícono "user-trash-symbolic"
        delete_row = Adw.ActionRow(title=_("Delete Conversation"))
        delete_row.add_css_class("destructive")
        delete_row.set_icon_name("user-trash-symbolic")
        delete_row.set_activatable(True)  # Hacerla accionable
        delete_row.connect("activated", lambda x: self.get_root().get_application().on_delete_activate(None, None))
        actions_group.add(delete_row)

        # Modelo - uso de ícono de IA "preferences-system-symbolic"
        model_id = self.config.get('model') or self.llm_client.get_model_id() if self.llm_client else None
        self.model_row = Adw.ActionRow(title=_("Change Model"),
                                       subtitle="Provider: " + llm_client.get_provider_for_model(model_id) if llm_client else None)
        self.model_row.set_icon_name("brain-symbolic")
        # NO establecer subtítulo aquí, lo hará model-loaded
        self.model_row.set_activatable(True)  # Hacerla accionable
        self.model_row.connect("activated", self._on_model_button_clicked)
        actions_group.add(self.model_row)

        actions_page.append(actions_group)
        
        # Grupo separado para About
        about_group = Adw.PreferencesGroup()
        # About - uso de ícono "help-about-symbolic" en su propio grupo
        about_row = Adw.ActionRow(title=_("About"))
        about_row.set_icon_name("help-about-symbolic")
        about_row.set_activatable(True)  # Hacerla accionable
        about_row.connect("activated", lambda x: self.get_root().get_application().on_about_activate(None, None))
        about_group.add(about_row)
        actions_page.append(about_group)
        self.stack.add_titled(actions_page, "actions", _("Actions"))

        # --- Nueva ActionRow para Parámetros del Modelo en la página de Acciones ---
        parameters_action_row = Adw.ActionRow(title=_("Model Parameters"))
        parameters_action_row.set_icon_name("brain-augmented-symbolic") # O un ícono más adecuado
        parameters_action_row.set_activatable(True)
        parameters_action_row.connect("activated", self._on_model_parameters_button_clicked)
        actions_group.add(parameters_action_row) # Añadir al primer grupo de acciones

        # --- Página 2: Lista de Proveedores ---
        provider_page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Añadir header para la página de proveedores con botón atrás simbólico
        provider_header = Adw.HeaderBar()
        provider_header.set_show_end_title_buttons(False)
        provider_header.add_css_class("flat")
        back_button = Gtk.Button(icon_name="go-previous-symbolic")
        back_button.connect("clicked", lambda x: self.stack.set_visible_child_name("actions"))
        provider_header.pack_start(back_button)
        provider_header.set_title_widget(Gtk.Label(label=_("Select Provider")))
        provider_page_box.append(provider_header)
        
        provider_list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                  vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                                  vexpand=True)
        self.provider_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.provider_list.add_css_class('navigation-sidebar')
        self.provider_list.connect("row-activated", self._on_provider_row_activated)
        provider_list_scroll.set_child(self.provider_list)
        provider_page_box.append(provider_list_scroll)
        self.stack.add_titled(provider_page_box, "providers", _("Providers"))

        # --- Página 3: Lista de Modelos ---
        model_page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Añadir header para la página de modelos con botón atrás simbólico
        model_header = Adw.HeaderBar()
        model_header.set_show_end_title_buttons(False)
        model_header.add_css_class("flat")
        back_button = Gtk.Button(icon_name="go-previous-symbolic")
        back_button.connect("clicked", lambda x: self.stack.set_visible_child_name("providers"))
        model_header.pack_start(back_button)
        model_header.set_title_widget(Gtk.Label(label=_("Select Model")))
        model_page_box.append(model_header)
        
        # Banner para API key (inicialmente oculto)
        self.api_key_banner = Adw.Banner(revealed=False)
        gizmo = self.api_key_banner.get_first_child().get_first_child()
        gizmo.set_css_classes(['card'])
        self.api_button = gizmo.get_last_child()

        self.api_key_banner.connect("button-clicked", self._on_banner_button_clicked)
        model_page_box.append(self.api_key_banner)
        
        # ScrolledWindow para la lista de modelos
        model_list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                               vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                               vexpand=True)
        self.model_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.model_list.add_css_class('navigation-sidebar')
        self.model_list.connect("row-activated", self._on_model_row_activated)
        model_list_scroll.set_child(self.model_list)
        model_page_box.append(model_list_scroll)
        
        self.stack.add_titled(model_page_box, "models", _("Models"))

        # --- Página 4: Parámetros del Modelo ---
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

        # No cargamos los modelos aquí - se cargarán bajo demanda 
        # cuando el usuario haga clic en el botón de modelo
        # Sin embargo, programaremos la carga para que ocurra poco después de la inicialización
        # para evitar bloquear la UI durante el arranque
        GLib.timeout_add(500, self._delayed_model_load)

        # Si ya tenemos llm_client, programar la actualización del modelo
        self.llm_client.connect('model-loaded', self._on_model_loaded)
        if self.llm_client:
            # Programar la actualización con el modelo actual
            GLib.idle_add(self.update_model_button)

        # Volver a la primera pantalla al colapsar el sidebar
        def _on_sidebar_toggled(self, toggled):
            if toggled:
                # Asegurar que los modelos se carguen si no lo han hecho
                if not self._models_loaded:
                    self._populate_providers_and_group_models()
                    self._models_loaded = True
            else:
                self.stack.set_visible_child_name("actions")

        # Conectar el evento de colapsar el sidebar
        self.connect("notify::visible", lambda obj, pspec: self._on_sidebar_toggled(self.get_visible()))
        
    def _delayed_model_load(self):
        """Carga los modelos después de un breve retraso para no bloquear la UI durante el arranque."""
        if not self._models_loaded:
            debug_print("ChatSidebar: Cargando modelos en segundo plano...")
            self._populate_providers_and_group_models()
            self._models_loaded = True
        return False  # No repetir el timeout

    def _get_provider_display_name(self, provider_key):
        """Obtiene un nombre legible para la clave del proveedor."""
        if provider_key == LOCAL_PROVIDER_KEY: # Comparar con None
            return _("Local/Other")
        return provider_key.replace('-', ' ').title().removeprefix('Llm ') if provider_key else _("Unknown Provider")

    def _clear_list_box(self, list_box):
        """Elimina todas las filas de un Gtk.ListBox."""
        child = list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            list_box.remove(child)
            child = next_child

    def _populate_providers_and_group_models(self):
        """Agrupa modelos por needs_key y puebla la lista de proveedores usando introspección de plugins para descubrir todos los posibles, incluso si falta la key."""
        from llm.plugins import pm, load_plugins
        self.models_by_provider.clear()
        self._provider_to_needs_key = {}
        try:
            # 1. Asegurar que los plugins están cargados, sin forzar recarga
            import llm.plugins
            if not hasattr(llm.plugins, '_loaded') or not llm.plugins._loaded:
                # Solo cargar si no están ya cargados
                load_plugins()
                debug_print("ChatSidebar: Plugins cargados correctamente")
            else:
                debug_print("ChatSidebar: Plugins ya estaban cargados, omitiendo carga")
            all_possible_models = []
            
            # Función de registro para capturar modelos durante la invocación del hook
            def register_model(model, async_model=None, aliases=None):
                all_possible_models.append(model)
            
            # Llamar explícitamente al hook de registro de modelos
            pm.hook.register_models(register=register_model)
            
            # Log para debug
            debug_print(f"Encontrados {len(all_possible_models)} modelos posibles durante introspección")

            # 2. Obtener plugins con hook 'register_models'
            all_plugins = llm.get_plugins()
            plugins_with_models = [plugin for plugin in all_plugins if 'register_models' in plugin['hooks']]
            providers_set = {plugin['name']: plugin for plugin in plugins_with_models}
            
            debug_print(f"Plugins con modelos: {list(providers_set.keys())}")

            # 3. Construir mapping provider_key -> needs_key y agrupar modelos
            for provider_key in providers_set.keys():
                found_needs_key = None
                provider_models = []
                
                for model_obj in all_possible_models:
                    model_needs_key = getattr(model_obj, 'needs_key', None)
                    # Heurística: si el provider_key es substring o prefijo del needs_key o viceversa
                    if model_needs_key and (provider_key in model_needs_key or model_needs_key in provider_key):
                        found_needs_key = model_needs_key
                        provider_models.append(model_obj)
                    elif provider_key.lower() in getattr(model_obj, 'model_id', '').lower():
                        # Heurística adicional: si el provider está en el ID del modelo
                        provider_models.append(model_obj)
                
                # Agregar los modelos encontrados para este proveedor
                if provider_models:
                    self.models_by_provider[provider_key] = provider_models
                    debug_print(f"Proveedor {provider_key}: {len(provider_models)} modelos")
                
                if found_needs_key:
                    self._provider_to_needs_key[provider_key] = found_needs_key
                else:
                    # Si no hay modelos (por falta de key), usar heurística: quitar 'llm-' si existe
                    self._provider_to_needs_key[provider_key] = provider_key.replace('llm-', '')

            # 4. Limpiar y poblar la lista de proveedores
            self._clear_list_box(self.provider_list)
            def sort_key(p_key):
                return self._get_provider_display_name(p_key).lower() if p_key else "local/other"
            sorted_provider_keys = sorted(providers_set.keys(), key=sort_key)
            
            if not sorted_provider_keys:
                # Si no hay proveedores, intentar obtener modelos directamente
                all_models = llm.get_models()
                debug_print(f"No se encontraron proveedores, intentando obtener modelos directamente: {len(all_models)} modelos")
                
                # Agrupar modelos por proveedor
                providers_from_models = defaultdict(list)
                for model in all_models:
                    provider = getattr(model, 'needs_key', None) or LOCAL_PROVIDER_KEY
                    providers_from_models[provider].append(model)
                
                # Si hay modelos, usarlos para poblar proveedores
                if providers_from_models:
                    self.models_by_provider = providers_from_models
                    sorted_provider_keys = sorted(providers_from_models.keys(), key=sort_key)
                    
                    for provider_key in sorted_provider_keys:
                        display_name = self._get_provider_display_name(provider_key)
                        row = Adw.ActionRow(title=display_name)
                        row.set_activatable(True)
                        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                        row.provider_key = provider_key
                        self.provider_list.append(row)
                    return
                
                # Si todavía no hay proveedores, mostrar mensaje de error
                row = Adw.ActionRow(title=_("No models found"), selectable=False)
                self.provider_list.append(row)
                return
                
            # Si hemos llegado aquí, tenemos proveedores de la primera forma
            for provider_key in sorted_provider_keys:
                display_name = self._get_provider_display_name(provider_key)
                row = Adw.ActionRow(title=display_name)
                row.set_activatable(True)
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.provider_key = provider_key
                self.provider_list.append(row)
        except Exception as e:
            print(f"Error getting or processing models/plugins: {e}")
            import traceback
            traceback.print_exc()

    def _populate_model_list(self, provider_key):
        """Puebla la lista de modelos y actualiza el banner de API key, usando introspección para mostrar todos los modelos posibles."""
        self._clear_list_box(self.model_list)
        self._selected_provider_key = provider_key

        # --- Actualizar y Mostrar/Ocultar Banner de API Key ---
        if provider_key != LOCAL_PROVIDER_KEY:  # Si se necesita key
            self._update_api_key_banner(provider_key)  # Actualizar contenido del banner
            self.api_key_banner.set_revealed(True)  # Mostrar banner
        else:
            self.api_key_banner.set_revealed(False)  # Ocultar banner si es local

        # --- Poblar Modelos usando el cliente LLM si está disponible ---
        if getattr(self, 'llm_client', None) and hasattr(self.llm_client, 'get_all_models'):
            try:
                # Usar el método del cliente para obtener los modelos sin recargar plugins
                debug_print("Obteniendo modelos desde llm_client.get_all_models()")
                all_models = self.llm_client.get_all_models()
                
                # Agrupar modelos por proveedor si no lo hemos hecho antes
                if not self.models_by_provider:
                    # Inicializar grouping
                    provider_models = defaultdict(list)
                    for model in all_models:
                        provider = getattr(model, 'needs_key', None) or LOCAL_PROVIDER_KEY
                        provider_models[provider].append(model)
                    self.models_by_provider = provider_models
            except Exception as e:
                debug_print(f"Error al obtener modelos desde llm_client: {e}")
                # Caer en el comportamiento normal si falla
        
        # --- Poblar Modelos usando self.models_by_provider (ya incluye todos los posibles) ---
        models = self.models_by_provider.get(provider_key, [])
        if not models:
            row = Adw.ActionRow(title=_('No models found for this provider'), selectable=False)
            self.model_list.append(row)
            return

        models = sorted(models, key=lambda m: getattr(m, 'name', getattr(m, 'model_id', '')).lower())

        # Obtener el modelo actual de la conversación desde LLMClient
        current_model_id = None
        if self.llm_client:
            current_model_id = self.llm_client.get_model_id()
        if not current_model_id:
            current_model_id = self.config.get('model')

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

    def _get_provider_needs_key(self, provider_key):
        """Busca el valor de needs_key real para un provider_key dado, usando los modelos cargados."""
        all_models = llm.get_models()
        for model in all_models:
            if getattr(model, 'needs_key', None) == provider_key:
                return getattr(model, 'needs_key', None)
        # Si no se encuentra, devolver el provider_key tal cual
        return provider_key

    def _get_needs_key_map(self):
        """Devuelve un mapeo {provider_key: needs_key} usando el mapping calculado en _populate_providers_and_group_models."""
        if hasattr(self, '_provider_to_needs_key'):
            return self._provider_to_needs_key
        # Fallback legacy
        needs_key_map = {}
        all_models = llm.get_models()
        for model in all_models:
            nk = getattr(model, 'needs_key', None)
            if nk:
                needs_key_map[nk] = nk
        needs_key_map[None] = None
        return needs_key_map

    def _get_keys_json(self):
        """Lee y cachea keys.json solo una vez por ciclo de UI, con debug."""
        if not hasattr(self, '_cached_keys_json'):
            keys_path = os.path.join(llm.user_dir(), "keys.json")
            debug_print(f"Leyendo keys.json desde: {keys_path}")
            if os.path.exists(keys_path):
                try:
                    with open(keys_path, 'r') as f:
                        self._cached_keys_json = json.load(f)
                        debug_print(f"Contenido de keys.json: {self._cached_keys_json}")
                except Exception as e:
                    debug_print(f"Error leyendo/parsing keys.json: {e}")
                    self._cached_keys_json = {}
            else:
                debug_print("keys.json no existe, usando dict vacío")
                self._cached_keys_json = {}
        return self._cached_keys_json

    def _invalidate_keys_cache(self):
        if hasattr(self, '_cached_keys_json'):
            del self._cached_keys_json

    def _update_api_key_banner(self, provider_key):
        """Actualiza el banner de API key: solo pide la clave si falta en keys.json, y muestra verde si ya existe. Debug detallado."""
        debug_print(f"Actualizando banner de API key para el proveedor: {provider_key}")
        if not self.api_key_banner:
            debug_print("El banner de API key no está inicializado.")
            return
        if provider_key is None:
            self.api_key_banner.set_revealed(False)
            debug_print("Ocultando banner porque el proveedor es None o Local.")
            return

        needs_key_map = self._get_needs_key_map()
        real_key = needs_key_map.get(provider_key, provider_key)
        debug_print(f"Provider seleccionado: {provider_key} | needs_key usado: {real_key}")

        stored_keys = self._get_keys_json()
        key_exists_in_file = real_key in stored_keys and bool(stored_keys[real_key])
        debug_print(f"¿Clave existe en keys.json para {real_key}? {key_exists_in_file}")

        if key_exists_in_file:
            self.api_key_banner.set_title(_("API Key is configured"))
            self.api_key_banner.set_button_label(_("Change Key"))
            self.api_button.remove_css_class("error")
            self.api_button.add_css_class("success")
            self.api_key_banner.set_revealed(True)
        else:
            self.api_key_banner.set_title(_("API Key Required"))
            self.api_key_banner.set_button_label(_("Set Key"))
            self.api_button.remove_css_class("success")
            self.api_button.add_css_class("error")
            self.api_key_banner.set_revealed(True)

    def _on_model_button_clicked(self, row):
        """Handler para cuando se activa la fila del modelo."""
        # Solo cargar los modelos la primera vez que se haga clic
        if not self._models_loaded:
            self._populate_providers_and_group_models()
            self._models_loaded = True
        
        # Mostrar la lista de proveedores
        self.stack.set_visible_child_name("providers")

    def _on_provider_row_activated(self, list_box, row):
        """Manejador cuando se selecciona un proveedor."""
        provider_key = getattr(row, 'provider_key', 'missing')
        if provider_key != 'missing':
            self._populate_model_list(provider_key)
            self.stack.set_visible_child_name("models")

    # Actualizar el modelo en la base de datos al cambiarlo
    def _on_model_row_activated(self, list_box, row):
        model_id = getattr(row, 'model_id', None)
        if model_id:
            # Intentar cambiar el modelo, solo continuar si fue exitoso
            # No es necesario actualizar manualmente - la señal model-loaded lo hará
            success = self.llm_client.set_model(model_id) if self.llm_client else False
            if success:
                self.config['model'] = model_id
                # Volver a la página de acciones
                self.stack.set_visible_child_name("actions")
                # Actualizar el modelo en la base de datos si hay una conversación actual
                cid = self.llm_client.get_conversation_id() if self.llm_client else None
                if cid:
                    self.llm_client.chat_history.update_conversation_model(cid, model_id)
                
                # Notificar a la aplicación que debe ocultar el sidebar
                # Primero retrocedemos al panel principal
                self.stack.set_visible_child_name("actions")
                # Luego cerramos todo el sidebar
                window = self.get_root()
                if window and hasattr(window, 'split_view'):
                    # Damos un pequeño tiempo para que se vea la transición
                    GLib.timeout_add(100, lambda: window.split_view.set_show_sidebar(False))

    def _on_banner_button_clicked(self, banner):
        """Manejador para el clic del botón en el Adw.Banner."""
        provider_key = self._selected_provider_key
        if provider_key is None or provider_key == LOCAL_PROVIDER_KEY:
            print("Error: Banner button clicked but provider key is local or None.")
            return

        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            heading=_("Enter API Key"),
            body=f"{_('Enter the API key for')} {self._get_provider_display_name(provider_key)}:",
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("set", _("Set Key"))
        dialog.set_response_appearance("set", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("set")

        key_entry = Gtk.Entry(
            hexpand=True,
            placeholder_text=_("Paste your API key here")
        )
        # Conectar señal activate para que Enter funcione
        key_entry.connect("activate", lambda entry: dialog.response("set"))

        clamp = Adw.Clamp(maximum_size=400)
        clamp.set_child(key_entry)
        dialog.set_extra_child(clamp)

        dialog.connect("response", self._on_api_key_dialog_response, provider_key, key_entry)
        dialog.present()

    def _on_api_key_dialog_response(self, dialog, response_id, provider_key, key_entry):
        """Manejador para la respuesta del diálogo de API key. Guarda la clave usando el identificador needs_key real y refresca el cache y la UI de modelos."""
        if response_id == "set":
            api_key = key_entry.get_text()
            if api_key:
                try:
                    keys_path = os.path.join(llm.user_dir(), "keys.json")
                    keys_path_obj = pathlib.Path(keys_path)
                    keys_path_obj.parent.mkdir(parents=True, exist_ok=True)

                    default_keys = {"// Note": "This file stores secret API credentials. Do not share!"}
                    current_keys = default_keys.copy()
                    newly_created = False

                    if keys_path_obj.exists():
                        try:
                            current_keys = json.loads(keys_path_obj.read_text())
                            if not isinstance(current_keys, dict):
                                current_keys = default_keys.copy()
                        except json.JSONDecodeError:
                            current_keys = default_keys.copy()
                    else:
                        newly_created = True

                    needs_key_map = self._get_needs_key_map()
                    real_key = needs_key_map.get(provider_key, provider_key)
                    debug_print(f"Guardando API key para {real_key} (provider original: {provider_key})")
                    current_keys[real_key] = api_key

                    keys_path_obj.write_text(json.dumps(current_keys, indent=2) + "\n")

                    if newly_created:
                        try:
                            keys_path_obj.chmod(0o600)
                        except OSError as chmod_err:
                            print(f"Error setting permissions for {keys_path}: {chmod_err}")

                    print(f"API Key set for {real_key} in {keys_path}")
                    self._invalidate_keys_cache()
                    self._update_api_key_banner(provider_key)
                    # --- Recargar lista de modelos y proveedores para reflejar los nuevos modelos disponibles ---
                    self._populate_providers_and_group_models()
                    self._populate_model_list(provider_key)

                except Exception as e:
                    print(f"Error saving API key for {provider_key} to {keys_path}: {e!r}")
            else:
                print(f"API Key input empty for {provider_key}. No changes made.")

        dialog.destroy()

    def _on_temperature_changed(self, adjustment):
        """Manejador para cuando cambia el valor de la temperatura."""
        temperature = adjustment.get_value()
        self.config['temperature'] = temperature
        if self.llm_client and hasattr(self.llm_client, 'set_temperature'):
             try:
                  self.llm_client.set_temperature(temperature)
             except Exception as e:
                  print(f"Error setting temperature in LLM client: {e}")
        self._update_temperature_subtitle() # Actualizar subtítulo de temperatura

    def _update_temperature_subtitle(self):
        """Actualiza el subtítulo de la fila de temperatura con el valor actual."""
        if hasattr(self, 'adjustment') and hasattr(self, 'temperature_row'):
            temp_value = self.adjustment.get_value()
            self.temperature_row.set_subtitle(f"{temp_value:.2f}")
        else:
            debug_print("ChatSidebar: Saltando actualización de subtítulo de temperatura (adjustment o temperature_row no inicializados).")

    def update_model_button(self):
        """Actualiza la información del modelo seleccionado en la interfaz."""
        if not self.llm_client:
            return
            
        current_model_id = self.llm_client.get_model_id()
            
        # Actualizar la configuración con el modelo actual
        self.config['model'] = current_model_id
        
        # Si los modelos aún no se han cargado, cargarlos para poder buscar el nombre 
        if not self._models_loaded:
            self._populate_providers_and_group_models()
            self._models_loaded = True

        
        self.model_row.set_subtitle(f"Provider: {self.llm_client.get_provider_for_model(current_model_id) or 'Unknown Provider'}")
        self._update_system_prompt_row_subtitle() # Asegurar que el subtítulo del system prompt también se actualice

    def _on_model_loaded(self, client, model_id):
        """Callback para la señal model-loaded del LLMClient."""
        debug_print(f"ChatSidebar: Model loaded: {model_id}")

        # Obtener el proveedor del modelo cargado
        provider_name = "Unknown Provider"
        if self.llm_client:
            provider_name = self.llm_client.get_provider_for_model(model_id) or "Unknown Provider"
        
        self.model_row.set_subtitle(f"Provider: {provider_name}")

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

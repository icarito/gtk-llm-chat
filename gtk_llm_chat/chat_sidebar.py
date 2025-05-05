import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib
import llm
from collections import defaultdict
import os
import pathlib
import json

try:
    from .chat_application import _
except ImportError:
    def _(s): return s

# Usaremos None para representar la ausencia de 'needs_key'
LOCAL_PROVIDER_KEY = None
PROVIDER_LIST_NAME = "providers"
MODEL_LIST_NAME = "models"
# Ya no necesitamos API_KEY_ROW_NAME

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
        # self.api_key_row = None # Ya no se usa

        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs) # Sin espacio entre header y stack

        self.set_margin_top(0) # Sin margen superior, el header lo maneja
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # --- Stack y Navegación ---
        self.view_stack = Adw.ViewStack()
        self.view_title = Adw.ViewSwitcherTitle(stack=self.view_stack, title=_("Select Provider"))
        switcher_header = Adw.HeaderBar()
        switcher_header.set_title_widget(self.view_title)
        switcher_header.add_css_class('flat')
        switcher_header.set_show_end_title_buttons(False)
        self.append(switcher_header)

        # --- Página 1: Lista de Proveedores ---
        provider_list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                  vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        self.provider_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.provider_list.add_css_class('navigation-sidebar') # Estilo Adwaita
        self.provider_list.connect("row-activated", self._on_provider_row_activated)
        provider_list_scroll.set_child(self.provider_list)
        self.view_stack.add_titled(provider_list_scroll, PROVIDER_LIST_NAME, _("Providers"))

        # --- Página 2: Banner de API Key + Lista de Modelos ---
        # Usar un Box vertical para contener el Banner y la ScrolledWindow
        model_page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Crear el Banner (inicialmente oculto)
        self.api_key_banner = Adw.Banner(revealed=False)
        self.api_key_banner.connect("button-clicked", self._on_banner_button_clicked)
        model_page_box.append(self.api_key_banner)

        # Crear ScrolledWindow y ListBox para los modelos
        model_list_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                               vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                               vexpand=True) # Permitir que la lista ocupe espacio
        self.model_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.model_list.add_css_class('navigation-sidebar')
        self.model_list.connect("row-activated", self._on_model_row_activated)
        model_list_scroll.set_child(self.model_list)
        model_page_box.append(model_list_scroll) # Añadir lista debajo del banner

        # Añadir el Box contenedor como la página del stack
        self.view_stack.add_titled(model_page_box, MODEL_LIST_NAME, _("Models")) # Título se actualizará

        self.view_stack.set_vexpand(True)
        self.append(self.view_stack)

        # --- Poblar datos iniciales ---
        self._populate_providers_and_group_models()

        # --- Fila para ajustar la temperatura ---
        prefs_group_temp = Adw.PreferencesGroup()
        self.append(prefs_group_temp)
        self.temperature_row = Adw.ActionRow(title=_("Temperature"))
        initial_temp = self.config.get('temperature', 0.7)
        self.adjustment = Gtk.Adjustment(value=initial_temp, lower=0.0, upper=2.0, step_increment=0.1, page_increment=0.2)
        self.adjustment.connect("value-changed", self._on_temperature_changed)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.adjustment, digits=1, value_pos=Gtk.PositionType.RIGHT)
        scale.set_hexpand(True)
        self.temperature_row.add_suffix(scale)
        self.temperature_row.set_activatable_widget(scale)
        prefs_group_temp.add(self.temperature_row)

        # --- Estado Inicial ---
        GLib.idle_add(self._set_initial_state)


    def set_llm_client(self, llm_client):
        """Permite establecer el cliente LLM después de la inicialización."""
        self.llm_client = llm_client

    def _get_provider_display_name(self, provider_key):
        """Obtiene un nombre legible para la clave del proveedor."""
        if provider_key == LOCAL_PROVIDER_KEY: # Comparar con None
            return _("Local/Other")
        return provider_key.replace('-', ' ').title() if provider_key else _("Unknown Provider")

    def _clear_list_box(self, list_box):
        """Elimina todas las filas de un Gtk.ListBox."""
        child = list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            list_box.remove(child)
            child = next_child

    def _populate_providers_and_group_models(self):
        """Obtiene modelos, los agrupa por proveedor y puebla la lista de proveedores."""
        self.models_by_provider.clear()
        providers_set = set()

        try:
            all_models = llm.get_models()
            if not all_models:
                print("Warning: llm.get_models() returned empty list.")
                return

            for model_obj in all_models:
                provider_key = getattr(model_obj, 'needs_key', None) or LOCAL_PROVIDER_KEY
                providers_set.add(provider_key)
                self.models_by_provider[provider_key].append(model_obj)

        except Exception as e:
            print(f"Error getting or processing models: {e}")
            return

        self._clear_list_box(self.provider_list)
        def sort_key(p_key):
            if p_key is None: return ""
            return self._get_provider_display_name(p_key).lower()

        sorted_providers = sorted(list(providers_set), key=sort_key)

        if not sorted_providers:
             row = Adw.ActionRow(title=_("No models found"), selectable=False)
             self.provider_list.append(row)
             return

        for provider_key in sorted_providers:
            row = Adw.ActionRow(title=self._get_provider_display_name(provider_key), activatable=True)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.provider_key = provider_key
            self.provider_list.append(row)

    def _populate_model_list(self, provider_key):
        """Puebla la lista de modelos y actualiza el banner de API key."""
        self._clear_list_box(self.model_list)
        self._selected_provider_key = provider_key
        # self.api_key_row = None # Ya no se usa

        # --- Actualizar y Mostrar/Ocultar Banner de API Key ---
        if provider_key != LOCAL_PROVIDER_KEY: # Si se necesita key
            self._update_api_key_banner(provider_key) # Actualizar contenido del banner
            self.api_key_banner.set_revealed(True) # Mostrar banner
        else:
            self.api_key_banner.set_revealed(False) # Ocultar banner si es local

        # --- Poblar Modelos ---
        models = self.models_by_provider.get(provider_key, [])
        models.sort(key=lambda m: getattr(m, 'name', getattr(m, 'model_id', '')).lower())

        current_model_id = self.config.get('model')
        active_row = None

        if not models:
             # Mostrar mensaje solo si NO hay banner visible (proveedor local sin modelos)
             if not self.api_key_banner.get_revealed():
                  row = Adw.ActionRow(title=_("No models found for this provider"), selectable=False)
                  self.model_list.append(row)
             return

        for model_obj in models:
            model_id = getattr(model_obj, 'model_id', None)
            model_name = getattr(model_obj, 'name', None) or model_id
            if model_id:
                row = Adw.ActionRow(title=model_name, activatable=True)
                row.model_id = model_id
                self.model_list.append(row)
                if model_id == current_model_id:
                    active_row = row

        if active_row:
            self.model_list.select_row(active_row)

    def _update_api_key_banner(self, provider_key):
        """Actualiza el título y etiqueta del botón del banner de API key,
           verificando la *existencia* de la clave en keys.json."""
        if not self.api_key_banner: return
        if provider_key is None:
             self.api_key_banner.set_revealed(False)
             return

        button_label = None
        title = ""
        # CORRECCIÓN: Solo nos importa si la clave *existe* en el archivo JSON
        key_exists_in_file = False

        try:
            keys_path = os.path.join(llm.user_dir(), "keys.json")
            if os.path.exists(keys_path):
                with open(keys_path, 'r') as f:
                    try:
                        stored_keys = json.load(f)
                        # Verificar si la clave para este provider_key existe en el diccionario
                        if provider_key in stored_keys:
                            key_exists_in_file = True
                            # Para depuración, puedes imprimir el valor encontrado:
                            # print(f"Debug: Found key '{provider_key}' with value: {stored_keys.get(provider_key)}")
                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode {keys_path}")
                        title = _("Error reading keys file")
                        button_label = _("Check File")
                        self.api_key_banner.set_title(title)
                        self.api_key_banner.set_button_label(button_label)
                        return
            else:
                # Si keys.json no existe, ninguna clave está configurada
                key_exists_in_file = False

            # Determinar título y etiqueta basado en key_exists_in_file
            if key_exists_in_file:
                # Asumimos que si la clave existe, está "configurada" (aunque podría estar vacía)
                # El comportamiento de 'llm set "" alias' no borra la clave, la deja vacía.
                title = _("API Key is configured") # O podríamos decir "Key entry exists"
                button_label = _("Change Key")
            else:
                # Si la clave no existe en el archivo, definitivamente es requerida y no está configurada
                title = _("API Key Required")
                button_label = _("Set Key")

        except Exception as e:
            # Capturar otros errores (p.ej., permisos de archivo)
            print(f"Error accessing or reading API keys file: {e!r}")
            title = _("Error accessing keys file")
            button_label = _("Check Permissions")

        # Actualizar el banner
        self.api_key_banner.set_title(title)
        self.api_key_banner.set_button_label(button_label)

    def _set_initial_state(self):
        """Configura la vista inicial basada en la configuración."""
        current_model_id = self.config.get('model')
        initial_provider = LOCAL_PROVIDER_KEY

        if current_model_id:
            found = False
            for provider_key, models in self.models_by_provider.items():
                for model_obj in models:
                    if getattr(model_obj, 'model_id', None) == current_model_id:
                        initial_provider = provider_key
                        found = True
                        break
                if found: break

        self._populate_model_list(initial_provider)
        page = self.view_stack.get_page(self.model_list.get_parent().get_parent()) # Box -> ScrolledWindow -> ListBox
        if page:
             page.set_title(self._get_provider_display_name(initial_provider))

        # Mostrar la página de modelos si el proveedor inicial requiere key o si es local pero ya tiene un modelo seleccionado
        if initial_provider != LOCAL_PROVIDER_KEY or (current_model_id and initial_provider == LOCAL_PROVIDER_KEY):
             self.view_stack.set_visible_child_name(MODEL_LIST_NAME)
        else:
             self.view_stack.set_visible_child_name(PROVIDER_LIST_NAME)

        return GLib.SOURCE_REMOVE

    def _on_provider_row_activated(self, list_box, row):
        """Manejador cuando se selecciona un proveedor."""
        provider_key = getattr(row, 'provider_key', 'missing')
        if provider_key != 'missing':
            self._populate_model_list(provider_key)
            # El page se obtiene diferente ahora que hay un Box intermedio
            page = self.view_stack.get_page(self.model_list.get_parent().get_parent()) # Box -> ScrolledWindow -> ListBox
            if page:
                 page.set_title(self._get_provider_display_name(provider_key))
            self.view_stack.set_visible_child_name(MODEL_LIST_NAME)

    def _on_model_row_activated(self, list_box, row):
        """Manejador cuando se selecciona un modelo."""
        # Ya no necesitamos chequear por API_KEY_ROW_NAME
        model_id = getattr(row, 'model_id', None)
        if model_id:
            print(f"Sidebar: Model selected: {row.get_title()} (ID: {model_id})")
            if self.config.get('model') != model_id:
                self.config['model'] = model_id
                if self.llm_client and hasattr(self.llm_client, 'set_model'):
                    try:
                        self.llm_client.set_model(model_id)
                    except Exception as e:
                        print(f"Error setting model ID in LLM client: {e}")

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
        """Manejador para la respuesta del diálogo de API key.
           Guarda la clave directamente en keys.json."""
        if response_id == "set":
            api_key = key_entry.get_text()
            if api_key:
                try:
                    # Lógica adaptada de llm/cli.py keys_set
                    keys_path = os.path.join(llm.user_dir(), "keys.json")
                    keys_path_obj = pathlib.Path(keys_path) # Usar pathlib para manejo más fácil
                    keys_path_obj.parent.mkdir(parents=True, exist_ok=True)

                    default_keys = {"// Note": "This file stores secret API credentials. Do not share!"}
                    current_keys = default_keys
                    newly_created = False

                    if keys_path_obj.exists():
                        try:
                            current_keys = json.loads(keys_path_obj.read_text())
                            # Asegurarse de que sea un diccionario
                            if not isinstance(current_keys, dict):
                                print(f"Warning: {keys_path} does not contain a valid JSON object. Overwriting.")
                                current_keys = default_keys
                        except json.JSONDecodeError:
                            print(f"Warning: Could not decode {keys_path}. Overwriting.")
                            current_keys = default_keys
                    else:
                        newly_created = True

                    # Actualizar la clave
                    current_keys[provider_key] = api_key

                    # Escribir el archivo
                    keys_path_obj.write_text(json.dumps(current_keys, indent=2) + "\n")

                    # Establecer permisos si es nuevo (imitando cli.py)
                    if newly_created:
                        try:
                            # chmod solo funciona bien en sistemas POSIX (Linux/macOS)
                            if os.name == 'posix':
                                os.chmod(keys_path_obj, 0o600)
                        except OSError as chmod_err:
                             print(f"Warning: Could not set permissions on {keys_path_obj}: {chmod_err}")


                    print(f"API Key set for {provider_key} in {keys_path}")
                    # Actualizar el banner para reflejar el cambio
                    self._update_api_key_banner(provider_key)

                except Exception as e:
                    # Capturar errores de E/S, permisos, etc.
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

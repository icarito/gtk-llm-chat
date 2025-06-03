import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib
import llm
from collections import defaultdict
import os
import pathlib
import json

from chat_application import _
DEBUG = os.environ.get('DEBUG') or False

def debug_print(*args):
    if DEBUG:
        print(*args)

class ModelSelectionManager(GObject.Object):
    """
    Clase que maneja la selección de modelo y proveedor para gtk-llm-chat.
    Incluye gestión de API keys y agrupación de modelos por proveedor.
    """
    __gsignals__ = {
        'provider-selected': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'model-selected': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'api-key-changed': (GObject.SignalFlags.RUN_LAST, None, (str,))
    }

    def __init__(self, config=None, llm_client=None):
        """Inicializa el administrador de selección de modelos."""
        super().__init__()
        self.config = config or {}
        self.llm_client = llm_client
        self.models_by_provider = defaultdict(list)
        self._provider_to_needs_key = {}
        self._selected_provider_key = None
        self._models_loaded = False
        self._keys_cache = None
        self._provider_key_map = {}  # Normaliza provider_key -> provider_key original

    def get_provider_display_name(self, provider_key):
        """Obtiene un nombre legible para la clave del proveedor."""
        norm_key = provider_key.lower().strip() if provider_key else "local/other"
        display = self._provider_key_map.get(norm_key)
        if display is not None:
            if display is None:
                return _("Local/Other")
            return display.replace('-', ' ').title().removeprefix('Llm ')
        if provider_key is None:
            return _("Local/Other")
        return provider_key.replace('-', ' ').title().removeprefix('Llm ') if provider_key else _("Unknown Provider")

    def get_provider_needs_key(self, provider_key):
        """Busca el valor de needs_key real para un provider_key dado."""
        all_models = llm.get_models()
        for model in all_models:
            if getattr(model, 'needs_key', None) == provider_key:
                return getattr(model, 'needs_key', None)
        return provider_key

    def get_needs_key_map(self):
        """Devuelve un mapeo {provider_key: needs_key}."""
        if hasattr(self, '_provider_to_needs_key'):
            return self._provider_to_needs_key
        needs_key_map = {}
        all_models = llm.get_models()
        for model in all_models:
            nk = getattr(model, 'needs_key', None)
            if nk:
                needs_key_map[nk] = nk
        needs_key_map[None] = None
        return needs_key_map

    def _get_keys_json(self):
        """Lee y cachea keys.json."""
        if self._keys_cache is None:
            try:
                keys_path = os.path.join(llm.user_dir(), "keys.json")
                if os.path.exists(keys_path):
                    with open(keys_path) as f:
                        self._keys_cache = json.load(f)
                else:
                    self._keys_cache = {}
            except Exception as e:
                debug_print(f"Error leyendo keys.json: {e}")
                self._keys_cache = {}
        return self._keys_cache

    def invalidate_keys_cache(self):
        """Invalida el caché de llaves API."""
        self._keys_cache = None

    def populate_providers_and_group_models(self):
        """
        Agrupa modelos por needs_key y puebla la lista de proveedores 
        usando introspección de plugins para descubrir todos los posibles.
        Además, añade cualquier modelo que sólo aparezca en llm.get_models() (como openai).
        """
        from llm.plugins import pm, load_plugins
        self.models_by_provider.clear()
        self._provider_to_needs_key = {}
        self._provider_key_map = {}
        try:
            # 1. Asegurar que los plugins están cargados
            import llm.plugins
            if not hasattr(llm.plugins, '_loaded') or not llm.plugins._loaded:
                load_plugins()
                debug_print("ModelSelection: Plugins cargados correctamente")
            else:
                debug_print("ModelSelection: Plugins ya estaban cargados")
            
            all_possible_models = []
            def register_model(model, async_model=None, aliases=None):
                all_possible_models.append(model)
            pm.hook.register_models(register=register_model)
            
            all_plugins = llm.get_plugins()
            plugins_with_models = [plugin for plugin in all_plugins if 'register_models' in plugin['hooks']]
            providers_set = {plugin['name']: plugin for plugin in plugins_with_models}
            debug_print(f"Plugins con modelos: {list(providers_set.keys())}")

            for provider_key in providers_set.keys():
                # Normalizar quitando 'llm-' si existe al inicio
                clean_key = provider_key
                if clean_key.startswith('llm-'):
                    clean_key = clean_key[4:]
                norm_key = clean_key.lower().strip() if clean_key else None
                self._provider_key_map[norm_key] = clean_key
                found_needs_key = None
                provider_models = {}
                for model_obj in all_possible_models:
                    model_needs_key = getattr(model_obj, 'needs_key', None)
                    model_id = getattr(model_obj, 'model_id', None)
                    if not model_id:
                        continue
                    # Solo agregar si needs_key coincide exactamente con el proveedor
                    if model_needs_key == clean_key:
                        found_needs_key = model_needs_key
                        provider_models[model_id] = model_obj
                if provider_models:
                    self.models_by_provider[norm_key] = list(provider_models.values())
                    debug_print(f"Proveedor {clean_key}: {len(provider_models)} modelos")
                if found_needs_key:
                    self._provider_to_needs_key[norm_key] = found_needs_key
                else:
                    self._provider_to_needs_key[norm_key] = clean_key

            # 4. Añadir modelos que sólo aparecen en llm.get_models() (core, openai, etc), evitando duplicados exactos por model_id
            all_models = llm.get_models()
            for model in all_models:
                provider = getattr(model, 'needs_key', None)
                # Normalizar quitando 'llm-' si existe al inicio
                if provider is None:
                    clean_key = "local/other"
                    norm_key = "local/other"
                else:
                    clean_key = provider
                    if isinstance(clean_key, str) and clean_key.startswith('llm-'):
                        clean_key = clean_key[4:]
                    norm_key = clean_key.lower().strip() if clean_key else None
                self._provider_key_map[norm_key] = clean_key
                model_id = getattr(model, 'model_id', None)
                if not model_id:
                    continue
                if norm_key not in self.models_by_provider:
                    self.models_by_provider[norm_key] = []
                existing_ids = {getattr(m, 'model_id', None) for m in self.models_by_provider[norm_key]}
                if model_id not in existing_ids:
                    self.models_by_provider[norm_key].append(model)
                if norm_key not in self._provider_to_needs_key:
                    self._provider_to_needs_key[norm_key] = clean_key

            debug_print(f"ModelSelection: Proveedores detectados: {list(self.models_by_provider.keys())}")
            return True
        except Exception as e:
            print(f"Error getting or processing models/plugins: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_models_for_provider(self, provider_key):
        """Obtiene la lista de modelos para un proveedor."""
        if not self._models_loaded:
            self.populate_providers_and_group_models()
            self._models_loaded = True
        norm_key = provider_key.lower().strip() if provider_key else "local/other"
        return sorted(
            self.models_by_provider.get(norm_key, []),
            key=lambda m: getattr(m, 'name', getattr(m, 'model_id', '')).lower()
        )

    def check_api_key_status(self, provider_key):
        """Verifica el estado de la API key para un proveedor usando solo la agrupación interna."""
        norm_key = provider_key.lower().strip() if provider_key else "local/other"
        models_for_provider = self.models_by_provider.get(norm_key, [])
        if not models_for_provider:
            # Si no hay modelos, asumimos que no requiere clave
            return {'needs_key': False}

        # Si todos los modelos de este provider tienen needs_key == None, no requiere clave
        needs_key_required = any(getattr(m, 'needs_key', None) not in (None, "", False) for m in models_for_provider)
        if not needs_key_required:
            return {'needs_key': False}

        # Si requiere clave, buscar si la tiene
        needs_key_map = self.get_needs_key_map()
        real_key = needs_key_map.get(provider_key, provider_key)
        stored_keys = self._get_keys_json()
        return {
            'needs_key': True,
            'has_key': real_key in stored_keys and bool(stored_keys[real_key]),
            'real_key': real_key
        }

    def set_api_key(self, provider_key, api_key):
        """Establece la API key para un proveedor."""
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

            needs_key_map = self.get_needs_key_map()
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
            self.invalidate_keys_cache()
            self.emit('api-key-changed', provider_key)
            return True
        except Exception as e:
            print(f"Error saving API key: {e}")
            return False

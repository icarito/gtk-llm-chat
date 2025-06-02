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

# Usaremos None para representar la ausencia de 'needs_key'
LOCAL_PROVIDER_KEY = None
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
        self._selected_provider_key = LOCAL_PROVIDER_KEY
        self._models_loaded = False
        self._keys_cache = None

    def get_provider_display_name(self, provider_key):
        """Obtiene un nombre legible para la clave del proveedor."""
        if provider_key == LOCAL_PROVIDER_KEY:
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
        """
        from llm.plugins import pm, load_plugins
        self.models_by_provider.clear()
        self._provider_to_needs_key = {}
        try:
            # 1. Asegurar que los plugins están cargados
            import llm.plugins
            if not hasattr(llm.plugins, '_loaded') or not llm.plugins._loaded:
                load_plugins()
                debug_print("ModelSelection: Plugins cargados correctamente")
            else:
                debug_print("ModelSelection: Plugins ya estaban cargados")
            
            all_possible_models = []
            
            # Función de registro para capturar modelos durante la invocación del hook
            def register_model(model, async_model=None, aliases=None):
                all_possible_models.append(model)

            # Llamar explícitamente al hook de registro de modelos
            pm.hook.register_models(register=register_model)
            
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
                    # Si no hay modelos, usar heurística: quitar 'llm-' si existe
                    self._provider_to_needs_key[provider_key] = provider_key.replace('llm-', '')

            # 4. Si no hay proveedores, intentar obtener modelos directamente
            if not providers_set:
                all_models = llm.get_models()
                debug_print(f"No se encontraron proveedores, intentando obtener modelos directamente: {len(all_models)} modelos")
                
                # Agrupar modelos por proveedor
                providers_from_models = defaultdict(list)
                for model in all_models:
                    provider = getattr(model, 'needs_key', None) or LOCAL_PROVIDER_KEY
                    providers_from_models[provider].append(model)
                
                if providers_from_models:
                    self.models_by_provider = providers_from_models
                    for provider_key in providers_from_models.keys():
                        self._provider_to_needs_key[provider_key] = provider_key

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
        
        return sorted(
            self.models_by_provider.get(provider_key, []),
            key=lambda m: getattr(m, 'name', getattr(m, 'model_id', '')).lower()
        )

    def check_api_key_status(self, provider_key):
        """Verifica el estado de la API key para un proveedor."""
        if provider_key == LOCAL_PROVIDER_KEY:
            return {'needs_key': False}

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

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, GLib
import llm
from collections import defaultdict
import os
import pathlib
import json

from .chat_application import _
from .debug_utils import debug_print

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
        
        # Índices para optimizar búsquedas - se construyen una sola vez
        self._model_id_to_provider = {}  # model_id -> provider_key
        self._model_id_to_object = {}    # model_id -> model_object
        self._all_models_cache = None    # Cache de llm.get_models()
        self._cache_timestamp = 0       # Timestamp del último cache
        
        # Separación entre información estática y dinámica
        self._static_providers_loaded = False  # Solo se carga una vez
        self._dynamic_models_cache = None     # Cache de modelos dinámicos

    def _build_model_indices(self):
        """Construye índices para búsquedas rápidas de modelos."""
        import time
        current_time = time.time()
        
        # Solo reconstruir si han pasado más de 5 segundos desde el último cache
        if self._all_models_cache is not None and (current_time - self._cache_timestamp) < 5:
            return
        
        debug_print("ModelSelection: Construyendo índices de modelos...")
        self._model_id_to_provider.clear()
        self._model_id_to_object.clear()
        
        # Cache de llm.get_models() para no llamarlo múltiples veces
        try:
            self._all_models_cache = list(llm.get_models())
            self._cache_timestamp = current_time
            debug_print(f"ModelSelection: Cached {len(self._all_models_cache)} modelos de llm.get_models()")
        except Exception as e:
            debug_print(f"Error obteniendo modelos: {e}")
            self._all_models_cache = []
        
        # Construir índices desde models_by_provider
        for provider_key, models in self.models_by_provider.items():
            for model_obj in models:
                model_id = getattr(model_obj, 'model_id', None)
                if model_id:
                    self._model_id_to_provider[model_id] = provider_key
                    self._model_id_to_object[model_id] = model_obj
        
        # Agregar modelos del cache que no estén en los índices
        for model_obj in self._all_models_cache:
            model_id = getattr(model_obj, 'model_id', None)
            if model_id and model_id not in self._model_id_to_object:
                self._model_id_to_object[model_id] = model_obj
                # Intentar determinar el proveedor
                provider = getattr(model_obj, 'needs_key', None) or 'local/other'
                if provider not in self._model_id_to_provider.get(model_id, []):
                    self._model_id_to_provider[model_id] = provider
        
        debug_print(f"ModelSelection: Índices construidos - {len(self._model_id_to_object)} modelos indexados")

    def get_model_by_id(self, model_id):
        """Obtiene un objeto modelo por su ID de manera eficiente."""
        self._build_model_indices()
        return self._model_id_to_object.get(model_id)
    
    def get_provider_for_model_id(self, model_id):
        """Obtiene el proveedor para un model_id de manera eficiente."""
        self._build_model_indices()
        return self._model_id_to_provider.get(model_id)

    def invalidate_model_cache(self):
        """Invalida el cache de modelos forzando una reconstrucción."""
        self._all_models_cache = None
        self._cache_timestamp = 0
        self._model_id_to_provider.clear()
        self._model_id_to_object.clear()
        # Solo invalida modelos dinámicos, no los datos estáticos de plugins
        self._dynamic_models_cache = None

    def invalidate_static_cache(self):
        """Invalida completamente incluyendo datos estáticos de plugins."""
        self.invalidate_model_cache()
        self._static_providers_loaded = False
        self.models_by_provider.clear()
        self._provider_to_needs_key.clear()
        self._provider_key_map.clear()

    def get_provider_display_name(self, provider_key):
        """Obtiene un nombre legible para la clave del proveedor."""
        if provider_key is None:
            return _("Local/Other")
        
        # Buscar en el mapeo de nombres
        display = self._provider_key_map.get(provider_key)
        if display is not None:
            if display is None:
                return _("Local/Other")
            return display.replace('-', ' ').title().removeprefix('Llm ')
        
        # Fallback: formatear el provider_key
        return provider_key.replace('-', ' ').title().removeprefix('Llm ') if provider_key else _("Unknown Provider")

    def get_provider_needs_key(self, provider_key):
        """Busca el valor de needs_key real para un provider_key dado usando cache cuando es posible."""
        # Usar cache dinámico si está disponible
        if self._dynamic_models_cache:
            all_models = self._dynamic_models_cache
        else:
            all_models = llm.get_models()
        
        for model in all_models:
            if getattr(model, 'needs_key', None) == provider_key:
                return getattr(model, 'needs_key', None)
        return provider_key

    def get_needs_key_map(self):
        """Devuelve un mapeo {provider_key: needs_key} usando cache cuando es posible."""
        if hasattr(self, '_provider_to_needs_key') and self._provider_to_needs_key:
            return self._provider_to_needs_key
        
        # Fallback a llm.get_models() si no hay cache
        needs_key_map = {}
        if self._dynamic_models_cache:
            # Usar cache si está disponible
            all_models = self._dynamic_models_cache
        else:
            # Solo llamar llm.get_models() si es absolutamente necesario
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
                from .platform_utils import ensure_user_dir_exists
                user_dir = ensure_user_dir_exists()
                keys_path = os.path.join(user_dir, "keys.json")
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

    def _load_static_providers(self):
        """
        Carga información estática de proveedores usando introspección de plugins.
        Esto solo se ejecuta una vez por sesión ya que la información no cambia.
        """
        if self._static_providers_loaded:
            return
        
        from llm.plugins import pm, load_plugins
        
        try:
            # Asegurar que los plugins están cargados
            import llm.plugins
            if not hasattr(llm.plugins, '_loaded') or not llm.plugins._loaded:
                load_plugins()
                debug_print("ModelSelection: Plugins cargados correctamente")
            else:
                debug_print("ModelSelection: Plugins ya estaban cargados")
            
            # Obtener todos los plugins con modelos
            all_plugins = llm.get_plugins()
            plugins_with_models = [plugin for plugin in all_plugins if 'register_models' in plugin['hooks']]
            providers_set = {plugin['name']: plugin for plugin in plugins_with_models}
            debug_print(f"Plugins con modelos encontrados: {list(providers_set.keys())}")

            # Procesar plugins para crear la estructura base de proveedores
            for provider_key in providers_set.keys():
                # Normalizar quitando 'llm-' si existe al inicio
                clean_key = provider_key
                if clean_key.startswith('llm-'):
                    clean_key = clean_key[4:]
                norm_key = clean_key.lower().strip() if clean_key else None
                self._provider_key_map[norm_key] = clean_key
                
                debug_print(f"Procesando plugin {provider_key} -> clean_key: {clean_key}, norm_key: {norm_key}")
                
                # Inicializar proveedor (se llenará en el siguiente paso)
                if norm_key not in self.models_by_provider:
                    self.models_by_provider[norm_key] = []
                
                # Establecer el mapeo de needs_key para este proveedor
                self._provider_to_needs_key[norm_key] = clean_key
            
            # Agregar siempre el proveedor local/other para modelos sin needs_key
            if None not in self.models_by_provider:
                self.models_by_provider[None] = []
                self._provider_to_needs_key[None] = None
                self._provider_key_map[None] = None
            
            self._static_providers_loaded = True
            debug_print(f"Proveedores estáticos cargados: {list(self.models_by_provider.keys())}")
            
        except Exception as e:
            debug_print(f"Error cargando proveedores estáticos: {e}")
            import traceback
            traceback.print_exc()

    def _load_dynamic_models(self):
        """
        Carga modelos dinámicos usando llm.get_models().
        Este método se puede llamar cuando cambian las API keys.
        """
        try:
            # Limpiar modelos existentes pero mantener estructura de proveedores
            for provider_key in self.models_by_provider:
                self.models_by_provider[provider_key] = []
            
            # Obtener modelos actuales
            all_models = llm.get_models()
            debug_print(f"Total de modelos obtenidos de llm.get_models(): {len(all_models)}")
            
            # Agrupar modelos por needs_key
            for model in all_models:
                needs_key = getattr(model, 'needs_key', None)
                
                # Normalizar needs_key para coincidencia
                if needs_key:
                    norm_key = needs_key.lower().strip()
                else:
                    norm_key = None
                
                # Agregar modelo al proveedor correspondiente
                if norm_key in self.models_by_provider:
                    self.models_by_provider[norm_key].append(model)
                else:
                    # Proveedor no encontrado en introspección estática, agregarlo dinámicamente
                    debug_print(f"Proveedor dinámico no esperado: {needs_key} -> {norm_key}")
                    self.models_by_provider[norm_key] = [model]
                    self._provider_to_needs_key[norm_key] = needs_key
                    self._provider_key_map[norm_key] = needs_key
            
            # Cachear los modelos dinámicos
            self._dynamic_models_cache = all_models
            debug_print(f"Modelos por proveedor: {[(k, len(v)) for k, v in self.models_by_provider.items()]}")
            
        except Exception as e:
            debug_print(f"Error cargando modelos dinámicos: {e}")
            import traceback
            traceback.print_exc()

    def populate_providers_and_group_models(self):
        """
        Método optimizado que separa carga estática de proveedores de modelos dinámicos.
        """
        debug_print("ModelSelection: Iniciando carga optimizada de proveedores y modelos")
        
        try:
            # 1. Cargar información estática de proveedores (solo una vez por sesión)
            self._load_static_providers()
            
            # 2. Cargar modelos dinámicos (se puede repetir cuando cambian API keys)
            self._load_dynamic_models()
            
            self._models_loaded = True
            debug_print("ModelSelection: Carga optimizada completada")
            return True
        except Exception as e:
            debug_print(f"Error en populate_providers_and_group_models: {e}")
            import traceback
            traceback.print_exc()
            return False

    def reload_dynamic_models_only(self):
        """
        Recarga solo los modelos dinámicos manteniendo la estructura de proveedores.
        Útil cuando cambian las API keys.
        """
        debug_print("ModelSelection: Recargando solo modelos dinámicos")
        self._load_dynamic_models()
        # Invalidar solo cache dinámico
        self.invalidate_model_cache()

    def get_models_for_provider(self, provider_key):
        """Obtiene la lista de modelos para un proveedor."""
        if not self._models_loaded:
            self.populate_providers_and_group_models()
            self._models_loaded = True
        # No normalizar aquí, usar la clave tal como viene
        norm_key = provider_key if provider_key is not None else None
        return sorted(
            self.models_by_provider.get(norm_key, []),
            key=lambda m: getattr(m, 'name', getattr(m, 'model_id', '')).lower()
        )

    def check_api_key_status(self, provider_key):
        """Verifica el estado de la API key para un proveedor usando solo la agrupación interna."""
        # No normalizar aquí, usar la clave tal como viene
        norm_key = provider_key if provider_key is not None else None
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
            from .platform_utils import ensure_user_dir_exists
            user_dir = ensure_user_dir_exists()
            keys_path = os.path.join(user_dir, "keys.json")
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
                    debug_print(f"Error setting permissions for {keys_path}: {chmod_err}")

            debug_print(f"API Key set for {real_key} in {keys_path}")
            self.invalidate_keys_cache()
            self.emit('api-key-changed', provider_key)
            return True
        except Exception as e:
            debug_print(f"Error saving API key: {e}")
            return False

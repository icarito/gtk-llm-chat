"""
Stub del módulo llm para modo sin LLM.
Este archivo intercepta las llamadas a llm cuando se ejecuta con --no-llm.
"""

# Clases stub básicas
class UnknownModelError(Exception):
    """Excepción cuando un modelo no se encuentra"""
    pass

class StubModel:
    def __init__(self, model_id="stub-model"):
        self.model_id = model_id
        self.id = model_id
        self.needs_key = None
        
    def __str__(self):
        return self.model_id
        
    def conversation(self):
        """Crea una conversación para este modelo"""
        return StubConversation(self.model_id)

class StubConversation:
    def __init__(self, model_id="stub-model"):
        self.model_id = model_id
        self.id = "stub-conversation-id"
        
    def prompt(self, text, **kwargs):
        """Simula una respuesta del modelo"""
        return f"[MODO SIN LLM] Respuesta simulada para: {text[:50]}..."

# Funciones stub principales
def get_models():
    """Devuelve una lista de modelos stub"""
    return [
        StubModel("stub-local-model"),
        StubModel("stub-test-model"),
    ]

def get_default_model():
    """Devuelve un modelo por defecto stub"""
    return "stub-local-model"

def set_default_model(model_id):
    """Simula establecer un modelo por defecto"""
    print(f"[STUB] Modelo por defecto establecido: {model_id}")
    return True

def get_model(model_id):
    """Devuelve un modelo stub específico"""
    return StubModel(model_id)

def get_plugins():
    """Devuelve una lista vacía de plugins"""
    return []

# Simulación del directorio de usuario
def user_dir():
    """Devuelve un directorio de usuario simulado"""
    import os
    return os.path.expanduser("~/.config/io.datasette.llm")

# Clase para simular conversaciones
class Conversation:
    def __init__(self, model_id="stub-model"):
        self.model = StubModel(model_id)
        self.id = "stub-conversation-id"
        
    def prompt(self, text, **kwargs):
        """Simula una respuesta del modelo"""
        return f"[MODO SIN LLM] Respuesta simulada para: {text[:50]}..."

# Función para crear conversación
def conversation(model_id=None):
    """Crea una conversación stub"""
    return Conversation(model_id or "stub-model")

# Simular los plugins y registros
class StubPluginManager:
    def __init__(self):
        pass
        
    def load_plugins(self):
        pass

# Crear instancia del plugin manager
pm = StubPluginManager()

# Módulo plugins stub
class plugins:
    pm = StubPluginManager()
    _loaded = True
    
    @staticmethod
    def load_plugins():
        pass

# Funciones adicionales que podrían ser llamadas
def logs_db():
    """Simula la base de datos de logs"""
    import os
    user_dir_path = user_dir()
    return os.path.join(user_dir_path, "logs.db")

# Decorador hookimpl para plugins
def hookimpl(func):
    """Decorador stub para hookimpl"""
    return func

print("[STUB] Módulo llm stub cargado - modo sin LLM activo")

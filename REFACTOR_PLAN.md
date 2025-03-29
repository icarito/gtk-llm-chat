# Plan de Refactorización: Reemplazo de `LLMProcess` con API `python-llm`

## Objetivo

Reemplazar la clase `LLMProcess` actual, que gestiona el CLI `llm` como un subproceso, por una nueva clase `LLMClient` que utilice directamente la API de Python `python-llm`, aprovechando su manejo de conversaciones y streaming síncrono.

## Análisis y Descubrimientos Clave (Basado en API Docs)

*   **Streaming:** La API soporta streaming síncrono iterando sobre el objeto `response` (`for chunk in response:`). Ideal para integrar con `GLib.idle_add`.
*   **Conversaciones:** La API maneja el historial internamente mediante `model.conversation()`. `LLMClient` no necesitará gestionar la lista de mensajes manualmente.
*   **Configuración:** `system` prompt, opciones (`temperature`, etc.) y `key` se pasan directamente a `.prompt()` o `conversation.prompt()`.
*   **Callback `on_done`:** Disponible para ejecutar código al finalizar la respuesta completa. Útil para la señal `finished`.
*   **Errores:** Se esperan excepciones estándar y específicas como `llm.UnknownModelError`.
*   **Cancelación:** No hay un método explícito documentado para cancelar un stream en curso. `LLMClient.cancel()` tendrá una funcionalidad limitada (detener el procesamiento local).

## Plan Detallado

### Fase 1: Diseño (Confirmado/Refinado)

*   **Tecnología:**
    *   Usar `llm.get_model()` y `model.conversation()`.
    *   Integrar el stream síncrono con `GLib.idle_add`.
    *   Utilizar `response.on_done()` para la señal `finished`.
    *   Manejar excepciones (`try...except`).
*   **Nueva Clase:** `LLMClient(GObject.Object)` en `gtk_llm_chat/llm_client.py`
    *   **Señales GObject:**
        *   `response(str)`: Emite cada token recibido.
        *   `error(str)`: Emite mensajes de error.
        *   `finished(bool)`: Emite al final de una respuesta (True=éxito, False=error/cancelado).
    *   **Métodos:**
        *   `__init__(self, config)`: Guarda config, inicializa `model` y `conversation`.
        *   `send_message(self, prompt: str)`: Llama a `self.conversation.prompt()`, inicia el procesamiento del stream con `GLib.idle_add`, configura `on_done`.
        *   `cancel(self)`: Establece una bandera interna para detener el procesamiento de nuevos chunks y emite `finished(False)`.
    *   **Estado Interno:** `self.model`, `self.conversation`, `self.config`, `self._is_generating_flag`.

### Fase 2: Implementación

*   Crear el archivo `gtk_llm_chat/llm_client.py`.
*   Implementar la clase `LLMClient` según el diseño.
    *   Manejar la iteración del stream dentro de la función llamada por `GLib.idle_add`.
    *   Asegurar que las señales GObject se emitan desde el hilo principal.
    *   Implementar el manejo de errores y la lógica de `cancel()`.
*   Añadir `llm` a las dependencias del proyecto (`requirements.txt` o `pyproject.toml`).

### Fase 3: Integración y Refactorización

*   En `gtk_llm_chat/chat_application.py`:
    *   Cambiar la importación a `from llm_client import LLMClient`.
    *   Instanciar `self.llm = LLMClient(...)`.
    *   Eliminar `self.llm.initialize()` si no es necesario.
    *   Conectar las nuevas señales: `response`, `error`, `finished`.
    *   Crear `_on_llm_finished(self, llm_client, success: bool)` para manejar la señal `finished` (p.ej., re-habilitar UI).
    *   **Simplificar `_start_llm_task`:** Obtener solo el texto del input y llamar a `self.llm.send_message(texto_del_input)`.
    *   Asegurar que `_on_close_request` y `do_shutdown` llamen al nuevo `self.llm.cancel()`.
    *   Eliminar conexiones a señales antiguas (`ready`, `model-name`, `process-terminated`).

### Fase 4: Pruebas

*   Verificar envío/recepción de mensajes.
*   Probar conversaciones largas (mantenimiento de contexto).
*   Probar diferentes configuraciones (modelos, system prompts, parámetros).
*   Simular y verificar manejo de errores (API key inválida, etc.).
*   Probar la funcionalidad (limitada) de cancelación.
*   Verificar carga de historiales existentes.
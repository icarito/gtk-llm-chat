## Why

Cuando un comando/backend LLM falla antes de arrancar el streaming (backend
sin inicializar, generación ya en curso, sin modelo configurado), la señal
`'error'` del cliente se emite pero nunca se emite `'finished'`. Como el
spinner y la reactivación del input sólo ocurren en el handler de
`'finished'`, la ventana queda con el input deshabilitado y el spinner
girando indefinidamente tras un error — el usuario no puede seguir
escribiendo sin reiniciar la app.

## What Changes

- El manejo de errores del backend LLM reactiva el input (equivalente a
  `set_enabled(True)`) siempre que ocurre un error, sin depender de que
  `'finished'` también se emita.
- Se documenta/unifica el contrato entre las señales `error` y `finished`
  respecto a la limpieza de estado de UI (spinner, input habilitado), para
  que futuros caminos de error no reintroduzcan el mismo bug.

## Capabilities

### New Capabilities
- `llm-command-error-recovery`: contrato de limpieza de estado de UI
  (spinner/input) ante un error de backend LLM, cubriendo tanto errores
  previos al streaming como errores durante el streaming.

### Modified Capabilities
(ninguna — no hay spec existente para este comportamiento)

## Impact

- `gtk_llm_chat/chat_window.py`: handler `_on_llm_error` (~línea 3390) y
  `_on_llm_finished` (~línea 3428-3430).
- `gtk_llm_chat/llm_client.py`: `send_message` (~líneas 45-59), caminos
  tempranos que emiten `'error'` sin lanzar `_process_stream`.
- Sin cambios de API pública ni de configuración; es un fix de UI/estado.

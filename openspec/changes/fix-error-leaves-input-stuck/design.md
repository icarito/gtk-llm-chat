## Context

El spinner/input del chat se reactiva únicamente en `_on_llm_finished`
(`chat_window.py` ~3428-3430), conectado a la señal `finished` del backend.
`_on_llm_error` (~3390), conectado a `error`, sólo muestra el error pero no
reactiva el input.

En `llm_client.py` `send_message` (~45-59), dos condiciones detectadas
antes de lanzar el hilo `_process_stream` (generación ya en curso, backend
sin inicializar / sin modelo) emiten `error` y retornan sin lanzar el hilo
— por lo tanto `finished` nunca se emite para esos casos y el input queda
deshabilitado indefinidamente.

Los errores que ocurren dentro de `_process_stream` ya están cubiertos: un
`try/finally` (try en línea 184, finally en 282) garantiza que `finished`
se emita siempre, así que ese camino no tiene el bug.

## Goals / Non-Goals

**Goals:**
- Que cualquier error de backend, sin importar si ocurre antes o durante el
  streaming, deje el input utilizable.

**Non-Goals:**
- No rediseñar el contrato de señales `error`/`finished` en general — el
  fix es puntual al punto de falla identificado, no una refactorización del
  sistema de señales.
- No cambiar el comportamiento de `_process_stream` ni su `try/finally`
  existente (ya funciona correctamente).

## Decisions

Se reactiva el input directamente en `_on_llm_error`, igual que hace
`_on_llm_finished`. Alternativa considerada: hacer que los caminos
tempranos de `send_message` emitan `finished` además de `error` para
preservar el invariante "toda emisión termina en finished". Se descarta
por ser un cambio de contrato más amplio y menos localizado que simplemente
reactivar el input en el handler de error — la señal `error` ya es la señal
correcta semánticamente para este caso; el bug es que su handler no hace
toda la limpieza que debería.

## Risks / Trade-offs

- [Duplicar lógica de reactivación entre `_on_llm_error` y
  `_on_llm_finished`] → Mitigación: aceptable dado el tamaño del fix; si en
  el futuro aparecen más caminos de limpieza compartidos, considerar
  extraer un helper común en ese momento, no ahora (evitar abstracción
  prematura).

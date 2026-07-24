## 1. Servidor (verificación de prerequisito)

- [x] 1.1 Confirmado: el comando `approval-bypass` ya está desplegado y
      verificado end-to-end en producción (`claudio-w`), ver change
      `xmpp-approval-bypass-and-fallback-cleanup` en `openclaw-xmpp`. Sin
      trabajo adicional requerido en este repo.

## 2. Cliente — funciones de ejecución del comando

- [x] 2.1 `_set_approval_bypass(enabled, minutes=10, on_done=None)` en
      `chat_window.py`: descubre el nodo vía `request_commands`, ejecuta
      el flujo de dos pasos XEP-0050 completando el form con `mode`/
      `minutes` sin mostrar diálogo.
- [x] 2.2 `_query_approval_bypass_status(on_done)`: mismo mecanismo con
      `mode=status`, parsea "activo, quedan Xm/Xs" del texto de respuesta.

## 3. Cliente — UI en el popover de la sticky card

- [x] 3.1 Popover de detalle (`info_button`) extendido: cuando
      `is_approval`, envuelve el label de detalle existente y un
      `Adw.SwitchRow` (dentro de `Gtk.ListBox` con clase `boxed-list`) en
      un `Gtk.Box` vertical.
- [x] 3.2 `on_bypass_toggled` conectado a `notify::active`, llama
      `_set_approval_bypass` y refleja el mensaje real del servidor en el
      subtítulo de la fila.
- [x] 3.3 `refresh_bypass_status` conectado a la señal `show` del popover:
      consulta status cada vez que se abre, con `handler_block_by_func` /
      `handler_unblock_by_func` alrededor de `set_active()` para no
      re-disparar el comando de activación al sincronizar el estado.

## 4. Verificación

- [x] 4.1 `python3 -m py_compile` sobre `chat_window.py`,
      `xmpp_commands.py`, `agent_commands_sidebar.py`: sin errores de
      sintaxis. No hay type-checker configurado en este repo (Python sin
      mypy/pyright en el flujo estándar).
- [x] 4.2 Confirmado sin cambios necesarios: `agent_commands_sidebar.py`
      clasifica `approval-bypass` en la sección "Administration" por
      coincidencia exacta de nodo (`section_for`); funcionará
      automáticamente ahora que el servidor anuncia el nodo real.
- [ ] 4.3 Verificación en un cliente GTK real conectado a un agente con
      una aprobación pendiente real: no ejecutada en esta pasada (requiere
      GUI interactiva + una card de aprobación real generada por un
      agente). Pendiente de que el usuario lo pruebe en uso normal.

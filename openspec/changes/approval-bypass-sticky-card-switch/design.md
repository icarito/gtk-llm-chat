## Context

GTK ya tiene toda la maquinaria de comandos ad-hoc XEP-0050/XEP-0004 en
`xmpp_commands.py` (`XmppCommandClient`, `XmppCommandFormDialog`,
`SimpleDataForm`/`create_field` de nbxmpp), usada por
`_open_agent_model_command`/`_execute_agent_command` para el resto de
comandos del agente. El patrón estándar (`_execute_agent_command`) muestra
un diálogo genérico (`XmppCommandFormDialog`) cuando el comando pide un
formulario XEP-0004 — apropiado para comandos con campos arbitrarios, pero
no para un switch: el bypass no debe abrir un diálogo modal cada vez que
se toca, tiene que completarse en el mismo gesto.

`approval-bypass` (igual que el resto de comandos de este plugin) siempre
pide formulario en el primer `execute` porque declara parámetros
(`mode`, `minutes` opcional) — el servidor nunca completa en un solo paso
cuando `action.params.length > 0` (ver `openclaw-xmpp/src/xep-0050.ts`).
Esto es análogo a lo que se confirmó al implementar el fix en
`gtk-llm-chat-android`.

## Goals / Non-Goals

**Goals:**
- Reusar `XmppCommandClient` sin duplicar el protocolo XEP-0050 (descubrir
  vía disco, ejecutar, completar formulario).
- No mostrar el diálogo de formulario genérico para este caso — completar
  el segundo paso del protocolo automáticamente con los valores del switch.
- Reflejar el estado real (consultando `status`) cada vez que se abre el
  popover, para no confiar solo en el estado optimista local del switch.

**Non-Goals:**
- No se toca `agent_commands_sidebar.py` — su categorización por prefijo ya
  funciona sin cambios una vez que el servidor anuncia el nodo real.
- No se implementa polling en background continuo — la consulta de status
  ocurre solo al abrir el popover (`popover.connect("show", ...)`), no en
  un timer recurrente, para no generar tráfico XMPP mientras el popover
  está cerrado.
- No se persiste el estado del switch entre sesiones de la app.

## Decisions

**Reimplementar el flujo de dos pasos en vez de reusar
`_execute_agent_command`.** `_execute_agent_command` está acoplado a
`XmppCommandFormDialog` (siempre muestra el diálogo si hay form). Separar
`_set_approval_bypass`/`_query_approval_bypass_status` evita modificar el
comportamiento compartido de esa función para todos los demás comandos del
agente, a costa de duplicar unas pocas líneas del protocolo de dos fases.

**`Adw.SwitchRow` envuelto en un `Gtk.ListBox` con clase `boxed-list`.**
Es el contenedor idiomático de Adwaita para una fila suelta fuera de un
`Adw.PreferencesGroup` completo (que traería título/descripción de grupo
no necesarios acá); confirmado que el resto del repo (`xmpp_account_dialog.py`,
`xmpp_commands.py`) usa `Adw.SwitchRow` siempre dentro de un contenedor de
lista, nunca suelto en un `Gtk.Box`.

**Bloqueo del handler de `notify::active` durante el refresh de status.**
Sin `handler_block_by_func`/`handler_unblock_by_func`, cada refresh de
status que cambia `set_active()` programáticamente dispararía
`on_bypass_toggled` como si el usuario lo hubiera tocado, reenviando el
comando de activación/desactivación en un loop de retroalimentación.

## Risks / Trade-offs

- **[Riesgo] Parseo de texto libre para status** (mismo trade-off que en
  Android) → degrada a "activo sin minutos mostrados" si el regex no
  matchea, no lanza error visible al usuario.
- **[Trade-off] Sin prueba en un cliente GTK real conectado a un agente
  con una aprobación pendiente real dentro de esta sesión** → el código
  compila (`py_compile`) y sigue exactamente los patrones ya usados por
  comandos ad-hoc existentes en este mismo archivo, pero no se ejecutó el
  flujo visual real. Pendiente de que el usuario lo pruebe en uso normal.

## Why

El servidor (`openclaw-xmpp`, change `xmpp-approval-bypass-and-fallback-cleanup`,
ya desplegado y verificado en producción) expone un comando ad-hoc real
`approval-bypass` para relajar temporalmente las aprobaciones de exec de una
sesión. El cliente Android ya tenía (y se acaba de corregir en
`gtk-llm-chat-android`) un switch para esto en el popover de la sticky card
de aprobación. GTK no tenía ningún control equivalente — solo quedaba una
entrada muerta de categorización de menú (`agent_commands_sidebar.py:34`,
prefijo `approval-bypass` en la sección "Administration") que nunca hacía
match porque el servidor nunca anunciaba ese nodo hasta ahora.

## What Changes

- Nuevas funciones `_set_approval_bypass`/`_query_approval_bypass_status`
  en `chat_window.py`, siguiendo el mismo patrón que
  `_open_agent_model_command`/`_execute_agent_command` (descubrimiento
  dinámico de comandos vía disco#items, ejecución XEP-0050 real vía
  `XmppCommandClient`), pero completando el formulario del comando
  directamente con los valores del switch en vez de mostrar el diálogo
  genérico `XmppCommandFormDialog`.
- El popover que expande la sticky card de una aprobación (el botón de
  información junto al detalle) ahora incluye un `Adw.SwitchRow` de bypass
  cuando la card visible es una aprobación, con estado refrescado (consulta
  de `status`) cada vez que se abre el popover.
- Sin cambios en `agent_commands_sidebar.py`: el dead code de
  categorización ya funciona correctamente ahora que el servidor anuncia
  el nodo real — no requiere ningún cambio de código, solo se confirma que
  el comando aparecerá bien clasificado si el usuario lo busca ahí también.

## Capabilities

### New Capabilities
- `xmpp-approval-bypass-sticky-switch`: switch de bypass temporal,
  contextual al popover de la sticky card de aprobación, con reflejo veraz
  de estado vía consulta al servidor.

### Modified Capabilities
(ninguna)

## Impact

- `gtk_llm_chat/chat_window.py`: dos funciones nuevas
  (`_set_approval_bypass`, `_query_approval_bypass_status`), y el bloque de
  `_rebuild_sticky_response_box` que arma el popover de detalle de la
  sticky card, extendido condicionalmente cuando `is_approval`.
- Depende del servidor ya desplegado y verificado; sin cambios de servidor
  en este change.

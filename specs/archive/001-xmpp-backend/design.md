# 001 — Design notes

## Library choice: nbxmpp (primary), slixmpp (fallback)

Evaluated 2026-07-03:

| | python-nbxmpp | slixmpp | aioxmpp |
|---|---|---|---|
| Event model | **GLib mainloop native**, GObject signals | asyncio | asyncio |
| Maintenance | Active (7.2.0, Apr 2026; drives Gajim 2.x/GTK4) | Active, largest community | **Inactive** — discarded |
| Docs | Sparse (wiki + Gajim source as reference) | Best-in-class | — |
| Packaging | In Arch repos (`python-nbxmpp`), PyPI `nbxmpp` | PyPI | — |
| Fit with our stack | Perfect: same GObject signal world as `LLMClient`, zero loop-integration work | Needs asyncio loop in a worker thread + `GLib.idle_add` bridging (pattern already proven in `llm_client.py`) | — |

**Decision (confirmed by spike, 2026-07-03):** **nbxmpp 7.2.0**.
The spike (`spike/spike_nbxmpp.py`) passed all four checks against
yax.im — connect+auth, roster fetch, message round-trip, XEP-0085
chat-state — running directly on the GLib mainloop in ~120 lines.
slixmpp fallback not needed.

### Spike findings (API gotchas for T3)

- `Client` is `Observable`: `subscribe('connected'|'disconnected'|
  'connection-failed', cb)`; incoming stanzas via
  `register_handler(StanzaHandler(name='message', callback=cb))` where
  the callback gets `(client, stanza, properties)`.
- **Wrong password fails silently** unless you subscribe to
  `'disconnected'` and inspect `client.get_error()` — `'connection-failed'`
  only fires for transport-level failures. `XmppClient` must map both
  paths to its `error`/`state-changed` signals.
- `properties.has_chatstate` / `properties.chatstate` are properties,
  not methods; chatstate arrives on the same message handler.
- An initial `Presence()` must be sent after connect or the server
  won't route incoming messages to the resource. Moreover (found in T3):
  the startup order must be roster → initial presence → announce
  "connected"; if a message is sent before the initial presence, the
  server treats us as offline and queues it instead of delivering.
- A deliberate `client.disconnect()` surfaces as
  `StreamError.STREAM: stream-end` in `get_error()` — a session must
  remember it requested the disconnect to avoid reporting it as an error.
- Roster: `client.get_module('Roster').request_roster()` returns a
  `Task`; use `add_done_callback(cb)` + `task.finish()`.
- Messages sent to your own bare JID are reflected back by the server —
  handy for tests without a second account.

## Backend abstraction

`LLMClient` already defines an implicit contract via GObject signals:
`response(str)`, `error(str)`, `finished(bool)`, `model-loaded(str)`.

Plan: make this contract explicit and give `XmppClient` the same shape.

```
ChatBackend (informal interface — duck-typed GObject)
  signals:  response(str) · error(str) · finished(bool) · ready(str)
            state-changed(str)        # xmpp: connected/disconnected/…;
                                      # llm: model-loaded maps onto ready
  methods:  send_message(text) · cancel() · get_display_name() · shutdown()
```

- `ChatWindow` talks to a `ChatBackend`, not to `LLMClient` directly.
  First task on the UI side is this refactor, verified by the LLM flow
  behaving unchanged (regression criterion in spec).
- `XmppClient(GObject.Object)` wraps one XMPP session (nbxmpp `Client`),
  shared by all XMPP windows; each window binds to one bare JID
  conversation. Chat states (XEP-0085) surface as a `typing(bool)` signal
  consumed only by XMPP windows in MVP.
- Note: XMPP messages arrive whole — no streaming chunks. `response` +
  immediate `finished` keeps the widget contract working without special
  cases.

## Account & credentials

- JID + server settings in a small config file under the app's user dir
  (not `llm.user_dir()`'s `logs.db`).
- Password via `keyring` (Secret Service on Linux). `keyring` is already
  in the dependency tree through `llm`; add it as a direct dependency.
- Account setup: minimal dialog reachable from the model/contact
  selector ("Add XMPP account…"). Welcome-wizard integration is Layer 2.

## Selector integration (revised in T5/T6, 2026-07-03)

Original plan: add an "XMPP contacts" section inside
`wide_model_selector.py` / `model_selector.py`. Revised after inspecting
that code — it's tightly coupled to `ModelSelectionManager` (API keys,
provider aliases, dynamic reload) and touching it risks the regression
criterion (LLM flow must stay identical).

**Decision:** XMPP conversations get a separate entry point instead:
an application action (`app.new-xmpp-conversation`, same pattern as
the existing `rename`/`delete`/`about` actions in
`chat_application.py`) opens a small roster-picker dialog — or the
account setup dialog first, if no account is configured yet. The LLM
model selector is untouched. Merging XMPP into that selector can
happen later as a Layer 2+ polish item once the backend abstraction
has proven itself.

`LLMChatWindow` gains an optional `backend=` constructor parameter: if
given, it's used as-is (skipping `LLMClient` construction and the
model/provider-specific UI wiring); if omitted, behavior is exactly
what it is today. This keeps the injection point minimal and the
regression surface small.

## What we deliberately don't build (MVP)

- No local storage of XMPP messages (window lifetime only).
- No tray-applet integration for XMPP conversations (tray reads `logs.db`,
  which XMPP never touches).
- No reconnection sophistication beyond nbxmpp's built-ins + a visible
  disconnected state and a manual reconnect action.

## XEPs in play (MVP)

- RFC 6120/6121 (core, roster)
- XEP-0085 Chat State Notifications (typing)
- XEP-0198/0199 (stream management/ping) — whatever nbxmpp enables by
  default; no explicit work planned.

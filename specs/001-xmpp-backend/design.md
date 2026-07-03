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

**Decision:** start the spike with **nbxmpp**. Its GLib-native design
removes the whole asyncio↔GTK integration problem, and Gajim's source is
a working GTK4 reference for every XEP we need. If the spike shows the
API is too Gajim-coupled for our simple use case, fall back to slixmpp
in an isolated thread (the `LLMClient` threading pattern applies as-is).

The spike (task 1) must demonstrate: connect to yax.im, auth, fetch
roster, send/receive a message, receive a chat-state notification —
in a standalone script, before any UI work.

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

## Selector integration

`wide_model_selector.py` / `model_selector.py` currently list providers →
models. Add a top-level "XMPP contacts" section fed by the roster when an
account is configured (plus the "Add XMPP account…" entry when not).
Selecting a contact opens a `ChatWindow` bound to an `XmppClient`
conversation instead of an `LLMClient`.

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

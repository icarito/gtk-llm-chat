# Architecture

How gtk-llm-chat actually works as of v4.0.5 (June 2025 codebase, revised
2026-07). The original 2025 design spec (subprocess-based, now obsolete) is
archived at [archive/spec-2025.md](archive/spec-2025.md).

## Big picture

```
                    ┌──────────────────────────────┐
 llm gui / CLI ───▶ │ LLMChatApplication (Adw.App) │◀── D-Bus OpenConversation(cid)
                    │  org.fuentelibre.gtk_llm_Chat│  (single-instance activation)
                    │  one process, many windows   │
                    └──────────┬───────────────────┘
                               │ window per conversation (CID)
                    ┌──────────▼──────────┐
                    │  ChatWindow (+ UI)  │ chat_window.py, widgets.py,
                    │  sidebar, selector  │ chat_sidebar.py, markdownview.py
                    └──────────┬──────────┘
                               │ ChatBackend contract (GObject signals:
                               │ response/error/finished/ready/state-changed/
                               │ typing/quick-responses)
                    ┌──────────▼──────────────────────────┐
                    │            ChatBackend               │  chat_backend.py
                    ├──────────────────┬───────────────────┤
        ┌───────────▼──────┐   ┌───────▼───────────────┐
        │    LLMClient     │   │   XmppConversation     │  xmpp_client.py
        │  llm_client.py   │   │  (per bare JID)        │
        └────────┬─────────┘   └───────┬────────────────┘
                 │                     │ shares one
        ┌────────▼─────────┐   ┌───────▼───────────────┐
        │ python-llm       │   │   XmppSession          │──▶ nbxmpp ──▶ XMPP server
        │ (in-proc) + plugins   │  (one per account)     │
        └────────┬─────────┘   └────────────────────────┘
                 │
        ┌────────▼─────────┐
        │   ChatHistory    │──▶ ~/…/io.datasette.llm/logs.db
        │ db_operations.py │    (LLM only; XMPP is not persisted)
        └──────────────────┘
```

Key decision: the LLM runs **in-process** through the `llm` Python API.
There is no subprocess, no stdout parsing. Streaming happens in a worker
thread; chunks are marshalled to the main loop with `GLib.idle_add` and
emitted as GObject signals. XMPP (spec 001) reuses the same window and
the same `ChatBackend` signal vocabulary, but runs entirely on the GLib
main loop via nbxmpp — no threads needed there.

## Modules

### Entry and lifecycle

- `main.py` — CLI entry (`gtk-llm-chat`). Parses args (`--cid`, `-s`, `-m`,
  `-c`, template options), applies frozen-app compatibility patches
  (NumPy/Python 3.13), then launches the chat application. Always a single
  process — no fork, no separate applet.
- `llm_gui.py` — registers the app as an `llm` plugin (`llm gui`).
- `chat_application.py` — `LLMChatApplication(Adw.Application)`, application
  id `org.fuentelibre.gtk_llm_Chat`, `HANDLES_COMMAND_LINE`. Single instance
  per session; opening a conversation from outside goes through the D-Bus
  method `OpenConversation(cid)`. Keeps a CID → window map. Detects
  first-run and shows the welcome assistant (`welcome.py`). Closing the last
  window quits the app, unless an XMPP session is connected (spec 003) — see
  `_on_close_request` in `chat_window.py`.

### Conversation UI

- `chat_window.py` — one window per conversation: header bar, message list,
  adaptive input (`Enter` sends, `Shift+Enter` newline), banners for API
  keys. Shortcuts: F10 sidebar, F2 rename, Ctrl+W delete, Ctrl+M model
  selector, Ctrl+S system prompt, Ctrl+N new window, Escape minimize.
- `widgets.py` — message bubbles (user/assistant/error) and input widgets.
- `markdownview.py` — Markdown rendering of responses (markdown-it-py).
- `chat_sidebar.py` — parameters panel (temperature, system prompt) and
  settings.
- `model_selector.py`, `model_selection.py`, `wide_model_selector.py` —
  provider/model pickers (narrow and wide layouts).
- `welcome.py` — first-run assistant (API keys, model selection,
  .desktop integration).

### Conversation backends

`ChatWindow` does not talk to a concrete client; it depends on a
`ChatBackend` contract, so the same window drives an LLM model or an
XMPP contact.

- `chat_backend.py` — `ChatBackend(GObject.Object)`, the contract.
  Signals: `response(str)`, `error(str)`, `finished(bool)`,
  `ready(str)` (backend can send / display name), `state-changed(str)`
  (connection state; local backends may never emit it), `typing(bool)`,
  `quick-responses(object)` (button definitions for the last received
  message; optional, used by NanoClaw XMPP).
  History signals (spec 004): `history-message(str, str, str)`
  (body, direction, timestamp) and `history-complete(bool)` (has_more),
  plus `load_more_history()` (no-op default; XMPP backends override
  for scroll-to-load paging). LLM backends do not use these —
  their history comes from `logs.db` via `ChatHistory`.
  Methods: `send_message`, `cancel`, `get_conversation_id`,
  `get_display_name`, `notify_composing`, `shutdown`, `load_more_history`.
  `response` may stream (many emits) or arrive whole (one emit); always
  followed by `finished`. `LLMChatWindow(backend=…)` injects a non-LLM
  backend; when omitted it builds an `LLMClient` and shows the model sidebar.
- `llm_client.py` — `LLMClient(ChatBackend)`. Deferred model loading;
  `send_message()` streams in a thread; emits `ready` on model load.
  Cancellation supported.
- `xmpp_client.py` — XMPP backend. `XmppSession(GObject)`: one nbxmpp
  connection per account on the GLib main loop, owns state, roster,
  presence and incoming-message routing; shared by all conversations of
  that account. Signals: `state-changed`, `session-error`,
  `roster-updated`, `message-received(jid, body)`,
  `presence-changed(jid, state)`, `contact-status-changed(jid)`,
  `subscription-request(jid)`. Presence is keyed on **bare JID**,
  aggregated across resources
  (`_online_resources`); a presence handler guards `jid is None` (an
  nbxmpp 7.2.0 bug crashes its own base handler on from-less presences).
  Transient disconnects schedule automatic reconnect with exponential
  backoff; deliberate disconnects and account-dialog probe sessions do not
  reconnect. NanoClaw contacts are detected from entity caps node
  `https://github.com/nanocoai/nanoclaw`; the full resource JID is retained
  for agent IQ commands, and presence `<status>` is exposed to the roster
  and chat header. Incoming message stanzas are also scanned for XEP-0439
  quick responses (`urn:xmpp:tmp:quick-response`), delivered through
  `ChatBackend.quick-responses`.
  `accept_subscription`/`deny_subscription` use the `BasePresence`
  module. `XmppConversation(ChatBackend)`: one per bare JID, maps XMPP
  messages/chat-states onto the contract (a whole message = `response` +
  optional `quick-responses` + `finished`). See
  `specs/archive/001-xmpp-backend/` for the base design
  and gotchas (silent auth failure, startup order, disconnect-as-error);
  `specs/002-xmpp-roster-notifications/` for presence/roster/notifications.
- `xmpp_commands.py` — XEP-0050/XEP-0004 client for NanoClaw agent
  commands. It uses nbxmpp's `AdHoc` and dataforms helpers to discover
  commands from the agent full JID, execute commands, render common form
  fields in a libadwaita dialog, and submit with `next`/`complete`.
- `xmpp_account.py` / `xmpp_account_dialog.py` — XMPP account: JID in a
  plain JSON file under the user dir, password in the system keyring
  (Secret Service, service `gtk-llm-chat-xmpp`); the dialog validates
  by connecting a throwaway session before persisting. Reachable any
  time via the header menu action `app.xmpp-account`.
- `xmpp_roster_dialog.py` — first-open contact picker (modal).
  `xmpp_roster_sidebar.py` — persistent in-window contact list with live
  presence dots (bound to `roster-updated` / `presence-changed`), docked
  left in XMPP windows; picking a contact goes through the app's
  `open_xmpp_conversation()` (focus-or-open, keyed
  `xmpp:<account>:<contact>`).
- Header entry points: a primary menu (`Gtk.MenuButton` in the window
  header) with "New LLM Conversation" (`app.new-conversation`), "New XMPP
  Conversation…" (`app.new-xmpp-conversation`), "XMPP Account…"
  (`app.xmpp-account`), reconnect/disconnect, and remove-account actions.
  XMPP windows add a left roster toggle button and a connection-status
  label; NanoClaw chats add an Agent menu with context actions (`/compact`,
  `/clear`) and discovered ad-hoc commands; incoming-message and subscription-request
  desktop notifications go through `Gio.Application.send_notification`
  with `app.open-xmpp` / `app.accept-xmpp-sub` / `app.deny-xmpp-sub`
  actions.
- `db_operations.py` — `ChatHistory`: read/write conversations in `llm`'s
  own `logs.db` (sqlite-utils + `llm.migrations.migrate`). ULIDs for ids.
  Thread-local connections. **XMPP conversations are not persisted here**
  — they use `xmpp_history.py` (spec 004) for local message cache with
  MAM backfill.
- `xmpp_history.py` — `XmppHistory`: local SQLite cache for XMPP messages
  per bare JID, with dedup via MAM archive id. Thread-local connections,
  same pattern as `ChatHistory` but own schema and file (`xmpp_history.db`).
- `stubs/llm/` — stub of the `llm` module enabling `--no-llm` UI-only mode
  (see `plans/NO_LLM_MODE_DOCUMENTATION.md`).

### Desktop integration

There is no system-tray applet (removed in spec 003 — it forked a second
process, talked to the main app over D-Bus, and depended on a vendored
`pystray` fork; a major portability and complexity cost for what the
in-window sidebars now cover). Conversation browsing lives in
`llm_conversation_sidebar.py` (LLM) and `xmpp_roster_sidebar.py` (XMPP),
docked left in each window (see "Conversation backends" above). The app
starts and stays a single process; `LLMChatApplication`'s D-Bus interface
(`OpenConversation`) still provides single-instance activation, so a
second `gtk-llm-chat --cid=…` invocation opens/focuses a window in the
existing process instead of starting a new one.

- `platform_utils.py` — platform detection, user dir resolution
  (`llm.user_dir()`), Flatpak detection.
- `resource_manager.py` — icons/resources across dev, frozen (PyInstaller)
  and Flatpak layouts.
- `style_manager.py` — per-platform CSS and window-control quirks
  (Windows margins, macOS decoration layout). The `haiku_port` branch
  refactors this into `styles/*.css` + GResource — consider adopting that
  refactor on main when Haiku work resumes.

### Compatibility shims

- `python313_compatibility.py`, `numpy_python313_patch.py`, `hooks/` —
  workarounds for frozen (PyInstaller) builds; `hooks/hook-llm*.py` teach
  PyInstaller about llm provider plugins.

## Packaging

- **PyInstaller**: `build.spec` + `build-ci.py` (all three OSes; CI in
  `.github/workflows/`).
- **Linux**: AppImage (CI), Flatpak (`linux/*.yml` + `linux/shared-modules`
  submodule), Arch (`linux/arch/PKGBUILD`).
- **Windows**: `windows/` (installer bits). **macOS**: `macos/` bundle bits.
- **PyPI / llm plugin**: standard wheel; entry point `llm` → `gtk_llm_chat.llm_gui`.

## i18n

gettext catalogs under `po/<lang>/LC_MESSAGES/gtk-llm-chat.po`;
helper scripts `update_po.sh`, `compile_po.sh`, `add_language.sh`.

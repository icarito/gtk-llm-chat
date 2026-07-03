# Architecture

How gtk-llm-chat actually works as of v4.0.5 (June 2025 codebase, revised
2026-07). The original 2025 design spec (subprocess-based, now obsolete) is
archived at [archive/spec-2025.md](archive/spec-2025.md).

## Big picture

```
                    ┌──────────────────────────────┐
 tray (pystray) ───▶│ LLMChatApplication (Adw.App) │◀── D-Bus OpenConversation(cid)
 llm gui / CLI ───▶ │  org.fuentelibre.gtk_llm_Chat│
                    │  one process, many windows   │
                    └──────────┬───────────────────┘
                               │ window per conversation (CID)
                    ┌──────────▼──────────┐
                    │  ChatWindow (+ UI)  │ chat_window.py, widgets.py,
                    │  sidebar, selector  │ chat_sidebar.py, markdownview.py
                    └──────────┬──────────┘
                               │ ChatBackend contract (GObject signals:
                               │ response/error/finished/ready/state-changed/typing)
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
  `-c`, template options, `--applet`), applies frozen-app compatibility
  patches (NumPy/Python 3.13), then either launches the tray applet or the
  chat application. `fork_or_spawn_applet` in platform_utils decides how.
- `llm_gui.py` — registers the app as an `llm` plugin (`llm gui`).
- `chat_application.py` — `LLMChatApplication(Adw.Application)`, application
  id `org.fuentelibre.gtk_llm_Chat`, `HANDLES_COMMAND_LINE`. Single instance
  per session; opening a conversation from outside goes through the D-Bus
  method `OpenConversation(cid)`. Keeps a CID → window map. Detects
  first-run and shows the welcome assistant (`welcome.py`).
- `single_instance.py` + `platform_utils.ensure_single_instance` — lockfile
  guard, mainly for the tray applet.

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
  (connection state; local backends may never emit it), `typing(bool)`.
  Methods: `send_message`, `cancel`, `get_conversation_id`,
  `get_display_name`, `notify_composing`, `shutdown`. `response` may
  stream (many emits) or arrive whole (one emit); always followed by
  `finished`. `LLMChatWindow(backend=…)` injects a non-LLM backend;
  when omitted it builds an `LLMClient` and shows the model sidebar.
- `llm_client.py` — `LLMClient(ChatBackend)`. Deferred model loading;
  `send_message()` streams in a thread; emits `ready` on model load.
  Cancellation supported.
- `xmpp_client.py` — XMPP backend. `XmppSession(GObject)`: one nbxmpp
  connection per account on the GLib main loop, owns state, roster,
  presence and incoming-message routing; shared by all conversations of
  that account. Signals: `state-changed`, `session-error`,
  `roster-updated`, `message-received(jid, body)`,
  `presence-changed(jid, state)`, `subscription-request(jid)`. Presence
  is keyed on **bare JID**, aggregated across resources
  (`_online_resources`); a presence handler guards `jid is None` (an
  nbxmpp 7.2.0 bug crashes its own base handler on from-less presences).
  `accept_subscription`/`deny_subscription` use the `BasePresence`
  module. `XmppConversation(ChatBackend)`: one per bare JID, maps XMPP
  messages/chat-states onto the contract (a whole message = `response` +
  `finished`). See `specs/archive/001-xmpp-backend/` for the base design
  and gotchas (silent auth failure, startup order, disconnect-as-error);
  `specs/002-xmpp-roster-notifications/` for presence/roster/notifications.
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
  Conversation…" (`app.new-xmpp-conversation`) and "XMPP Account…"
  (`app.xmpp-account`). XMPP windows add a left roster toggle button and
  a connection-status label; incoming-message and subscription-request
  desktop notifications go through `Gio.Application.send_notification`
  with `app.open-xmpp` / `app.accept-xmpp-sub` / `app.deny-xmpp-sub`
  actions.
- `db_operations.py` — `ChatHistory`: read/write conversations in `llm`'s
  own `logs.db` (sqlite-utils + `llm.migrations.migrate`). ULIDs for ids.
  Thread-local connections. **XMPP conversations are not persisted here**
  (spec 001: no local history in the MVP).
- `stubs/llm/` — stub of the `llm` module enabling `--no-llm` UI-only mode
  (see `plans/NO_LLM_MODE_DOCUMENTATION.md`).

### Desktop integration

- `tray_applet.py` — system tray icon (pystray; on Linux the
  `pystray-freedesktop` fork, vendored as submodule `linux/pystray`).
  Menu of recent conversations, watches `logs.db` with watchdog to stay
  fresh, opens conversations via D-Bus.
- `platform_utils.py` — platform detection, user dir resolution
  (`llm.user_dir()`), applet spawn/fork logic, Flatpak detection.
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

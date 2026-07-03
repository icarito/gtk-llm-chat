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
                               │ GObject signals (response/error/finished/model-loaded)
                    ┌──────────▼──────────┐        ┌────────────────────┐
                    │      LLMClient      │───────▶│ python-llm (in-proc)│
                    │  llm_client.py      │        │ + provider plugins  │
                    └──────────┬──────────┘        └────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │     ChatHistory     │──▶ ~/…/io.datasette.llm/logs.db
                    │  db_operations.py   │    (schema owned by llm.migrations)
                    └─────────────────────┘
```

Key decision: the LLM runs **in-process** through the `llm` Python API.
There is no subprocess, no stdout parsing. Streaming happens in a worker
thread; chunks are marshalled to the main loop with `GLib.idle_add` and
emitted as GObject signals.

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

### LLM integration

- `llm_client.py` — `LLMClient(GObject.Object)`. Signals: `response(str)`,
  `error(str)`, `finished(bool)`, `model-loaded(str)`. Deferred model
  loading; `send_message()` streams in a thread. Cancellation supported.
- `db_operations.py` — `ChatHistory`: read/write conversations in `llm`'s
  own `logs.db` (sqlite-utils + `llm.migrations.migrate`). ULIDs for ids.
  Thread-local connections.
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

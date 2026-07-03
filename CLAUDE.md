# Gtk LLM Chat — Agent Guide

Desktop chat application for Large Language Models, built with GTK4 + Libadwaita
on top of [python-llm](https://llm.datasette.io/) (Simon Willison's `llm`).
GPL-3.0-or-later. Website: https://gtk-llm-chat.fuentelibre.org/

## Source of truth

All standards and specifications live in `docs/` — read before making changes:

- [docs/base-standards.md](docs/base-standards.md) — development principles and conventions
- [docs/architecture.md](docs/architecture.md) — how the app actually works (modules, signals, flows)
- [docs/development-guide.md](docs/development-guide.md) — environment setup, running, packaging, i18n
- [docs/data-model.md](docs/data-model.md) — the `llm` SQLite database this app shares
- [docs/roadmap.md](docs/roadmap.md) — current direction and pending work

Feature work follows the spec-driven flow described in [specs/README.md](specs/README.md):
spec first, then tasks, then implementation in small verifiable steps.

## Quick facts

- Package: `gtk_llm_chat/` (flat module layout, no `src/`).
- Run from source: `.venv/bin/gtk-llm-chat` (venv uses `--system-site-packages`
  for PyGObject; see development guide).
- Entry points: CLI script `gtk-llm-chat` → `gtk_llm_chat.main:main`;
  also installable as an `llm` plugin exposing `llm gui`.
- The LLM integration is **embedded** (`llm_client.py` uses the `llm` Python API
  directly with threads + GObject signals). It is *not* a subprocess wrapper —
  old docs describing subprocess architecture are archived in `docs/archive/`.
- Conversations persist in `llm`'s own `logs.db` (shared with the CLI); schema
  is owned by `llm.migrations` — never migrate or alter it by hand.
- Versioning: `setuptools-scm` from git tags (`vX.Y.Z`). No manual version bumps.
- i18n: gettext, catalogs in `po/`. User-visible strings must be wrapped in `_()`.
- Multi-platform: Linux (AppImage, Flatpak, Arch), Windows, macOS; an experimental
  Haiku port lives in the `haiku_port` branch. Platform quirks are isolated in
  `platform_utils.py` and `style_manager.py` — keep it that way.

## Conventions

- flake8, max line length 95 (`pyproject.toml [tool.flake8]`).
- Never block the GTK main loop: long work goes to threads, results return
  via `GLib.idle_add` (see `llm_client.py` for the established pattern).
- Debug output through `debug_utils.debug_print` (activated by `DEBUG` env var),
  not bare `print`.
- Commit messages: short imperative subject; Spanish or English both occur in
  history, English preferred going forward.

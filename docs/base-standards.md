# Base Standards

Core development principles for gtk-llm-chat. Adapted from the
[LIDR specboot](https://github.com/LIDR-academy/lidr-specboot) methodology
for a Python/GTK desktop application.

## Process

1. **Spec before code.** Non-trivial changes start as a spec under `specs/`
   (see [specs/README.md](../specs/README.md)). Bug fixes with an obvious cause
   may skip the spec but not the verification.
2. **Small incremental tasks.** Each task in a spec's `tasks.md` should be
   completable and verifiable on its own. Prefer several small commits over
   one large one.
3. **Verify by running.** The app must launch and the affected flow must be
   exercised before a task is checked off. "It imports" is not verification.
4. **Review before merge.** Feature branches get a code review pass
   (self-review with a checklist at minimum) before merging to `main`.
5. **Archive completed specs** to `specs/archive/` so `specs/` only shows
   work in flight.

## Code

- Python ≥ 3.10 in practice (pyproject says 3.8, but GTK4/Libadwaita stacks
  in CI use ≥ 3.10; don't add syntax beyond what CI builds support).
- Style: flake8, line length ≤ 95, E402 tolerated (GTK requires
  `gi.require_version` before imports).
- Naming: descriptive, no abbreviations; modules snake_case, classes CapWords,
  GObject signals kebab-case (`model-loaded`).
- **Never block the GTK main loop.** Blocking calls (model loading, network,
  DB scans) run in `threading.Thread`; results come back with `GLib.idle_add`.
  The reference implementation of this pattern is `llm_client.py`.
- User-visible strings wrapped in `_()` (gettext). Update catalogs with
  `./update_po.sh` when strings change.
- Platform-specific behavior goes in `platform_utils.py` (logic) or
  `style_manager.py` (appearance) — never inline `sys.platform` checks
  scattered through UI code.
- Debug output via `debug_utils.debug_print` (gated by `DEBUG` env var).
- Follow GNOME HIG: Libadwaita widgets, 12px default spacing, system
  dark/light mode support.

## Documentation

- `docs/` is the single source of truth; update it in the same change that
  invalidates it.
- English for durable documentation; conversations and commit messages may
  be Spanish.
- Docstrings for public classes and non-obvious methods; comments only for
  constraints the code cannot express.

## Testing

- There is no formal test suite yet (see roadmap). New logic that can be
  tested headless (db_operations, markdown parsing, platform_utils) should
  come with pytest tests under `tests/` as it is touched — build coverage
  opportunistically, don't chase a percentage.
- UI verification is manual: run the app, exercise the flow, note it in
  the spec's tasks.
- `--no-llm` mode (stubs in `stubs/llm/`) allows running the UI without
  real models — useful for UI-only verification.

## Git

- `main` is releasable; features on branches.
- Versioning is automatic via setuptools-scm from tags `vX.Y.Z` — never
  hand-edit versions.
- Don't force-push shared branches; don't rewrite `main` history.
- Branch inventory and triage decisions: [branch-inventory.md](branch-inventory.md).

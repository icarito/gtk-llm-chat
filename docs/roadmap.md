# Roadmap

Revised 2026-07-03 on project resumption. The original 2025 checklist is
archived at [archive/todo-2025.md](archive/todo-2025.md) — everything
shipped in v4.x is dropped from this list.

## Next: killer features (2026)

> To be specified with the owner and developed through the spec-driven
> flow in [specs/](../specs/README.md). Each feature starts as
> `specs/<NNN>-<slug>/spec.md`.

- [ ] _(pending: capture and enrich the new feature ideas)_

## Parked work (resumable)

- **Haiku port** — branch `haiku_port` (+5 on main): native window
  controls, per-platform CSS files, GResource bundle. pystray-side
  experiments in `icarito/pystray@haiku-experiments`. The CSS/GResource
  refactor of `style_manager.py` is worth merging to main regardless of
  Haiku.
- **No-LLM mode** — branch `decouple_llm` (+1 on main): run UI without the
  `llm` package via `stubs/`.
- **Welcome druid rework** — branch `welcome-druid` (31 commits, diverged).
- **release.yml rework** — `stash@{0}` (−209/+97 lines, unfinished).
- **Flatpak modernization** — branch `flatpak-fix`.

## Carried over from the 2025 checklist (still open, still wanted)

- [ ] Test suite: start with headless-testable modules
      (`db_operations`, `markdownview`, `platform_utils`).
- [ ] Screen reader labels / accessibility audit.
- [ ] Keyboard shortcuts overlay (Ctrl+?).
- [ ] Retry mechanism for failed messages.
- [ ] Conversation search.
- [ ] Export/import conversations.
- [ ] User guide (usage, shortcuts, troubleshooting) + contribution guidelines.

## Housekeeping

- [ ] Branch triage round 2: delete confirmed-dead branches
      ([branch-inventory.md](branch-inventory.md)); decide fate of the three
      local-only branches (`ci/macos-builds`, `gtk3`, `performance_refactor`).
- [ ] Review `stash@{0}` (release.yml) and `stash@{1}` (resource_manager),
      then drop remaining stashes.
- [ ] Raise `requires-python` to `>=3.10` in pyproject to match reality.
- [ ] Absorb still-useful content from `plans/` (gitignored) into `docs/`.

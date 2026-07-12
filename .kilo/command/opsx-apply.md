---
description: Implement tasks from a spec's tasks.md checklist, updating artifacts as needed.
agent: code
---
You are running the `/opsx:apply` command from OpenSpec.

## Purpose

Implement the tasks from an existing spec's `tasks.md` checklist. Work through them methodically, committing per task or small groups.

## Context

This project is gtk-llm-chat. Architecture: `docs/architecture.md`. Development standards: `docs/base-standards.md`. Spec workflow: `specs/README.md`.

## Instructions

1. If the user did not specify which change, ask or infer from context. The change lives at `specs/NNN-short-slug/`.
2. Read `specs/NNN-short-slug/tasks.md` to get the task checklist.
3. Read `specs/NNN-short-slug/spec.md` and `specs/NNN-short-slug/design.md` (if exists) to understand constraints.
4. Work through tasks one at a time:
   - Mark the current task as in-progress (using `todowrite`)
   - Implement the change following existing code patterns and conventions
   - Verify the task works (read code, run tests if available, check lint)
   - Mark it complete in `tasks.md` (change `- [ ]` to `- [x]`)
   - Commit with a message referencing the spec (e.g., `spec/NNN: task 1.2 add foo`)
5. Follow these project conventions strictly:
   - flake8, max line length 95
   - Never block the GTK main loop (use threads + GLib.idle_add)
   - Debug output via `debug_utils.debug_print`, not bare `print`
   - User-visible strings wrapped in `_()`
   - Platform quirks isolated in `platform_utils.py` / `style_manager.py`
6. If implementation reveals the spec/design was wrong, pause and tell the user the spec needs updating first.
7. When all tasks are complete, report summary and suggest `/opsx:archive`.

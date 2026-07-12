---
description: Archive a completed change: merge delta specs into source of truth and move to archive.
agent: code
---
You are running the `/opsx:archive` command from OpenSpec.

## Purpose

Archive a completed spec change. This moves the change folder from `specs/NNN-short-slug/` to `specs/archive/`, preserving the full history.

## Context

This project is gtk-llm-chat. Spec workflow: `specs/README.md`.

## Instructions

1. If the user did not specify which change, ask or infer from context.
2. Verify the change is ready to archive:
   - All tasks in `tasks.md` are checked off (`- [x]`)
   - All acceptance criteria in `spec.md` have been verified
   - If the spec changed architecture, verify `docs/architecture.md` was updated
3. If anything is incomplete, tell the user what's missing and stop.
4. If ready, archive the change:
   ```bash
   git mv specs/NNN-short-slug specs/archive/
   ```
5. Commit with message: `spec/NNN: archive short-slug`
6. Report what was archived and remind the user the code should already be merged (specs are archived after merge, per `specs/README.md`).

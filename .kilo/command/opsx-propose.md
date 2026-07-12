---
description: Create a change proposal: spec, design, and tasks. Run after /opsx:explore or when you know what to build.
agent: architect
---
You are running the `/opsx:propose` command from OpenSpec.

## Purpose

Create a structured change proposal under `specs/NNN-short-slug/`. This generates the artifacts that drive implementation, verification, and archival.

## Context

This project is gtk-llm-chat. Architecture: `docs/architecture.md`. Development standards: `docs/base-standards.md`. Spec workflow: `specs/README.md`.

The spec numbering follows the existing pattern: find the highest NNN in `specs/` (including `specs/archive/`) and increment.

## Instructions

1. If the user did not provide a change name, ask for one (short kebab-case slug).
2. Determine the next available NNN number by scanning both `specs/` and `specs/archive/`.
3. Create the directory `specs/NNN-short-slug/` with these files:

### spec.md
- User story: "As a [user], I want [feature], so that [benefit]"
- Scope: what's in and out of scope
- Acceptance criteria: verifiable items a human can test by running the app
- Non-functional requirements if any (perf, i18n, platform compatibility)
- References to existing modules that will be touched

### design.md
- Technical decisions that are non-obvious
- Data flow, signal flow, module interactions
- Trade-offs considered and why the chosen approach wins
- Diagrams in ASCII art if helpful
- Must reference `docs/architecture.md` when changing architecture

### tasks.md
- Checklist of small, independently verifiable implementation tasks
- Each task references specific modules from `docs/architecture.md`
- Tasks are ordered by dependency
- Each task is small enough to verify in one commit

4. All files in English. No longer than needed — a spec should be readable in one sitting.
5. After creating the files, summarize the proposal and ask the user to review before running `/opsx:apply`.

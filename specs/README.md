# Specs — spec-driven change flow

> **Historical tree.** New changes start in `openspec/changes/` and use the
> shared `opsx:*` workflow. `specs/archive/` remains intact as project history.
> Spec 006 moved to the `gtk-llm-chat-android` repository.

The material below documents the previous lightweight adaptation of the cycle
(*enrich → new → artifacts → apply → verify → review → archive*)
for a solo-maintained desktop app.

## Layout

```
specs/
  README.md            ← this file
  NNN-short-slug/      ← one folder per change, numbered in order of creation
    spec.md            ← WHY and WHAT (user story, scope, acceptance criteria)
    tasks.md           ← HOW, as a checklist of small verifiable tasks
    design.md          ← optional: technical decisions when non-obvious
  archive/             ← completed changes move here untouched
```

## The cycle

1. **Enrich** — turn the raw idea into `spec.md`: user story
   ("As a user … I want … so that …"), in/out of scope, acceptance
   criteria that a human can verify by running the app.
2. **Plan** — derive `tasks.md`: small tasks, each independently
   verifiable, referencing the modules to touch
   (see [docs/architecture.md](../docs/architecture.md)).
3. **Apply** — implement task by task on a feature branch, committing per
   task or small groups. Follow
   [docs/base-standards.md](../docs/base-standards.md).
4. **Verify** — exercise every acceptance criterion in the running app
   (use `--no-llm` mode when models aren't needed); check off criteria in
   `spec.md`.
5. **Review** — adversarial pass over the full diff before merge
   (`/code-review` or equivalent).
6. **Archive** — after merge, `git mv specs/NNN-slug specs/archive/`.

## Conventions

- Specs are written in English, small enough to read in one sitting.
- A spec that changes architecture must update `docs/architecture.md`
  in the same change.
- If work reveals the spec was wrong, fix the spec first, then the code.

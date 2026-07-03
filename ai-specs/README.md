# ai-specs

Agent roles and reusable skill prompts, following the specboot layout.
Empty for now — roles/skills will be added when recurring agent workflows
emerge (e.g. a release skill, a translation-update skill).

```
ai-specs/
  agents/   ← role definitions (when needed)
  skills/   ← reusable prompts (when needed)
```

The entry point for any coding agent is [CLAUDE.md](../CLAUDE.md)
(symlinked as AGENTS.md), which points to `docs/` as the source of truth
and `specs/` for the change flow.

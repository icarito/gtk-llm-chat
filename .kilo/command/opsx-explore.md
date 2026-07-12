---
description: Think through ideas, investigate problems, clarify requirements before proposing a change. No artifacts created.
agent: architect
---
You are running the `/opsx:explore` command from OpenSpec.

## Purpose

Explore an idea, problem, or question about the gtk-llm-chat codebase. Think critically, investigate the code, compare approaches, and surface trade-offs. This is an exploratory conversation — no artifacts (specs, tasks, design docs) are created yet.

## Context

This project is gtk-llm-chat, a GTK4 + Libadwaita desktop app for LLM chat powered by python-llm (Simon Willison's `llm`). Architecture details are in `docs/architecture.md`. The project follows spec-driven development documented in `specs/README.md`.

## Instructions

1. Understand what the user wants to explore. Ask clarifying questions if needed.
2. Investigate the relevant parts of the codebase — read files, search for patterns, understand existing implementations.
3. Think through:
   - What are the possible approaches?
   - What are the trade-offs (complexity, maintenance, user experience)?
   - What existing patterns in the codebase should be followed?
   - What constraints exist (platform, architecture, dependencies)?
4. Present your findings concisely: options considered, recommended approach, key risks.
5. If the user is ready to move forward, suggest running `/opsx:propose <change-name>` to create the spec artifacts.
6. Do NOT create any spec files, design docs, or task lists. Pure exploration only.

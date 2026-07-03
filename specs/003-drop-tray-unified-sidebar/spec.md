# 003 — Drop the tray applet, unify navigation in sidebars

**Status:** in progress — see tasks.md
**Created:** 2026-07-03
**Owner:** Sebastian Silva
**Depends on:** 001 (ChatBackend, XMPP window), 002 (roster sidebar,
XMPP session lifecycle)

## User story

As a maintainer, I want to remove the system-tray applet — a major
source of complexity (separate process, D-Bus, fork/spawn, the vendored
`pystray` fork submodule, PyInstaller hooks) that makes porting hard —
and, as a user, still be able to browse and switch between my
conversations. The conversation list should live in a left sidebar that
mirrors the XMPP roster, so LLM and XMPP windows feel like one coherent,
styled design; secondary options move a level deeper.

## Why

The tray applet is the single biggest portability obstacle: it forks a
second process, talks to the main app over D-Bus, depends on the
`pystray-freedesktop` fork (a git submodule) and per-plugin PyInstaller
hooks, and its lifecycle logic (`fork_or_spawn_applet`, `--applet`,
lockfiles) leaks into `main.py`, `platform_utils.py`, `welcome.py` and
`chat_application.py`. Removing it simplifies startup, packaging and the
Haiku/Windows/macOS ports. The conversation list it provided is better
served by an in-window sidebar, consistent with the XMPP roster from 002.

## Acceptance criteria (MVP)

Status as of `236860c` (2026-07-03) — see tasks.md for the task-level
breakdown and evidence.

- [ ] 1. The tray applet is gone: no `tray_applet.py`, no `--applet`
         path, no `pystray` dependency, no `linux/pystray` submodule, no
         D-Bus/fork/lockfile machinery introduced solely for it. The app
         starts as a single process.
         **Not started.** `tray_applet.py`, `pystray`/`pystray-freedesktop`
         (requirements.txt, pyproject.toml) and the `linux/pystray`
         submodule are all still present and unchanged. This is the
         spec's actual reason for existing — see tasks.md T8.
- [x] 2. LLM conversation windows have a **left sidebar listing recent
         conversations** (mirroring the XMPP roster: same widget style,
         same left dock, same toggle button), replacing the tray's
         conversation menu. Selecting one opens/focuses it.
         Done: `llm_conversation_sidebar.py` (tasks.md T5). Caveat: see
         criterion 5/T7 — "opens/focuses" today always opens a *second*
         window rather than reusing a picker-mode window; whether that's
         acceptable is exactly T7's open question.
- [~] 3. Secondary options (model parameters, system prompt, API keys
         for LLM; account for XMPP) move to a **second level** of the
         sidebar — the sidebar's top level is the list (conversations or
         contacts), a row navigates into options. The header toolbar
         uses **two rows** to reduce clutter: row 1 primary actions,
         row 2 contextual.
         Sidebar second-level navigation: done for both LLM (T5) and XMPP
         (account dialog reachable from the header menu). Two-row header:
         done for XMPP windows (connection-status row); **not done** for
         LLM windows (still single header row).
- [x] 4. Lifecycle: closing the last window **quits the app UNLESS an
         XMPP session is connected** — closing a chat window must not log
         you out of XMPP (as no XMPP client would). With an active
         session the app keeps running headless and can resurface a
         conversation; with no session, last-window-close quits.
         (Verified headless 2026-07-03: `_on_close_request` checks
         `app._xmpp_session.is_connected` before quitting; also added
         Ctrl+Q as an explicit, unconditional quit shortcut.)
- [ ] 5. No regression: LLM chat (send/stream/rename/delete) and all of
         001/002's XMPP behavior (chat, typing, roster, presence,
         notifications) keep working.
         **Not formally verified since T1–T6 landed** — no pass has run
         end-to-end against the live app since these six commits went in
         ad-hoc. See tasks.md T9.

## Out of scope

- A unified LLM+XMPP list (kept as **one panel per type** — LLM windows
  list LLM conversations, XMPP windows list contacts; parallel designs,
  not merged, preserving the backend separation from 001).
- Reimplementing tray/indicator support in any form (StatusNotifier,
  AppIndicator). If desktop presence is wanted later it's a separate spec.
- New packaging targets; this only *removes* tray-related packaging.
- Autostart / "launch on login".

## Design intent (to be detailed in design.md)

- **Conversation sidebar**: a sibling of `XmppRosterSidebar` for LLM
  conversations (recent list from `ChatHistory.get_conversations`, live
  refresh on new/rename/delete). Both dock left via the window's
  `Adw.OverlaySplitView` (`PackType.START`), toggled from row-1 of the
  header. Second level = the existing options currently in
  `chat_sidebar.py` (`ModelSelectorWidget`, parameters, system prompt),
  reached by a row that switches the sidebar's `Gtk.Stack` page — the
  stack already has an "actions" vs deeper-pages pattern to build on.
- **Two-row header**: `Adw.ToolbarView` / stacked `Adw.HeaderBar`s, or a
  second `Adw.HeaderBar` — row 1: sidebar toggle, title, primary menu;
  row 2: contextual (connection status for XMPP, model subtitle for LLM,
  etc.). Exact split to be mocked in design.md.
- **Lifecycle**: replace the tray's always-`hold()` with a conditional
  hold — the app holds while `XmppSession.is_connected`, releases
  otherwise, so last-window-close quits only when no XMPP session is up.
  A minimal way to resurface a conversation without the tray (e.g. the
  `llm gui` entry point, or a notification) must remain.

## Risks

- The tray is entangled in `main.py` startup, `platform_utils.py`,
  `welcome.py` (the welcome druid offers to set up the tray) and
  `chat_application.py`. Removal must be surgical and each touched flow
  re-verified. This is the largest single change since the port resumed.
- Removing background persistence changes user-visible behavior; criteria
  4 pins the replacement semantics.

## Note on the external `feat/003-...-13113499902314437696` branch

A separate agent ("Jules") produced an independent implementation on that
branch, based on a commit (`798dcf1`) 7 commits behind current `main` at
the time this spec's real work landed. It takes a much more destructive
approach (see `b7826de`'s commit message for specifics) and predates the
picker/roster/two-level-sidebar/lifecycle work actually on `main`. Not a
base for anything here — reference only, do not merge. One idea from it
(the LLM conversation-list sidebar shape) was deliberately re-implemented
from scratch against this repo's actual patterns; see tasks.md T5.

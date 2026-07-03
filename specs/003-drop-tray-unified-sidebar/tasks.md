# 003 — Tasks

Written retroactively 2026-07-03: T1–T6 were implemented ad-hoc directly on
`main` (commits `4b197a0`..`236860c`) before this file existed, skipping the
spec→tasks→apply→verify→review→archive flow the repo otherwise follows.
Documented here from the actual commits/diffs (not from the stale spec.md
checkboxes) so the record is accurate, then the remaining work — most of it,
including the spec's actual reason for existing (criterion 1) — is broken
into real tasks.

Branch `feat/003-drop-tray-unified-sidebar-13113499902314437696` (external,
by another agent/"Jules", based on `798dcf1` — 7 commits behind current
`main`) is **not** a base for any of this. Reference only if ever useful;
do not merge.

## Phase 1 — Entry points (done, ad-hoc on main)

- [x] **T1. Chat-type picker on launch** (`400dda6`). New
      `chat_type_picker.py`: `Adw.StatusPage` with two choice-card buttons
      shown on any argument-less launch (`do_command_line` when
      `!has_args`, and `do_activate`'s D-Bus-activation fallback). Picking
      LLM routes to the welcome wizard if unconfigured, else straight to a
      new conversation; picking XMPP routes through
      `on_new_xmpp_conversation_activate` (account dialog if unconfigured,
      else the roster). Launches with explicit args (`--cid`, `--model`,
      `--template`, `--applet`) bypass the picker — verified as a
      regression case headless and live.
- [x] **T2. Add-contact row** (`400dda6`). `XmppSession.add_contact()`
      (`BasePresence.subscribe`); `XmppRosterSidebar` gained an
      "Add Contact…" row opening a JID-entry dialog. Verified headless.
- [x] **T3. Icon/copy polish on the picker** (`fa77ac0`, `ee6517f`).
      Dropped the redundant app icon and long copy; fixed `brain-symbolic`
      being illegible at 48px (dropped to 32px) and swapped
      `system-users-symbolic` for `chat-bubbles-empty-symbolic` on the
      XMPP button (a "person" icon is misleading once XMPP contacts
      include bots, e.g. the user's planned OpenClaw integration).

## Phase 2 — Sidebar unification (mostly done, criterion 2/3)

- [x] **T4. Replace the modal XMPP contact picker with the roster
      sidebar** (`952ede0`). Removed `xmpp_roster_dialog.py`.
      `LLMChatWindow` gained an `xmpp_session=` constructor path (backend
      still `None`, session live): the roster sidebar shows expanded
      immediately, input disabled, title "Choose a contact". Picking a
      contact opens/focuses that conversation and closes this placeholder
      window. Verified headless + regression (concrete-backend windows
      unaffected).
- [x] **T5. Two-level LLM conversation sidebar** (`b7826de`). New
      `llm_conversation_sidebar.py`: `LLMConversationSidebar` wraps the
      existing `ChatSidebar` as an "options" page behind a `Gtk.Stack`,
      alongside a new "list" page (`ChatHistory.get_conversations`,
      mirrors `XmppRosterSidebar`'s design — this is what replaces the
      tray's conversation menu, addressing spec.md's user story). Ctrl+M
      → options + model-selector page; Ctrl+S → options + system-prompt
      dialog; closing the sidebar resets both stack levels. List
      refreshes when a conversation gets its first CID and on rename.
      Verified headless: navigation, list rendering, shortcuts, refresh,
      regression (XMPP windows keep `model_sidebar`/`model_options` as
      `None`). **Not yet done**: the two-row header toolbar itself (spec.md
      criterion 3's "row 1 primary actions, row 2 contextual" for the LLM
      side — XMPP windows already show a connection-status second row, LLM
      windows still use a single header row).
- [x] **T6. Lifecycle: Ctrl+Q + conditional last-window-close**
      (`236860c`). Added Ctrl+Q (explicit, unconditional `app.quit()`).
      `_on_close_request` now quits on last-window-close only if
      `app._xmpp_session` is missing or disconnected; with a connected
      session the app stays alive in the background (`self.hold()` from
      `do_startup`, overridden by an explicit `quit()` when it does fire —
      verified). Verified headless: all four cases (Ctrl+Q, no session,
      connected session, disconnected-but-present session) plus the
      multi-window regression.

## Phase 3 — Remaining work

- [ ] **T7. Fix: selecting a contact/conversation should transform the
      current window, not open a new one and abandon the picker window.**
      Bug found in manual testing (not caught by the headless verification
      above, which checked *that* a new window opens, not *whether a
      second window is the right UX*). Both sides have the same shape:
      - `chat_window.py::_on_roster_contact_selected` (XMPP, ~L397) calls
        `app.open_xmpp_conversation(session, bare_jid)` then `self.close()`
        if the window was the contact-less picker (T4) — i.e. it always
        opens a *second* window and throws the first away, instead of
        reusing it.
      - `chat_window.py::_on_llm_conversation_selected` (LLM, ~L415) calls
        `app.open_conversation_window({'cid': cid})` — same shape, no
        window reuse at all (not even the close-the-picker fallback T4
        has).
      - `chat_application.py::open_conversation_window` (~L677) and
        `open_xmpp_conversation` always go through
        `_create_new_window_with_config`, which always constructs a fresh
        `LLMChatWindow` — there's no path to reconfigure an existing one.

      **Design needed before implementing**: `LLMChatWindow.__init__` does
      one-shot construction (chrome + backend binding together, ~1050
      lines, see architecture.md). Turning an existing window from
      "picker/list mode" into "conversation mode" in place means either
      (a) splitting `__init__` into a chrome-build phase and a
      backend-bind phase that can be called again, or (b) something
      narrower — e.g. only the two picker-shaped cases (T4's contact-less
      XMPP window, and clicking your own currently-open conversation in
      the LLM list) need to *not* spawn a second window; genuinely
      switching an *already-bound* conversation window to a different
      conversation might be out of scope. Decide the actual shape here
      before touching code — this is a navigation-model decision, not a
      one-line fix.
      *Verify:* clicking a contact in an empty XMPP roster window turns
      that window into the conversation (no second window, no orphaned
      roster window left behind); clicking a different conversation in
      the LLM sidebar likewise doesn't leave two windows for one intent.
      Regression: opening a conversation from a *different* window (not
      the picker) must still work as it does today (focus-or-open via the
      registry) — this task is about not creating *extra* windows for the
      picker-style entry points, not about changing focus-or-open
      semantics generally.

- [ ] **T8. Remove the tray applet entirely** (criterion 1 — the spec's
      actual reason for existing; not done yet despite being the headline
      goal). Break down:
      - [ ] Delete `gtk_llm_chat/tray_applet.py`.
      - [ ] Remove `pystray-freedesktop` / `pystray` from
        `requirements.txt` and `pyproject.toml`.
      - [ ] Remove the `linux/pystray` git submodule (confirm still present
        in `.gitmodules` before touching — `haiku_port`/`haiku-experiments`
        branches reference it too, don't break those if still wanted;
        check with the user before deleting a submodule with cross-branch
        history).
      - [ ] Remove `--applet` CLI flag, D-Bus applet activation, and any
        lockfile/fork logic that exists *solely* for the tray in
        `main.py`, `platform_utils.py`, `welcome.py` (the welcome druid
        offers to set up the tray), `chat_application.py`. Cross-check
        against `docs/architecture.md`'s "Desktop integration" section,
        which still documents `tray_applet.py` as load-bearing — update it
        in the same change.
      - [ ] Remove tray-specific PyInstaller hooks/spec entries
        (`build.spec`, `hooks/`) and the `.desktop` autostart entry
        (`desktop/org.fuentelibre.gtk_llm_Applet.desktop`) if it exists
        only for the tray.
      *Verify:* app builds/launches with `pystray` fully absent from the
      venv; no `--applet` code path reachable; PyInstaller build (or at
      least `build.spec` review) doesn't reference removed modules; a
      packaging smoke build if feasible.

- [ ] **T9. Explicit no-regression pass** (criterion 5). No formal
      verification has run since T1–T6 landed. Walk, in the real running
      app: LLM send/stream/rename/delete; XMPP 1:1 chat, typing indicators,
      roster with live presence, subscription accept/deny, incoming-message
      notifications (001+002's acceptance criteria). A second independent
      review pass (agent-based, as done for 001/002) is worth it given how
      much landed without one.

- [ ] **T10. Update spec.md checkboxes to match reality**, then continue
      the normal cycle: docs (`architecture.md`'s tray section, once T8
      lands), review, archive to `specs/archive/003-drop-tray-unified-sidebar/`,
      merge (already on `main` — this becomes closing the loop rather than
      an actual merge).

## Housekeeping (low priority, not blocking)

- [ ] Branch cleanup per `docs/branch-inventory.md` (if present) — old
      experiment branches, stale stashes. Unrelated to spec 003, do only
      if there's slack.

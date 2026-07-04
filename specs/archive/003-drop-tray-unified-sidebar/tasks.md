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

- [x] **T7. Fix: selecting a contact/conversation should transform the
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
      *Result (2026-07-03, commit `ee8baa6`):* went with option (a),
      the two-phase split, per the owner's call — chose durability over
      the narrower patch. `__init__` still builds chrome once; the old
      "Panel Lateral" section became `_bind_backend()`/`_unbind_backend()`,
      callable again on a live window. `_on_roster_contact_selected` now
      re-binds this window in place when it was the contact-less picker
      (registering it under the right `xmpp:...` key), and still defers
      to `open_xmpp_conversation`'s focus-or-open when the window already
      had a conversation. `_on_llm_conversation_selected` focuses an
      existing window for that cid if one is registered, else updates
      `config['cid']` and re-runs `_bind_backend(backend=None)` — the
      same LLM-branch code `__init__` uses to open an existing cid,
      reused for an in-place switch. Verified headless: all three
      pre-existing window modes unaffected; both new re-bind paths work
      (XMPP picker→contact, LLM conversation switch); the
      focus-existing-window fallback holds for both; the
      `show-sidebar`↔toggle-button `GObject.Binding` doesn't stack across
      repeated re-binds (tracked and `unbind()`'d in `_unbind_backend`,
      which also now backs `_on_close_request`, removing a
      previously-duplicated cleanup block). Real app clean on both entry
      paths. Noted, not fixed (pre-existing, out of scope):
      `LLMClient.cancel()` is a no-op, so switching conversations
      mid-stream doesn't cancel the old backend's thread.

- [x] **T9. Explicit no-regression pass** (criterion 5).
      *Result (2026-07-03):* independent agent-based verify pass, done
      *before* T8's surgery (deliberately reordered — a clean baseline
      before touching the tray). 37/37 assertions PASS: LLM
      send/stream/rename/delete, the full two-level sidebar navigation
      (Ctrl+M/S, close-resets-stack), XMPP baseline (001: connect,
      self-chat roundtrip, typing, status label), XMPP roster/
      notifications (002: live presence, message/subscription
      notification logic), and T1/T2/T4/T6's specific claims — all
      re-verified against real network/XMPP traffic, not just mocks.
      One real bug found (pre-dates spec 003, confirmed byte-identical
      at `798dcf1`): new LLM conversations never got a row in the
      `conversations` table (only `responses`), because
      `chat_window.py`'s `_on_llm_response` eagerly set `config['cid']`
      before `llm_client.py`'s creation guard ran, permanently
      defeating it. This directly undermined T5's new sidebar (new
      conversations were invisible to it) so it was fixed immediately
      (commit `d03ef8e`) rather than deferred — verified end-to-end
      against the real model: new conversation now appears in
      `get_conversations()` and in the live sidebar right after send.
- [x] **T8. Remove the tray applet entirely** (criterion 1 — the spec's
      actual reason for existing).
      *Result (2026-07-03):* done in three commits
      (`b51f501`/`ba44ae5`/`51f6981`). `tray_applet.py` deleted;
      `pystray`/`pystray-freedesktop`/`pyxdg`/`pillow`/`watchdog` dropped
      from dependencies (all were tray-only — `watchdog` fed the file
      watcher for the tray menu, `pyxdg`/`pillow` fed autostart/icon
      rendering); `linux/pystray` submodule removed via
      `deinit`+`rm` (haiku_port/haiku_build keep their own history,
      untouched — confirmed before touching it, per the earlier
      decision to ask first). `--applet` flag, `launch_tray_applet`/
      `fork_or_spawn_applet`/`spawn_tray_applet`/
      `send_ipc_open_conversation`/`ensure_single_instance`/autostart
      helpers all removed from `main.py`/`platform_utils.py`
      (738→285 lines)/`chat_application.py`/`llm_gui.py`.
      `welcome.py`'s entire tray-setup wizard page removed (was page 2
      of 4 in the `Adw.Carousel`), with every hardcoded page-index
      reference renumbered and verified via a real `GLib.MainLoop`
      (index math is easy to get wrong silently — confirmed 0→1→2
      navigation and button visibility at each page with actual
      wall-clock animation timing, not just iteration counts).
      `single_instance.py` also removed (orphaned once
      `ensure_single_instance` — its only caller — was gone).
      `build.spec`, the Flatpak manifest, and the Applet `.desktop` file
      updated/removed; `docs/architecture.md`, `development-guide.md`,
      `data-model.md`, `README.md` updated to drop stale tray mentions.
      *Verify:* real app launch shows **exactly one process** (`ps`
      confirmed no forked/spawned child) — the core goal. Zero
      tracebacks on both entry paths (`--model=...` opens directly; a
      bare launch shows the chat-type picker). One false-positive during
      verification, resolved: a stale D-Bus-registered instance from an
      earlier manual test made a bare launch look silently broken
      (`Gio.Application` forwarded args to the existing primary instance
      instead of starting fresh) — confirmed non-issue by killing the
      stale process and re-testing clean.

- [x] **T10. Update spec.md checkboxes to match reality**, then continue
      the normal cycle: docs (`architecture.md`'s tray section, once T8
      lands), review, archive to `specs/archive/003-drop-tray-unified-sidebar/`,
      merge (already on `main` — this becomes closing the loop rather than
      an actual merge).
      *Result (2026-07-03):* independent adversarial review of the full
      diff since `798dcf1` (tray removal + persistence fix + T7's
      two-phase refactor). Found and fixed one real bug introduced by T7
      (commit `ae9c948`): `_unbind_backend` dropped the old backend's
      reference without disconnecting its GObject signal handlers, and
      never reset the history-loaded flags or `messages_box`. Since
      `LLMClient.cancel()` (and therefore the default
      `ChatBackend.shutdown()`, which just calls `cancel()`) is a no-op,
      switching an in-place window to a different LLM conversation left
      the old `LLMClient`'s still-running stream thread able to mutate the
      window's now-current state (`cid`, `accumulated_response`, the
      active message widget) after the switch — and separately, the new
      conversation's history never rendered because the "already loaded"
      flags from the previous conversation were never cleared. Fixed by
      tracking handler ids and disconnecting them in `_unbind_backend`,
      alongside resetting the history flags and clearing `messages_box`
      (the same reset `__init__` already did for a fresh window, now also
      done on every rebind). Verified with a headless repro against the
      real `_unbind_backend` method (not a mock). Two trivial cleanups
      also applied: an orphaned `ChatSidebar` import (dead since T5) and a
      stale tray-applet comment (dead since T8). Everything else in the
      diff — tray removal, the `d03ef8e` persistence fix, the
      `_sidebar_toggle_binding` lifecycle, `welcome.py`'s carousel
      renumbering, reentrancy of sidebar replacement from within its own
      signal callback — reviewed and confirmed clean, no further findings.
      `docs/roadmap.md` updated to mark this spec done & archived.

## Housekeeping (low priority, not blocking)

- [ ] Branch cleanup per `docs/branch-inventory.md` (if present) — old
      experiment branches, stale stashes. Unrelated to spec 003, do only
      if there's slack.

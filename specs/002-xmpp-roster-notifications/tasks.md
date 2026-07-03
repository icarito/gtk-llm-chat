# 002 — Tasks

Small, individually verifiable. Feature branch: `feat/xmpp-roster-notifications`
(branch off `main` after 001 merges, or off `feat/xmpp-backend` if 001
isn't merged yet — decide at start).

## Phase 0 — Spike (done)

- [x] **T1. Presence + subscription spike** (`spike/spike_presence.py`):
      *Result (2026-07-03):* validated against yax.im. Incoming presence
      via `StanzaHandler(name='presence')` → `properties.type/show/jid`;
      presence module is `get_module('BasePresence')` with
      `subscribe/subscribed/unsubscribed`; subscription request is a
      presence with `type==SUBSCRIBE`. Found an nbxmpp 7.2.0 bug
      (`_process_presence_base` crashes on `from`-less presence) —
      guard documented in design.md. Multi-resource presence confirmed
      (must key on bare JID). See design.md → "Spike findings".

## Phase 1 — Presence in the session (no UI)

- [ ] **T2. Presence tracking in `XmppSession`**: register a presence
      handler; maintain `roster_items[bare_jid]['presence']`
      ('online'/'offline') aggregated across resources; emit a new
      `presence-changed(bare_jid, state)` signal. Guard against the
      None-`jid` case (design.md).
      *Verify:* headless — connect, log presence-changed events for the
      test account's own resources (open a second client / the Dino
      resource seen in the spike) and assert online→offline transitions.

## Phase 2 — Roster sidebar

- [ ] **T3. `XmppRosterSidebar` widget** (new): list of contacts with
      name + presence dot, bound to `roster-updated` and
      `presence-changed`. Model it on `chat_sidebar.py`.
      *Verify:* headless construct with a fake/populated session, assert
      rows render and a `presence-changed` emission flips the dot.
- [ ] **T4. Dock it left in the XMPP window**: add a second
      `Adw.OverlaySplitView` sidebar (or reuse with `PackType.START`)
      shown only for injected XMPP backends, with a header toggle
      button; selecting a contact focuses-or-opens that conversation
      (per design.md's leaning). Retire the modal `XmppRosterDialog` as
      the primary picker (keep it only if still needed for first open).
      *Verify:* run the app, open an XMPP conversation, confirm the
      left sidebar lists contacts with live presence and picking one
      opens/focuses its window. Regression: LLM windows and 001's
      right-side model sidebar unchanged. (AC 1, AC 2)

## Phase 3 — Notifications

- [ ] **T5. Incoming-message notifications**: when a message arrives and
      its conversation window isn't focused (or doesn't exist), fire a
      `Gio.Notification` (id = bare JID); default action opens/focuses
      the conversation. Track per-window focus.
      *Verify:* send a message from a second client to the test account
      while the window is unfocused/closed; confirm the notification
      appears and clicking it focuses/opens the chat. (AC 3)
- [ ] **T6. Subscription-request notifications**: `XmppSession` emits
      `subscription-request(bare_jid)`; app shows a notification with
      Accept/Deny actions wired to `BasePresence.subscribed/unsubscribed`.
      *Verify:* trigger a subscribe request from a second account/client;
      confirm the notification with both actions, and that Accept adds
      the contact (roster-updated) while Deny doesn't. (AC 4)

## Phase 4 — Hardening & docs

- [ ] **T7. i18n**: new strings wrapped in `_()`; run `./update_po.sh`.
- [ ] **T8. Verification pass**: walk all 4 acceptance criteria in the
      running app against yax.im; check them off in `spec.md`.
      Regression pass over 001's 5 criteria and the LLM flow.
- [ ] **T9. Docs**: update `docs/architecture.md` (presence, roster
      sidebar, notifications) in the same change.
- [ ] **T10. Review & archive**: adversarial review of the branch;
      merge; `git mv specs/002-xmpp-roster-notifications specs/archive/`.

## Note on test infrastructure

Several acceptance criteria (AC 3, AC 4, and T2's offline transition)
genuinely need a *second* XMPP identity to exercise — the self-chat
reflection trick from 001 doesn't produce subscription requests or
contact-initiated messages. Before Phase 3, either register a second
yax.im test account or use the already-observed Dino resource on the
same account. Decide and note it here.

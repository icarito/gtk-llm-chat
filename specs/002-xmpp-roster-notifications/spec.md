# 002 — XMPP Roster & Notifications

**Status:** draft — pending review
**Created:** 2026-07-03
**Owner:** Sebastian Silva
**Depends on:** [001-xmpp-backend](../001-xmpp-backend/spec.md) (`XmppSession`,
`XmppConversation`, `ChatBackend` contract)

## User story

As a gtk-llm-chat user chatting over XMPP, I want a persistent contact
list with live presence and desktop notifications, so that I can see
who's around and know when I get a message without keeping every chat
window focused — the same baseline experience any XMPP client
(Dino, Conversations, Gajim) already gives me.

## Why this is a separate spec from 001

001 proved the protocol and the backend contract end-to-end (connect,
roster fetch, message round-trip, typing) but deliberately scoped the
roster down to a disposable picker dialog with no presence, and shipped
no notifications at all. Those are big enough pieces of UI/behavior —
and orthogonal enough to the backend plumbing — to deserve their own
spec rather than reopening 001's acceptance criteria after the fact.

## Acceptance criteria (MVP)

The user can:

- [ ] 1. See a persistent contact list, as a left-side panel in XMPP
         conversation windows (mirrors the LLM model sidebar, mirrored
         to the opposite edge), replacing today's disposable roster
         dialog. Selecting a different contact switches the
         conversation without closing the window.
- [ ] 2. See each contact's presence (online / offline at minimum) in
         that list, updated live as contacts connect/disconnect.
- [ ] 3. Receive a desktop notification when an XMPP message arrives
         and its conversation window isn't focused (or doesn't exist
         yet); clicking the notification focuses/opens that
         conversation.
- [ ] 4. Receive a desktop notification when someone requests to
         subscribe to their roster, with actions to Accept or Deny
         directly from the notification.

## Out of scope (this spec)

- away/dnd/xa presence granularity (Layer 3 polish; online/offline only
  here)
- A standalone contact-list window or tray-applet integration (the
  sidebar-per-window design below supersedes those alternatives for now)
- Notifications for presence changes of existing contacts (only new
  messages and subscription requests, per the acceptance criteria)
- Editing roster entries (rename, delete, add contact manually) —
  read-only roster display beyond accept/deny subscriptions
- Local persistence of anything (still no local history/roster cache,
  consistent with 001 — the roster is always live from the session)

## UI shape

Mirrors the LLM model-sidebar pattern (`chat_sidebar.py` +
`Adw.OverlaySplitView`) but on the **opposite edge**: the existing
model sidebar docks at `Gtk.PackType.END` (right); the XMPP roster
sidebar docks at `Gtk.PackType.START` (left), so a future window that
somehow needs both never has them collide. A toggle button in the
header (mirroring `sidebar_button`) shows/hides it. Each row shows
contact name, presence dot, and (later, out of scope here) unread
indicator.

Notifications use `Gio.Application.send_notification()` (already have
`Adw.Application`; no new dependency) with a stable notification ID per
conversation so repeated messages update rather than stack.

## Constraints

- Follow [docs/base-standards.md](../../docs/base-standards.md) and the
  `ChatBackend` contract rules in
  [001's design.md](../001-xmpp-backend/design.md) — no blocking calls,
  signals marshalled via GLib.
- Must not regress 001's acceptance criteria (1:1 chat, typing,
  connection status) or the LLM flow.
- Presence and subscription requests are both XEP/RFC 6121 roster
  push + `<presence>` stanzas nbxmpp already exposes
  (`client.get_module('Roster')`, presence handlers) — no new protocol
  library needed.

## Open questions for design.md

- Exact nbxmpp API for presence subscription requests and for sending
  accept/deny (`Presence` stanzas with `subscribed`/`unsubscribed`
  types) — needs a short spike similar to 001's T1, reusing the
  existing test account.
- Whether the roster sidebar is per-window (one roster per open XMPP
  window, all showing the same session) or the app keeps one shared
  roster widget reparented — leaning per-window for simplicity, to
  confirm once the sidebar is prototyped.

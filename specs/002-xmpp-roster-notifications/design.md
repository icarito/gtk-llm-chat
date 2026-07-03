# 002 — Design notes

Builds on [001's design](../001-xmpp-backend/design.md). Same library
(nbxmpp 7.2.0, GLib-native), same `XmppSession`/`ChatBackend` structure.

## Spike findings (presence + subscriptions, 2026-07-03)

`spike/spike_presence.py` run against yax.im. Resolves the spec's open
technical questions:

- **Incoming presence** surfaces through a `StanzaHandler(name='presence')`
  callback with `properties.type` (`PresenceType.AVAILABLE` /
  `UNAVAILABLE` / `SUBSCRIBE` / …), `properties.show`
  (`PresenceShow.ONLINE` / `AWAY` / …) and `properties.jid` (the full
  from-JID). Confirmed live: saw `AVAILABLE/ONLINE` and a self-sent
  `AWAY` reflected, including presence from a *second* resource
  (`…/dino.eb7dc749`) — so presence tracking must key on **bare JID**
  and aggregate resources (a contact is "online" if any resource is).
- **The presence module is `get_module('BasePresence')`** (not
  `'Presence'` — that KeyErrors). It exposes `subscribe(jid)`,
  `subscribed(jid)` (accept), `unsubscribed(jid)` (deny),
  `unsubscribe(jid)`.
- **A subscription request** arrives as a presence with
  `type == PresenceType.SUBSCRIBE`; accept with
  `get_module('BasePresence').subscribed(from_jid)`, deny with
  `.unsubscribed(from_jid)`.

### ⚠️ Known nbxmpp 7.2.0 bug to guard against

`modules/presence.py::_process_presence_base` (nbxmpp's own priority-10
handler, runs before ours) does
`properties.jid.bare_match(own_jid)` **without checking `jid is None`**.
A presence stanza with no `from` (some server-originated presences)
makes it raise `AttributeError` — logged to stderr, but the stream
survives (verified: the spike kept running). We can't prevent that
handler from running. Mitigation for our code: never assume every
presence produces a clean event; drive the roster UI from
roster-push + the presences that *do* carry a JID, and treat our own
handler defensively (`if properties.jid is None: return`). If it proves
noisy, consider pinning/patching nbxmpp — track separately, don't block
this spec on it.

## Presence model

`XmppSession` extends its `roster_items[bare_jid]` dict with a
`presence` field ('online' / 'offline'), updated from the presence
handler (bare-JID keyed, resource-aggregated) and emits a new
`presence-changed(bare_jid, state)` signal. `roster-updated` already
exists for roster structure changes.

## Roster sidebar

Mirror of the LLM model sidebar (`chat_sidebar.py` in an
`Adw.OverlaySplitView`) but docked **left** (`Gtk.PackType.START`) vs
the model sidebar's right (`END`) — see spec. Rows: contact name +
presence dot, bound to the session's `presence-changed`. Selecting a
row swaps the window's backend to that contact's `XmppConversation`
(the window already supports an injected backend from 001 T5/T6; here
we let it re-bind live rather than only at construction).

Open question to settle while building: re-binding the backend of a
live window vs opening/focusing a separate window per contact. Leaning
toward "focus-or-open per contact" (reuses 001's
`_window_by_cid`-style registry idea) since re-binding mid-window
means tearing down signal connections cleanly — simpler to keep one
window = one contact.

## Notifications

`Gio.Application.send_notification(id, Gio.Notification)` — no new
dependency (we have `Adw.Application`). Two triggers:

1. **Incoming message, window unfocused/absent**: notification id =
   the bare JID (so repeats replace, not stack); default action
   focuses/opens that conversation. Needs the app to track window
   focus (`is_active`) per conversation.
2. **Subscription request**: notification with two actions
   (Accept → `subscribed`, Deny → `unsubscribed`). Actions wired as
   app-level `Gio.SimpleAction`s parameterised by the requester JID.

`XmppSession` grows a `subscription-request(bare_jid)` signal; the app
turns it into the notification.

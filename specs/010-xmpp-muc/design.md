# Design notes — Spec 010 (MUC + notification policy)

Decisions that are not obvious from the spec. Everything else follows the
existing architecture (docs/architecture.md).

## 1. One `XmppSession`, not a parallel MUC session

Rooms are handled by the existing `XmppSession` (xmpp_client.py), not a new
class. Rationale: nbxmpp multiplexes everything over the one stream anyway;
presence, MAM, reconnection and backoff logic are already there and MUC needs
all of them. MUC state lives in a `self._rooms: dict[str, RoomState]` where
`RoomState` is a small dataclass: `nick`, `subject`, `occupants: dict`,
`joined: bool`, `notify_mode`.

## 2. Signal surface (GObject)

Extend, don't overload. New signals on `XmppSession`:

- `muc-message-received(room_jid: str, nick: str, body: str, is_own: bool,
  timestamp: str)` — live groupchat traffic. Keeping it separate from
  `message-received` means spec 002's notification handler and every existing
  1-to-1 consumer stay untouched (they must not start seeing room traffic by
  accident).
- `muc-joined(room_jid)`, `muc-left(room_jid, reason)` — drive UI state.
- `muc-subject-changed(room_jid, subject)`.
- `muc-occupants-changed(room_jid)` — coarse-grained; UI re-reads
  `get_occupants(room_jid)`. Fine-grained add/remove signals are not worth
  the plumbing for a list that redraws cheaply.
- `muc-invitation(room_jid, from_jid, reason)` — both mediated and direct
  invites normalize to this.

## 3. Own-echo detection

A groupchat message is "mine" iff `from` resource == our current nick in that
room. Track nick changes (the service can rename you on conflict, presence
code 210). Do NOT rely on origin-id round-tripping — servers vary. This is
the same class of bug as the Android telemetry attribute traps: write the
dedup test against the live server in the T1 spike before trusting it.

## 4. MUC MAM

Query MAM *addressed to the room JID* (the room keeps its own archive), with
`start` = last seen timestamp for that room. Reuse the spec 004 insert-by-
timestamp + dedup path — the 1-week-overlap lesson (gtk_message_order_bug)
applies identically. Dedup key: MAM stanza-id vs live message stanza-id when
present, else (nick, body, rounded-timestamp) as last resort.

## 5. Bookmarks / persistence

Try XEP-0402 (PEP native bookmarks) via nbxmpp's bookmarks module; it gives
interop with Gajim/Cheogram on the same account. If the account's server
lacks the PEP feature, fall back to a local JSON section in the app config
(same store that will hold `notify_mode`). The abstraction is one small
`RoomStore` with `list() / save(room) / remove(room)` — callers never know
which backend served them. Local `notify_mode` is *always* local (bookmarks
have no field for it).

## 6. Window/registry integration (spec 009 world)

Room conversations register as `xmpp-muc:<account>:<room_jid>` in
`_window_by_cid`. The room window is the existing chat window with a
`ChatBackend` variant (`MucBackend` implementing the same contract 009
formalizes). Nick attribution renders as sender label above the bubble
(colored via a stable hash of the nick → accent palette), no avatar column.

## 7. Notification policy & unread counters

- Policy decision point: `chat_application._on_xmpp_message_received` stays
  1-to-1-only; a new `_on_muc_message_received` applies the per-room mode
  (default `mentions`). Mention = case-insensitive whole-word match of our
  nick in the body (word boundary; nick "ana" must not fire on "banana").
- Unread counters live in the sidebar model (per conversation key, both
  kinds), incremented by the same handlers that decide about notifications,
  cleared by window `notify::is-active`. Withdrawal:
  `app.withdraw_notification(id)` with the existing per-conversation id
  scheme (`xmpp-msg:<jid>` → also `xmpp-muc:<room>`).

## 8. Reconnect / rejoin

On `_on_connected` after a drop, re-send presence to every `RoomState` with
`joined=True`, with MAM catch-up from last seen. This mirrors what the
OpenClaw plugin does server-side (memory: re-join MUC prepared in xmpp.ts).

## Known traps checklist (from project memory, do not rediscover)

- MUC component is a **subdomain**; discover via disco#items, don't guess.
- nbxmpp leaves custom payloads in `.item`, attributes not text.
- Without `+notify` caps, PEP (bookmarks!) never pushes — check caps string.
- Never block the main loop: joins/MAM are async task callbacks with
  `GLib.idle_add` marshalling, like every other nbxmpp call in the file.

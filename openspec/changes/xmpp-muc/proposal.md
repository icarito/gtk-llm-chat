# Spec 010: Group chats (MUC) and a human-grade notification policy

## User Story

As a gtk-llm-chat user, I want to join XMPP group chats (MUC rooms) and talk
with other humans there — not only 1-to-1 with agents — so that this client
can be my everyday XMPP client on `hablar.fuentelibre.org` and federated
servers.

As a user who is in rooms with real people, I want notifications that respect
my attention: a busy room should only alert me when someone mentions my nick,
while a direct message should always alert me, and the sidebar should show me
at a glance where the unread messages are.

## Why now

The server side already works: the OpenClaw gateway joins rooms by invitation
and answers in them (sala `ulefote` with Rolando has been live since
2026-07-11). The GTK client is the missing half — today it silently drops
`type=groupchat` stanzas, so a human using this client cannot even see the
room the agent is in. "Full XMPP client" starts here.

## Scope

### In

1. **Join/leave rooms** (XEP-0045): join by address + nick, leave, rejoin on
   reconnect. Room address entered by hand or received via invitation.
2. **Invitations**: accepting mediated (XEP-0045 §7.8) and direct (XEP-0249)
   invites — this is how agents pull humans into rooms today.
3. **Groupchat messaging**: send and receive `type=groupchat` messages with
   correct nick attribution; own-message echo recognized as "mine" (no
   duplicate bubble); room subject shown.
4. **Occupants**: track who is in the room (join/leave presence); show the
   occupant list (a simple popover or sidebar section is enough).
5. **History**: MUC MAM catch-up on join (XEP-0313 addressed to the room),
   deduplicated against live traffic, inserted by timestamp — reusing the
   spec 004 machinery and its lessons (see memory: insert-by-timestamp).
6. **Persistence / autojoin**: joined rooms survive a restart. Native
   bookmarks (XEP-0402) if the server supports them, otherwise a local
   fallback; either way invisible to the user ("my rooms are just there").
7. **Notification policy**:
   - Direct chats: notify always when unfocused (current behavior, kept).
   - Rooms: notify only on nick mention by default; per-room override
     (All / Mentions / Nothing) stored with the room.
   - Sidebar shows per-conversation unread counters (rooms and 1-to-1);
     counters clear when the conversation window gains focus.
   - Notifications are withdrawn when their conversation is read.
8. **Roster integration**: rooms appear in the unified sidebar (spec 003/009
   world) as first-class conversations, with the `xmpp-muc:<account>:<room>`
   window-registry key convention.

### Out

- Room administration: configuration forms, kick/ban, affiliations,
  moderation (XEP-0425). Join, talk, leave — nothing more.
- Private messages to occupants (whisper). Can be a later spec.
- OMEMO or any encryption.
- Avatars for rooms/occupants (1-to-1 avatar work continues separately).
- File upload *to rooms* is a stretch goal (S1 below), not a criterion.
- Android client parity (tracked in the Android repo).

## Acceptance criteria

Verified by a human running the app against `hablar.fuentelibre.org`:

- [ ] 1. From the sidebar I can "Join a group chat", type
         `room@salas.hablar.fuentelibre.org` and a nick, and the room opens
         as a conversation window showing its subject and recent history.
- [ ] 2. Messages I send appear once (no echo duplicate); messages from
         others show their nick; two different senders are visually
         distinguishable (nick color or label).
- [ ] 3. When another participant (e.g. Rolando's agent, or a second client
         logged in as another user) mentions my nick while the room window
         is unfocused, I get a desktop notification; ordinary room chatter
         produces no notification but increments the sidebar unread badge.
- [ ] 4. A direct 1-to-1 message still notifies as before; its unread badge
         increments and clears on focus.
- [ ] 5. An invitation from an agent or another user pops a notification /
         dialog; accepting it joins and persists the room.
- [ ] 6. After quitting and relaunching the app, my rooms rejoin
         automatically and show history since I left (MAM catch-up).
- [ ] 7. The occupant list shows who is in the room and updates when
         someone joins or leaves.

### Stretch (nice, not blocking)

- [ ] S1. Attach button works in room windows (XEP-0363 upload + OOB link
          to the room), reusing the spec-82eb6d9 send path.
- [ ] S2. Per-room notification mode selectable from the room window's
          menu (All / Mentions / Nothing).

## Notes

- nbxmpp is Gajim's wire library and ships MUC building blocks
  (`nbxmpp.modules.muc`, bookmarks, direct invitations). Prefer its modules
  over hand-rolled stanzas — but expect the usual first-contact bugs
  (attribute-vs-text, domain-vs-subdomain) when touching new XEP surface;
  verify against the live server early (T1 spike) before building UI.
- The MUC service on hablar lives on a dedicated subdomain — discover it via
  disco#items on the account domain (same lesson as the upload service),
  never hardcode.
- This spec changes `docs/architecture.md` (new signal shapes, new window
  key): update it as part of the change, per specs/README.md conventions.

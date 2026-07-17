# Tasks — Spec 010 (MUC + notification policy)

Each task is independently verifiable. Feature branch: `feat/010-xmpp-muc`.
Live server for verification: `hablar.fuentelibre.org` (sala `ulefote` exists
and has an agent in it — a free conversation partner for testing).

- [ ] **T1 — Spike: nbxmpp MUC against the live server.**
      Standalone script under `specs/010-xmpp-muc/spike/` (pattern of
      001's `spike_nbxmpp.py`): discover the MUC service via disco#items,
      join `ulefote` with a test nick, print live groupchat messages with
      nick + own-echo flag, send one message, leave. Proves: service
      discovery, join handshake, echo detection (design §3). No GTK.

- [ ] **T2 — `XmppSession` room core.**
      `join_room(room_jid, nick)`, `leave_room(room_jid)`, `RoomState`
      dict, `send_muc_text()`, signals `muc-joined/left/message-received/
      subject-changed` (design §2). Occupant tracking from MUC presence +
      `muc-occupants-changed`. Unit-testable parsing helpers split out like
      `_parse_oob_url` is today.

- [ ] **T3 — Room window (UI).**
      `MucBackend` (ChatBackend contract) + window registration under
      `xmpp-muc:<account>:<room>`; nick label + stable color hash on
      bubbles; subject as window subtitle; occupant list popover fed by
      `get_occupants()`. Verify: two clients in `ulefote`, criterion 2 + 7.

- [ ] **T4 — Sidebar: rooms section + "Join a group chat…" dialog.**
      Rooms listed as conversations in the unified sidebar; join dialog
      (room address + nick, pre-filled MUC domain from discovery). Verify:
      criterion 1.

- [ ] **T5 — MUC MAM catch-up.**
      MAM query addressed to the room on join, insert-by-timestamp + dedup
      into the room window (design §4). Verify: join a room with history →
      backlog appears once, ordered; no duplicates with live traffic.

- [ ] **T6 — Invitations.**
      Normalize mediated + direct invites to `muc-invitation`; notification
      with Accept/Ignore buttons (pattern of the spec 002 subscription
      notification). Accept → join + persist. Verify: criterion 5 (have an
      agent send the invite, as in the 2026-07-11 server rollout).

- [ ] **T7 — Persistence + autojoin + rejoin.**
      `RoomStore` (XEP-0402 with local fallback, design §5); autojoin on
      connect; rejoin on reconnect with MAM since last-seen. Verify:
      criterion 6, plus kill the TCP connection and watch the rejoin.

- [ ] **T8 — Notification policy + unread counters.**
      `_on_muc_message_received` in chat_application with mention detection
      (word-boundary, design §7); default mode `mentions`; unread badges in
      sidebar for both room and 1-to-1 conversations, cleared on focus,
      notifications withdrawn on read. Verify: criteria 3 + 4.

- [ ] **T9 — Docs + i18n + review.**
      Update `docs/architecture.md` (new signals, MucBackend, window key);
      all new user-visible strings in `_()` + `update_po.sh`; adversarial
      `/code-review` pass over the branch diff.

- [ ] **T10 — Live acceptance run.**
      Walk criteria 1–7 in the running app against hablar, check them off
      in spec.md with date + evidence notes (the 002/004 style).

Stretch, only after T10: S1 attach-to-room (reuse `send_file` with the room
JID + groupchat OOB), S2 per-room notify mode in the window menu.

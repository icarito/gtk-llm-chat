# 001 — XMPP Backend: chat with personal agents over XMPP

**Status:** ready for implementation
**Created:** 2026-07-03
**Owner:** Sebastian Silva

## User story

As a gtk-llm-chat user, I want to chat with my personal AI agents
(NanoClaw, OpenClaw) and human contacts through XMPP, so that my desktop
chat app speaks an open federated protocol instead of only proprietary
LLM APIs — and any XMPP client anywhere can talk to my agents too.

## Why XMPP

- Open, federated IETF standard, supported by dozens of clients
  (Dino, Conversations, Gajim…).
- Rich native features on the protocol level: typing indicators,
  multi-device, file transfer, E2EE, group rooms — available to grow into.
- Gives NanoClaw/OpenClaw a channel they don't have today (a `/add-xmpp`
  channel for NanoClaw is already planned on that side).
- This app becomes a native desktop messenger for AI agents:
  gtk-llm-chat ↔ XMPP ↔ NanoClaw.

## Product decisions (resolved 2026-07-03)

1. **Backend is chosen per conversation.** When creating a conversation
   the user picks either an LLM model or an XMPP contact from the same
   selector (the roster appears alongside the providers). LLM and XMPP
   windows coexist at runtime. The `llm` backend is **not** removed.
2. **No local history in MVP.** XMPP windows show the live session only;
   closing the window discards it. Server-side history (XEP-0313 MAM)
   arrives in Layer 2. We never write XMPP messages into `llm`'s
   `logs.db` (see [docs/data-model.md](../../docs/data-model.md)).
3. **Credentials in the system keyring.** Password via Secret Service
   (python-keyring); JID in a plain config file in the user dir.
   Same approach as Gajim.

## Acceptance criteria (MVP)

The user can (all verified live against yax.im, 2026-07-03 — see
tasks.md T10 for the full report):

- [x] 1. Enter their JID (`user@yax.im`) and password in an account setup UI;
         the password is stored in the system keyring, not on disk.
- [x] 2. Connect successfully to yax.im (public XMPP server with open
         registration); connection state (connected/disconnected/error)
         is visible in the UI.
- [x] 3. Pick a contact from their roster when starting a new conversation.
         (Scope note: via a separate entry point / roster dialog, not the
         LLM model selector — see design.md "Selector integration".)
- [x] 4. Send and receive text messages with that contact in a chat window.
         (Verified via self-chat reflection; a review pass caught and fixed
         a dangling-empty-bubble bug that only manifests with a real remote
         peer — see tasks.md T10.)
- [x] 5. See "contact is typing…" (XEP-0085 chat states), and the remote
         side sees ours.

## Out of scope (MVP)

- OMEMO encryption
- Group rooms (MUC)
- File transfer
- Server-side history (MAM) / any local persistence
- Multi-device sync
- In-app XMPP account registration (user registers on yax.im beforehand)

## UI refocus for XMPP conversations

The current UI is built around model selection, API keys and generation
parameters — none of which apply to an XMPP conversation:

| LLM conversation | XMPP conversation |
|---|---|
| Model/provider selector | Roster (contact list) |
| "model loaded" | Connection state |
| Provider/model in header | Contact name + avatar |
| Sidebar: temperature, system prompt | Sidebar: account/connection info (minimal in MVP) |
| Chat window, streaming bubbles | Chat window (same widgets) |

The chat window itself is reused; what changes is the backend behind it
and which controls are visible.

## Constraints

- Follow [docs/base-standards.md](../../docs/base-standards.md): never
  block the GTK main loop; user-visible strings in `_()`; platform quirks
  stay out of UI code.
- The abstraction must not degrade the existing LLM flow — regression
  criterion: LLM conversations behave exactly as before.
- Library decision (nbxmpp vs slixmpp) is validated by a spike, see
  [design.md](design.md).

## Layering

This is **Layer 1** of the XMPP roadmap. Layer 2+: MAM history, MUC,
PubSub, OMEMO, avatars/vCards beyond the basics, file transfer.

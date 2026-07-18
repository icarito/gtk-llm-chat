# Spec 011: Streaming, progress and approval UX polish

## User Story

As a gtk-llm-chat user talking to OpenClaw agents, I want the client to feel
as alive as Telegram does: I see the agent typing, I watch its single answer
bubble grow and correct itself while it works, I can tell tool activity from
prose, approvals are one tap, and agents have faces (avatars) — so that the
XMPP path is not the "second-class" way to reach my agents.

## Why now

The gateway side reached parity on 2026-07-18: the XMPP plugin now streams a
single per-turn bubble via XEP-0308 (tool activity + partial text that
*becomes* the final answer), sends compact approval requests with inline
buttons, and agents set their avatars via `xmpp.avatar.set` (odiseo and
rolando burned real money trying — the server now has avatars nobody
renders). The GTK client renders corrections, but the experience around them
was never designed: no typing/progress affordance, no visual distinction
between a still-streaming bubble and a final one, approval cards are plain
text+buttons, and avatars are ignored.

## Scope

### In

1. **Streaming bubble affordance**: while a message is being edited by
   XEP-0308 corrections, style it as "in progress" (subtle spinner or pulsing
   border; monospace/dimmed style for tool-activity lines) and switch to
   final style on the last correction. No flicker, no scroll jumps (respect
   the spec 004 upper-growth rule).
2. **Typing indicators** (XEP-0085): render `composing`/`paused` from agents
   as the standard "está escribiendo…" row; send our own chat states.
3. **Approval cards**: distinct visual treatment for approval requests
   (icon, accent border, sticky until resolved), button rows preserved from
   presentation blocks, and a resolved state (approved/rejected + by whom)
   when the compact resolution edit arrives.
4. **Avatars**: fetch and render contact avatars (XEP-0084 PEP avatars, with
   vCard XEP-0153 fallback) in the sidebar and next to bubbles; cache to disk;
   update on change notification.
5. **Delivery states**: show sent/failed for our own messages (stream
   management ack or error bounce) with tap-to-retry on failure.

### Out

- MUC-specific UX (belongs to `xmpp-muc`).
- Attachment picker parity for Android (its own change, other repo).
- Any gateway/plugin work — server side is done; this change is client-only.

## Verification

Manual E2E against `hablar.fuentelibre.org` with a live agent: one turn with
tool use (streaming bubble grows, then finalizes), one approval round-trip
(card renders, button resolves, resolution state shown), avatar visible for
an agent that has one set, typing indicator during agent turn, and a forced
send failure showing the failed state. Compare side-by-side with the same
agent on Telegram.

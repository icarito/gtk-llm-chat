# 007 — XMPP response streaming via Last Message Correction

**Status:** reverted — backend work failed in production, needs staging env
**Created:** 2026-07-12
**Owner:** Sebastian Silva
**Depends on:** 001 (XMPP backend), 004 (XMPP history/MAM), 005 (NanoClaw agent integration)

## User Story

As a NanoClaw user, I want an agent's reply to appear token by token
in the chat window — like a native LLM chat — instead of arriving as one
silent lump after the whole answer is generated, so that long agent
replies feel responsive and I can start reading immediately.

## Scope

- **Client (this repo):** detect XEP-0308 Last Message Correction
  (`<replace xmlns='urn:xmpp:message-correct:0' id='…'/>`) on incoming
  message stanzas and update the existing agent bubble in place via
  `MessageWidget.update_content()`, rather than appending a new bubble.
- Track the last received message id per XMPP conversation so a correction
  can be matched to the bubble it replaces.
- Persist only the final corrected body to the history cache (spec 004),
  not each intermediate token snapshot.
- **Backend (nanoclaw repo, tracked here for coordination):** stream the
  agent's partial output as an initial message followed by throttled
  XEP-0308 corrections carrying the accumulated body so far. See
  [design.md](design.md) for the pipeline gap and the cross-repo split.

## Out Of Scope

- Word-level or diff-based corrections. A correction always carries the
  full accumulated body; the client replaces, it does not patch.
- Streaming for non-agent (human) XMPP contacts — corrections from humans
  are still honored, but no client throttling/accumulation is assumed.
- Streaming over the local LLM backend — `llm_client.py` already streams
  natively and is unaffected.
- Changes to Prosody. XEP-0308 is client-to-client; the server only routes
  the stanzas and needs no new module.
- MAM replay of correction chains (loading a mid-stream snapshot from the
  archive). The backend is expected to archive only the final body; the
  client does not reconstruct corrections from history.

## Acceptance Criteria

- [ ] An incoming agent message immediately followed by one or more
      XEP-0308 corrections shows a single growing bubble, not a stack of
      bubbles.
- [ ] The bubble's final content equals the last correction's body.
- [ ] A correction whose `<replace id>` matches no known recent message is
      treated as a plain new message (graceful degradation), not dropped.
- [ ] After streaming completes, the history cache holds exactly one
      entry for that reply, with the final body.
- [ ] Reopening the conversation (history from cache or MAM) shows the
      final reply once, with no duplicate or stale-snapshot bubbles.
- [ ] Corrections addressed to a conversation whose window is closed do
      not error; the message-received notification path is unaffected.
- [ ] Existing LLM chats, ordinary XMPP chats, and NanoClaw quick
      responses / ad-hoc commands continue to work unchanged.

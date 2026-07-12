# 004 — XMPP message history (MAM + local cache)

**Status:** draft
**Created:** 2026-07-03
**Owner:** Sebastian Silva
**Depends on:** 001 (XMPP backend, `ChatBackend` contract), 002 (roster
sidebar, session lifecycle), 003 (unified sidebar navigation, since the
LLM conversation sidebar's shape is the model to mirror for a future XMPP
history UI)

## User story

As a user, when I open a conversation with an XMPP contact, I want to see
the messages we already exchanged — today every XMPP window starts
completely empty, even for a contact I've been chatting with for weeks.
Opening a conversation should show recent history immediately (from a
local cache) and let me scroll up for more (fetched from the server via
MAM), the way any XMPP client behaves.

## Why

Spec 001 explicitly deferred this: *"No local history in MVP. XMPP
windows show the live session only; closing the window discards it.
Server-side history (XEP-0313 MAM) arrives in Layer 2."* That Layer 2
never got scheduled — 002 built the roster/presence/notifications side
instead. Today `XmppConversation.get_conversation_id()` always returns
`None` (`xmpp_client.py`, commented "sin historial local en el MVP") and
nothing is stored anywhere, in memory or on disk: closing a window loses
the conversation, and reopening it starts blank regardless of how much
was said before. This is the single biggest gap between this app's XMPP
support and any baseline XMPP client (Gajim, Dino, Conversations).

## Why both MAM and a local cache

XEP-0313 (MAM) alone would mean every window-open blocks on a network
round-trip and shows nothing while offline. A local cache alone would
drift from the server's authoritative archive (other clients, multi-device)
and never backfill messages sent before this app started caching. Together:
the cache makes opening a conversation instant and offline-capable; MAM
keeps it truthful and lets scrolling back reach further than local cache
depth, exactly like how `logs.db` (LLM side, see
[docs/data-model.md](../../docs/data-model.md)) is this app's own
persistent record but is never the *only* source of truth for a model's
behavior.

## Acceptance criteria (MVP)

- [x] 1. **Local cache**: a new SQLite database, separate from `llm`'s
      `logs.db` (never touch that schema — see data-model.md's existing
      rule), storing XMPP messages per contact (bare JID), with enough
      fields to render history (body, direction, timestamp, XEP-0313
      archive id for dedup/resume). Lives in the same config directory as
      `logs.db` but as its own file.
- [x] 2. **Instant local history on open**: opening a conversation with an
      existing contact immediately renders the most recent cached
      messages (no network wait), styled consistently with the LLM
      history view (`chat_window.py`'s existing
      `_display_conversation_history` bubble rendering, reused or mirrored
      — not reinvented).
- [x] 3. **MAM backfill on open**: after showing the local cache, query
      the server via MAM (`nbxmpp`'s `MAM` module, XEP-0059 RSM paging,
      `max_=50`-ish page size) for anything newer than the latest cached
      message for that JID; merge results into the cache and the visible
      view, deduped by MAM archive id. If the server has nothing new (or
      is unreachable), the cached view stands as-is — never block the
      window on this.
- [x] 4. **Scroll-to-load-more**: scrolling to the top of the message view
      requests one more page — from the local cache first if it has older
      messages not yet shown, else via MAM (RSM `before`) — appending
      further back until MAM reports the archive's start (`complete`
      flag) or the user stops scrolling.
- [x] 5. **Every live message gets cached**: messages sent or received
      during a live session (already working via `XmppConversation`'s
      existing `response`/`deliver` path) are written to the new cache as
      they happen, not just MAM-fetched ones — so the cache is
      self-sufficient even for a contact never queried via MAM yet.
- [x] 6. **No regression**: 001/002's live chat, typing, presence,
      notifications, and 003's roster/session lifecycle keep working
      exactly as before for contacts/sessions that exercise no history at
      all (e.g. a brand new contact with nothing to show).

## Out of scope

- MUC (group chat) history — this spec is 1:1 conversations only,
  consistent with 001/002's scope.
- OMEMO-encrypted history (decrypting/caching encrypted archives) — cache
  stores plaintext bodies only; if OMEMO lands later, that spec decides
  how encrypted history interacts with this cache.
- Cross-device sync of *read state* / message carbons beyond what's needed
  to dedup MAM results — full XEP-0280 Carbons support is separate.
- Search across history (mentioned in `docs/roadmap.md` as a general,
  backend-agnostic feature) — this spec only makes history exist and
  render; searching it is a follow-up.
- Exporting/deleting cached history — no UI for cache management in this
  MVP; the cache is an implementation detail, not a user-facing feature
  surface, beyond the history view itself.

## Design intent (to be detailed in design.md)

- **New module** `xmpp_history.py` (or similar), sibling to
  `db_operations.py`'s pattern (thread-local connections, short
  transactions) but its own schema/file — never reuse `ChatHistory`'s
  connection or schema.
- **`ChatBackend` contract growth**: today's contract
  (`chat_backend.py`) has no history hook — `response`/`finished` are for
  live turns only. This will likely need a new signal (e.g.
  `history-message` carrying body/timestamp/direction, distinct from live
  `response`) and a `load_more_history()`-shaped method, so
  `LLMChatWindow` can drive paging generically. `LLMClient` (LLM side)
  would simply not emit it / no-op the method, same pattern as `typing`
  today ("backends that don't support it just don't emit it").
- **`XmppSession`/`XmppConversation` (`xmpp_client.py`)**: needs a MAM
  query path wired into the existing `message` `StanzaHandler`
  (`_on_message`), branching on `properties.is_mam_message` /
  `properties.mam` to route archived results separately from live
  traffic, correlated by `queryid` with `nbxmpp`'s `MAM.make_query(...)`
  completion.
- **Rendering reuse**: `chat_window.py`'s `_display_conversation_history`
  is built around LLM's `history_entries` shape
  (`db_operations.py`); decide whether to generalize it to a
  backend-agnostic entry format or give XMPP windows a parallel render
  path that produces the same visual bubbles.

## Risks

- MAM result correlation (matching `queryid` to the right conversation,
  knowing when a page is "done") is the fiddliest new protocol logic in
  this spec — get this wrong and history duplicates, drops messages, or
  never signals completion (infinite "loading").
- Growing the shared `ChatBackend` contract touches both backends; must
  not regress LLM windows (which have their own, separate history system
  via `logs.db` and don't need this new signal at all).
- A new local SQLite file means new file-lifecycle questions (created on
  first XMPP message ever, or eagerly at startup?) — small decision but
  needs to be explicit in design.md.

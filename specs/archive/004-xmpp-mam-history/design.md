# 004 — Design: XMPP message history (MAM + local cache)

Companion to [spec.md](spec.md). Concrete shapes for the local cache
schema, the `ChatBackend` contract growth, and MAM query/correlation
logic — grounded in the actual code (`xmpp_client.py`, `chat_window.py`,
`chat_backend.py`, `db_operations.py`) as of spec 003's close.

## 1. Local cache: `xmpp_history.db`

New file, sibling to `logs.db` in the same `platform_utils.ensure_user_dir_exists()`
directory. Own schema, own connection — never shares `ChatHistory`'s
connection or touches `llm`'s tables (per the data-model.md rule).

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bare_jid TEXT NOT NULL,       -- contact's bare JID; the conversation key
    body TEXT NOT NULL,
    direction TEXT NOT NULL,      -- 'in' | 'out'
    timestamp TEXT NOT NULL,      -- ISO 8601 UTC, from MAM delay or local send time
    mam_id TEXT,                  -- XEP-0313 archive id; NULL for locally-sent
                                   -- messages not yet confirmed by a MAM roundtrip
    UNIQUE(bare_jid, mam_id)      -- dedup MAM refetches; NULLs don't collide (SQLite)
);
CREATE INDEX IF NOT EXISTS idx_messages_jid_ts ON messages(bare_jid, timestamp);
```

- New module `xmpp_history.py`, mirroring `db_operations.py`'s
  thread-local-connection pattern (`threading.local()`, lazy connect,
  `get_connection()`), but its own class `XmppHistory` — no inheritance
  from `ChatHistory`, no shared code beyond the pattern shape (the
  schemas and lifecycles are unrelated enough that sharing a base class
  would be a false abstraction).
- File created lazily on first write (first live message, or first MAM
  page fetched) — not eagerly at startup. Mirrors `ChatHistory`'s own
  `_ensure_db_exists()` lazy-migration pattern.
- API surface `XmppHistory` needs:
  - `record_message(bare_jid, body, direction, timestamp, mam_id=None)` —
    idempotent insert (`INSERT OR IGNORE`, relying on the `UNIQUE`
    constraint for MAM-sourced rows; locally-sent messages always insert
    since `mam_id` is `NULL` and doesn't collide).
  - `get_recent(bare_jid, limit=50)` — most recent N, ascending order for
    display.
  - `get_before(bare_jid, before_timestamp, limit=50)` — one page further
    back, for scroll-to-load.
  - `get_latest_timestamp(bare_jid)` — drives criterion 3's "ask MAM for
    anything newer than this."

## 2. `ChatBackend` contract growth

Today's contract (`chat_backend.py`) is turn-oriented: `response` +
`finished` for one send/receive cycle. History is a different shape
(a batch of past messages, each with its own direction/timestamp, no
"in-flight" semantics), so it gets its own signal rather than overloading
`response`:

```python
__gsignals__ = {
    # ... existing signals unchanged ...
    'history-message': (GObject.SignalFlags.RUN_LAST, None,
                         (str, str, str)),   # body, direction, timestamp (ISO 8601)
    'history-complete': (GObject.SignalFlags.RUN_LAST, None, (bool,)),  # has_more
}

def load_more_history(self):
    """Request one more page of older history, if the backend has any
    concept of history. No-op by default (e.g. LLMClient doesn't need
    this — its history comes from logs.db via ChatHistory directly)."""
    pass
```

- `LLMClient` does not override `load_more_history` or emit the new
  signals — same "backends that don't support it just don't emit it"
  pattern already used for `typing`. `chat_window.py`'s LLM history path
  (`_on_backend_ready` → `self.chat_history.get_conversation_history`)
  is untouched; it does not go through this new signal pair at all.
- `XmppConversation` emits `history-message` once per cached/fetched
  message (oldest-to-newest within a page) when a page becomes available
  (from local cache instantly, or from a MAM page once complete), then
  `history-complete(has_more)` once per page, where `has_more=False`
  means MAM reported `complete=True` (start of archive reached) — until
  then the sidebar/message view can keep offering "load more" on scroll.

## 3. `chat_window.py` integration

- On `_on_backend_ready` (existing hook), for XMPP windows
  (`self._injected_backend`), instead of the LLM-only `self.cid` branch:
  call a new `self._load_xmpp_history()` which:
  1. Connects `history-message`/`history-complete` handlers (tracked in
     `_backend_handler_ids` alongside the others, so `_unbind_backend`
     disconnects them the same way — this closes the exact class of bug
     T10's review found in T7: no signal survives a rebind unaccounted
     for).
  2. Calls `self.backend.load_history_from_cache()` (see below) to render
     instantly, then `self.backend.load_history_from_mam()` to backfill.
- Rendering: generalize `_display_conversation_history`'s bubble-creation
  loop to accept a backend-agnostic `(body, direction, timestamp)` tuple
  shape instead of LLM's raw DB row dicts — a thin adapter at each call
  site (LLM path already has the DB row; XMPP path builds the tuple from
  the signal args), not a rewrite of the widget code itself.
- Scroll-to-load: connect to the message `Gtk.ScrolledWindow`'s
  `edge-reached` signal (`Gtk.PositionType.TOP`) — call
  `self.backend.load_more_history()`, which no-ops for LLM backends and
  triggers a cache/MAM page for XMPP.

## 4. `xmpp_client.py`: MAM query + correlation

**Revised after T1's spike** (see tasks.md T1 result) — two corrections
to the shape originally sketched here:

- This `nbxmpp` version's `MAM.make_query(jid, queryid, start, end, with_,
  after, max_)` has no `before=` parameter — only forward paging via
  `after` (an archive id). Paging *older* messages (scroll-to-load) must
  instead use the RSM `first` id from the *earliest* page already seen as
  a new anchor, querying with `start`/`end` bounds or accepting that this
  API only naturally walks forward. Simplest correct approach: request
  with `end=<timestamp of the oldest message currently shown>` (no
  `after`) to get the page immediately preceding it, `max_` sized — MAM
  servers return results oldest-to-newest within the requested window
  regardless of anchor direction.
- Real archived stanzas include ones with `properties.body is None`
  (OMEMO key-exchange/receipt/chatstate-only traffic MAM archives but
  which has no displayable text) and, separately, contacts with OMEMO
  traffic can surface literal placeholder bodies. Since OMEMO is out of
  scope (spec.md), `_on_mam_page`/the caching layer must **drop any MAM
  result with no non-empty plain body** before it ever reaches
  `XmppHistory.record_message` or `history-message` — never cache or
  display a null or placeholder body as if it were a real message.

`XmppConversation` gains:

```python
def __init__(self, session, bare_jid):
    ...
    self._history_shown_from = None  # oldest timestamp rendered so far, for paging
    self._pending_mam_queryid = None
    self._mam_page_buffer = []

def load_history_from_cache(self):
    for msg in self.session.history.get_recent(self.bare_jid):
        self.emit('history-message', msg.body, msg.direction, msg.timestamp)
    self._history_shown_from = ... # oldest of that batch, or None if empty

def load_history_from_mam(self):
    """Backfill: ask the server for anything newer than the latest cached
    message. Best-effort — network/server failure must not block the
    window (spec.md criterion 3)."""
    if not self.session.is_connected:
        return
    after_ts = self.session.history.get_latest_timestamp(self.bare_jid)
    self._pending_mam_queryid = self.session.query_mam(
        self.bare_jid, after=after_ts, callback=self._on_mam_page)

def load_more_history(self):
    """Scroll-to-load: older page, cache first, else MAM 'end'-anchored
    query (no 'before' param exists on this nbxmpp version — T1)."""
    older = self.session.history.get_before(self.bare_jid, self._history_shown_from)
    if older:
        for msg in older:
            self.emit('history-message', msg.body, msg.direction, msg.timestamp)
        self._history_shown_from = older[0].timestamp
        self.emit('history-complete', True)  # cache might have more, or MAM will
        return
    self._pending_mam_queryid = self.session.query_mam(
        self.bare_jid, end=self._history_shown_from, callback=self._on_mam_page)

def _on_mam_page(self, messages, complete):
    # messages is already filtered to plain, non-empty bodies by
    # XmppSession.query_mam's _on_message branch (T1) — OMEMO/receipt/
    # chatstate-only archived stanzas never reach here.
    for msg in messages:  # oldest-to-newest
        self.session.history.record_message(
            self.bare_jid, msg.body, msg.direction, msg.timestamp, msg.mam_id)
        self.emit('history-message', msg.body, msg.direction, msg.timestamp)
    if messages:
        self._history_shown_from = messages[0].timestamp
    self.emit('history-complete', not complete)
```

`XmppSession` gains `query_mam(bare_jid, after=None, end=None, callback=...)`:

- Wraps `nbxmpp`'s `client.get_module('MAM').make_query(jid=own_jid,
  queryid=<generated>, with_=bare_jid, after=after, end=end, max_=50)`
  (RSM paging built into the module — see `.venv/.../nbxmpp/modules/mam.py`;
  confirmed via T1's spike this version has no `before=` param, only
  `start`/`end`/`after`).
- **Correlation**: MAM results arrive as ordinary `message` stanzas
  through the *existing* `_on_message` handler
  (`xmpp_client.py:234`), not as the query's return value. `_on_message`
  needs a new branch, checked *before* the existing live-message logic:
  ```python
  if getattr(properties, 'is_mam_message', False):
      # properties.mam is a MAMData(id, query_id, archive, namespace,
      # timestamp) — confirmed directly via T1's spike, no nested lookup.
      pending = self._pending_mam_queries.get(properties.mam.query_id)
      if pending is not None and properties.body:
          # Drop OMEMO/receipt/chatstate-only archived stanzas (T1): they
          # archive with body=None and must never reach the cache/UI.
          direction = 'out' if properties.jid.bare == self._jid.bare else 'in'
          pending['buffer'].append(
              (properties.body, direction, properties.mam.timestamp, properties.mam.id))
      return  # never fall through to live-message handling (deliver/notifications)
  ```
  `XmppSession` keeps `self._pending_mam_queries: dict[queryid, dict]`
  (buffer list + the requester's callback), keyed by the `queryid` passed
  to `make_query`. The query itself is issued via
  `client.get_module('MAM').make_query(...)`, which returns a `Task`;
  `task.add_done_callback(self._on_mam_query_done)` is the same idiom
  already used elsewhere in this file (`_on_connected`/`_on_roster`, T1
  confirmed no new async pattern is needed). Inside the done-callback,
  `task.finish()` raises on error or returns `MAMQueryData(jid, complete,
  rsm)`; on success, `pending['callback'](pending['buffer'], complete)`
  fires and the entry is popped from `_pending_mam_queries`.
- Guard against the case a window closes mid-query: `_pending_mam_queries`
  entries are keyed by `queryid`, not by conversation object, so a
  finished query with no one listening (conversation forgotten via
  `forget_conversation`) should just cache-write and drop, not error.

## 5. Sequencing / risk mitigation

The riskiest new logic was MAM correlation (section 4) — de-risked by
T1's spike against real server traffic before wiring anything into
`XmppConversation`/`chat_window.py` (see tasks.md T1's result: PASS, plus
two real corrections folded into §4 above — no `before=` param, and MAM
results with null/OMEMO-placeholder bodies must be filtered).

## Open questions for tasks.md to resolve during implementation

- Whether `direction` needs a third value for MUC-originated history
  later (not needed now — 1:1 only, `'in'`/`'out'` suffices for this
  spec).

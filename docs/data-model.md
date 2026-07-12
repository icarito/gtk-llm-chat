# Data Model

gtk-llm-chat does **not** own a database. It reads and writes the SQLite
database of the `llm` CLI (`logs.db` inside `llm.user_dir()`, typically
`~/.config/io.datasette.llm/` on Linux), so conversations are shared
bidirectionally with the command line.

## Ownership and migrations

- The schema is defined and migrated by `llm.migrations.migrate()`
  (invoked by `ChatHistory._run_llm_migrations` in
  [db_operations.py](../gtk_llm_chat/db_operations.py) only when the DB
  does not exist yet).
- **Rule: never ALTER these tables or add our own migrations.** If we need
  app-specific state, it goes in a separate file/db, not in `logs.db`.
- Upstream schema reference: https://llm.datasette.io/en/stable/logging.html

## Tables we touch

| Table | Used for | Access |
|---|---|---|
| `conversations` | id (ULID), name, model | read (list/history), write (rename, create, delete) |
| `responses` | prompt, response, model, timestamps, options, conversation_id | read (history); written by `llm` itself when streaming completes |
| `schema_migrations` (managed by llm) | migration bookkeeping | never touched directly |

Conversation ids are ULIDs (`python-ulid`), lexicographically sortable —
"recent conversations" in `llm_conversation_sidebar.py` relies on that
ordering.

## Concurrency

- `ChatHistory` keeps **thread-local** sqlite connections (UI thread vs
  streaming thread).
- SQLite WAL/locking is the only coordination between the GUI (possibly
  several windows in the same process) and the `llm` CLI — keep
  transactions short.

## XMPP history: `xmpp_history.db`

XMPP message history (spec 004) lives in its own SQLite file,
`xmpp_history.db`, located in the same `llm.user_dir()` directory as
`logs.db`. Unlike `logs.db`, this database is app-owned: the schema is
defined and migrated by `gtk_llm_chat.xmpp_history.XmppHistory`, not by
`llm.migrations`. The file is created lazily on first write.

### Schema

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bare_jid TEXT NOT NULL,       -- contact's bare JID; the conversation key
    body TEXT NOT NULL,
    direction TEXT NOT NULL,      -- 'in' | 'out'
    timestamp TEXT NOT NULL,      -- ISO 8601 UTC
    mam_id TEXT,                  -- XEP-0313 archive id; NULL for unsynced local
    UNIQUE(bare_jid, mam_id)      -- dedup MAM refetches; NULLs don't collide
);
CREATE INDEX IF NOT EXISTS idx_messages_jid_ts ON messages(bare_jid, timestamp);
```

### Concurrency

Same thread-local-connection pattern as `ChatHistory` (`threading.local()`,
lazy connect via `get_connection()`), but with WAL journal mode.
Transactions are short — one `INSERT OR IGNORE` per message, committed
immediately. No shared state with `logs.db`.

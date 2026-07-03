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
"recent conversations" in the tray applet relies on that ordering.

## Concurrency

- `ChatHistory` keeps **thread-local** sqlite connections (UI thread vs
  streaming thread vs tray watcher).
- The tray applet watches `logs.db` with `watchdog` to refresh its menu
  when the CLI or another window writes.
- SQLite WAL/locking is the only coordination between the GUI, the tray
  and the `llm` CLI — keep transactions short.

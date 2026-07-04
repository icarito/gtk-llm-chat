# 004 — Tasks

Sequenced to de-risk the fiddliest part (MAM protocol correlation) first,
in isolation, before touching the shared `ChatBackend` contract or UI —
per design.md §5.

- [x] **T1. Spike: raw MAM round-trip.** `spike/mam_roundtrip.py` — connects
      as the test JID (`icarito-test@yax.im`), calls
      `client.get_module('MAM').make_query(jid=, queryid=, with_=, max_=)`,
      confirms round-trip correlation and completion against the real
      server. *Result (2026-07-03):* PASS — 9 archived stanzas returned,
      all correlated to the issued `queryid` via `properties.mam.query_id`,
      `query.complete=True` fired once via the done-callback's
      `task.finish()` (idiom already used elsewhere in `xmpp_client.py`,
      e.g. `_on_connected`/`_on_roster` — no new async pattern needed).
      No `before=` parameter exists on this `nbxmpp` version's
      `make_query` (only `start`/`end`/`after`) — **design.md's
      scroll-to-load-older plan needs revising**: MAM paging here goes
      forward from an anchor (`after`), not backward from "before"; the
      RSM `first`/`last` ids need to be used instead. Two real,
      previously-unmodeled cases showed up in live data: (a) archived
      stanzas with `body=None` (OMEMO key-exchange/receipt/chatstate-only
      traffic that MAM archives but has nothing to display) — must be
      filtered, not treated as an empty message; (b) a plaintext-looking
      body that is actually the literal string
      `'[This message is OMEMO encrypted]'` (a client-side placeholder,
      not real ciphertext-as-text, but a reminder that this test contact
      has OMEMO traffic) — since OMEMO is explicitly out of scope, MAM
      results must be filtered to plain (non-OMEMO-wrapped) bodies only;
      storing either of these as a cached "message" would corrupt the
      history view. **Action before T4/T5**: revise design.md §4's page
      logic to (1) drop MAM results with no usable plain-text body, (2)
      use RSM `first`/`last` for paging instead of a `before=` kwarg that
      doesn't exist in this `make_query` signature.

- [ ] **T2. `xmpp_history.py`: local cache module.** New `XmppHistory`
      class per design.md §1 — schema, thread-local connections
      (mirroring `db_operations.py`'s pattern, no shared base class),
      `record_message`/`get_recent`/`get_before`/`get_latest_timestamp`.
      Lazy file creation on first write.
      *Verify:* unit-level exercise (headless, real sqlite file in a temp
      dir) — write messages, dedup a repeated `mam_id`, page backward with
      `get_before`, confirm ordering.

- [ ] **T3. `ChatBackend` contract growth.** Add `history-message`,
      `history-complete` signals and `load_more_history()` no-op default
      per design.md §2. Confirm `LLMClient` needs zero changes (it simply
      doesn't emit/override) — regression-check LLM windows still load
      history via the existing `logs.db` path, untouched.
      *Verify:* headless — instantiate `LLMClient`, confirm it has no
      history-related behavior change; instantiate a dummy `ChatBackend`
      subclass, confirm the new signals exist and `load_more_history()`
      is callable and inert.

- [ ] **T4. `XmppSession.query_mam` + `_on_message` MAM branch.** Wire
      T1's confirmed correlation shape into `xmpp_client.py`:
      `_pending_mam_queries` dict, the new `is_mam_message` branch in
      `_on_message` (before existing live-message logic, per design.md
      §4), `query_mam(bare_jid, after=, before=, callback=)`.
      *Verify:* against the real test account, request history for a
      contact with known prior messages; confirm the callback fires once
      with correctly-ordered, correctly-attributed (direction) messages
      and the right `complete` value; confirm a live message sent
      *during* a pending query doesn't get misrouted into the MAM buffer
      (the `is_mam_message` check must actually discriminate).

- [ ] **T5. `XmppConversation`: cache + MAM integration.** Add
      `load_history_from_cache`, `load_history_from_mam`,
      `load_more_history`, `_on_mam_page` per design.md §4. Every live
      `deliver()` and `send_message()` call also writes to
      `session.history` (criterion 5) — confirm outgoing messages are
      captured too, not just incoming.
      *Verify:* headless with the real `XmppHistory` (temp dir) and real
      session against the test account: open a conversation with no
      cache yet → confirm `history-complete` fires with an empty/short
      first render, then MAM backfill populates it and writes to cache;
      reopen (fresh `XmppConversation`, same cache file) → confirm cache
      alone renders the same messages instantly, no network dependency
      for that step.

- [ ] **T6. `chat_window.py`: render history + scroll-to-load.**
      `_load_xmpp_history()` on `_on_backend_ready` for XMPP windows;
      generalize or adapt `_display_conversation_history`'s bubble
      rendering to the `(body, direction, timestamp)` shape; wire
      `history-message`/`history-complete` handler ids into
      `_backend_handler_ids` so `_unbind_backend` disconnects them (T10's
      spec-003 review found exactly this class of bug — don't repeat it);
      connect `edge-reached` (`Gtk.PositionType.TOP`) on the message
      scroller to `self.backend.load_more_history()`.
      *Verify:* live app against the test account — open a contact with
      history, confirm instant render then backfill; scroll to top,
      confirm older messages load; switch away and back to this
      conversation via the sidebar (spec 003's in-place rebind path),
      confirm no duplicate handlers / no crash / history still correct
      (this is the regression case T10 flagged as the risk).

- [ ] **T7. No-regression pass (criterion 6).** Independent pass —
      LLM history (untouched path) still works; a brand-new XMPP contact
      with zero history opens cleanly (empty cache, empty MAM result,
      no error, no infinite "loading" state); 001/002/003 behaviors
      (typing, presence, notifications, roster, sidebar navigation,
      lifecycle) unaffected.

- [ ] **T8. Close the loop.** Update spec.md checkboxes, `docs/data-model.md`
      (document the new `xmpp_history.db` alongside the existing
      `logs.db` section — same "ownership and migrations" framing, noting
      this one *is* app-owned, unlike `logs.db`), `docs/architecture.md`
      if the `ChatBackend` contract section needs updating, archive to
      `specs/archive/004-xmpp-mam-history/`.

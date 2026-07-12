# 007 — Design

## Backend confirmation (nanoclaw + Prosody)

Verified against the live host (`ssh nanoclaw@187.127.47.38`, 2026-07-12):

- **Prosody** routes XEP-0308 corrections as ordinary `<message>` stanzas.
  No server module is required — the `<replace>` child is client-handled.
  Confirmed running (Lua 5.4); nothing blocks message-correction traffic.
- **NanoClaw already implements the correction primitive.**
  `buildCorrectionStanza(to, type, body, replaceId, newId?)` in
  `src/channels/xmpp-control/outbound-render.ts` emits exactly:

  ```xml
  <message type="chat" to="…" id="nc-corr-…">
    <body>…accumulated text…</body>
    <replace xmlns="urn:xmpp:message-correct:0" id="ORIGINAL"/>
  </message>
  ```

  Today it is called in **one** place — `resolveQuestion()` in
  `src/channels/xmpp.ts` — to retire an answered XEP-0004 question (drop
  its buttons). It is **not** wired to token streaming.

- **The gap is the streaming pipeline, not the stanza.** The
  `ChannelAdapter` contract (`src/channels/adapter.ts`) exposes a
  one-shot `deliver(platformId, threadId, message)`; there is no
  `onChunk`/streaming hook from the agent-runner through the host to the
  adapter. Emitting "initial message, then corrections as tokens arrive"
  requires new backend plumbing:
  1. agent-runner surfaces partial deltas (it currently writes one
     completed row to `messages_out`);
  2. the host forwards them to the adapter;
  3. the adapter sends the first `<message>`, remembers its id, then
     throttles `buildCorrectionStanza(...)` calls carrying the running
     body, and archives only the final body in MAM.

  **This backend work lives in the nanoclaw repo and is a prerequisite
  for the feature to do anything observable.** The client change below is
  correct and safe to land first — it is a no-op until the backend
  streams — but the acceptance criteria can only be verified end-to-end
  once the backend pipeline exists.

## Client design (this repo)

XEP-0308 arrives as a normal message with a `<replace>` child pointing at
an earlier stanza id. The transport layer already threads message stanzas
through `XmppSession._on_message`, which calls
`XmppConversation.deliver(...)`, which emits `response` + `finished`. For a
messaging backend, `chat_window._on_llm_response` treats **every**
`response` as a fresh, independent bubble (see `chat_window.py`). So a
naive correction would just stack another bubble — the opposite of what we
want.

### The correction seam

Add one signal to the `ChatBackend` contract:

```
'response-correction': (GObject.SignalFlags.RUN_LAST, None, (str,))
```

Semantics: "the last received bubble's body is now this string." Emitted
by `XmppConversation` when an incoming stanza carries a `<replace>` whose
id matches the last message it delivered. `chat_window` handles it by
calling `MessageWidget.update_content()` on the current received bubble
instead of creating a new one — mirroring how LLM streaming reuses one
widget. Backends that never correct simply never emit it, so the contract
stays compatible with spec 004/005.

### Matching corrections to bubbles

`XmppSession._on_message` must read the incoming stanza id and the
`<replace id>`:

- Track `last_incoming_id` per `XmppConversation` (set on each delivered
  message).
- On a stanza with `<replace id=X>`: if `X == last_incoming_id`, route it
  as a correction (`deliver_correction(body)` → emits `response-correction`
  and updates the cached final body). Otherwise deliver it as a plain new
  message (graceful degradation — matches XEP-0308's advice for unknown
  ids and keeps history sane).

The `<replace>` element is `urn:xmpp:message-correct:0`; parse it with the
same `getTags(..., namespace=...)` approach already used for quick
responses and inline commands in `_on_message`.

### History (spec 004)

`deliver()` currently records every incoming body. For a correction we
must **update, not append**: replace the last cached row's body for that
JID rather than inserting a new one, so the cache and MAM-loaded history
each show the reply once. The final body is whatever the last correction
carried. This keeps the spec-004 invariant that the cache mirrors what the
user saw, and avoids a stack of snapshot rows.

Since the client does not reconstruct corrections from MAM (out of scope),
the only history requirement is: while live, collapse corrections onto the
one row; the backend is responsible for archiving a single final body.

### Throttling

Throttling/accumulation is a **backend** concern (it decides how often to
correct). The client renders whatever it receives; `update_content()` is
cheap (a markdown re-render) and GLib.idle_add already coalesces on the
main loop, so no client-side rate limiting is needed for a reasonable
correction cadence.

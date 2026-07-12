# 007 — Tasks

## Client (this repo)

- [x] Add spec artifacts for XMPP response streaming.
- [x] Add a `response-correction(str)` signal to `ChatBackend` and document
      it alongside `response` in `chat_backend.py`.
- [x] Parse the `<replace xmlns='urn:xmpp:message-correct:0' id='…'/>`
      element and the incoming stanza id in `XmppSession._on_message`.
- [x] Track `last_incoming_id` per `XmppConversation`; route a matching
      correction to `deliver_correction(body)` and a non-matching one to
      the existing plain `deliver(...)` path (graceful degradation).
- [x] Emit `response-correction` from `XmppConversation` and update the
      last cached history row in place instead of appending
      (spec-004 cache + MAM final-body invariant).
- [x] Handle `response-correction` in `chat_window._on_llm_response`'s
      sibling handler: call `update_content()` on the current received
      bubble rather than creating a new one; keep quick-response/command
      rows intact.
- [x] Source-level verification (flake8, `--no-llm` smoke run) that a
      normal message still creates a bubble and existing flows are intact.

## Backend (nanoclaw repo — prerequisite, tracked here)

- [x] Surface partial agent deltas from the agent-runner (currently one
      completed `messages_out` row).
- [x] Forward deltas host → adapter (extend the `ChannelAdapter` contract
      with an optional streaming/correction hook, keeping `deliver`
      one-shot for non-streaming channels).
- [x] In the XMPP adapter, send the initial `<message>`, remember its id,
      then throttle `buildCorrectionStanza(...)` with the running body;
      archive only the final body in MAM.

## End-to-end

- [ ] Once the backend pipeline lands, run the manual streaming smoke test
      against NanoClaw and check off the spec's acceptance criteria.

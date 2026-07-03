# 001 — Tasks

Small, individually verifiable. Feature branch: `feat/xmpp-backend`.

## Phase 0 — Spike (validates the library decision)

- [x] **T1. nbxmpp spike script** (`specs/001-xmpp-backend/spike/`):
      standalone script that connects to yax.im with a test account,
      fetches the roster, sends/receives a message, and receives
      chat-state notifications.
      *Result (2026-07-03):* **PASS 4/4** with nbxmpp 7.2.0 — connect+auth,
      roster, message round-trip (server reflection), XEP-0085 chat state
      parsed. GLib mainloop native, no thread bridging needed.
      Library decision confirmed: **nbxmpp**. Gotchas recorded in
      design.md → "Spike findings".

## Phase 1 — Backend abstraction (no behavior change)

- [ ] **T2. Extract `ChatBackend` contract**: document the signal/method
      contract (design.md) in code; adjust `ChatWindow` to depend on the
      contract instead of `LLMClient` concretely.
      *Verify:* full LLM conversation flow works exactly as before
      (send, stream, error, rename, delete).

## Phase 2 — XMPP core

- [ ] **T3. `xmpp_client.py`**: `XmppClient(GObject)` — connect/auth,
      `state-changed` signal, roster fetch, clean shutdown.
      *Verify:* DEBUG run shows connect→roster against yax.im.
- [ ] **T4. Credentials**: JID config file + password in keyring;
      account setup dialog ("Add XMPP account…").
      *Verify:* password absent from disk; reconnect works after restart.
- [ ] **T5. Send/receive messages** bound to a `ChatWindow` via the
      `ChatBackend` contract (message in → bubble; `response`+`finished`
      on receive).
      *Verify:* two-way text chat with a second client. (AC 4)

## Phase 3 — UI integration

- [ ] **T6. Selector**: "XMPP contacts" section in the model selector
      (roster entries; "Add XMPP account…" when unconfigured); selecting
      a contact opens an XMPP-backed window. (AC 3)
- [ ] **T7. XMPP window chrome**: contact name in header, connection
      state indicator; hide LLM-only controls (temperature, system
      prompt, API-key banner) for XMPP windows. (AC 2)
- [ ] **T8. Typing indicators** (XEP-0085) both directions:
      show "typing…" from remote; emit our own composing state. (AC 5)

## Phase 4 — Hardening & docs

- [ ] **T9. i18n**: new strings wrapped in `_()`; run `./update_po.sh`.
- [ ] **T10. Verification pass**: walk all five acceptance criteria in
      spec.md against yax.im and check them off; regression pass over
      the LLM flow.
- [ ] **T11. Docs**: update `docs/architecture.md` (backend abstraction,
      xmpp_client module) in the same change; add `nbxmpp` + `keyring`
      to pyproject/requirements.
- [ ] **T12. Review & archive**: adversarial code review of the branch;
      merge; `git mv specs/001-xmpp-backend specs/archive/`.

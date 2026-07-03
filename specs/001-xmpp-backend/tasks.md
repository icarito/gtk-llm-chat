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

- [x] **T2. Extract `ChatBackend` contract**: document the signal/method
      contract (design.md) in code; adjust `ChatWindow` to depend on the
      contract instead of `LLMClient` concretely.
      *Result (2026-07-03):* `chat_backend.py` defines the 5 signals
      (`model-loaded` renamed to `ready`) + methods; `LLMClient` inherits;
      `ChatWindow.backend` replaces `.llm`. Verified: headless full flow
      (ready→response→finished vs deepseek-reasoner, test conversation
      cleaned from logs.db) and real app launch showing
      "Backend listo: deepseek-reasoner". Found pre-existing latent bug:
      `LLMClient` fallback passes `fragments_path` to `ChatHistory`,
      which doesn't accept it (unreachable from the app; noted for T10).

## Phase 2 — XMPP core

- [x] **T3. `xmpp_client.py`**: `XmppSession` (una conexión por cuenta:
      estado, roster, ruteo de entrantes) + `XmppConversation(ChatBackend)`
      (una por bare JID). Incluye ya el núcleo de send/receive y recepción
      de chat states (adelanto de T5/T8).
      *Result (2026-07-03):* verificado headless contra yax.im —
      round-trip de mensaje sin errores espurios al desconectar, y
      contraseña errada emite `error` (StreamError.SASL: not-authorized)
      en vez de fallar en silencio. Lección nueva para design.md: el
      orden de arranque debe ser roster → presence → 'connected'; si se
      envía antes del presence inicial el servidor encola el mensaje
      como offline. Dependencia `nbxmpp` añadida a pyproject/requirements.
- [x] **T4. Credentials**: JID config file + password in keyring;
      account setup dialog ("Add XMPP account…").
      *Result (2026-07-03):* `xmpp_account.py` (JSON with only the JID
      under the app's user dir + password via `keyring`/Secret Service,
      service name `gtk-llm-chat-xmpp`) and `xmpp_account_dialog.py`
      (`Adw.Window` with `EntryRow`/`PasswordEntryRow`, validates by
      actually connecting a throwaway `XmppSession` before persisting).
      Verified headless end-to-end against yax.im, both paths: (1) happy
      path — dialog connects, persists, calls back with the JID, and a
      simulated restart (fresh `load_account()`) recovers the same
      password; confirmed the on-disk file contains only `{"jid": ...}`,
      no password. (2) wrong password — nothing persisted, no callback,
      error surfaced in the dialog's UI label
      ("StreamError.SASL: not-authorized").
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

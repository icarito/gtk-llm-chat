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
- [x] **T5. Send/receive messages** bound to a `ChatWindow` via the
      `ChatBackend` contract (message in → bubble; `response`+`finished`
      on receive).
      *Result (2026-07-03):* done together with T6 (see below) —
      `LLMChatWindow` accepts an injected `backend=`; when present it
      wires `XmppConversation` signals straight into the existing
      `_on_llm_response`/`_on_llm_error`/`_on_llm_finished` handlers
      unchanged. Verified with a real `LLMChatWindow` + real send click
      against yax.im (self-chat echo): 2 bubbles, correct text in both,
      title = contact JID. (AC 4)

## Phase 3 — UI integration

- [x] **T6. Selector**: separate entry point instead of touching the LLM
      model selector (**scope revised**, see design.md → "Selector
      integration"): `app.new-xmpp-conversation` action → account dialog
      if unconfigured, else `XmppRosterDialog` (new) listing the live
      roster → picking a contact opens an XMPP-backed `LLMChatWindow`.
      *Result (2026-07-03):* `xmpp_roster_dialog.py` (new) +
      `chat_application.py` wiring
      (`on_new_xmpp_conversation_activate`/`_open_xmpp_roster_picker`).
      LLM model selector untouched — zero regression risk there.
      Verified: regression pass on a real unmodified app launch (no
      injected backend) shows no tracebacks and normal
      "Backend listo: <model>" behavior; separately, a real
      `LLMChatWindow(backend=xmpp_conversation)` shows the contact JID
      as subtitle and hides the model-sidebar toggle. (AC 3)
- [x] **T7. XMPP window chrome**: connection state indicator (connected/
      disconnected/error) somewhere visible in the header, driven by
      `state-changed`. Contact name in header and hiding LLM-only
      controls already landed in T5/T6 (subtitle = contact JID, sidebar
      toggle hidden entirely for injected backends — there's no
      temperature/system-prompt/API-key UI shown at all, so nothing left
      to selectively hide). (AC 2)
      *Result (2026-07-03):* `connection_status_label` in the header,
      visible only for injected backends, driven by `state-changed`
      ("Connecting…"/"Connected"/"Disconnected", the last with an
      `error` CSS class) plus a fallback on the `error` signal for
      session errors that don't carry a state transition (e.g. a failed
      roster fetch). Verified live against yax.im: label goes
      Connected → Disconnected with the error style the instant the
      session drops. Regression: the label is hidden for ordinary
      (non-injected) LLM windows.
- [x] **T8. Typing indicators** (XEP-0085) both directions:
      show "typing…" from remote; emit our own composing state. (AC 5)
      *Result (2026-07-03):* `ChatBackend` gained `notify_composing()`
      (no-op default, harmless for `LLMClient`) and the `typing` signal
      moved from `XmppConversation`-only into the shared contract.
      `chat_window._on_text_changed` calls `notify_composing(True)` on
      first keystroke and arms a 5s idle timeout that calls
      `notify_composing(False)`; sending a message cancels that timer.
      `XmppSession.send_chatstate()` sends a bare XEP-0085 stanza
      (composing/active). Incoming chat states reuse the connection
      status label ("Typing…", restored to the last connection state
      when it clears). Verified live against yax.im (self-chat): typing
      emits composing, the server reflection comes back as
      `typing=True` on the same conversation, the UI shows "Typing…",
      and sending clears it back to "Connected". Regression: LLMClient
      windows are unaffected (`notify_composing` no-op).

## Phase 4 — Hardening & docs

- [ ] **T9. i18n**: new strings wrapped in `_()`; run `./update_po.sh`.
- [x] **T10. Verification pass**: walk all five acceptance criteria in
      spec.md against yax.im and check them off; regression pass over
      the LLM flow.
      *Result (2026-07-03):* independent verify+review pass. All 5 AC
      PASS live against yax.im; flake8 clean on the XMPP files. The
      review found 4 real issues, all fixed in this branch:
      **#1 (correctness)** — outgoing XMPP messages created a dangling
      empty assistant bubble (LLM-style placeholder) that never filled;
      a later reply would fill the stale bubble. Masked by self-chat.
      Fixed: injected backends don't create a placeholder on send;
      incoming `response` creates its own bubble. Verified: send leaves
      only the user bubble; incoming makes a fresh bubble; LLM streaming
      still uses its placeholder (regression checked).
      **#2 (leak)** — `XmppConversation` connected handlers on the shared
      session but `shutdown()` was a no-op, so closed conversations kept
      receiving signals. Fixed: store handler ids, disconnect them and
      `forget_conversation()` on shutdown. Verified: after one
      conversation's shutdown it stops receiving, siblings unaffected.
      **#3 (minor)** — composing timeout not cancelled on window close
      (stray chatstate). Fixed in `_on_close_request`.
      **#4 (cosmetic)** — non-fatal `session-error` left "Error" stuck in
      the header. Fixed: restore last connection state after 4s if still
      connected.
- [ ] **T11. Docs**: update `docs/architecture.md` (backend abstraction,
      xmpp_client module) in the same change; add `nbxmpp` + `keyring`
      to pyproject/requirements.
- [ ] **T12. Review & archive**: adversarial code review of the branch;
      merge; `git mv specs/001-xmpp-backend specs/archive/`.

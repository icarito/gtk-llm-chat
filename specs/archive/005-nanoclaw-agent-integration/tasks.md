# 005 — Tasks

- [x] Add spec artifacts for the NanoClaw client integration.
- [x] Extend `ChatBackend` with a `quick-responses(object)` signal.
- [x] Parse XEP-0439 quick response elements from raw XMPP message stanzas.
- [x] Track NanoClaw entity caps, full agent JID, and presence status in `XmppSession`.
- [x] Render response buttons in `MessageWidget` and wire clicks to `XmppConversation`.
- [x] Show agent status in the chat header and roster rows.
- [x] Add a header Agent menu with context actions and discovered ad-hoc commands.
- [x] Add `xmpp_commands.py` for XEP-0050 execution and simple XEP-0004 form dialogs.
- [x] Add automatic XMPP reconnect/backoff while keeping account-dialog probes one-shot.
- [x] Add manual XMPP reconnect/disconnect account controls.
- [x] Run source-level verification and manual XMPP smoke test against NanoClaw.

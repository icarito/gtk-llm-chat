# Observable client lifecycle and XMPP profile

## Problem

The application can remain alive without a window, while XMPP startup is tied
to window creation. On launch, users cannot reliably distinguish loading,
connecting, synchronizing the roster, online, retrying, offline-by-choice and
fatal configuration errors. Their own presence and vCard are not visible or
editable from the primary UI.

## Outcome

Make XMPP an application-scoped service independent of conversation windows.
Show a lightweight startup surface immediately, then transition to the roster
with an explicit lifecycle state, useful retry/error feedback, and no indefinite
spinner. Add a self-profile surface for presence availability/status and vCard
display name, avatar and profile fields.

Interactive approvals follow the same lifecycle principle: one visible card is
updated in place instead of exposing transport acknowledgements as chat turns.

## Non-goals

- Redesigning conversation bubbles or agent telemetry.
- Treating agent execution status as the user's own XMPP presence.

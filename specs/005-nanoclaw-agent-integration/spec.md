# 005 — NanoClaw agent integration over XMPP

**Status:** draft
**Created:** 2026-07-11
**Owner:** Sebastian Silva
**Depends on:** 001 (XMPP backend), 002 (roster/presence), 003 (unified sidebar)

## User Story

As a NanoClaw user, I want gtk-llm-chat to behave like a native agent
client over XMPP: agent questions should show inline response buttons,
agent presence should expose useful status, and common agent commands
should be available from the chat window.

## Scope

- Parse NanoClaw XEP-0439 quick responses from incoming message stanzas
  and render them as buttons attached to the received bubble.
- Detect NanoClaw contacts from entity caps node
  `https://github.com/nanocoai/nanoclaw` and keep the full resource JID
  for IQ commands.
- Preserve presence status text and show it in the chat header and roster.
- Add an Agent menu for fixed context actions (`/compact`, `/clear`) and
  discovered XEP-0050 ad-hoc commands, including simple XEP-0004 forms.
- Make the XMPP session resilient to transient disconnects with automatic
  reconnect/backoff and manual reconnect/disconnect controls.
- Expose basic account lifecycle controls: edit, disconnect/reconnect, and
  remove saved XMPP account.

## Out Of Scope

- XMPP history/MAM. Spec 004 keeps ownership of persisted history.
- Session browsing and workspace file browsing.
- OMEMO and MUC support.

## Acceptance Criteria

- [ ] Incoming NanoClaw questions with `<response xmlns='urn:xmpp:tmp:quick-response'>`
      render one button per response under the agent bubble.
- [ ] Clicking a response sends its `value` as a normal XMPP chat message,
      renders the human label locally, and disables that button row.
- [ ] Contacts with NanoClaw caps show their presence status in the roster
      and the active chat header.
- [ ] The Agent menu appears for NanoClaw chats and can send `/compact`
      or `/clear` after confirmation.
- [ ] The Agent menu can discover ad-hoc commands from the agent full JID
      and execute a command, submitting a displayed data form when one is
      returned.
- [ ] Existing LLM chats and ordinary XMPP chats continue to work unchanged.
- [ ] A transient XMPP disconnect moves the session to reconnecting and
      recovers without recreating chat windows or losing signal handlers.
- [ ] The account dialog validation does not auto-reconnect after failed
      credentials.

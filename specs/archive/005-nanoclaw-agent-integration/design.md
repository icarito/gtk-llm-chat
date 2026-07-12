# 005 — Design

NanoClaw already exposes three XMPP surfaces that gtk-llm-chat can consume
without inventing a private protocol:

- XEP-0115 entity caps identify agent resources with node
  `https://github.com/nanocoai/nanoclaw`.
- Presence `<status>` carries a short agent status line.
- XEP-0050 ad-hoc commands expose command discovery/execution, with XEP-0004
  data forms for commands that need input.

Quick responses use the de facto XEP-0439 shape:

```xml
<response xmlns="urn:xmpp:tmp:quick-response" value="1" label="Approve"/>
```

The app keeps the protocol behavior simple: clicking a quick response sends
the `value` as a normal chat message so NanoClaw's existing option matcher
continues to work. The local user bubble renders `label` for readability.
Future MAM history will archive the actual sent body (`value`); spec 004 can
decide whether to enrich historical display later.

`ChatBackend` grows only one signal, `quick-responses(object)`, emitted after
`response` and before `finished`. It carries a Python list of dictionaries:
`{"value": str, "label": str}`. This keeps the contract compatible with
spec 004's reserved `history-*` names and with ordinary LLM streaming.

Ad-hoc command support lives in `xmpp_commands.py` so `xmpp_client.py` remains
the transport/session layer. The dialog maps common XEP-0004 fields to
libadwaita rows and submits with `AdHocAction.NEXT`, falling back to
`COMPLETE` when the command advertises no next action.

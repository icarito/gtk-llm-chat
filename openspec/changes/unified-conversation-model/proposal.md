# Spec 009: Unified Conversation Model

## User Story

As a gtk-llm-chat user, I want LLM conversations and XMPP chats to behave the
same way: both listed in the same roster, both opened as their own window, both
offering their settings in the same place. Today an LLM conversation is a
special case — it takes over the current window instead of opening its own, and
its model-parameter panel is buried inside the left roster sidebar (or missing
entirely). I want one way of doing things, not two.

As a maintainer, I want the window to depend only on the `ChatBackend` contract,
so that adding a third backend (or giving XMPP a settings panel) does not mean
adding a third branch to every method.

## Problem

Two asymmetries, one causing the other.

### 1. Opening a conversation has two code paths

| | XMPP | LLM |
|---|---|---|
| Roster click | `app.open_xmpp_conversation()` → **new window**, focus-or-open by key | `_on_llm_conversation_selected()` → **transforms the current window in place** |
| Backend | built by the caller, injected | built *inside* `_bind_backend()` |
| Registry key | `xmpp:<account>:<jid>` | the bare `cid` |

Because an LLM selection mutates the window rather than opening one, the code
must unregister the window's old key and register the new one by hand
(`old_xmpp_key`, `_window_by_cid` juggling in `_on_llm_conversation_selected`).
That bookkeeping exists *only* because a window can change identity.

### 2. The backend is chosen by branching, not by polymorphism

`_bind_backend(backend=None)` means "construct an LLMClient"; passing a backend
means "use this one". The resulting `_injected_backend` flag is then consulted in
nine places to decide what the window looks like. The right-hand settings sidebar
was a casualty: the LLM branch mounted it, the XMPP branch did not.

Related: `ChatSidebar` (the model-parameter panel) is currently a page inside
`ChatRosterSidebar`'s `Gtk.Stack` — the settings panel lives *inside the roster*,
on the left, sharing space with the contact list.

## Scope

### In scope
- **One opening path**: a single `open_conversation(descriptor)` on the
  application, used by the roster, the D-Bus entry point, and session restore.
  Focus-or-open by key, for every conversation kind.
- **Backends are always injected**: the application constructs the `ChatBackend`
  (LLM or XMPP) and hands it to the window. `LLMChatWindow` never constructs one,
  and `_injected_backend` disappears.
- **Settings sidebar as a backend capability**: the window asks the backend for
  a settings panel instead of asking what type it is. Each backend fills it with
  whatever it actually has to offer:
  - `LLMClient` → the model-parameter panel (`ChatSidebar`).
  - `XmppConversation` → the agent's ad-hoc commands (XEP-0050), which today live
    in a cramped popover hanging off a header button.
- **Right-hand settings sidebar restored**: the panel moves out of the roster's
  stack into its own sidebar on the right, so roster (left) and settings (right)
  are independent.
- **Agent commands move to that sidebar**: the command list is a proper panel,
  not a popover — it has room for the sections we already group by (session /
  skills / admin), for command descriptions, and for the XEP-0004 forms some
  commands ask for. The header's agent-menu button becomes the sidebar toggle.
- **Roster lists both kinds** (already true) and opens both the same way.

### Out of scope
- The chat input telemetry (spec 008) — already shipped; this spec must not
  regress it.
- `ChatRosterSidebar`'s internal layout, beyond removing the options page.
- Android (`gtk-llm-chat-android`) — mirrored afterwards, once this settles.

## Design

### Conversation descriptor

A conversation is identified by a descriptor, and a descriptor maps to exactly
one registry key and one backend:

| kind | descriptor | registry key | backend |
|---|---|---|---|
| `llm` | `{'kind': 'llm', 'cid': <cid or None>}` | `llm:<cid>` | `LLMClient` |
| `xmpp` | `{'kind': 'xmpp', 'account': <jid>, 'jid': <jid>}` | `xmpp:<account>:<jid>` | `XmppConversation` |

A `cid` of `None` means "a new LLM conversation": it gets a real key once the
backend reports its conversation id, at which point the window is re-registered.
This is the one place where a window's key legitimately changes, and it is
confined to conversation creation.

### Application

```
open_conversation(descriptor) -> window     # focus-or-open, the only entry point
  key = registry_key(descriptor)
  if key in _windows: focus it, return
  backend = build_backend(descriptor)       # LLMClient | XmppConversation
  window  = LLMChatWindow(backend=backend)  # always injected
  register, present, return
```

`open_xmpp_conversation()` becomes a thin wrapper over it (kept for callers), and
`open_conversation_window(config)` is reduced to
`open_conversation({'kind': 'llm', 'cid': config.get('cid')})`.

### ChatBackend contract additions

```python
def get_settings_panel(self) -> Gtk.Widget | None:
    """Panel for this backend's settings, shown in the window's right-hand
    sidebar. None if the backend has nothing to offer (the window then hides
    the sidebar and its toggle)."""
    return None
```

- `LLMClient` returns its `ChatSidebar` — the model parameters.
- `XmppConversation` returns an agent panel: the ad-hoc command list (grouped
  session / skills / admin, as the popover already does), plus room for the
  XEP-0004 form a command may request, rendered in place instead of in a
  separate modal.

No caller asks "is this LLM?" — the window asks "do you have a panel?", and both
kinds answer yes for their own reasons. `None` stays legal so a future backend
(or an XMPP contact that is not an agent, and so exposes no commands) simply gets
no sidebar.

This also retires the header's agent-menu button and its popover: the same
commands, with room to breathe.

### Window

`LLMChatWindow(backend=...)` — backend required, never constructed internally.
`_bind_backend` keeps its job (wire signals, swap chrome) but stops branching on
backend type; it asks the backend for its capabilities.

The `_is_agent_contact` flag added in spec 008 for the model badge is replaced by
the same mechanism: the badge routes to `backend.get_settings_panel()` when there
is one, and to the agent's `model` command when the backend exposes ad-hoc
commands.

## Acceptance Criteria

1. Clicking an LLM conversation in the roster opens (or focuses) **its own
   window**; the window you clicked from keeps its own conversation and merely
   closes its sidebar — identical to the current XMPP behaviour.
2. Clicking an XMPP contact behaves exactly as it does today (no regression).
3. `LLMChatWindow` never instantiates a backend; `grep -c _injected_backend`
   returns 0.
4. There is exactly one focus-or-open registry, keyed uniformly, and
   `_on_llm_conversation_selected` no longer rewrites registry keys.
5. The model-parameter panel appears in a **right-hand sidebar**, not inside the
   roster's stack; the roster (left) and settings (right) can be shown
   independently.
6. In an XMPP conversation the same right-hand sidebar shows the agent's ad-hoc
   commands, grouped (session / skills / admin) as the popover does today.
   Executing a command that asks for a XEP-0004 form renders the form in the
   sidebar; the header's agent-menu button and its popover are gone.
7. A backend with no panel to offer (e.g. a non-agent XMPP contact) hides the
   sidebar and its toggle, and nothing breaks by its absence.
8. Opening a brand-new LLM conversation (no cid) works, and the window gets
   registered under its real key once the backend reports its conversation id.
9. Spec 008's input telemetry (context LevelBar, model badge, spinner/stop) keeps
   working in both kinds, with no new type-branching. The model badge opens the
   right-hand sidebar in both cases.
10. Session restore and the D-Bus `OpenConversation` entry point both go through
    `open_conversation(descriptor)`.

## Migration Notes

- `_bind_backend(backend=None)` currently doubles as "make me an LLMClient".
  Every caller must be found and given an explicit backend; the LLM construction
  code moves to the application's `build_backend`.
- Window-geometry restore (`_window_geometry`) is passed through the descriptor
  path, not the config dict.
- The in-place transformation (`_bind_backend` on an existing window) is kept
  only for the cold-start picker window (a window with no conversation yet).
  If we drop that too, the picker becomes a window that closes itself after
  opening the real one — decide during implementation, but the default is:
  **keep the picker, everything else opens a window**.

## References
- `gtk_llm_chat/chat_application.py` — `open_xmpp_conversation` (the pattern to
  generalize), `_window_by_cid`, `open_conversation_window`
- `gtk_llm_chat/chat_window.py` — `_bind_backend`, `_injected_backend`,
  `_on_llm_conversation_selected`, `_on_roster_contact_selected`
- `gtk_llm_chat/chat_backend.py` — the contract to extend
- `gtk_llm_chat/chat_roster_sidebar.py` — `options_sidebar` inside the stack
- `docs/architecture.md`
- Spec 008 (chat UI telemetry) — must not regress

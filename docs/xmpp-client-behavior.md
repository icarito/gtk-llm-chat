# XMPP client behavior

## Approval actions

Approval controls are rendered as sticky response cards above the composer.
Command items from XEP-0050 are not duplicated as quick buttons inside the
message bubble; the sticky card is the single action surface.

Action metadata may include `expires-at-ms`. Expired approval actions are
removed from live UI and filtered from restored local history. Older cached
approval actions without explicit expiry use a short fallback expiry so dead
cards do not reappear after restart.

## Code fences

Triple-backtick code fences render as separate code blocks inside a message.
Each block has a language label, monospace body, horizontal scrolling, and a
copy button that copies only that code block.

Normal message text still uses the Pango markdown label path for predictable
GTK layout and link activation.

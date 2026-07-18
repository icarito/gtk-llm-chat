# Design

Use one application-owned lifecycle model:
`starting → loading-account → connecting → syncing-roster → online`, with
`retrying`, `offline-by-user`, `unconfigured`, and `error` branches. Windows
observe the model; they do not own the session.

The first frame is a small Libadwaita startup window with app identity, current
phase and a bounded progress indication. Once account loading settles it becomes
the normal roster window. Errors expose Retry and Account Settings.

The self-profile dialog edits local presence (`show` plus free-text status) and
vCard fields. Publish profile changes through the XMPP session and only persist
them locally after server acknowledgement.


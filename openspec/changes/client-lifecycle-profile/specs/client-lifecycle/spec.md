## ADDED Requirements

### Requirement: Window-independent connection lifecycle

The desktop application MUST start and maintain its configured XMPP session at
application scope, regardless of whether a conversation window was restored.

#### Scenario: Cold start without saved windows

- **WHEN** the application starts with an XMPP account and no saved windows
- **THEN** it immediately shows startup progress and begins connecting before a
  conversation is selected

### Requirement: Actionable lifecycle UI

Every non-terminal startup phase MUST be named, and retryable failures MUST
offer Retry and Account Settings without an indefinite spinner.

#### Scenario: Connection takes longer than expected

- **WHEN** connecting or roster synchronization exceeds the normal interval
- **THEN** the UI states what is pending and offers a safe retry

### Requirement: Editable self profile

The user MUST be able to inspect and edit their presence status and supported
vCard fields from the primary application UI.

#### Scenario: Profile update succeeds

- **WHEN** the server acknowledges a profile or presence update
- **THEN** the new values appear consistently in the self-profile surface

### Requirement: Single-surface approval lifecycle

An approval MUST appear as one actionable card whose state changes in place;
transport acknowledgements and command-submission metadata MUST NOT create
additional visible chat bubbles.

#### Scenario: User allows a command once

- **WHEN** the approval command is submitted and acknowledged
- **THEN** the original card becomes approved/running and no acknowledgement,
  empty-turn or technical confirmation bubble is appended

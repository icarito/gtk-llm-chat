## MODIFIED Requirements

### Requirement: Unified conversation opening

The application MUST open every LLM and XMPP conversation through one
descriptor-driven, focus-or-open path and MUST inject its backend.

#### Scenario: Existing conversation selected

- **WHEN** the roster selects a conversation whose window is already open
- **THEN** that window is focused without changing another window's identity

#### Scenario: New conversation selected

- **WHEN** the roster selects a conversation with no open window
- **THEN** a new window is created with the descriptor's injected backend


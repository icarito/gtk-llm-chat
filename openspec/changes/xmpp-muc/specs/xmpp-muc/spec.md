## ADDED Requirements

### Requirement: First-class XMPP rooms

The desktop client MUST support joining, leaving, restoring and messaging MUC
rooms as first-class conversations in the unified roster.

#### Scenario: Join a room

- **WHEN** the user accepts an invitation or enters a valid room and nickname
- **THEN** the room opens, traffic is attributed by occupant, and it is restored
  according to the persisted autojoin policy

### Requirement: Human-grade room notifications

Room notifications MUST default to mentions and MUST support per-room All,
Mentions and Nothing modes with unread counters.

#### Scenario: Unmentioned room message

- **WHEN** an unfocused room in Mentions mode receives a message without the
  user's nickname
- **THEN** unread state updates without generating an attention notification


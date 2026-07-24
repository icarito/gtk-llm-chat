## ADDED Requirements

### Requirement: Bypass switch on the approval sticky card popover

The app SHALL show a bypass switch inside the popover that expands the
detail of a pending approval sticky card, and SHALL NOT show it for
non-approval pending responses.

#### Scenario: Expanding an approval card's detail popover

- **WHEN** the user opens the info popover of a sticky card that is an
  approval request
- **THEN** a bypass switch is shown alongside the approval detail text

#### Scenario: Expanding a non-approval pending response popover

- **WHEN** the user opens the info popover of a sticky card that is not an
  approval request
- **THEN** no bypass switch is shown

### Requirement: Switch invokes the real ad-hoc command without a form dialog

The app SHALL activate/deactivate the bypass by executing the server's
`approval-bypass` XEP-0050 ad-hoc command directly, completing its
parameter form with the switch's own values, without presenting the
generic form dialog used by other ad-hoc commands.

#### Scenario: Turning the switch on

- **WHEN** the user turns the switch on
- **THEN** the app executes `approval-bypass` with `mode=on` and a
  `minutes` value, without opening any additional dialog

#### Scenario: Turning the switch off

- **WHEN** the user turns the switch off
- **THEN** the app executes `approval-bypass` with `mode=off`, without
  opening any additional dialog

### Requirement: Switch state reflects server-side status on popover open

The app SHALL query the server's bypass status each time the popover is
opened, so the switch does not show a stale "on" state after the bypass
has already auto-reverted server-side.

#### Scenario: Reopening the popover after expiration

- **WHEN** the user reopens the popover after a previously active bypass
  has expired server-side
- **THEN** the switch shows as inactive, without the user needing to have
  interacted with it

#### Scenario: Status refresh does not re-trigger activation

- **WHEN** the status query updates the switch's displayed state
  programmatically
- **THEN** this update does not itself send another activate/deactivate
  command to the server

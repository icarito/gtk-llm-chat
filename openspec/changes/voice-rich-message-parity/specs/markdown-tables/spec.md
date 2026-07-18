## ADDED Requirements

### Requirement: Structured Markdown table rendering
The client SHALL render valid GitHub-style Markdown tables as structured rows and cells with a visually distinct header.

#### Scenario: Message contains a table
- **WHEN** a message contains a valid Markdown header row, delimiter row, and body rows
- **THEN** the client displays the table structure rather than raw delimiter characters

### Requirement: Table overflow and message updates
The client SHALL keep wide tables within the message layout using horizontal scrolling and SHALL re-render tables after message corrections.

#### Scenario: Table exceeds available width
- **WHEN** table content is wider than the message bubble
- **THEN** the table scrolls horizontally without widening the conversation viewport

#### Scenario: Corrected message changes a table
- **WHEN** an XEP-0308 correction changes table source text
- **THEN** the displayed table reflects the corrected content

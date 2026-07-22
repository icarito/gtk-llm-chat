## ADDED Requirements

### Requirement: Input re-enabled on backend error before streaming starts
When `LlmClient.send_message` emits the `error` signal for a condition
detected before `_process_stream` is launched (generation already in
progress, backend not initialized, no model configured), the chat window
SHALL re-enable the message input and stop the spinner, without depending
on a `finished` signal that is never emitted for these paths.

#### Scenario: Error before streaming starts
- **WHEN** `send_message` detects generation already in progress (or
  another pre-stream error condition) and emits `error` without launching
  `_process_stream`
- **THEN** the chat window's input is re-enabled and the spinner stops,
  the same as it would after a normal `finished` signal

### Requirement: Input re-enabled on error during streaming (no regression)
When an error occurs during an active stream (inside `_process_stream`),
the existing `try/finally` already guarantees `finished` is emitted and the
input is re-enabled. This behavior SHALL remain unchanged.

#### Scenario: Error during active streaming
- **WHEN** `_process_stream` encounters an error while a response is being
  generated
- **THEN** `finished` is still emitted via the existing `try/finally` and
  the input is re-enabled, unchanged from current behavior

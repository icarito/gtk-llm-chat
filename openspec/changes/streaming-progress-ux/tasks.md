# Tasks — streaming-progress-ux

## 1. Streaming bubble affordance
- [x] 1.1 Track "streaming" state per message id (first XEP-0308 correction
      marks streaming; heuristic: final when no correction for N seconds or
      explicit final marker from plugin bubble format).
- [x] 1.2 In-progress style: pulsing/dimmed accent + spinner glyph in the
      bubble header; tool-activity lines (plugin prefixes them) rendered
      monospace/dimmed.
- [x] 1.3 Final style switch without reflow flicker; keep spec 004
      auto-scroll rule (upper-growth ≠ user intent).

## 2. Chat states (XEP-0085)
- [x] 2.1 Render incoming composing/paused as typing row under the last
      message.
- [x] 2.2 Emit composing/active from our input box (debounced).

## 3. Approval cards
- [x] 3.1 Detect approval requests (compact card format from the plugin) and
      style distinctly (icon + accent border), keep buttons.
- [x] 3.2 Render resolution edits as resolved state; disable buttons after
      resolution.

## 4. Avatars
- [x] 4.1 XEP-0084 PEP avatar fetch + change notifications (+notify caps).
- [x] 4.2 vCard XEP-0153 fallback; disk cache keyed by hash.
- [x] 4.3 Show in sidebar and next to first bubble of a run.

## 5. Delivery states
- [x] 5.1 Mark own messages pending→sent on SM ack; failed on error stanza.
- [x] 5.2 Tap-to-retry failed messages.

## 6. Verification
- [ ] 6.1 Manual E2E matrix from proposal against a live agent; side-by-side
      with Telegram; record results in this file.

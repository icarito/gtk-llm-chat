## Why

The desktop and Android clients need the same rich-message behavior: real voice notes that remain audio attachments, and readable Markdown tables. The gateway already transcribes inbound audio, so client-side transcription or simulated recordings would duplicate responsibility and lose the original message.

## What Changes

- Record real voice notes, upload them through XEP-0363, and send the resulting URL as an XEP-0066 out-of-band attachment.
- Keep voice notes as first-class audio attachments in local and synchronized history, with duration, MIME type, delivery state, retry behavior, and integrated playback.
- Never synthesize recordings, invent transcription text, or replace the attachment with a client-generated transcript; the gateway receives the attachment URL and performs transcription.
- Render GitHub-style Markdown tables as structured, horizontally scrollable content instead of flattened text.
- Preserve interoperability with the Android client for common audio formats including Ogg/Opus, M4A/AAC, MP3, and WAV.

## Capabilities

### New Capabilities

- `voice-attachments`: Real audio capture, XMPP attachment delivery, durable history, error recovery, and in-message playback.
- `markdown-tables`: Structured and accessible rendering of Markdown tables within message bubbles.

### Modified Capabilities

None.

## Impact

- Affects the GTK composer, message widgets, Markdown rendering, XMPP upload/OOB sending, and message history metadata.
- Uses GStreamer for non-blocking recording and playback while reusing the existing XEP-0363 upload path.
- Establishes a shared wire contract with `gtk-llm-chat-android`; no gateway transcription changes are required.

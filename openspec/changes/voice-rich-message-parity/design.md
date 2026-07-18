## Context

The GTK client already uploads generic files through XEP-0363 and sends XEP-0066 URLs, but it has no real voice-note lifecycle or audio bubble. Its Markdown pipeline targets Pango text and does not represent tables. A draft PR demonstrates useful press/slide/lock interaction ideas but records simulated data, invents transcripts, and blocks the UI; those behaviors are not acceptable.

## Goals / Non-Goals

**Goals:**

- Capture real audio without blocking the GTK main loop, deliver it through the existing attachment protocol, and play received or sent notes inline.
- Preserve enough attachment metadata for history restoration, retry, and Android interoperability.
- Render tables as structured GTK content inside message bubbles.

**Non-Goals:**

- Client-side speech recognition, fake fallback audio, or transcript generation.
- Changing the gateway transcription pipeline or defining a new XMPP extension.
- Merging the draft voice PR wholesale.

## Decisions

1. **Use the existing XEP-0363/XEP-0066 path as the wire contract.** The message carries the uploaded audio URL as OOB data; MIME type, duration, URL, and delivery state remain client metadata. This works with the gateway's existing `mediaUrl` ingestion and avoids a proprietary stanza.
2. **Use a GStreamer pipeline for real recording and playback.** Prefer Ogg/Opus for compact, broadly supported output, while playback accepts M4A/AAC, Ogg/Opus, MP3, and WAV. Pipeline state changes and bus messages are integrated asynchronously with GLib; no sleeps or synchronous waits run on the main thread.
3. **Treat capture and upload as separate durable states.** A successful capture produces a temporary local attachment. If upload fails, the UI retains it for retry or explicit discard; it is deleted only after success or cancellation.
4. **Reuse only interaction concepts from PR #70.** Hold-to-record, slide-to-cancel, and lock-to-continue may inform the GTK state machine and styling, but simulation and transcription code are excluded.
5. **Render tables as dedicated widgets.** The Markdown tokenizer identifies table blocks and emits a horizontally scrollable GTK grid with header styling, cell wrapping, and accessible text. Non-table Markdown and code-block behavior remain intact.

## Risks / Trade-offs

- [Codec/plugin availability varies by distribution] → Detect recorder/player initialization failure and show a visible actionable error; package required GStreamer plugins.
- [Temporary recordings can leak after crashes] → Store them under an app-owned cache directory and clean abandoned files on startup with a conservative age threshold.
- [Large tables can make bubbles unwieldy] → Bound cell widths and scroll horizontally without expanding the conversation viewport.
- [Remote media can be unavailable] → Keep retry controls and never block history rendering on eager download.

## Migration Plan

Add optional attachment metadata to history with backward-compatible defaults, then ship recording/player and table rendering. Existing text and generic file messages remain readable. Rollback leaves XEP-0066 audio messages usable as generic links/files.

## Open Questions

- Confirm the exact GStreamer encoder/muxer combination present in every packaging target during implementation verification.

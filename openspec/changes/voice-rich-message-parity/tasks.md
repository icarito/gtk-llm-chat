## 1. Audio Contract and Persistence

- [x] 1.1 Extend message/history attachment metadata for audio URL, MIME type, duration, local retry path, and delivery state with backward-compatible loading
- [x] 1.2 Add audio MIME/extension recognition for Ogg/Opus, M4A/AAC, MP3, and WAV and cover it with unit tests
- [x] 1.3 Verify the existing XEP-0363/XEP-0066 sender preserves the audio attachment URL without generating client transcription text

## 2. Real Voice Capture and Sending

- [x] 2.1 Implement a non-blocking GStreamer recorder that creates real Ogg/Opus audio and reports duration and actionable capture errors
- [x] 2.2 Implement composer recording states for hold, slide-to-cancel, lock, stop, captured, uploading, failed, retry, and discard using only suitable interaction ideas from PR #70
- [x] 2.3 Connect successful capture to upload and OOB sending, retaining failed uploads for retry and cleaning temporary files after success, cancellation, or stale-cache expiry
- [x] 2.4 Add tests for cancellation, recorder failure, successful OOB send, upload failure, retry, and the prohibition on simulated audio/transcript substitution

## 3. Voice Playback

- [x] 3.1 Add an audio message widget with play, pause, progress, duration, loading, failure, and retry states
- [x] 3.2 Integrate asynchronous GStreamer playback and release pipelines/resources when playback ends or widgets are destroyed
- [x] 3.3 Restore sent and received audio bubbles from history and handle corrected/reconciled message metadata

## 4. Markdown Tables

- [x] 4.1 Extend Markdown block parsing to identify valid GitHub-style tables without regressing prose, links, lists, or fenced code
- [x] 4.2 Render table blocks as accessible styled GTK grids inside horizontal scrollers with bounded cell widths
- [x] 4.3 Add tests for headers, alignment delimiters, escaped cell text, wide tables, malformed tables, and XEP-0308 updates

## 5. Verification and Interoperability

- [x] 5.1 Run the documented desktop test, lint, and packaging checks and resolve feature-related failures
- [x] 5.2 Verify GTK-to-Android and Android-to-GTK playback for representative supported formats
- [x] 5.3 Verify an audio OOB message reaches the gateway as media for gateway-side transcription while the original attachment remains visible in history

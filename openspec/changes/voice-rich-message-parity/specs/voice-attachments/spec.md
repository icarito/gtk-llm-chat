## ADDED Requirements

### Requirement: Real voice capture
The client SHALL capture microphone input into a real audio file and SHALL NOT simulate audio or generate transcription text.

#### Scenario: User completes a recording
- **WHEN** the user starts and completes voice recording
- **THEN** the client produces a playable audio attachment with measured duration and MIME type

#### Scenario: Microphone capture fails
- **WHEN** microphone permission, device access, or encoding fails
- **THEN** the client shows a visible error and sends neither a fake attachment nor substitute text

### Requirement: Standard XMPP audio delivery
The client SHALL upload voice recordings through XEP-0363 and send the resulting URL as an XEP-0066 attachment for gateway-side transcription.

#### Scenario: Voice note sends successfully
- **WHEN** capture and upload complete
- **THEN** the outgoing message contains the uploaded audio URL as XEP-0066 OOB data and retains audio metadata in history

#### Scenario: Upload fails
- **WHEN** the upload cannot complete
- **THEN** the client preserves the local recording for retry or explicit discard and does not report the message as delivered

### Requirement: Integrated voice playback
The client SHALL render sent and received audio attachments as voice-note controls supporting playback, pause, progress, duration, and retry.

#### Scenario: History contains an audio attachment
- **WHEN** a conversation is restored with a supported audio URL
- **THEN** the message appears as a playable voice note without requiring an eager download

#### Scenario: Peer sends a supported format
- **WHEN** an attachment uses M4A/AAC, Ogg/Opus, MP3, or WAV
- **THEN** the client recognizes it as audio and attempts integrated playback

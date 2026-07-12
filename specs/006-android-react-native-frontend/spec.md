# Spec 006: Android React Native Frontend

## User Story

As a gtk-llm-chat user, I want to chat with LLMs and my XMPP contacts from
my Android phone, so that I can continue conversations when I'm away from my
desktop. The mobile app reuses the same `logs.db` and LLM configuration from
the desktop, keeping my conversation history in sync between devices.

## Scope

### In scope
- A separate React Native (Expo) app in a new repository (`gtk-llm-chat-android`)
  or a sibling directory — this spec creates a **new project**, not modifies
  the existing GTK app
- Chat UI: message bubbles, conversation list, model selector, system prompt
- Python backend service embedded in the Android APK (Chaquopy or
  `python-for-android`) that reuses `llm_client.py` and `db_operations.py`
  from gtk-llm-chat
- LLM streaming: real-time token-by-token display via WebSocket between the RN
  frontend and the embedded Python service
- Conversation management: create, rename, delete, browse history
- Same `logs.db` schema — shareable via file sync (Syncthing, Nextcloud, etc.)
  with the desktop app
- Configuration: model selection, API keys (from keyring or manual entry),
  system prompts, fragments
- Dark theme only (matching desktop app's Adwaita-dark aesthetic, adapted to
  Material You dark)

### Out of scope
- XMPP backend — LLM only in this spec. XMPP adds significant complexity
  (nbxmpp, GLib main loop, roster, presence) and deserves its own spec.
- iOS — Android first. The architecture (Python backend in APK) is
  Android-specific via Chaquopy. iOS would need a different approach
  (embedded CPython, `python3-ios`, or a remote server).
- Modifying the existing gtk-llm-chat codebase. The mobile app is a consumer
  of the same `llm` library and `logs.db`, not a fork of gtk-llm-chat.
- Offline LLM inference — uses API-based models only (same as desktop).
- Flatpak-style packaging — uses standard Android APK/AAB via EAS.

## Acceptance Criteria

1. User can launch the Android app and see a conversation list (empty on first
   run).
2. User can configure API keys for at least one provider (OpenAI, Anthropic)
   and select a model.
3. User can start a new conversation, type a message, and see streaming
   token-by-token responses.
4. User can browse past conversations from `logs.db` and continue them.
5. User can rename and delete conversations.
6. User can set a system prompt and temperature per conversation.
7. User can use fragment specifiers (alias, URL, file path, hash) in prompts.
8. The app works on Android 10+ (API 29+).
9. The app handles network errors gracefully (disconnected, timeout, API
   error) with user-visible messages.
10. The app respects `LLM_USER_PATH` or a configurable path for `logs.db`
    location (for sync with desktop).
11. When offline (airplane mode, no network), the app still allows browsing
    past conversations from the local `logs.db`.

## Non-functional Requirements

- Performance: Streaming response latency should match desktop (no added
  buffering beyond network).
- Size: APK < 80 MB (Python runtime + native libs + RN bundle).
- Battery: No background CPU usage when idle. Stream processing should not
  prevent device sleep during long generations.
- Privacy: API keys stored in Android Keystore, never logged.
- i18n: User-visible strings must be wrapped in gettext-equivalent (React
  Native i18n library TBD).

## References

### gtk-llm-chat modules reused
- `llm_client.py` → adapted as headless Python service (remove GObject
  signals, replace with callback/async interface)
- `db_operations.py` → reused as-is (pure Python, thread-safe)
- `platform_utils.py` → path resolution reused
- `debug_utils.py` → reused as-is

### Odisea_Dashboard as template
- Expo SDK 52 + Router v4 + TypeScript strict
- `src/api/client.ts` pattern → adapted to WebSocket + REST for the embedded
  Python service
- Navigation: Stack (root) + Tabs (conversations, settings)
- Dark theme constants in StyleSheet
- CI/CD: GitHub Actions for Android APK builds via `expo prebuild`

### Desktop architecture reference
- `docs/architecture.md` — module map, signal vocabulary
- `docs/data-model.md` — `logs.db` schema (owned by `llm.migrations`)

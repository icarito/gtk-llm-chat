# Tasks 006: Android React Native Frontend

## 1. Project Scaffold

- [ ] 0.0 **SPIKE**: Validate Chaquopy + Expo feasibility before full
  implementation
  - Create minimal Expo app with Chaquopy, Python "hello world", verify APK
    builds and Python code executes on device. Check `llm` imports, FastAPI
    server starts on background thread, uvicorn runs. Timebox: 1 day.
- [ ] 1.1 Create new repository/directory `gtk-llm-chat-android`
- [ ] 1.2 Initialize Expo SDK 52 with TypeScript template
- [ ] 1.3 Configure tsconfig.json, babel.config.js, .eslintrc.js, .prettierrc.json
  (copy from Odisea_Dashboard, adapt app name/slug)
- [ ] 1.4 Configure app.config.js with correct name, slug, bundle ID
  (`org.fuentelibre.gtk_llm_chat`), scheme, dark mode, typed routes
- [ ] 1.5 Set up navigation: Stack (root) + Tabs (conversations, settings)
- [ ] 1.6 Define TypeScript types for conversations, messages, models, config
  (`src/types/index.ts`)
- [ ] 1.7 Define dark theme constants matching desktop Adwaita-dark palette
  (`src/constants/theme.ts`)

## 2. Python Backend Service

- [ ] 2.1 Vendor pure-Python modules from gtk-llm-chat:
  `db_operations.py`, `platform_utils.py`, `debug_utils.py`
- [ ] 2.2 Create `headless_llm_client.py`: adapt `llm_client.py` by removing
  GObject signals, replacing with plain callbacks
- [ ] 2.3 Create `python/requirements.txt`: llm, fastapi, uvicorn,
  sqlite-utils, python-ulid, markdown-it-py
- [ ] 2.4 Create `python/server.py`: FastAPI app with REST endpoints for
  conversations, models, history and WebSocket endpoint for chat streaming
- [ ] 2.5 Create `python/android_keys.py`: read API keys from env vars
  (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
- [ ] 2.6 Verify Python backend works standalone (run server.py locally,
  test with curl and wscat)

## 3. Android Integration (Chaquopy)

- [ ] 3.1 Prebuild Android project: `npx expo prebuild --platform android`
- [ ] 3.2 Add Chaquopy Gradle plugin to `android/build.gradle` and
  `android/app/build.gradle`
- [ ] 3.3 Configure Chaquopy: Python version (3.10), pip packages from
  `python/requirements.txt`, source directory `../python/`
- [ ] 3.4 Move Python source files to `android/app/src/main/python/`
  (or configure Chaquopy source dir)
- [ ] 3.5 Create Android native module that starts the uvicorn server in
  a background thread on app startup
- [ ] 3.6 Expose server status (port, errors) to React Native via a
  native module bridge or event emitter
- [ ] 3.7 Handle app lifecycle: start server in `onCreate`, stop in
  `onDestroy`, handle configuration changes

## 4. React Native API Client

- [ ] 4.1 Create `src/api/client.ts`: REST client (fetch-based) for
  conversations CRUD and model listing
- [ ] 4.2 Create `src/hooks/useChatStream.ts`: WebSocket hook for
  streaming chat (connect, send, receive chunks, handle errors,
  auto-reconnect with exponential backoff)
- [ ] 4.3 Add connection state management (Connecting, Connected,
  Disconnected, Error) with UI indicators
- [ ] 4.4 Handle token streaming: accumulate chunks into displayed text,
  update in real-time via `useState`

## 5. Conversations List Screen (Tab 1)

- [ ] 5.1 Create `app/(tabs)/index.tsx`: conversations list with FlatList
- [ ] 5.2 Create `src/components/ConversationCard.tsx`: list item with
  title, model, last message preview, timestamp
- [ ] 5.3 Implement pull-to-refresh, pagination (load more on scroll)
- [ ] 5.4 Implement create new conversation (FAB or header button)
- [ ] 5.5 Implement rename conversation (long-press → dialog)
- [ ] 5.6 Implement delete conversation (swipe-to-delete or
  long-press → confirm)
- [ ] 5.7 Handle empty state: first-run message, loading spinner,
  error state with retry

## 6. Chat Screen

- [ ] 6.1 Create `app/conversation/[cid].tsx`: chat screen with
  message list and input
- [ ] 6.2 Create `src/components/MessageBubble.tsx`: user bubble (right),
  assistant bubble (left), error bubble
- [ ] 6.3 Create `src/components/MarkdownRenderer.tsx`: message body with
  Markdown (code blocks, lists, bold, italic)
- [ ] 6.4 Implement message input: TextInput with Send button, Enter=send,
  Shift+Enter=newline (Android keyboard behavior)
- [ ] 6.5 Implement streaming display: assistant bubble updates in
  real-time as chunks arrive, show typing indicator
- [ ] 6.6 Implement cancel generation (stop button during streaming)
- [ ] 6.7 Load conversation history on screen mount, show loading state
- [ ] 6.8 Handle WebSocket disconnection during streaming: show error,
  offer retry

## 7. Settings Screen (Tab 2)

- [ ] 7.1 Create `app/(tabs)/settings.tsx`: settings list
- [ ] 7.2 Model selector: fetch models from backend, display grouped by
  provider, allow selection
- [ ] 7.3 API key management: per-provider key entry (secure text input),
  store in `expo-secure-store`, pass to Python via env vars on next startup
- [ ] 7.4 System prompt editor: multi-line TextInput, per-conversation or
  global default
- [ ] 7.5 Temperature slider: 0.0 to 2.0 with 0.1 steps
- [ ] 7.6 Database path configuration: show current path, allow changing
  (for sync with desktop via Syncthing/Nextcloud)
- [ ] 7.7 About section: version, license, link to desktop app

## 8. Error Handling & Polish

- [ ] 8.1 Network error handling: offline indicator, auto-reconnect,
  user-visible error messages (not raw exceptions)
- [ ] 8.2 API key missing handling: detect when model needs key but none
  is configured, show settings prompt
- [ ] 8.3 Loading states: skeleton screens or spinners for all async
  operations
- [ ] 8.4 Keyboard avoidance: chat input stays visible when keyboard opens
- [ ] 8.5 Handle Android back button: exit settings → conversations,
  exit chat → conversations, exit conversations → app minimize
- [ ] 8.6 Handle configuration changes (rotation, dark/light) gracefully

## 9. Testing & CI

- [ ] 9.1 Write unit tests for `headless_llm_client.py` (mock llm library)
- [ ] 9.2 Write unit tests for `src/api/client.ts` (mock fetch)
- [ ] 9.3 Write unit tests for `useChatStream` hook (mock WebSocket)
- [ ] 9.4 Write component tests for MessageBubble, ConversationCard
  (@testing-library/react-native)
- [ ] 9.5 Set up GitHub Actions for lint, type-check, tests on PR
- [ ] 9.6 Set up GitHub Actions for Android APK build
  (Expo prebuild + Gradle, with Chaquopy)
- [ ] 9.7 Set up EAS for development/preview builds
- [ ] 9.8 Manual testing: install APK on device, run through acceptance
  criteria

## 10. Documentation

- [ ] 10.1 Write README.md: project overview, setup, build, run, sync
  with desktop
- [ ] 10.2 Write AGENTS.md: architecture summary, conventions, references
  to gtk-llm-chat docs
- [ ] 10.3 Document logs.db sync setup (Syncthing, Nextcloud)
- [ ] 10.4 Document vendor update process (how to pull changes from
  gtk-llm-chat)

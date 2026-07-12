# Design 006: Android React Native Frontend

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Android APK                                            │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  React Native (Expo) — UI Layer                    │  │
│  │  • Conversation list (FlatList)                    │  │
│  │  • Chat screen (message bubbles, streaming text)   │  │
│  │  • Settings (model, API keys, system prompt)       │  │
│  │  • Markdown rendering (react-native-markdown)      │  │
│  └──────────────────┬────────────────────────────────┘  │
│                     │ WebSocket (ws://localhost:8765)    │
│  ┌──────────────────▼────────────────────────────────┐  │
│  │  Python Service (Chaquopy) — Backend Layer         │  │
│  │  • FastAPI/Flask HTTP + WebSocket server           │  │
│  │  • LLMClient (adapted, no-GObject)                 │  │
│  │  • ChatHistory (as-is from db_operations.py)       │  │
│  │  • Fragment resolution (resolve_fragment)          │  │
│  └──────────────────┬────────────────────────────────┘  │
│                     │                                    │
│  ┌──────────────────▼────────────────────────────────┐  │
│  │  Python `llm` library + plugins + models           │  │
│  │  • logs.db (shared SQLite, same schema as desktop) │  │
│  │  • API keys (Android Keystore → injected)          │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Key Decisions

### Decision 0: Why embed Python instead of porting to TypeScript

We evaluated two approaches: embedding the existing Python backend via Chaquopy
vs rewriting `llm_client.py` + `db_operations.py` in TypeScript. Comparison:

| Dimension | Chaquopy + Python | TypeScript Port |
|-----------|------------------|-----------------|
| Code reuse | 90% (~900 lines reused) | 0% (rewrite everything) |
| Feature parity | Automatic (full `llm` plugin ecosystem) | Manual (no JS equivalent of `llm`) |
| Maintenance | Same codebase for desktop + mobile | Two codebases, perpetual sync burden |
| APK size | ~55-65 MB | ~30-40 MB |
| Time to prototype | ~1.5-2 weeks | ~3-4 weeks |
| API key security | On-device (APK .pyc) | Requires backend proxy server |
| Streaming | Works via `llm` thread model | Requires XHR SSE workaround (Hermes lacks `ReadableStream`) |
| `logs.db` compatibility | Full (same Python code reads it) | Manual schema replication, drift risk |
| Fragment system | Works as-is | Full reimplementation needed |

There is no JavaScript/TypeScript equivalent of Simon Willison's `llm` Python
package — no library combines its plugin system (`pluggy`), conversation
management, SQLite logging with migrations (`sqlite-migrate`), and fragment
resolution. Porting would mean reimplementing ~900 lines of battle-tested
Python plus an ongoing maintenance tax keeping two codebases in sync.

The 25 MB APK size penalty is acceptable for a chat app targeting LLM power
users. Google Play's limit is 150 MB.

### Decision 1: Chaquopy for Python embedding

**Chosen**: [Chaquopy](https://chaquo.com/) v17.0.0 (Dec 2025) — embeds CPython 3.10+ in Android APK.

**Compatibility verified**:
- Chaquopy 17.0 supports Android Gradle Plugin 7.3–9.2, Gradle 8.x (what Expo
  prebuild generates)
- `minSdk` 24 required (API 24 = Android 7.0, our target is API 29+)
- `arm64-v8a` ABI for production, `x86_64` for emulator
- Supports `asyncio` — FastAPI/uvicorn can run on a background thread via
  Chaquopy's `Python.start()` on a non-main thread (Chaquopy issue #1243)
- Active maintenance: v17.0.0 (2025-12-01), v16.1.0 (2025-05-08)

**Alternatives considered**:
- **TypeScript port** (see Decision 0): ~3x development time, perpetual sync burden
- **python-for-android (p4a)**: Mature Kivy ecosystem, but complex Gradle
  integration and heavy for non-Kivy apps
- **Remote server**: Simplest architecture but requires network — defeats the
  purpose of a mobile app
- **Termux + proot**: Fragile, not distributable via Play Store

**Risk**: Chaquopy builds Python from source during APK build — CI build
times may be 15-30 minutes. Mitigated by Gradle caching and pre-built CI
Docker image with Android SDK + NDK.

### Decision 2: WebSocket for streaming, REST for CRUD

The Python service runs an HTTP server on `localhost` with two transports:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /models` | REST | List available models |
| `GET /conversations` | REST | Paginated conversation list |
| `GET /conversations/{id}/history` | REST | Message history |
| `POST /conversations` | REST | Create conversation |
| `DELETE /conversations/{id}` | REST | Delete conversation |
| `PUT /conversations/{id}/title` | REST | Rename conversation |
| `WS /conversations/{id}/stream` | WebSocket | Send message + receive streaming response |

**Why WebSocket for chat**: Streaming is the core UX. Server-Sent Events
(SSE) would work but React Native SSE support is spotty. WebSocket has
mature RN support (`react-native-use-websocket` or raw `WebSocket` API).

**WebSocket protocol**:
```
Client → Server:  {"type": "send", "prompt": "Hello", "temperature": 0.7, "system": "..."}
Server → Client:  {"type": "response", "chunk": "Hello"}
Server → Client:  {"type": "response", "chunk": " there"}
Server → Client:  {"type": "finished", "success": true}
Server → Client:  {"type": "error", "message": "API key not configured"}
```

### Decision 3: LLMClient adaptation strategy

The headless `LLMClient` will be a plain Python class with callbacks:

```python
class HeadlessLLMClient:
    def __init__(self, config, chat_history, on_response, on_error, on_finished, on_ready):
        self._on_response = on_response   # callable(str)
        self._on_error = on_error         # callable(str)
        self._on_finished = on_finished   # callable(bool)
        self._on_ready = on_ready         # callable(str)
        # ... identical internal logic to LLMClient ...
```

Every `GLib.idle_add(self.emit, 'response', chunk)` becomes
`self._on_response(chunk)`. The threading model (daemon thread for streaming)
stays identical.

This adapter lives in a **new file** `headless_llm_client.py` in the mobile
repository. It does NOT modify gtk-llm-chat. It imports the pure-Python
utilities (`ChatHistory`, `platform_utils`) from a vendored copy or a shared
package.

### Decision 4: Code sharing strategy

**Chosen**: Vendored copy of gtk-llm-chat pure-Python modules, kept in sync
manually or via git subtree.

**Why not a shared pip package**:
- gtk-llm-chat is not published as a reusable library
- The shared surface is small (~2 files: `llm_client.py` core logic,
  `db_operations.py`)
- A shared package would lock both projects to the same release cycle
- Vendoring avoids dependency hell between the desktop (GTK) and mobile
  (headless) environments

**Files to vendor**:
- `db_operations.py` → copied as-is
- `platform_utils.py` → copied as-is
- `debug_utils.py` → copied as-is
- `llm_client.py` → adapted to `headless_llm_client.py` (removing GObject)

The vendored files include a header comment pointing to the original source
and the git commit they were copied from.

### Decision 5: API key storage

**Chosen**: Android Keystore via `expo-secure-store`.

The `llm` library expects API keys from `~/.config/io.datasette.llm/keys.json`
or the system keyring. On Android:
1. User enters API keys in the settings screen (React Native UI)
2. Keys are stored in Android Keystore via `expo-secure-store`
3. The Python service reads keys from environment variables set at startup:
   `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.
4. The `llm` library already supports these env vars natively

No modification to `llm`'s key resolution is needed.

### Decision 6: logs.db location and sync

**Default**: Android app-private storage (`/data/data/.../files/logs.db`).

**Sync path**: User-configurable. Options:
1. Local only (default)
2. Syncthing-compatible watch directory (e.g., `/storage/emulated/0/Syncthing/logs.db`)
3. Manual export/import

The `ChatHistory(db_path=...)` constructor already supports arbitrary paths.
The mobile app sets `LLM_USER_PATH` env var for the Python process.

### Decision 7: Python HTTP server framework

**Chosen**: FastAPI with uvicorn.

**Why FastAPI**:
- Native async support (WebSocket + HTTP in same process)
- Auto-generated OpenAPI schema (useful for debugging)
- Lightweight, no ORM dependency
- Works on Python 3.10+ (Chaquopy's default)

**Why not Flask**: No native WebSocket support without extensions.
**Why not aiohttp**: Less ecosystem maturity than FastAPI.

### Decision 8: Project structure

```
gtk-llm-chat-android/
├── app/                          # Expo Router screens
│   ├── _layout.tsx               # Root Stack navigator
│   ├── (tabs)/
│   │   ├── _layout.tsx           # Tab navigator
│   │   ├── index.tsx             # Conversations list
│   │   └── settings.tsx          # Model, API keys, path config
│   └── conversation/
│       └── [cid].tsx             # Chat screen
├── src/
│   ├── api/
│   │   └── client.ts             # WebSocket + REST client
│   ├── components/
│   │   ├── MessageBubble.tsx     # User/assistant message bubbles
│   │   ├── ConversationCard.tsx  # List item for conversation
│   │   ├── ModelSelector.tsx     # Model picker
│   │   └── MarkdownRenderer.tsx  # Markdown message display
│   ├── hooks/
│   │   └── useChatStream.ts      # WebSocket chat hook
│   ├── types/
│   │   └── index.ts              # TypeScript interfaces
│   └── constants/
│       └── theme.ts              # Dark theme colors
├── python/                       # Python backend (Chaquopy)
│   ├── requirements.txt          # llm, fastapi, uvicorn, sqlite-utils
│   ├── server.py                 # FastAPI entry point
│   ├── headless_llm_client.py    # Adapted LLMClient
│   ├── vendored/
│   │   ├── db_operations.py      # from gtk-llm-chat
│   │   ├── platform_utils.py     # from gtk-llm-chat
│   │   └── debug_utils.py        # from gtk-llm-chat
│   └── android_keys.py           # Read keys from env vars
├── android/                      # Expo prebuild output (gitignored)
├── app.config.js                 # Expo dynamic config
├── eas.json                      # EAS build profiles
├── tsconfig.json
├── babel.config.js
└── package.json
```

## Data Flow

### Sending a message
```
1. User types message, presses Send
2. useChatStream hook → WebSocket.send({"type": "send", "prompt": "..."})
3. Python server receives message
4. headless_llm_client.send_message(prompt)
5. Worker thread streams from llm.Conversation.prompt()
6. Each chunk: _on_response(chunk) → WebSocket.send({"type": "response", "chunk": ...})
7. Finally: _on_finished(True) → WebSocket.send({"type": "finished", "success": true})
8. ChatHistory.add_history_entry() writes to logs.db
9. UI: MessageBubble accumulates chunks in real-time
```

### Loading conversation history
```
1. User taps conversation in list
2. REST GET /conversations/{id}/history
3. ChatHistory.get_conversation_history(id) reads from logs.db
4. Returns JSON array of {prompt, response, datetime} pairs
5. UI renders FlatList of MessageBubble components
```

### Model list
```
1. User opens model selector
2. REST GET /models
3. headless_llm_client.get_all_models() → llm.get_models()
4. Returns JSON array of {id, name, provider} objects
5. UI renders picker list
```

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Chaquopy build failures on CI | High | Pre-built base image with Android SDK + NDK + Python 3.10 |
| WebSocket reconnection on Android | Medium | Exponential backoff, connection state in UI |
| Large APK size (Python + libs) | Medium | ABI splits (arm64-v8a only), pip dependency audit |
| llm library API breakage | Low | Pin llm version, same as desktop |
| logs.db concurrent access (sync tools) | Low | WAL mode, gtk-llm-chat already uses thread-local connections |
| Fragments with file:// paths not working on Android | Medium | Fragment resolution adapts to Android scoped storage |
| Double-architecture complexity (RN + Python) | Medium | Chaquopy is well-documented; uvicorn on background thread is proven (see Chaquopy issue #1243); debug with local testing first |
| Python thread safety with `_is_generating_flag` | Low | Same thread model as desktop; flag + daemon thread pattern already works

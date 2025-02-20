# LLM Frontend Project Checklist

## Phase 1: Application Foundation
- [x] Create Gtk.Application subclass with unique ID
- [x] Implement window creation on activation
- [x] Support multiple instances (new window per launch)
- [x] Style with Libadwaita
- [x] Create empty window titled "LLM Chat"
- [x] Set default window size to 600x700
- [x] Verify window independence between instances
- [x] Test application launch from CLI with multiple instances
- [ ] Center window on screen (Known GTK4 issue - window positioning unreliable)

## Phase 2: Core UI Layout
- [x] Implement vertical box layout hierarchy
- [x] Create ScrolledWindow for message history
- [x] Set up input area box with proper proportions
- [x] Configure TextView with:
  - [x] Dynamic height adjustment
  - [x] Enter vs Shift+Enter handling
  - [x] Minimum/maximum line limits
- [x] Add Send button with keyboard shortcut
- [x] Verify UI responsiveness at different window sizes

## Phase 3: Message Handling
- [x] Implement Message class with:
  - [x] Sender type (user/assistant/error)
  - [x] Content storage
  - [x] Timestamp tracking
- [x] Create message queue system
- [x] Add input sanitization pipeline
- [x] Build MessageWidget components:
  - [x] CSS styling classes
  - [x] Alignment logic
  - [x] Content formatting
- [x] Implement auto-scroll behavior
- [x] Connect message submission to display system

## Phase 4: LLM Integration
- [x] Create LLMProcess controller class
- [x] Implement async subprocess execution
- [x] Set up stdout/stderr capture system
- [ ] Develop CLI command builder with:
  - [x] Basic command construction
  - [ ] Model parameter handling
  - [ ] System prompt injection
  - [ ] CID management
- [ ] Create streaming response parser:
  - [ ] Regex pattern matching
  - [x] Response buffer system
- [x] Add typing indicators
- [x] Implement cancellation support

## Phase 5: Error Handling & Status
- [x] Create ErrorWidget components:
  - [x] Warning icon integration
  - [x] Styling hierarchy
  - [x] Error message formatting
- [x] Implement error capture system for:
  - [x] Subprocess failures
  - [ ] Invalid CIDs
  - [ ] Model errors
- [ ] Add status bar with:
  - [x] Connection indicators (via window title)
  - [ ] Loading animations
- [ ] Create retry mechanism for failed messages
- [ ] Implement graceful degradation for critical errors

## Phase 6: Configuration & Persistence
- [ ] Set up GSettings schema
- [ ] Create model selector dropdown
- [ ] Implement system prompt editor
- [ ] Add conversation ID tracking
- [ ] Build SQLite storage system:
  - [ ] Message schema design
  - [ ] CID-based conversation tracking
  - [x] Auto-save implementation (usando persistencia nativa del LLM)
- [ ] Create history navigation controls
- [ ] Add "New Conversation" button

## Phase 7: UI Polish
- [ ] Implement CSS for:
  - [ ] Dark/light mode support
  - [ ] Message bubble styling
  - [ ] Error state visuals
- [ ] Apply GNOME HIG spacing rules
- [ ] Add accessibility features:
  - [ ] Screen reader labels
  - [ ] Keyboard navigation
  - [ ] Contrast validation
- [ ] Create loading animations
- [ ] Implement keyboard shortcuts overlay
- [ ] Verify touchpad gesture support

## Testing & Validation
- [ ] Create test suite for:
  - [ ] Message serialization
  - [ ] Subprocess execution
  - [ ] Error handling paths
- [ ] Perform cross-version Python testing
- [ ] Validate GNOME HIG compliance
- [ ] Test persistence across restarts
- [ ] Verify multi-instance resource isolation

## Documentation
- [ ] Write install instructions
- [ ] Create user guide for:
  - [ ] Basic usage
  - [ ] Keyboard shortcuts
  - [ ] Troubleshooting
- [ ] Generate API documentation
- [ ] Add inline docstrings
- [ ] Create contribution guidelines

## Stretch Goals
- [ ] Implement conversation search
- [ ] Add message editing
- [ ] Create export/import functionality
- [ ] Develop system tray integration
- [ ] Add notification support
- [ ] Create Flatpak package
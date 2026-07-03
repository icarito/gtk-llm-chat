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
- [ ] ~~Center window on screen (Known GTK4 issue - window positioning unreliable)~~

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
- [x] Develop CLI command builder with:
  - [x] Basic command construction
  - [x] Model parameter handling
  - [x] System prompt injection
  - [x] CID management
  - [x] Template support (-t)
  - [x] Template parameters (-p)
  - [x] Model options (-o)
- [x] Create streaming response parser:
  - [x] Response buffer system
  - [x] Clean prompt character (">") from responses
- [x] Add typing indicators
- [x] Implement cancellation support
- [x] Implement argument parsing:
  - [x] Set up argparse with:
    - [x] --cid: Conversation ID
    - [x] -s: System prompt
    - [x] -m: Model selection
    - [x] -c: Continue last conversation
    - [x] -t: Template selection
    - [x] -p: Template parameters
    - [x] -o: Model options
  - [x] Create config dictionary from parsed args
  - [x] Pass config to LLMProcess constructor
  - [x] Update LLMProcess to use config for llm chat command

## Phase 5: Error Handling & Status
- [x] Create ErrorWidget components:
  - [x] Warning icon integration
  - [x] Styling hierarchy
  - [x] Error message formatting
- [x] Implement error capture system for:
  - [x] Subprocess failures
  - [x] Invalid CIDs
  - [x] Model errors
- [x] Add status bar with:
  - [x] Connection indicators (via window title)
  - [x] Model name display
- [ ] Create retry mechanism for failed messages (need to see how that looks like on the cli)
- [ ] Implement graceful degradation for critical errors (what errors?)

## Phase 6: Configuration & Persistence
- [ ] Set up GSettings schema (what for?)
- [ ] Create model selector dropdown (where?)
- [ ] Implement system prompt editor (where?)
- [ ] Add conversation ID tracking
- [ ] ~~Build SQLite storage system:~~
  - [ ] ~~Message schema design~~
  - [ ] CID-based conversation tracking
  - [x] Auto-save implementation (usando persistencia nativa del LLM)
- [x] Template support
- [ ] Create history navigation controls (where?)
- [ ] Add "New Conversation" button (where?)

## Phase 7: UI Polish
- [x] Implement CSS for:
  - [x] Message bubble styling
  - [x] Error state visuals
- [x] Apply GNOME HIG spacing rules
- [x] Add accessibility features:
  - [ ] Screen reader labels
  - [x] Keyboard navigation
    - [x] Enter to send
    - [x] Shift+Enter for newline
    - [ ] ~~Ctrl+C to cancel~~ (unsupported by llm)
    - [x] Escape to minimize
  - [x] Input focus on window open
- [ ] Create loading animations
- [ ] Implement keyboard shortcuts overlay
- [ ] ~~Verify touchpad gesture support~~

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
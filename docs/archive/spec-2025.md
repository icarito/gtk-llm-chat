# Gtk Frontend for llm

## 1. Overview
A native GUI frontend for the `python-llm` CLI tool enabling multi-conversation management through independent GTK4 windows. Supports real-time streaming, conversation persistence, and parameter customization while adhering to GNOME HIG.

## Core Features

### 1. Multi-Window Chat Interface
- **Instance Model**:
  - Each application instance maintains exactly one window
  - No main/parent window required - single window handles all functionality
  - Multiple instances can run concurrently for parallel conversations

- **Independent Conversations**:
  - Each window manages its own conversation state
  - Supports concurrent execution of multiple instances
  - Complete isolation of configurations (model, system prompt, CID)

- **Conversation Display**:
  - Scrollable history area with distinct message styling:
    - User messages (right-aligned, light blue background)
    - LLM responses (left-aligned, light gray background)
    - Error messages (red exclamation mark + distinct styling)
  - Minimal metadata display (User/Assistant labels only)

### 2. Input Management

- **Adaptive Text Input**:
  - Multi-line `Gtk.TextView` with dynamic height adjustment
  - Submit message: Enter key
  - New line: Shift+Enter
  - Auto-clear after submission

- **Parameter Handling**:
  - Direct passthrough of CLI arguments to `llm` subprocess:
    - `--cid`: Continue specific conversation
    - `-s`: System prompt
    - `-m`: Model selection
    - `-c`: Continue most recent conversation
    - New conversation created when no CID provided

### 3. Subprocess Integration
- **Asynchronous Execution**:
  - Dedicated subprocess per window using `asyncio`
  - Real-time stdout/stderr capture
  - Non-blocking UI during LLM processing

- **Error Handling**:
  - Startup errors (invalid CID) → Terminal logging
  - Conversation errors → In-window display with visual indicators
  - Critical failures → Graceful degradation with user notification

### 4. Design & Compliance
- **GNOME HIG Adherence**:
  - Libadwaita integration for modern styling
  - Consistent spacing/margins (12px default)
  - Accessible widget labeling
  - System-compliant dark/light mode support

- **Visual Hierarchy**:
  - Clear separation between history/input areas
  - Progressive disclosure of advanced controls
  - Status indicators for active processing

## Technical Implementation

### Architecture

1. **Window Manager**:
   - Handles multi-instance lifecycle
   - Enforces conversation isolation
   - Manages cross-window dependencies

2. **Subprocess Controller**:
   - Async wrapper for `llm` executable
   - Stream parsing with regex pattern matching
   - Output buffering for partial response display

3. **UI Components**:
   - Custom message widgets with CSS styling
   - Auto-scroll management
   - Input sanitization pipeline

### Dependency Management

- **Core Stack**:
  - Python 3.10+
  - PyGObject (GTK4/Libadwaita)
  - `python-llm` package

- **Patterns**:
  - MVC separation for UI/business logic
  - Observer pattern for stream updates
  - Factory pattern for message widgets


# Phase 1: Application Foundation

## Prompt 1 - Basic Application Structure
```text
Create a Gtk.Application skeleton with proper initialization and window management. Implement:
- Application subclass with unique ID
- Primary window creation on activation
- Multi-instance support (new window per application start)
- Basic window styling with Libadwaita
- Empty window titled "LLM Chat" with default size 600x700

End with a working application that shows empty windows when launched multiple times.
```

## Prompt 2 - Core UI Layout
```text
Add the core UI components to the window:
1. Vertical box layout
2. ScrolledWindow for message history (top 80% of window)
3. Box for input area (bottom 20%) containing:
   - TextView with dynamic height (min 3 lines, max 6 lines)
   - "Send" button with keyboard shortcut (Enter)
   
Implement dynamic text view height adjustment. Connect Enter key to send action while allowing Shift+Enter for newlines.

End with a functional UI layout ready for message display.
```

# Phase 2: Message Handling

## Prompt 3 - Message Submission
```text
Implement message submission workflow:
1. Create Message class to store sender/content/timestamp
2. Add message queue system
3. Create method to handle input sanitization:
   - Strip whitespace
   - Prevent empty submissions
4. Clear input after submission
5. Add temporary console logging of sent messages

End with messages being captured/logged but not yet displayed.
```

## Prompt 4 - Message Display System
```text
Implement message visualization:
1. Create custom MessageWidget extending Gtk.Box
2. Add CSS classes for user/assistant styling
3. Implement right/left alignment based on sender
4. Add auto-scroll to bottom on new message
5. Connect message queue to display pipeline

End with submitted messages appearing in history with basic styling.
```

# Phase 3: LLM Integration

## Prompt 5 - Async Subprocess Setup
```text
Implement async subprocess controller:
1. Create LLMProcess class with asyncio integration
2. Basic command construction from messages
3. stdout/stderr capture infrastructure
4. Non-blocking execution that maintains UI responsiveness
5. Temporary debug output of raw LLM responses

Use python-llm CLI syntax. End with messages triggering LLM execution with output logged to console.
```

## Prompt 6 - Streaming Response Handling
```text
Add real-time response processing:
1. Implement output parser with regex pattern matching
2. Create response buffer with incremental updates
3. Connect subprocess output to message display
4. Add typing indicator during generation
5. Implement cancellation support via CTRL+C

End with streaming responses appearing incrementally in chat history.
```

# Phase 4: Error Handling & Status

## Prompt 7 - Error Management
```text
Implement error handling system:
1. Create ErrorWidget with warning icon and styling
2. Capture subprocess exceptions
3. Handle invalid CIDs and model errors
4. Add status bar with connection indicators
5. Implement retry mechanism for failed messages

End with error messages displaying in-chat and recoverable failures.
```

# Phase 5: Configuration & Persistence

## Prompt 8 - Parameter Management
```text
Add configuration controls:
1. Create persistent settings with GSettings
2. Add model selector dropdown
3. Implement system prompt text field
4. Add conversation ID tracking
5. Connect controls to LLMProcess parameters

End with configurable model/system prompt per window instance.
```

## Prompt 9 - Conversation Persistence
```text
Implement conversation history:
1. Add SQLite storage for messages
2. Create CID-based conversation tracking
3. Add history navigation controls
4. Implement auto-save on message exchange
5. Add "New Conversation" button

End with persistent conversations that survive application restarts.
```

# Phase 6: Final Integration

## Prompt 10 - UI Polish
```text
Apply final HIG-compliant styling:
1. Add CSS for dark/light mode support
2. Implement proper spacing/margins
3. Add accessibility labels
4. Create loading animations
5. Add keyboard shortcuts cheatsheet

End with a polished interface meeting all GNOME HIG requirements.
```
# GTK LLM Chat

A GTK graphical interface for chatting with Large Language Models (LLMs).

![screenshot](./docs/screenshot01.png)

## Key Features

- Simple and easy-to-use graphical interface built with GTK
- Support for multiple conversations in independent windows
- Integration with python-llm for chatting with various LLM models
- Modern interface using libadwaita
- Support for real-time streaming responses
- Message history with automatic scrolling
- Markdown rendering of the responses
- Keyboard shortcuts (Enter to send, Shift+Enter for new line)
- **Support for fragments:** Include external content (files, URLs, or text snippets) in your prompts.
- **Conversation Management:** Rename and delete conversations.
- **Applet Mode:** Run a system tray applet for quick access to recent conversations.
- **Model Selection:** Choose from different LLM models.
- **System Prompt:** Set a custom system prompt for each conversation.
- **Error Handling:** Clear error messages displayed in the chat.
- **Dynamic Input:** The input area dynamically adjusts its height.
- **Keyboard Shortcuts:**
    - `Enter`: Send message.
    - `Shift+Enter`: New line in the input.
    - `Ctrl+W`: Delete the current conversation.

## Installation

```
pipx install llm               # required by gtk-llm-chat
llm install gtk-llm-chat
```

### System Requirements

- [llm](https://llm.datasette.io/en/stable/)
- Python 3.8 or higher
- GTK 4.0
- libadwaita
- libayatana-appindicator

## Usage

Run the application:
```
llm gtk-applet
```

or for an individual chat:
```
llm gtk-chat
```

With optional arguments:
```
llm gtk-chat --cid CONVERSATION_ID  # Continue a specific conversation
llm gtk-chat -s "System prompt"  # Set system prompt
llm gtk-chat -m model_name  # Select specific model
llm gtk-chat -c  # Continue last conversation
```

## Development

To set up the development environment:
```
git clone https://github.com/icarito/gtk-llm-chat.git
cd gtk-llm-chat
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## License

GPLv3 License - See LICENSE file for more details.

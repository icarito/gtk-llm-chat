# GTK LLM Chat

A GTK graphical interface for chatting with large language models (LLMs).

![screenshot](./docs/screenshot01.png)

## Features

- Simple and easy-to-use graphical interface built with GTK
- Support for multiple conversations in independent windows
- Integration with python-llm for chatting with various LLM models
- Modern interface using libadwaita
- Support for real-time streaming responses
- Message history with automatic scrolling
- Keyboard shortcuts (Enter to send, Shift+Enter for new line)

## Installation

```
pipx install llm               # required by gtk-llm-chat
llm install gtk-chat
```

### System Requirements

- [llm](https://llm.datasette.io/en/stable/)
- Python 3.8 or higher
- GTK 4.0
- libadwaita
- libayatana-appindicator

On Debian/Ubuntu-based systems:
```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libadwaita-1-0 libayatana-appindicator3-1
```

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

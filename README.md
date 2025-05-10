# GTK LLM Chat

A GTK graphical interface for chatting with Large Language Models (LLMs).

![screenshot](./docs/screenshot01.png)

<a href="https://www.buymeacoffee.com/icarito" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a> if you find this project useful.


## Key Features

- Simple and easy-to-use graphical interface built with GTK
- Support for multiple conversations in independent windows
- Integration with python-llm for chatting with various LLM models
- Modern interface using libadwaita
- Support for real-time streaming responses
- Message history with automatic scrolling
- Windows installer and Linux AppImage available
- Markdown rendering of the responses

- **Sidebar Navigation:** Modern sidebar for model/provider selection, parameters, and settings.
- **Model Parameters:** Adjust temperature and system prompt per conversation.
- **API Key Management:** Banner with symbolic icons for setting/changing API keys per provider.
- **Keyboard Shortcuts:**
    - `F10`: Toggle sidebar
    - `F2`: Rename conversation
    - `Escape`: Minimize window
    - `Enter`: Send message
    - `Shift+Enter`: New line in input
    - `Ctrl+W`: Delete the current conversation
- **Conversation Management:** Rename and delete conversations.
- **Applet Mode:** Run a system tray applet for quick access to recent conversations.
- **Model Selection:** Choose from different LLM models.
- **System Prompt:** Set a custom system prompt for each conversation.
- **Error Handling:** Clear error messages displayed in the chat.
- **Dynamic Input:** The input area dynamically adjusts its height.

## Installation

```
pipx install llm               # required by gtk-llm-chat
llm install gtk-llm-chat
```

You may want to manually copy the .desktop files to `~/.local/share/applications/` to make them available in your application menu.

### Downloadable packages

Windows installers and Linux Appimages are available in our _releases_ section.

While they are fully functional, there is no mechanism provided thru the GUI for adding plugins or API keys <s>and no system tray applet support either</s>.

While in the future the UI will be complete, for now, you'll have to manually add your API keys to your `keys.json` file.

In order to invoke the applet from the AppImage, you can use the --applet command argument.

### Dependencies

These are collected here for reference only, let me know if the list needs adjusting.

```
 # fedora: # sudo dnf install cairo-devel object-introspection-devel gtk4-devel pkgconf-pkg-config gcc redhat-rpm-config
 # debian: # sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libadwaita-1-0
```

### System Requirements

- [llm](https://llm.datasette.io/en/stable/)
- Python 3.8 or higher
- GTK 4.0
- libadwaita
- libayatana-appindicator (optional)

## Usage


### Running the Application

To start the applet (system tray mode):
```
llm gtk-applet
```

To start a single chat window:
```
llm gtk-chat
```

#### Optional arguments:
```
llm gtk-chat --cid CONVERSATION_ID   # Continue a specific conversation
llm gtk-chat -s "System prompt"      # Set system prompt
llm gtk-chat -m model_name           # Select specific model
llm gtk-chat -c                      # Continue last conversation
```

### Features Overview

- Use the sidebar to select providers/models, adjust parameters, and manage API keys.
- API key banner will appear when a provider requires a key. Use the button with the key or open-lock icon to set or change your key.
- Model parameters (temperature, system prompt) are per conversation and accessible from the sidebar.
- Keyboard shortcuts for sidebar, rename, minimize, and more (see above).

## Development

To set up the development environment:
```
git clone https://github.com/icarito/gtk-llm-chat.git
cd gtk-llm-chat
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Shoulders of giants

This project is made possible thanks to these great components, among others:

- [llm](https://llm.datasette.io/en/stable/) by @simonw
- [hello-world-gtk](https://github.com/zevlee/hello-world-gtk) by @zevlee

## License

GPLv3 License - See LICENSE file for more details.

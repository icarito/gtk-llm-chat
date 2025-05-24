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
- Windows installer, Linux AppImage, and Macos bundles available!
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
- **Tray aooket:** Use a system tray applet for quick access to recent conversations.
- **Error Handling:** Clear error messages displayed in the chat.
- **Dynamic Input:** The input area dynamically adjusts its height.

**Gtk-LLM-Chat** is a graphical frontend for the command-line llm utility. Just as `llm` integrates large language models into the [command line interface](https://llm.datasette.io/en/stable/usage.html), Gtk-LLM-Chat aims to bring that same power to the desktop environment. Its goal is to provide intuitive affordances and seamless integration for using LLMs in everyday tasks — all while remaining convenient, lightweight, and transparent in its behavior.

## Installation

### Downloadable application bundles

While the command line is fun in every operating system, **Gtk-LLM-Chat** also offers prepackaged binary application bundles for all three major operating sytems: Windows installers, Linux Appimages and Macos Application Bundles are available in our [_releases_](https://github.com/icarito/gtk-llm-chat/releases) section.

An effort has been made to support desktop integration across systems but _your mileage may vary_ - as the Gtk tools are still maturing outside of the GNU/Linux ecosystem.

### As an `llm` plugin

Playing with LLMs in the command line is fun! I recommend you to install `llm` and play around with it to size up the possibilities. Gtk-LLM-Chat can be installed as a plugin extension for `llm` itself, thus extending the possibilities of `llm` with some graphical features. Not all features of `llm` are exposed yet.

```
pipx install llm               # required by gtk-llm-chat
llm install gtk-llm-chat
```

You may want to copy the provided .desktop files to your ~/.local/share/applications/ folder. A welcome assistant will do this in the future for you.


### System Requirements

- [llm](https://llm.datasette.io/en/stable/) (when installing as an llm plugin)
- Python 3.8 or higher
- GTK 4.0
- libadwaita
- libayatana-appindicator (on linux)

These dependency installation instructions are collected here for reference only:

```
 # fedora: # sudo dnf install cairo-devel object-introspection-devel gtk4-devel pkgconf-pkg-config gcc redhat-rpm-config
 # debian: # sudo apt install libgtk-4-1 python3-gi python3-gi-cairo libadwaita-1-0 libayatana-appindicator3
 # arch: # sudo pacman -S python-gobject gtk4 
```

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

#!/bin/bash

# Compile .po files to .mo files
for lang in po/*; do
    if [ -d "$lang" ]; then
        if [ -f "$lang/LC_MESSAGES/gtk-llm-chat.po" ]; then
            msgfmt "$lang/LC_MESSAGES/gtk-llm-chat.po" -o "$lang/LC_MESSAGES/gtk-llm-chat.mo"
            echo $lang
        fi
    fi
done

echo "Compiled .po files to .mo files."
#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: add_language.sh <language_code>"
    exit 1
fi

lang=$1

if [ -d "po/$lang" ]; then
    echo "Language '$lang' already exists."
    exit 1
fi

mkdir -p "po/$lang/LC_MESSAGES"
cp "po/gtk-llm-chat.pot" "po/$lang/LC_MESSAGES/gtk-llm-chat.po"

echo "Language '$lang' added."
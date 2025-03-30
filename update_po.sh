#!/bin/bash

# Update .pot file
xgettext --package-name=gtk-llm-chat --package-version=0.1 --copyright-holder="Your Name" --msgid-bugs-address="your@email.com" \
    --directory=. $(find gtk_llm_chat -name "*.py") -o po/gtk-llm-chat.pot

# Update .po files for each language
for lang in po/*; do
    if [ -d "$lang" ]; then
        if [ -f "$lang/LC_MESSAGES/gtk-llm-chat.po" ]; then
            msgmerge --update "$lang/LC_MESSAGES/gtk-llm-chat.po" po/gtk-llm-chat.pot
        fi
    fi
done

echo "Updated .pot and .po files."
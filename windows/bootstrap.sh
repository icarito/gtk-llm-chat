pacman -S --noconfirm mingw-w64-$(uname -m)-gtk4 mingw-w64-$(uname -m)-python-pip mingw-w64-$(uname -m)-python3-gobject mingw-w64-$(uname -m)-libadwaita mingw-w64-$(uname -m)-rust git zlib-devel mingw-w64-x86_64-python3-pillow
echo VERSION=\"$(git describe --tags --exact-match)\"  >> .env.ci

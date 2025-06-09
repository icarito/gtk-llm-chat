pacman -S --noconfirm mingw-w64-$(uname -m)-gtk4 mingw-w64-$(uname -m)-python-pip mingw-w64-$(uname -m)-python3-gobject mingw-w64-$(uname -m)-libadwaita mingw-w64-$(uname -m)-rust git zlib zlib-devel mingw-w64-x86_64-python3-pillow
# Usar git describe para versioning, con fallback a commit hash si no hay tag
VERSION=$(git describe --tags --exact-match 2>/dev/null || git describe --tags --always || echo "dev-$(git rev-parse --short HEAD)")
echo VERSION=\"$VERSION\" >> .env.ci

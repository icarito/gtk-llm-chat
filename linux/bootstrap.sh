apt install libgtk-4-1 libgtk-4-dev libadwaita-1-0 gir1.2-girepository-2.0 libgirepository1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi python3-gi-cairo
echo VERSION=\"$(git describe --tags --abbrev=0)\" >> .env.ci

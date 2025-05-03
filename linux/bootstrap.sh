apt install libgtk-4-1 libgtk-4-dev libadwaita-1-0 gcc libcairo2-dev pkg-config python3-dev libgirepository-2.0-0 libgirepository-2.0-dev gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-girepository-3.0 gir1.2-girepository-3.0-dev gir1.2-ayatanaappindicator3-0.1 libcairo-gobject2 libcairo2-dev libssl-dev
echo VERSION=\"$(git describe --tags --exact-match)\"  >> .env.ci

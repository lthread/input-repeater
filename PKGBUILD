# Maintainer: lthread
pkgname=input-repeater
pkgver=1.6.0
pkgrel=1
pkgdesc="Record and replay mouse and keyboard input on KDE Plasma (Wayland and X11)"
url="https://github.com/lthread/input-repeater"
arch=('any')
license=('MIT')
depends=('python' 'python-evdev' 'python-dbus' 'python-gobject' 'python-pyqt6' 'kwin' 'libnotify')
install=$pkgname.install
source=('input_repeater.py' 'gui.py' 'i18n.py' 'input-repeater.svg' 'input-repeater.desktop'
        '60-input-repeater.rules' 'LICENSE')
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')

package() {
    install -Dm644 input_repeater.py gui.py i18n.py -t "$pkgdir/usr/lib/$pkgname/"
    install -Dm644 input-repeater.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/$pkgname.svg"
    install -Dm644 input-repeater.desktop "$pkgdir/usr/share/applications/$pkgname.desktop"
    install -Dm644 60-input-repeater.rules -t "$pkgdir/usr/lib/udev/rules.d/"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"

    install -dm755 "$pkgdir/usr/bin"
    printf '#!/bin/sh\nexec python3 /usr/lib/%s/gui.py "$@"\n' "$pkgname" > "$pkgdir/usr/bin/$pkgname"
    printf '#!/bin/sh\nexec python3 /usr/lib/%s/input_repeater.py "$@"\n' "$pkgname" > "$pkgdir/usr/bin/$pkgname-cli"
    chmod 755 "$pkgdir/usr/bin/$pkgname" "$pkgdir/usr/bin/$pkgname-cli"
}

# Input Repeater

Record and replay mouse movement, clicks, scrolling and keyboard input on Linux with KDE Plasma. It uses global hotkeys, supports loops and runs from the system tray.

[Українська версія](README.uk.md)

## Features

- **Global hotkeys** start and stop recording and playback. A hotkey can be a single key, a combination like `Ctrl+Alt+R`, or a side mouse button.
- **Pixel-exact cursor positions** come straight from KWin, so pointer acceleration does not affect playback. Playback can also run relative to the current cursor position.
- **Loops:** repeat N times or until stopped, with a pause between repeats and speed from 0.1× to 10×.
- **Choose what to record:** mouse movement, clicks and wheel, keyboard.
- **Recording library:** rename recordings, or delete them to the trash.
- **Safe stop:** playback stops as soon as you move the mouse or press a key.
- **Live state:**
  - the tray icon changes with the state and animates while recording and playing;
  - playback progress ("Repeat 2 of 5 · 43%") shows in the window, in the tray tooltip and on the taskbar.
- **Interface languages:** English and Ukrainian.

## Requirements

- Linux with **KDE Plasma 6**, either Wayland or X11.
- Python 3 with `python-evdev`, `dbus-python`, `PyGObject` and `PyQt6`, plus `libnotify` (`notify-send`).
- Your user in the `input` group, to read keyboards and mice.
- Access to `/dev/uinput`, to replay input. The included udev rule grants it.

Other desktops (GNOME, Sway, Hyprland), Plasma 5, Windows and macOS are not supported. Exact cursor positions come from KWin, and input goes through Linux evdev/uinput.

## Installation

### Arch Linux and derivatives

From the AUR (once published):

```bash
yay -S input-repeater
```

Or build from this repository:

```bash
git clone https://github.com/lthread/input-repeater.git
cd input-repeater
makepkg -si
```

### Other distributions (from source)

Install the dependencies:

```bash
# Fedora
sudo dnf install python3-evdev python3-dbus python3-gobject python3-pyqt6 libnotify
# openSUSE Tumbleweed
sudo zypper install python3-evdev python3-dbus-python python3-gobject python3-PyQt6 libnotify-tools
# KDE neon / Kubuntu
sudo apt install python3-evdev python3-dbus python3-gi python3-pyqt6 libnotify-bin
```

Then get the code and allow your session to create virtual input devices:

```bash
git clone https://github.com/lthread/input-repeater.git
cd input-repeater
sudo install -Dm644 60-input-repeater.rules /etc/udev/rules.d/60-input-repeater.rules
sudo udevadm control --reload && sudo udevadm trigger --sysname-match=uinput
```

Start it with `python3 gui.py`, or run the script without the window with `python3 input_repeater.py`.

### Last step (all distributions)

```bash
sudo usermod -aG input $USER
```

Log out and back in for the group to take effect.

> Members of the `input` group can read all keyboards and mice. Global recording on Wayland is impossible without this.

## Usage

Start **Input Repeater** from the application menu and press **Start**. Default hotkeys:

- **F9**: start or stop recording. Each recording is saved separately and becomes the active one.
- **F10**: play the active recording. Press it again to stop.

Closing the window hides it to the tray. Quit from the tray icon menu; this also stops the script.

## Settings

Everything is configured in the window:

| Setting | Takes effect |
|---|---|
| Active recording, what to record, loop, pause, speed, mouse mode, safe stop | on the next recording or playback, no restart needed |
| Hotkeys, notifications | after restarting the script (locked while it runs) |
| Interface language | immediately; script messages switch after the script restarts |

**Hotkeys:** click the field and press a key, a combination or a side mouse button. Held modifiers show as `CTRL+ALT+…`. If you give both actions the same combination, they swap.

**Mouse movement during playback:**
- *Exact screen coordinates*: the cursor follows the same screen points as during recording.
- *From the current cursor position*: the whole recording shifts to start where the cursor is now.

**Files:**
- settings: `~/.config/input-repeater/config.json`;
- recordings: `~/.local/share/input-repeater/macros/`.

Deleted recordings go to the trash.

## How it works

- Keys, mouse buttons and the wheel are read directly from `/dev/input` (evdev), so recording is global.
- KWin reports the exact cursor position through a temporary KWin script. It runs only while recording, and briefly at the start of a relative playback.
- Playback uses two virtual `uinput` devices: a keyboard and an absolute pointer.

## Limitations

- Hotkeys are not grabbed, so the active window receives them too. Pick combinations that don't conflict.
- Combinations taken by KDE global shortcuts cannot be captured in the hotkey field.
- Touchpad taps and two-finger scrolling are gestures, so they are not recorded. Physical touchpad clicks are.
- A tablet pen is recorded as movement plus left click.
- If the monitor layout changes after recording, exact coordinates won't match.
- On Wayland, KWin decides where windows appear. To make the window keep its position, add a KWin window rule for the class `input-repeater` with *Position → Remember*.

## License

[MIT](LICENSE) © 2026 lthread

#!/usr/bin/env python3
"""Input Repeater — запис і повтор дій миші та клавіатури для KDE Plasma (Wayland).

Клавіші, кнопки миші та колесо читаються напряму з /dev/input (evdev),
точна позиція курсора — від KWin через тимчасовий KWin-скрипт,
відтворення — через віртуальні пристрої uinput (клавіатура + абсолютний вказівник).

З ключем --gui скрипт додатково друкує службові рядки для оболонки:
  @state idle|recording|waiting|playing,   @macro <назва нового запису>,
  @progress <повтор> <усього, 0 = ∞> <частка поточного повтору>
"""
import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

import dbus
import dbus.mainloop.glib
import dbus.service
import evdev
from evdev import AbsInfo, UInput, ecodes as e
from gi.repository import GLib

try:  # PyGObject ≥ 3.50; на старіших дистрибутивах (Debian 12, Ubuntu 22.04) — стара назва
    from gi.repository import GLibUnix
    unix_signal_add = GLibUnix.signal_add
except ImportError:
    unix_signal_add = GLib.unix_signal_add

from i18n import _, set_language

APP = "input-repeater"
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), APP)
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
MACROS_DIR = os.path.join(DATA_DIR, "macros")

# іконка сповіщень: із теки проєкту — шлях до SVG поруч; у встановленому пакеті — іконка теми й ярлик програми
LOCAL_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), APP + ".svg")
NOTIFY_ICON_ARGS = (["-i", LOCAL_ICON] if os.path.exists(LOCAL_ICON)
                    else ["-i", APP, "-h", f"string:desktop-entry:{APP}"])

DEFAULT_CONFIG = {
    "record_hotkey": "F9",
    "play_hotkey": "F10",
    "macro": "",
    "language": "",  # порожньо — мова системи; оболонка при першому запуску запам'ятовує її
    "loop": False,
    "loop_count": 0,
    "loop_delay": 1.0,
    "speed": 1.0,
    "relative": False,
    "stop_on_input": True,
    "record_moves": True,
    "record_clicks": True,
    "record_keys": True,
    "notifications": True,
}

# модифікатори для комбінацій: CTRL означає лівий або правий Ctrl тощо
MODIFIERS = {
    "CTRL": {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL},
    "ALT": {e.KEY_LEFTALT, e.KEY_RIGHTALT},
    "SHIFT": {e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT},
    "META": {e.KEY_LEFTMETA, e.KEY_RIGHTMETA},
}
MODIFIERS["SUPER"] = MODIFIERS["WIN"] = MODIFIERS["META"]
MODIFIER_CODES = set().union(*MODIFIERS.values())

DEV_PREFIX = "input-repeater"  # наші віртуальні пристрої — їх не слухаємо
KWIN_SCRIPT_NAME = "input_repeater_cursor"
DBUS_PATH = "/cursor"
DBUS_IFACE = "local.InputRepeater"
ABS_MAX = 65535
INTERRUPT_MOVE = 30  # на скільки одиниць треба зрушити мишу, щоб перервати відтворення

KEY_CODES = range(1, 256)                         # звичайні клавіші клавіатури
BUTTON_CODES = range(e.BTN_LEFT, e.BTN_TASK + 1)  # кнопки миші
WHEEL_CODES = (e.REL_WHEEL, e.REL_HWHEEL)

KWIN_SCRIPT = """
var g = workspace.virtualScreenGeometry;
callDBus("{service}", "{path}", "{iface}", "geometry", g.x, g.y, g.width, g.height);
function send() {{
    var p = workspace.cursorPos;
    callDBus("{service}", "{path}", "{iface}", "pos", p.x, p.y);
}}
send();
workspace.cursorPosChanged.connect(send);
"""


def write_json(path, data):
    """Атомарний запис: інший процес ніколи не прочитає напівзаписаний файл."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        write_json(CONFIG_PATH, DEFAULT_CONFIG)
    with open(CONFIG_PATH) as f:
        return {**DEFAULT_CONFIG, **json.load(f)}


def update_config(key, value):
    """Змінює один ключ, не зачіпаючи решту (файл пишуть і скрипт, і оболонка)."""
    cfg = load_config()
    cfg[key] = value
    write_json(CONFIG_PATH, cfg)
    return cfg


def macro_path(name):
    return os.path.join(MACROS_DIR, name + ".json")


def list_macros():
    """Назви записів, новіші першими."""
    if not os.path.isdir(MACROS_DIR):
        return []
    files = [f for f in os.listdir(MACROS_DIR) if f.endswith(".json")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(MACROS_DIR, f)), reverse=True)
    return [f[:-5] for f in files]


def load_macro(name):
    with open(macro_path(name)) as f:
        return json.load(f)


def parse_key(name):
    name = name.upper()
    for candidate in (name, "KEY_" + name):
        if candidate in e.ecodes:
            return e.ecodes[candidate]
    sys.exit(_("Unknown key in config.json: {name}").format(name=name))


def parse_hotkey(text):
    """'CTRL+ALT+R' -> (набір груп модифікаторів, код основної клавіші)."""
    *mods, key = [part.strip().upper() for part in text.split("+")]
    for mod in mods:
        if mod not in MODIFIERS:
            sys.exit(_("Unknown modifier in config.json: {mod} (available: CTRL, ALT, SHIFT, META)")
                     .format(mod=mod))
    return frozenset(frozenset(MODIFIERS[m]) for m in mods), parse_key(key)


def is_recordable(code):
    return code in KEY_CODES or code in BUTTON_CODES


class CursorReceiver(dbus.service.Object):
    """Приймає виклики від KWin-скрипта."""

    def __init__(self, bus, app):
        super().__init__(bus, DBUS_PATH)
        self.app = app

    @dbus.service.method(DBUS_IFACE)
    def pos(self, x, y):
        self.app.on_cursor(float(x), float(y))

    @dbus.service.method(DBUS_IFACE)
    def geometry(self, x, y, w, h):
        self.app.geometry = [float(x), float(y), float(w), float(h)]


class KWinCursorTracker:
    """Завантажує в KWin скрипт, який шле позицію курсора при кожному русі."""

    def __init__(self, bus):
        self.bus = bus
        self.scripting = bus.get_object("org.kde.KWin", "/Scripting")
        self.path = None

    def start(self):
        self.stop()
        fd, self.path = tempfile.mkstemp(prefix="input_repeater_", suffix=".js")
        with os.fdopen(fd, "w") as f:
            f.write(KWIN_SCRIPT.format(service=self.bus.get_unique_name(), path=DBUS_PATH, iface=DBUS_IFACE))
        sid = self.scripting.loadScript(self.path, KWIN_SCRIPT_NAME,
                                        dbus_interface="org.kde.kwin.Scripting", signature="ss")
        if sid < 0:
            raise RuntimeError(_("KWin failed to load the cursor tracking script"))
        self.bus.get_object("org.kde.KWin", f"/Scripting/Script{sid}").run(dbus_interface="org.kde.kwin.Script")

    def stop(self):
        self.scripting.unloadScript(KWIN_SCRIPT_NAME, dbus_interface="org.kde.kwin.Scripting")
        if self.path:
            os.remove(self.path)
            self.path = None


class Player:
    """Відтворює записані події у фоновому потоці."""

    def __init__(self):
        self.kbd = UInput({e.EV_KEY: list(KEY_CODES)}, name=f"{DEV_PREFIX} keyboard")
        self.ptr = UInput({
            e.EV_KEY: list(BUTTON_CODES),
            e.EV_REL: list(WHEEL_CODES),
            e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, ABS_MAX, 0, 0, 0)),
                       (e.ABS_Y, AbsInfo(0, 0, ABS_MAX, 0, 0, 0))],
        }, name=f"{DEV_PREFIX} pointer")
        self.pressed = set()
        self.iteration = 0   # який повтор зараз іде (з 1)
        self.progress = 0.0  # скільки пройдено в поточному повторі, 0..1
        self.stop_flag = threading.Event()
        self.thread = None

    def playing(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, macro, cfg, offset, on_done):
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._run, args=(macro, cfg, offset, on_done), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join()
        self.kbd.close()
        self.ptr.close()

    def _run(self, macro, cfg, offset, on_done):
        repeats = (cfg["loop_count"] if cfg["loop"] else 1) or float("inf")
        done = 0
        while done < repeats and not self.stop_flag.is_set():
            if done and self.stop_flag.wait(cfg["loop_delay"]):
                break
            self.iteration, self.progress = done + 1, 0.0
            self._play_once(macro, cfg["speed"], offset)
            self._release_all()
            done += 1
        on_done(done)

    def _play_once(self, macro, speed, offset):
        gx, gy, gw, gh = macro["geometry"]
        dx, dy = offset
        duration = macro["events"][-1][0] or 1.0
        start = time.monotonic()
        for t, kind, a, b in macro["events"]:
            if self.stop_flag.wait(max(0.0, start + t / speed - time.monotonic())):
                return
            self.progress = t / duration
            if kind == "m":
                self.ptr.write(e.EV_ABS, e.ABS_X, self._scale(a + dx - gx, gw))
                self.ptr.write(e.EV_ABS, e.ABS_Y, self._scale(b + dy - gy, gh))
                self.ptr.syn()
            elif kind == "k":
                self._key(a, b)
            elif kind == "w":
                self.ptr.write(e.EV_REL, a, b)
                self.ptr.syn()

    @staticmethod
    def _scale(v, size):
        return max(0, min(ABS_MAX, round(v * (ABS_MAX + 1) / size)))

    def _key(self, code, value):
        dev = self.kbd if code in KEY_CODES else self.ptr
        dev.write(e.EV_KEY, code, value)
        dev.syn()
        if value:
            self.pressed.add(code)
        else:
            self.pressed.discard(code)

    def _release_all(self):
        for code in list(self.pressed):
            self._key(code, 0)


class App:
    def __init__(self, gui=False):
        cfg = load_config()
        set_language(cfg["language"])
        self.gui = gui
        self.notifications = cfg["notifications"]
        self.rec_cfg = cfg
        self.hotkeys = [(parse_hotkey(cfg["record_hotkey"]), self.toggle_record),
                        (parse_hotkey(cfg["play_hotkey"]), self.toggle_play)]

        bus = dbus.SessionBus()
        self.receiver = CursorReceiver(bus, self)
        self.tracker = KWinCursorTracker(bus)
        self.tracker.stop()  # прибрати залишок після аварійного завершення
        self.player = Player()

        self.recording = False
        self.events = []
        self.t0 = 0.0
        self.geometry = None
        self.swallowed = set()       # основні клавіші спрацьованих комбінацій: їх відпускання не записуємо
        self.play_request = None     # (cfg, macro): відтворення чекає, поки відпустять клавіші комбінації
        self.awaiting_origin = None  # (cfg, macro): відтворення чекає поточну позицію курсора (режим relative)
        self.play_cfg = cfg
        self.moved = 0               # наскільки користувач зрушив мишу під час відтворення
        self.interrupted = False

        self.devices = {}
        self.warned_denied = False
        self.scan_devices()
        if not self.devices:
            sys.exit(_("No access to any keyboard or mouse. Add yourself to the input group (see README.md)."))
        GLib.timeout_add_seconds(2, self.scan_devices)

        print(_("Ready. {rec}: start/stop recording, {play}: play/stop.").format(
            rec=cfg["record_hotkey"], play=cfg["play_hotkey"]))
        print(_("Active recording: {name}").format(name=cfg["macro"]) if cfg["macro"] else _("No recordings yet"))
        self.emit("state", "idle")

    # ---------- пристрої ----------

    def scan_devices(self):
        denied = []
        for path in evdev.list_devices():
            if path in self.devices:
                continue
            try:
                dev = evdev.InputDevice(path)
            except PermissionError:
                denied.append(path)
                continue
            except OSError:
                continue
            keys = set(dev.capabilities().get(e.EV_KEY, []))
            pen = e.BTN_TOOL_PEN in keys
            if dev.name.startswith(DEV_PREFIX) or not (pen or any(map(is_recordable, keys))):
                dev.close()
                continue
            self.devices[path] = dev
            GLib.io_add_watch(dev.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                              self.on_readable, path, pen)
        if denied and not self.warned_denied:
            self.warned_denied = True
            print(_("Warning: no access to {count} input devices (the keyboard may not be recorded). "
                    "Add yourself to the input group, see README.md.").format(count=len(denied)))
        return True

    def on_readable(self, fd, cond, path, pen):
        dev = self.devices[path]
        try:
            for ev in dev.read():
                self.on_event(ev, pen)
        except BlockingIOError:
            pass
        except OSError:  # пристрій від'єднано
            dev.close()
            del self.devices[path]
            return False
        return True

    def held_keys(self):
        """Фізично затиснуті зараз клавіші й кнопки (стан ядра, тож не «залипає»)."""
        held = set()
        for dev in list(self.devices.values()):
            try:
                held.update(dev.active_keys())
            except OSError:
                pass
        return {code for code in held if is_recordable(code)}

    def on_event(self, ev, pen):
        if ev.type == e.EV_KEY and ev.value != 2:  # 2 = автоповтор, його відтворить сама система
            code = e.BTN_LEFT if pen and ev.code == e.BTN_TOUCH else ev.code
            if is_recordable(code):
                self.on_key(code, ev.value)
            # окремий модифікатор не перериває: з нього починається комбінація зупинки
            if ev.value == 1 and code not in self.swallowed and code not in MODIFIER_CODES:
                self.interrupt()
        elif ev.type == e.EV_REL:
            if ev.code in WHEEL_CODES:
                if self.recording:
                    self.add("w", ev.code, ev.value)
                self.interrupt()
            elif ev.code in (e.REL_X, e.REL_Y):
                self.moved += abs(ev.value)
                if self.moved > INTERRUPT_MOVE:
                    self.interrupt()

    def on_key(self, code, value):
        if value:
            action = self.hotkey_action(code)
            if action:
                self.swallowed.add(code)
                action()
            elif self.recording:
                self.add("k", code, value)
            return
        if code in self.swallowed:
            self.swallowed.discard(code)
        elif self.recording:
            self.add("k", code, value)
        if self.play_request and not self.held_keys():
            self.begin_play()

    def hotkey_action(self, code):
        held = self.held_keys() - {code}
        mods = frozenset(group for group in map(frozenset, MODIFIERS.values()) if group & held)
        for (need, key), action in self.hotkeys:
            if code == key and mods == need:
                return action
        return None

    def on_cursor(self, x, y):
        if self.recording:
            self.add("m", x, y)
        elif self.awaiting_origin:
            (cfg, macro), self.awaiting_origin = self.awaiting_origin, None
            GLib.idle_add(self.tracker.stop)
            first = next((ev for ev in macro["events"] if ev[1] == "m"), None)
            self.start_player(cfg, macro, (x - first[2], y - first[3]) if first else (0, 0))

    def add(self, kind, a, b):
        what = {"m": "record_moves", "w": "record_clicks"}.get(kind) or (
            "record_keys" if a in KEY_CODES else "record_clicks")
        if not self.rec_cfg[what]:
            return
        self.events.append([round(time.monotonic() - self.t0, 4), kind, a, b])

    # ---------- запис ----------

    def toggle_record(self):
        if self.player.playing() or self.play_request or self.awaiting_origin:
            print(_("Stop playback first."))
            return
        if not self.recording:
            try:
                self.rec_cfg = load_config()  # що записувати — читається заново при кожному записі
            except ValueError as ex:
                self.notify(_("Error in config.json: {error}").format(error=ex))
                return
            self.events = []
            self.geometry = None
            self.t0 = time.monotonic()
            self.tracker.start()
            self.recording = True
            self.emit("state", "recording")
            self.notify(_("Recording started"))
            return

        self.recording = False
        self.tracker.stop()
        self.emit("state", "idle")
        # модифікатори комбінації зупинки (напр. Ctrl+Alt) встигли записатись як натиснуті — прибираємо
        for code in self.held_keys():
            for i in range(len(self.events) - 1, -1, -1):
                if self.events[i][1] == "k" and self.events[i][2] == code:
                    if self.events[i][3] == 1:
                        del self.events[i]
                    break
        if not self.events or self.geometry is None:
            self.notify(_("Recording is empty, nothing saved"))
            return
        name = _("Recording") + time.strftime(" %Y-%m-%d %H:%M:%S")
        write_json(macro_path(name), {"geometry": self.geometry, "events": self.events})
        try:
            update_config("macro", name)
        except ValueError as ex:
            self.notify(_("Error in config.json: {error}").format(error=ex))
        self.emit("macro", name)
        self.notify(_("Saved “{name}”: {count} events, {seconds:.1f} s").format(
            name=name, count=len(self.events), seconds=self.events[-1][0]))

    # ---------- відтворення ----------

    def toggle_play(self):
        if self.recording:
            print(_("Stop recording first."))
            return
        if self.player.playing():
            self.player.stop()
            return
        if self.play_request or self.awaiting_origin:
            return
        # налаштування й активний запис читаються заново при кожному запуску
        try:
            cfg = load_config()
        except ValueError as ex:
            self.notify(_("Error in config.json: {error}").format(error=ex))
            return
        try:
            macro = load_macro(cfg["macro"]) if cfg["macro"] else None
        except (OSError, ValueError):
            macro = None
        if not macro:
            self.notify(_("Nothing to play"))
            return
        # старт — коли відпустять клавіші, інакше затиснуті Ctrl/Alt змішаються з відтворенням
        self.play_request = (cfg, macro)
        self.emit("state", "waiting")

    def begin_play(self):
        (cfg, macro), self.play_request = self.play_request, None
        if cfg["relative"]:
            self.awaiting_origin = (cfg, macro)  # продовження в on_cursor
            self.tracker.start()
        else:
            self.start_player(cfg, macro, (0, 0))

    def start_player(self, cfg, macro, offset):
        loop = "∞" if cfg["loop"] and not cfg["loop_count"] else (cfg["loop_count"] if cfg["loop"] else 1)
        mode = _("from cursor") if cfg["relative"] else _("exact coordinates")
        print(_("Playing “{name}” (repeats: {repeats}, speed ×{speed}, {mode})...").format(
            name=cfg["macro"], repeats=loop, speed=cfg["speed"], mode=mode))
        self.play_cfg = cfg
        self.moved = 0
        self.interrupted = False
        self.player.start(macro, cfg, offset, lambda n: GLib.idle_add(self.on_play_done, n))
        self.emit("state", "playing")
        if self.gui:
            GLib.timeout_add(250, self.report_progress, cfg["loop_count"] if cfg["loop"] else 1)

    def report_progress(self, total):
        """@progress <поточний повтор> <усього повторів, 0 = безкінечно> <частка поточного повтору>"""
        if not self.player.playing():
            return False
        self.emit("progress", f"{self.player.iteration} {total} {self.player.progress:.3f}")
        return True

    def interrupt(self):
        """Безпечна зупинка: користувач сам рухає мишею чи натискає клавіші."""
        if self.player.playing() and self.play_cfg["stop_on_input"] and not self.player.stop_flag.is_set():
            self.interrupted = True
            self.player.stop()

    def on_play_done(self, count):
        self.emit("state", "idle")
        if self.interrupted:
            self.notify(_("Playback interrupted: you moved the mouse or pressed a key"))
        else:
            self.notify(_("Playback finished (times played: {count})").format(count=count))
        return False

    # ---------- інше ----------

    def emit(self, kind, value):
        if self.gui:
            print(f"@{kind} {value}", flush=True)

    def notify(self, text):
        print(text, flush=True)
        if self.notifications:
            subprocess.Popen(["notify-send", "-a", "Input Repeater", *NOTIFY_ICON_ARGS, "-e", "-t", "2000",
                              "Input Repeater", text])

    def shutdown(self):
        if self.recording or self.awaiting_origin:
            self.tracker.stop()
        self.player.close()


def main():
    gui = "--gui" in sys.argv
    if gui:
        # якщо оболонка зникне будь-як (навіть kill -9), ядро надішле скрипту SIGTERM — сиротою він не залишиться
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)  # 1 = PR_SET_PDEATHSIG
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = App(gui=gui)
    loop = GLib.MainLoop()
    unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, loop.quit)
    unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
    try:
        loop.run()
    finally:
        app.shutdown()
        print(_("Exiting."))


if __name__ == "__main__":
    main()

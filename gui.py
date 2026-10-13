#!/usr/bin/env python3
"""Input Repeater — графічна оболонка: запуск/зупинка скрипта, записи, налаштування, трей.

Налаштування запису й відтворення зберігаються одразу й діють з наступного запису/відтворення.
Гарячі клавіші та сповіщення скрипт читає лише при старті, тому поки він працює — вони заблоковані.
Мова інтерфейсу змінюється одразу: вікно перебудовується, скрипт і журнал при цьому не зачіпаються.
"""
import math
import os
import signal
import sys

from PyQt6.QtCore import (QEasingCurve, QFile, QLocale, QPointF, QProcess, QRectF, QStandardPaths, Qt, QTimer,
                          QVariantAnimation)
from PyQt6.QtGui import QColor, QFontDatabase, QIcon, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSizePolicy, QSpacerItem, QLineEdit, QMenu, QMessageBox,
                             QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSystemTrayIcon, QToolButton,
                             QVBoxLayout, QWidget)

import dbus
import dbus.lowlevel

import i18n
import input_repeater as ir
from i18n import _

SCRIPT = ir.__file__
ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input-repeater.svg")

# стан -> (підпис, колір індикатора у вікні)
STATES = {
    "off": ("Off", "#7f8c8d"),
    "starting": ("Starting…", "#7f8c8d"),
    "idle": ("Idle", "#3daee9"),
    "recording": ("Recording", "#da4453"),
    "waiting": ("Release the keys", "#f67400"),
    "playing": ("Playing", "#27ae60"),
}
PULSING = {"recording", "playing"}  # стани з анімацією: пульсує індикатор, оживає іконка в треї

# стан -> (верх і низ градієнта фону іконки, знак у центрі)
STATE_ICONS = {
    "off": ("#a4abb2", "#6f777e", "ring"),
    "starting": ("#a4abb2", "#6f777e", "ring"),
    "idle": ("#4fbcf2", "#1b7fc4", "rec"),
    "recording": ("#f26b78", "#c0392b", "dot"),
    "waiting": ("#f9ad4e", "#d35400", "pause"),
    "playing": ("#52d68a", "#1e8e4e", "play"),
}


def draw_state_icon(state, pulse=1.0, angle=0.0, size=128):
    """Іконка застосунку в заданому стані (та сама форма, що й input-repeater.svg, координати 64×64).

    pulse (0..1) — розмір і яскравість крапки під час запису; angle — поворот стрілки під час відтворення.
    """
    top, bottom, glyph = STATE_ICONS[state]
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    white = QColor("white")

    gradient = QLinearGradient(0, 4, 0, 60)
    gradient.setColorAt(0, QColor(top))
    gradient.setColorAt(1, QColor(bottom))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)

    # стрілка-повтор: дуга на 300° за годинниковою стрілкою від верхньої точки + наконечник
    p.save()
    p.translate(32, 32)
    p.rotate(angle)
    pen = QPen(white, 4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-17, -17, 34, 34), 90 * 16, -300 * 16)
    p.translate(-14.72, -8.5)
    p.rotate(-60)
    pen = QPen(white, 1.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(white)
    p.drawPolygon(QPolygonF([QPointF(-3, -6.5), QPointF(7, 0), QPointF(-3, 6.5)]))
    p.restore()

    center = QPointF(32, 32)
    if glyph == "rec":
        p.setPen(QPen(white, 2))
        p.setBrush(QColor("#ed4c5c"))
        p.drawEllipse(center, 7.5, 7.5)
    elif glyph == "ring":
        p.setPen(QPen(white, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, 6, 6)
    elif glyph == "dot":
        color = QColor(white)
        color.setAlphaF(0.55 + 0.45 * pulse)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        radius = 5.5 + 3 * pulse
        p.drawEllipse(center, radius, radius)
    elif glyph == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(26, 25, 4.5, 14), 1.5, 1.5)
        p.drawRoundedRect(QRectF(33.5, 25, 4.5, 14), 1.5, 1.5)
    elif glyph == "play":
        p.setPen(QPen(white, 1.5))
        p.setBrush(white)
        p.drawPolygon(QPolygonF([QPointF(28.5, 24.5), QPointF(40, 32), QPointF(28.5, 39.5)]))
    p.end()
    return pixmap

QT_MODIFIERS = [(Qt.KeyboardModifier.ControlModifier, "CTRL"), (Qt.KeyboardModifier.AltModifier, "ALT"),
                (Qt.KeyboardModifier.ShiftModifier, "SHIFT"), (Qt.KeyboardModifier.MetaModifier, "META")]
KEY_MODIFIER = {Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier,
                Qt.Key.Key_Alt: Qt.KeyboardModifier.AltModifier,
                Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
                Qt.Key.Key_Meta: Qt.KeyboardModifier.MetaModifier,
                Qt.Key.Key_Super_L: Qt.KeyboardModifier.MetaModifier,
                Qt.Key.Key_Super_R: Qt.KeyboardModifier.MetaModifier}
MODIFIER_KEYS = set(KEY_MODIFIER) | {Qt.Key.Key_AltGr}
NO_MODIFIER = Qt.KeyboardModifier.NoModifier
MOUSE_BUTTONS = {Qt.MouseButton.BackButton: "BTN_SIDE", Qt.MouseButton.ForwardButton: "BTN_EXTRA"}


def hotkey_id(text):
    """Розібрана комбінація для порівняння, або None, якщо текст некоректний."""
    try:
        return ir.parse_hotkey(text)
    except SystemExit:
        return None


def modifier_names(modifiers):
    return [name for flag, name in QT_MODIFIERS if modifiers & flag]


class RenameDialog(QDialog):
    """Перейменування запису: помилка показується одразу під полем, а кнопка неактивна, поки назва неправильна."""

    def __init__(self, parent, name):
        super().__init__(parent)
        self.old = name
        self.setWindowTitle(_("Rename recording"))
        self.setMinimumWidth(420)
        self.edit = QLineEdit(name)
        self.edit.selectAll()
        self.error = QLabel()
        self.error.setStyleSheet("QLabel { color: #da4453; }")
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox()
        self.ok = buttons.addButton(_("Rename"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setIcon(QIcon.fromTheme("edit-rename"))
        buttons.addButton(_("Cancel"), QDialogButtonBox.ButtonRole.RejectRole).setIcon(QIcon.fromTheme("dialog-cancel"))
        buttons.accepted.connect(self.try_rename)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("New name:")))
        layout.addWidget(self.edit)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.edit.textChanged.connect(self.validate)
        self.validate()

    def new_name(self):
        return self.edit.text().strip()

    def problem(self):
        """Чому назва не підходить (текст помилки), або None."""
        new = self.new_name()
        if "/" in new or new.startswith("."):
            return _("The name cannot contain “/” or start with a dot.")
        if new != self.old and os.path.exists(ir.macro_path(new)):
            return _("Recording “{name}” already exists.").format(name=new)
        return None

    def validate(self):
        problem = self.problem()
        self.error.setText(problem or "")
        self.error.setVisible(bool(problem))
        self.ok.setEnabled(not problem and self.new_name() not in ("", self.old))

    def try_rename(self):
        if not self.ok.isEnabled():  # Enter у полі при неправильній назві
            return
        try:
            os.rename(ir.macro_path(self.old), ir.macro_path(self.new_name()))
        except OSError as ex:
            self.error.setText(_("Could not rename: {error}").format(error=ex.strerror or ex))
            self.error.show()
            return
        self.accept()


class SnapSpinBox(QDoubleSpinBox):
    """Колесо й стрілки завжди ведуть на сітку кроку (0.25, 0.5, …), навіть із мінімуму 0.1 чи вписаного 0.4."""

    def stepBy(self, steps):
        step = self.singleStep()
        position = self.value() / step
        # від значення поза сіткою перший крок веде до найближчої точки сітки саме в напрямку прокрутки
        base = math.floor(position + 1e-9) if steps > 0 else math.ceil(position - 1e-9)
        self.setValue(max(self.minimum(), min(self.maximum(), (base + steps) * step)))


class HotkeyEdit(QLineEdit):
    """Поле, яке записує натиснуту клавішу чи комбінацію (назвами evdev, як у config.json)."""

    def __init__(self, text):
        super().__init__(text)
        self.committed = text   # останнє збережене значення
        self.capturing = False  # затиснуті модифікатори, основну клавішу ще не натиснуто

    def keyPressEvent(self, event):
        if event.key() in MODIFIER_KEYS:  # показуємо CTRL+… і чекаємо основну клавішу
            self.preview(event.modifiers() | KEY_MODIFIER.get(event.key(), NO_MODIFIER))
            return
        name = ir.e.KEY.get(event.nativeScanCode() - 8)  # на Linux скан-код = код evdev + 8
        if isinstance(name, (list, tuple)):
            name = name[-1]
        if name:
            self.set_combo(event.modifiers(), name.removeprefix("KEY_"))

    def keyReleaseEvent(self, event):
        if self.capturing and event.key() in MODIFIER_KEYS:
            self.preview(event.modifiers() & ~KEY_MODIFIER.get(event.key(), NO_MODIFIER))

    def mousePressEvent(self, event):
        name = MOUSE_BUTTONS.get(event.button())
        if name:
            self.set_combo(event.modifiers(), name)
        else:
            super().mousePressEvent(event)

    def focusOutEvent(self, event):
        if self.capturing:
            self.preview(NO_MODIFIER)
        super().focusOutEvent(event)

    def preview(self, modifiers):
        """Показує затиснуті модифікатори без збереження; коли їх відпущено — повертає збережене значення."""
        names = modifier_names(modifiers)
        self.capturing = bool(names)
        self.blockSignals(True)
        self.setText("+".join(names) + "+…" if names else self.committed)
        self.blockSignals(False)

    def set_combo(self, modifiers, key):
        self.capturing = False
        self.setText("+".join(modifier_names(modifiers) + [key]))


class Window(QWidget):
    def __init__(self, icon):
        super().__init__()
        self.cfg = ir.load_config()
        if self.cfg["language"] not in dict(i18n.LANGUAGES):  # перший запуск: беремо мову системи
            self.save("language", i18n.system_language())
        i18n.set_language(self.cfg["language"])
        self.icon = icon
        self.state = "off"
        self.quitting = False
        self.tray_hint_shown = False
        self.out_buffer = ""
        self.body = None
        self.pill_color = QColor(STATES["off"][1])
        self.dot_alpha = 1.0
        self.pulse_value = 1.0
        self.arrow_angle = 0.0
        self.progress = None  # (повтор, усього повторів або 0 = ∞, частка поточного повтору) з @progress
        self.launcher_progress = None
        # прогрес на кнопці панелі задач KDE працює лише для встановленої програми (потрібен її ярлик)
        found = QStandardPaths.locate(QStandardPaths.StandardLocation.ApplicationsLocation, "input-repeater.desktop")
        self.launcher_uri = "application://input-repeater.desktop" if found else None
        self.setWindowTitle("Input Repeater")
        self.setWindowIcon(icon)
        self.setMinimumWidth(480)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self.read_output)
        self.proc.stateChanged.connect(self.on_process_state)

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.activated.connect(
            lambda reason: self.toggle_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self.log = QPlainTextEdit()  # живе поза build_ui, щоб журнал переживав зміну мови
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setMinimumHeight(90)

        # плавна зміна кольору індикатора між станами
        self.color_anim = QVariantAnimation(self)
        self.color_anim.setDuration(250)
        self.color_anim.valueChanged.connect(self.on_color)
        # пульсація крапки під час запису й відтворення; під час запису ще й блимає позначка на іконці
        self.pulse = QVariantAnimation(self)
        self.pulse.setStartValue(0.0)
        self.pulse.setKeyValueAt(0.5, 1.0)
        self.pulse.setEndValue(0.0)
        self.pulse.setDuration(1400)
        self.pulse.setLoopCount(-1)
        self.pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.pulse.valueChanged.connect(self.on_pulse)
        # кадри анімованої іконки в треї (~10 за секунду — частіше трей перемальовувати нема сенсу)
        self.icon_timer = QTimer(self)
        self.icon_timer.setInterval(100)
        self.icon_timer.timeout.connect(self.animate_tray)

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.build_ui()

    def build_ui(self):
        """Будує весь інтерфейс поточною мовою (і перебудовує після її зміни)."""
        if self.body:
            self.log.setParent(self)  # рятуємо журнал, решта старого інтерфейсу видаляється
            self.root.removeWidget(self.body)
            self.body.deleteLater()
        self.body = QWidget()
        self.root.addWidget(self.body)
        # формат чисел у полях (1.00 чи 1,00) — за мовою інтерфейсу
        self.setLocale(QLocale(QLocale.Language.Ukrainian if i18n.language() == "uk" else QLocale.Language.English))

        # --- стан, мова, кнопка ---
        self.status = QLabel()
        self.language = QComboBox()
        for code, label in i18n.LANGUAGES:
            self.language.addItem(label, code)
        self.language.setCurrentIndex(self.language.findData(self.cfg["language"]))
        self.language.setToolTip(_("Interface language. Script messages switch after the script restarts."))
        self.language.currentIndexChanged.connect(lambda: self.change_language(self.language.currentData()))
        self.toggle_btn = QPushButton()
        self.toggle_btn.setMinimumHeight(32)
        self.toggle_btn.clicked.connect(self.toggle)
        header = QHBoxLayout()
        header.addWidget(self.status)
        header.addStretch()
        header.addWidget(self.language)
        header.addWidget(self.toggle_btn)

        # --- записи ---
        macros = QGroupBox(_("Recordings"))
        box = QVBoxLayout(macros)
        row = QHBoxLayout()
        self.macro_box = QComboBox()
        self.macro_box.setPlaceholderText(_("No recordings yet"))
        self.macro_box.currentTextChanged.connect(self.on_macro_selected)
        self.rename_btn = self.tool_button("edit-rename", "✎", _("Rename"), self.rename_macro)
        self.delete_btn = self.tool_button("edit-delete", "✕", _("Delete"), self.delete_macro)
        row.addWidget(self.macro_box, 1)
        row.addWidget(self.rename_btn)
        row.addWidget(self.delete_btn)
        box.addLayout(row)
        self.macro_info = QLabel()
        self.macro_info.setEnabled(False)
        box.addWidget(self.macro_info)

        # --- що записувати ---
        record = QGroupBox(_("What to record (from the next recording)"))
        row = QHBoxLayout(record)
        for key, label in (("record_moves", "Mouse movement"), ("record_clicks", "Clicks and wheel"),
                           ("record_keys", "Keyboard")):
            row.addWidget(self.check_box(key, _(label)))

        # --- відтворення ---
        playback = QGroupBox(_("Playback (from the next run)"))
        form = QFormLayout(playback)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.loop = self.check_box("loop", _("Loop"))
        self.loop.toggled.connect(lambda v: self.count.setEnabled(v))
        form.addRow(self.loop)

        self.count = QSpinBox()
        self.count.setRange(0, 1_000_000)
        self.count.setSpecialValueText(_("∞  until stopped"))
        self.count.setValue(self.cfg["loop_count"])
        self.count.setEnabled(self.cfg["loop"])
        self.count.valueChanged.connect(lambda v: self.save("loop_count", v))
        form.addRow(_("Repeats:"), self.count)

        delay = QDoubleSpinBox()
        delay.setRange(0, 3600)
        delay.setSingleStep(0.1)
        delay.setSuffix(_(" s"))
        delay.setValue(self.cfg["loop_delay"])
        delay.valueChanged.connect(lambda v: self.save("loop_delay", v))
        form.addRow(_("Pause between repeats:"), delay)

        speed = SnapSpinBox()
        speed.setRange(0.1, 10)
        speed.setSingleStep(0.25)
        speed.setPrefix("× ")
        speed.setValue(self.cfg["speed"])
        speed.valueChanged.connect(lambda v: self.save("speed", v))
        form.addRow(_("Speed:"), speed)

        mode = QComboBox()
        mode.addItems([_("Exact screen coordinates"), _("From the current cursor position")])
        mode.setCurrentIndex(int(self.cfg["relative"]))
        mode.currentIndexChanged.connect(lambda i: self.save("relative", bool(i)))
        form.addRow(_("Mouse movement:"), mode)
        form.addRow(self.check_box("stop_on_input", _("Stop if I move the mouse or press keys")))

        # --- гарячі клавіші (лише коли скрипт зупинено) ---
        self.hotkeys = QGroupBox(_("Hotkeys"))
        self.hotkey_edits = {}
        form = QFormLayout(self.hotkeys)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(_("Record:"), self.hotkey_edit("record_hotkey"))
        form.addRow(_("Play / stop:"), self.hotkey_edit("play_hotkey"))
        form.addRow(self.check_box("notifications", _("System notifications")))
        self.lock_hint = QLabel(_("🔒 Can be changed only while the script is stopped"))
        self.lock_hint.setEnabled(False)
        form.addRow(self.lock_hint)

        self.log.setPlaceholderText(_("Script messages will appear here"))

        layout = QVBoxLayout(self.body)
        layout.setSpacing(10)
        layout.addLayout(header)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        layout.addWidget(self.progress_bar)
        layout.addWidget(macros)
        layout.addWidget(record)
        layout.addWidget(playback)
        layout.addWidget(self.hotkeys)
        layout.addWidget(self.log, 1)

        # --- меню трею ---
        old_menu = self.tray.contextMenu()
        menu = QMenu(self)
        menu.addAction(_("Show / hide window")).triggered.connect(self.toggle_window)
        self.tray_run = menu.addAction("")
        self.tray_run.triggered.connect(self.toggle)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("application-exit"), _("Quit")).triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        if old_menu:
            old_menu.deleteLater()

        self.refresh_macros()
        self.on_process_state()
        self.set_state(self.state)

    def change_language(self, code):
        self.save("language", code)
        i18n.set_language(code)
        QTimer.singleShot(0, self.build_ui)  # не видаляємо комбобокс посеред його ж сигналу

    # ---------- допоміжні віджети ----------

    def tool_button(self, icon, fallback, tip, slot):
        btn = QToolButton()
        btn.setIcon(QIcon.fromTheme(icon))
        if btn.icon().isNull():
            btn.setText(fallback)
        btn.setToolTip(tip)
        btn.clicked.connect(slot)
        return btn

    def check_box(self, key, label):
        box = QCheckBox(label)
        box.setChecked(self.cfg[key])
        box.toggled.connect(lambda v: self.save(key, v))
        return box

    def hotkey_edit(self, key):
        edit = HotkeyEdit(self.cfg[key])
        self.hotkey_edits[key] = edit
        edit.setPlaceholderText(_("click and press a key or combination"))
        hint = _("Click and press a key, a combination or a side mouse button")
        edit.setToolTip(hint)

        def changed(text):
            if hotkey_id(text) is None:
                edit.setStyleSheet("QLineEdit { border: 1px solid #da4453; }")
                edit.setToolTip(_("Unknown key, not saved"))
                return
            edit.setStyleSheet("")
            edit.setToolTip(hint)
            old = self.cfg[key]
            edit.committed = text.strip()
            self.save(key, edit.committed)
            other = "play_hotkey" if key == "record_hotkey" else "record_hotkey"
            if hotkey_id(text) == hotkey_id(self.cfg[other]):  # однакові — міняємо місцями
                self.hotkey_edits[other].setText(old)

        edit.textChanged.connect(changed)
        return edit

    def save(self, key, value):
        self.cfg = ir.update_config(key, value)

    # ---------- записи ----------

    def refresh_macros(self, select=None):
        names = ir.list_macros()
        current = select or self.cfg["macro"]
        if current not in names:
            current = names[0] if names else ""
        self.macro_box.blockSignals(True)
        self.macro_box.clear()
        self.macro_box.addItems(names)
        self.macro_box.setCurrentIndex(names.index(current) if current else -1)
        self.macro_box.blockSignals(False)
        if current != self.cfg["macro"]:
            self.save("macro", current)
        self.rename_btn.setEnabled(bool(names))
        self.delete_btn.setEnabled(bool(names))
        self.update_macro_info()

    def on_macro_selected(self, name):
        if name:
            self.save("macro", name)
            self.update_macro_info()

    def update_macro_info(self):
        name = self.cfg["macro"]
        if not name:
            self.macro_info.setText(_("New recordings appear here automatically"))
            return
        self.macro_info.setText(self.macro_summary(name))

    def macro_summary(self, name):
        try:
            events = ir.load_macro(name)["events"]
            return _("{count} events · {seconds:.1f} s").format(
                count=len(events), seconds=events[-1][0]) if events else _("empty")
        except (OSError, ValueError, KeyError, IndexError):
            return _("could not read the file")

    def rename_macro(self):
        dialog = RenameDialog(self, self.cfg["macro"])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_macros(select=dialog.new_name())

    def delete_macro(self):
        name = self.cfg["macro"]
        box = QMessageBox(QMessageBox.Icon.Warning, _("Delete recording"), _("Delete “{name}”?").format(name=name),
                          parent=self)
        box.setInformativeText(self.macro_summary(name) + "\n" + _("The recording will be moved to the trash."))
        delete = box.addButton(_("Delete"), QMessageBox.ButtonRole.DestructiveRole)
        delete.setIcon(QIcon.fromTheme("edit-delete"))
        cancel = box.addButton(_("Cancel"), QMessageBox.ButtonRole.RejectRole)
        cancel.setIcon(QIcon.fromTheme("dialog-cancel"))
        grid = box.layout()  # QMessageBox не має setMinimumWidth — розширюємо розпіркою, щоб текст не ламався
        grid.addItem(QSpacerItem(380, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding),
                     grid.rowCount(), 0, 1, grid.columnCount())
        box.setDefaultButton(delete)  # Enter видаляє (запис іде в смітник, його можна відновити), Esc скасовує
        box.exec()
        if box.clickedButton() is not delete:
            return
        moved, _trash_path = QFile.moveToTrash(ir.macro_path(name))
        if not moved:
            QMessageBox.warning(self, _("Delete recording"), _("Could not move the recording to the trash."))
            return
        self.refresh_macros()

    # ---------- скрипт ----------

    def running(self):
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def toggle(self):
        if self.running():
            self.proc.terminate()  # SIGTERM — скрипт коректно прибирає за собою
        else:
            self.out_buffer = ""
            self.proc.start(sys.executable, ["-u", SCRIPT, "--gui"])

    def on_process_state(self):
        running = self.running()
        if not running:
            self.set_state("off")
        elif self.state == "off":
            self.set_state("starting")
        self.toggle_btn.setText(_("  Stop") if running else _("  Start"))
        self.toggle_btn.setIcon(QIcon.fromTheme("media-playback-stop" if running else "media-playback-start"))
        self.tray_run.setText(_("Stop script") if running else _("Start script"))
        self.hotkeys.setEnabled(not running)
        self.lock_hint.setVisible(running)

    def read_output(self):
        self.out_buffer += bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        *lines, self.out_buffer = self.out_buffer.split("\n")
        for line in lines:
            if line.startswith("@state "):
                self.set_state(line[7:].strip())
            elif line.startswith("@progress "):
                current, total, fraction = line.split()[1:]
                self.progress = (int(current), int(total), float(fraction))
                self.show_progress()
            elif line.startswith("@macro "):
                self.cfg = ir.load_config()
                self.refresh_macros(select=line[7:].strip())
            elif line.strip():
                self.log.appendPlainText(line)

    def set_state(self, state):
        self.state = state if state in STATES else "idle"
        text, color = STATES[self.state]
        self.tray.setToolTip(f"Input Repeater — {_(text)}")
        self.color_anim.stop()
        self.color_anim.setStartValue(self.pill_color)
        self.color_anim.setEndValue(QColor(color))
        self.color_anim.start()
        if self.state in PULSING:
            if self.pulse.state() != QVariantAnimation.State.Running:
                self.pulse.start()
                self.icon_timer.start()
        else:
            self.pulse.stop()
            self.icon_timer.stop()
            self.dot_alpha = self.pulse_value = 1.0
            self.arrow_angle = 0.0
        if self.state != "playing":
            self.progress = None
        self.show_progress()
        self.render_pill()
        # іконка вікна змінюється разом зі станом, але не анімується — анімація лише в треї
        self.setWindowIcon(QIcon(draw_state_icon(self.state)))
        self.tray.setIcon(QIcon(draw_state_icon(self.state)))

    def show_progress(self):
        """Прогрес відтворення: смужка у вікні, підказка в треї та смужка на кнопці панелі задач."""
        if self.state != "playing":
            self.progress_bar.hide()
            self.set_launcher_progress(None)
            return
        current, total, fraction = self.progress or (1, 1, 0.0)
        # для скінченного циклу — частка всього відтворення; для безкінечного — поточного повтору
        overall = (current - 1 + fraction) / total if total else fraction
        if total == 1:
            label = "%p%"
        elif total:
            label = _("Repeat {current} of {total}").format(current=current, total=total) + " · %p%"
        else:
            label = _("Repeat {current}").format(current=current) + " · %p%"
        self.progress_bar.setValue(round(overall * 1000))
        self.progress_bar.setFormat(label)
        self.progress_bar.show()
        self.tray.setToolTip(f"Input Repeater — {_('Playing')} · {label.replace('%p', str(round(overall * 100)))}")
        self.set_launcher_progress(overall)

    def set_launcher_progress(self, value):
        """Смужка прогресу на кнопці програми в панелі задач KDE (Unity LauncherEntry)."""
        if not self.launcher_uri or value == self.launcher_progress:
            return
        if value is not None and self.launcher_progress is not None and abs(value - self.launcher_progress) < 0.01:
            return
        self.launcher_progress = value
        props = {"progress-visible": dbus.Boolean(value is not None)}
        if value is not None:
            props["progress"] = dbus.Double(value)
        msg = dbus.lowlevel.SignalMessage("/org/kde/input_repeater", "com.canonical.Unity.LauncherEntry", "Update")
        msg.append(self.launcher_uri, dbus.Dictionary(props, signature="sv"), signature="sa{sv}")
        dbus.SessionBus().send_message(msg)

    def on_color(self, color):
        self.pill_color = color
        self.render_pill()

    def on_pulse(self, value):
        self.pulse_value = value
        self.dot_alpha = 0.3 + 0.7 * value
        self.render_pill()

    def animate_tray(self):
        if self.state == "playing":
            self.arrow_angle = (self.arrow_angle + 18) % 360  # повний оберт за 2 с
        self.tray.setIcon(QIcon(draw_state_icon(self.state, self.pulse_value, self.arrow_angle)))

    def render_pill(self):
        self.status.setText(f'<span style="color: rgba(255, 255, 255, {self.dot_alpha:.2f})">●</span>'
                            f"&nbsp;&nbsp;{_(STATES[self.state][0])}")
        self.status.setStyleSheet(f"QLabel {{ color: white; background: {self.pill_color.name()};"
                                  " font-weight: bold; padding: 5px 14px; border-radius: 12px; }")

    # ---------- вікно й трей ----------

    def toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.bring_to_front()

    def bring_to_front(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def quit(self):
        """Повний вихід (меню трею, Ctrl+C, SIGTERM). Не залежить від того, чи вікно зараз видиме."""
        self.quitting = True
        self.shutdown()
        QApplication.quit()

    def shutdown(self):
        """Зупиняє скрипт і прибирає іконку з трею; безпечно викликати кілька разів."""
        if self.running():
            self.proc.terminate()  # скрипт отримує SIGTERM і сам відпускає клавіші та KWin-скрипт
            if not self.proc.waitForFinished(3000):
                self.proc.kill()
        self.tray.hide()

    def closeEvent(self, event):
        # хрестик ховає вікно в трей; але не під час виходу із сеансу — інакше KDE не зможе завершити сеанс
        if not self.quitting and self.tray.isVisible() and not QApplication.instance().isSavingSession():
            self.hide()
            event.ignore()
            if not self.tray_hint_shown:
                self.tray_hint_shown = True
                self.tray.showMessage("Input Repeater",
                                      _("The app keeps running in the tray. Quit from the icon menu."),
                                      self.icon, 3000)
            return
        event.accept()
        self.quit()


def main():
    # без цього тема KDE підміняє наші QMessageBox власними копіями: без наших налаштувань і без прив'язки до вікна
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app = QApplication(sys.argv)
    app.setApplicationName("Input Repeater")
    app.setQuitOnLastWindowClosed(False)
    if QStandardPaths.locate(QStandardPaths.StandardLocation.ApplicationsLocation, "input-repeater.desktop"):
        app.setDesktopFileName("input-repeater")

    # один екземпляр: повторний запуск лише показує вже відкрите вікно
    socket = QLocalSocket()
    socket.connectToServer(ir.APP)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(ir.APP)
    server = QLocalServer()
    server.listen(ir.APP)

    icon = QIcon.fromTheme(ir.APP, QIcon(ICON_FILE))
    window = Window(icon)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.bring_to_front()))
    app.aboutToQuit.connect(window.shutdown)  # будь-який інший шлях завершення Qt (напр. вихід із сеансу)
    # Ctrl+C у терміналі та SIGTERM: Python обробляє сигнали лише між подіями Qt, тож будимо його таймером
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_args: window.quit())
    wakeup = QTimer()
    wakeup.timeout.connect(lambda: None)
    wakeup.start(250)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

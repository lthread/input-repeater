"""Локалізація: у коді рядки англійською, тут — український переклад.

language: "en" або "uk"; порожнє чи невідоме значення — мова системи (так буває при першому запуску).
"""
import os

LANGUAGES = [("en", "English"), ("uk", "Українська")]

UK = {
    # --- скрипт ---
    "Unknown key in config.json: {name}": "Невідома клавіша в config.json: {name}",
    "Unknown modifier in config.json: {mod} (available: CTRL, ALT, SHIFT, META)":
        "Невідомий модифікатор у config.json: {mod} (є: CTRL, ALT, SHIFT, META)",
    "KWin failed to load the cursor tracking script": "KWin не зміг завантажити скрипт відстеження курсора",
    "No access to any keyboard or mouse. Add yourself to the input group (see README.md).":
        "Немає доступу до жодної клавіатури чи миші. Додайте себе до групи input (див. README.md).",
    "Ready. {rec}: start/stop recording, {play}: play/stop.":
        "Готово. {rec} — почати/зупинити запис, {play} — відтворити/зупинити.",
    "Active recording: {name}": "Активний запис: {name}",
    "No recordings yet": "Записів ще немає",
    "Warning: no access to {count} input devices (the keyboard may not be recorded). "
    "Add yourself to the input group, see README.md.":
        "Увага: немає доступу до {count} пристроїв введення (клавіатура може не записуватись). "
        "Додайте себе до групи input — див. README.md.",
    "Stop playback first.": "Спершу зупиніть відтворення.",
    "Stop recording first.": "Спершу зупиніть запис.",
    "Error in config.json: {error}": "Помилка в config.json: {error}",
    "Recording started": "Запис почато",
    "Recording is empty, nothing saved": "Запис порожній — нічого не збережено",
    "Recording": "Запис",
    "Saved “{name}”: {count} events, {seconds:.1f} s": "Збережено «{name}»: {count} подій, {seconds:.1f} с",
    "Nothing to play": "Немає запису для відтворення",
    "Playing “{name}” (repeats: {repeats}, speed ×{speed}, {mode})...":
        "Відтворення «{name}» (повторів: {repeats}, швидкість ×{speed}, {mode})...",
    "from cursor": "від курсора",
    "exact coordinates": "точні координати",
    "Playback interrupted: you moved the mouse or pressed a key":
        "Відтворення перервано: ви рухнули мишею чи натиснули клавішу",
    "Playback finished (times played: {count})": "Відтворення завершено (виконано разів: {count})",
    "Exiting.": "Вихід.",

    # --- оболонка: стани ---
    "Off": "Вимкнено",
    "Starting…": "Запуск…",
    "Idle": "Очікування",
    "Release the keys": "Відпустіть клавіші",
    "Playing": "Відтворення",

    # --- оболонка: вікно ---
    "  Start": "  Запустити",
    "  Stop": "  Зупинити",
    "Interface language. Script messages switch after the script restarts.":
        "Мова інтерфейсу. Повідомлення скрипта зміняться після його перезапуску.",
    "Recordings": "Записи",
    "Rename": "Перейменувати",
    "Delete": "Видалити",
    "New recordings appear here automatically": "Новий запис з'явиться тут автоматично",
    "{count} events · {seconds:.1f} s": "{count} подій · {seconds:.1f} с",
    "empty": "порожній",
    "could not read the file": "не вдалося прочитати файл",
    "What to record (from the next recording)": "Що записувати — з наступного запису",
    "Mouse movement": "Рух миші",
    "Clicks and wheel": "Кліки та колесо",
    "Keyboard": "Клавіатура",
    "Playback (from the next run)": "Відтворення — з наступного запуску",
    "Loop": "Зациклити",
    "∞  until stopped": "∞  до зупинки",
    "Repeats:": "Кількість повторів:",
    " s": " с",
    "Pause between repeats:": "Пауза між повторами:",
    "Speed:": "Швидкість:",
    "Exact screen coordinates": "Точні координати екрана",
    "From the current cursor position": "Від поточного положення курсора",
    "Mouse movement:": "Рух миші:",
    "Stop if I move the mouse or press keys": "Зупиняти, якщо я рухаю мишею чи натискаю клавіші",
    "Hotkeys": "Гарячі клавіші",
    "Record:": "Запис:",
    "Play / stop:": "Відтворення / стоп:",
    "System notifications": "Системні сповіщення",
    "🔒 Can be changed only while the script is stopped": "🔒 Змінюються, лише коли скрипт зупинено",
    "click and press a key or combination": "клацніть і натисніть клавішу чи комбінацію",
    "Click and press a key, a combination or a side mouse button":
        "Клацніть і натисніть клавішу, комбінацію або бічну кнопку миші",
    "Unknown key, not saved": "Невідома клавіша — не збережено",
    "Script messages will appear here": "Тут з'являтимуться повідомлення скрипта",
    "Repeat {current} of {total}": "Повтор {current} з {total}",
    "Repeat {current}": "Повтор {current}",

    # --- оболонка: діалоги й трей ---
    "Rename recording": "Перейменувати запис",
    "New name:": "Нова назва:",
    "The name cannot contain “/” or start with a dot.": "Назва не може містити «/» чи починатися з крапки.",
    "Recording “{name}” already exists.": "Запис «{name}» уже існує.",
    "Delete recording": "Видалити запис",
    "Delete “{name}”?": "Видалити «{name}»?",
    "The recording will be moved to the trash.": "Запис буде переміщено до смітника.",
    "Could not move the recording to the trash.": "Не вдалося перемістити запис до смітника.",
    "Could not rename: {error}": "Не вдалося перейменувати: {error}",
    "Cancel": "Скасувати",
    "Show / hide window": "Показати / сховати вікно",
    "Start script": "Запустити скрипт",
    "Stop script": "Зупинити скрипт",
    "Quit": "Вийти",
    "The app keeps running in the tray. Quit from the icon menu.":
        "Програма працює в треї. Вийти можна з меню іконки.",
}

_lang = "en"


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "uk" if value.startswith("uk") else "en"
    return "en"


def set_language(code):
    global _lang
    _lang = code if code in dict(LANGUAGES) else system_language()


def language():
    return _lang


def _(text):
    return UK.get(text, text) if _lang == "uk" else text

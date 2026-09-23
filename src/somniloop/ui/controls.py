from __future__ import annotations

import calendar
import html
import math
import random
import re

from PySide6.QtCore import QDate, QElapsedTimer, QLocale, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.dates import MONTHS, parse_birth_date
from somniloop.core.i18n import I18n


class _RoundedWindow:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        from .action_feedback import install_action_feedback

        install_action_feedback()
        self.setObjectName("roundedWindow")
        # Let the compositor own the outer frame and input region. Painting fake
        # transparent corners inside native decorations leaves a rectangular seam.


class RoundedDialog(QDialog):
    """Embed modal forms in their host; standalone/modeless forms stay native."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .action_feedback import install_action_feedback

        install_action_feedback()

    def exec(self):
        if self.parentWidget() and self.parentWidget().window().isVisible():
            from .modal_overlay import exec_embedded

            return exec_embedded(self)
        return super().exec()

    def done(self, result):
        super().done(result)
        overlay = getattr(self, "_modal_overlay", None)
        if overlay:
            overlay.release()


class RoundedMainWindow(_RoundedWindow, QMainWindow):
    pass


class SaveCelebration(QWidget):
    def __init__(self, parent: QWidget, text: str) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(310, 160)
        self.move(max(0, (parent.width() - self.width()) // 2), max(12, parent.height() // 3 - 70))
        self.text = text
        rng = random.Random()
        self.particles = [
            (
                rng.uniform(0, math.tau),
                rng.uniform(35, 125),
                rng.choice(("#8267e8", "#53bd96", "#ebb953", "#5d9bec")),
            )
            for _ in range(24)
        ]
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(25)
        self.show()
        self.raise_()

    def _tick(self) -> None:
        if self.elapsed.elapsed() >= 900:
            self.timer.stop()
            self.deleteLater()
        else:
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        progress = self.elapsed.elapsed() / 900
        painter.setOpacity(min(1.0, (1 - progress) * 3))
        for angle, speed, color in self.particles:
            x = 155 + math.cos(angle) * speed * progress
            y = 70 + math.sin(angle) * speed * progress + 30 * progress**2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QRectF(x, y, 5, 5))
        painter.setBrush(QColor("#2d2646"))
        painter.drawRoundedRect(QRectF(55, 55, 200, 45), 16, 16)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(55, 55, 200, 45), Qt.AlignmentFlag.AlignCenter, "✓  " + self.text)


def show_saved(widget: QWidget, text: str = "Сохранено") -> None:
    target = widget.window()
    previous = getattr(target, "_save_celebration", None)
    if previous is not None:
        try:
            previous.hide()
            previous.deleteLater()
        except RuntimeError:
            pass
    target._save_celebration = SaveCelebration(target, text)


def polish_dialog_buttons(buttons: QDialogButtonBox) -> None:
    """Give standard actions a stable hierarchy in every dialog."""
    from .action_feedback import install_action_feedback

    feedback = install_action_feedback()
    for button in buttons.buttons():
        feedback.watch(button)
    for role in (
        QDialogButtonBox.StandardButton.Save,
        QDialogButtonBox.StandardButton.Ok,
    ):
        button = buttons.button(role)
        if button is not None:
            button.setObjectName("primary")
            button.setMinimumSize(112, 38)
    for role in (
        QDialogButtonBox.StandardButton.Cancel,
        QDialogButtonBox.StandardButton.Close,
    ):
        button = buttons.button(role)
        if button is not None:
            button.setObjectName("secondary")
            button.setMinimumSize(104, 38)


class ScrollDateEdit(QWidget):
    dateChanged = Signal(QDate)

    def __init__(self, day: QDate | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("datePicker")
        self._updating = False
        self._include_year = True
        self._date = day if isinstance(day, QDate) and day.isValid() else QDate.currentDate()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setWrapping(True)
        self.day_spin.setMinimumWidth(64)
        self.month_combo = QComboBox()
        language = QApplication.instance().property("language") or "ru"
        i18n = I18n(language)
        locale = QLocale("ru_RU" if language == "ru" else "en_GB")
        self.month_combo.addItems(
            MONTHS
            if language == "ru"
            else [locale.monthName(month, QLocale.FormatType.ShortFormat) for month in range(1, 13)]
        )
        self.month_combo.setMinimumWidth(86)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(1800, 2300)
        self.year_spin.setMinimumWidth(90)
        for spin in (self.day_spin, self.year_spin):
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.lineEdit().setReadOnly(True)
            spin.setKeyboardTracking(False)
            spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.day_spin.setAccessibleName("Day")
        self.month_combo.setAccessibleName("Month")
        self.year_spin.setAccessibleName("Year")
        self.calendar_button = QPushButton(i18n.t("choose_date"))
        self.calendar_button.setToolTip(i18n.t("calendar"))
        self.calendar_button.setMinimumWidth(112)
        self.calendar_button.clicked.connect(self._open_calendar)
        for widget in (self.day_spin, self.month_combo, self.year_spin, self.calendar_button):
            row.addWidget(widget)
        self.day_spin.valueChanged.connect(self._changed)
        self.month_combo.currentIndexChanged.connect(self._changed)
        self.year_spin.valueChanged.connect(self._changed)
        self.setDate(self._date)

    def date(self) -> QDate:
        return self._date

    def setDate(self, day: QDate) -> None:
        if not day.isValid():
            return
        if not self._include_year:
            day = QDate(2000, day.month(), day.day())
        changed = day != self._date
        self._updating = True
        self._date = day
        self.year_spin.setValue(day.year())
        self.month_combo.setCurrentIndex(day.month() - 1)
        self.day_spin.setMaximum(calendar.monthrange(day.year(), day.month())[1])
        self.day_spin.setValue(day.day())
        self._updating = False
        if changed:
            self.dateChanged.emit(day)

    def _changed(self) -> None:
        if self._updating:
            return
        year, month = self.year_spin.value(), self.month_combo.currentIndex() + 1
        day = min(self.day_spin.value(), calendar.monthrange(year, month)[1])
        self.setDate(QDate(year, month, day))

    def setCalendarPopup(self, enabled: bool) -> None:
        self.calendar_button.setVisible(enabled)

    def setDisplayFormat(self, pattern: str) -> None:
        self._include_year = "yyyy" in pattern.lower()
        self.year_spin.setVisible(self._include_year)
        self.setDate(self._date)

    def _open_calendar(self) -> None:
        from .calendar_widgets import RoundCalendar

        dialog = RoundedDialog(self)
        i18n = I18n(QApplication.instance().property("language") or "ru")
        dialog.setWindowTitle(i18n.t("calendar"))
        layout = QVBoxLayout(dialog)
        calendar_widget = RoundCalendar(self._date)
        calendar_widget.clicked.connect(lambda day: (self.setDate(day), dialog.accept()))
        layout.addWidget(calendar_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()


class MonthSpinBox(QSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setRange(1, 12)
        self.setWrapping(True)
        self.lineEdit().setReadOnly(True)

    def textFromValue(self, value: int) -> str:
        return MONTHS[max(1, min(12, value)) - 1]


class BirthdayEdit(QWidget):
    changed = Signal()

    def __init__(self, value: str = "", parent=None) -> None:
        super().__init__(parent)
        row = QGridLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(12)
        row.setVerticalSpacing(6)
        self.known = QCheckBox("Дата известна")
        self.year_known = QCheckBox("Год известен")
        self.picker = ScrollDateEdit(QDate(2000, 1, 1))
        self.picker.setMinimumWidth(290)
        self.picker.setCalendarPopup(True)
        row.addWidget(self.known, 0, 0)
        row.addWidget(self.year_known, 0, 1)
        row.addWidget(self.picker, 1, 0, 1, 2)
        self.known.toggled.connect(self._update)
        self.year_known.toggled.connect(self._update)
        self.picker.dateChanged.connect(self.changed)
        self.set_value(value)

    def _update(self) -> None:
        self.picker.setEnabled(self.known.isChecked())
        self.year_known.setEnabled(self.known.isChecked())
        self.picker.year_spin.setVisible(self.year_known.isChecked())
        if not self.year_known.isChecked():
            day = self.picker.date()
            self.picker.setDate(QDate(2000, day.month(), day.day()))
        self.changed.emit()

    def set_value(self, value: str) -> None:
        parsed = parse_birth_date(value)
        self.known.setChecked(parsed is not None)
        self.year_known.setChecked(parsed is not None and parsed[0] is not None)
        if parsed:
            self.picker.setDate(QDate(parsed[0] or 2000, parsed[1], parsed[2]))
        self._update()

    def value(self) -> str:
        if not self.known.isChecked():
            return ""
        day = self.picker.date()
        return (
            day.toString("yyyy-MM-dd") if self.year_known.isChecked() else day.toString("--MM-dd")
        )


def open_web_url(url: str, parent=None) -> bool:
    parsed = QUrl(url)
    if not parsed.isValid() or parsed.scheme().lower() not in {"http", "https"}:
        return False
    started = QDesktopServices.openUrl(parsed)
    if not started:
        QMessageBox.warning(parent, "Ссылка", "Не удалось открыть ссылку в браузере по умолчанию.")
    return started


# Kept as a compatibility alias for extensions built against SomniLoop 0.3.
open_in_firefox = open_web_url


def linked_text(text: str) -> str:
    pieces = []
    position = 0
    for match in re.finditer(r"https?://[^\s<>]+", text):
        url = match.group().rstrip(".,;!)]}")
        pieces.append(html.escape(text[position : match.start()]))
        pieces.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>')
        position = match.start() + len(url)
    pieces.append(html.escape(text[position:]))
    return "".join(pieces).replace("\n", "<br>")


def link_label(text: str, parent=None) -> QLabel:
    label = QLabel(linked_text(text), parent)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setOpenExternalLinks(False)
    label.linkActivated.connect(lambda url: open_web_url(url, label))
    return label


def rich_details(text: str) -> str:
    paragraphs = []
    for line in text.splitlines():
        safe = html.escape(line)
        if line.startswith("⚠"):
            safe = f'<span style="color:#d14f69; text-decoration:underline;">{safe}</span>'
        elif ":" in line and not line.startswith("•"):
            title, rest = safe.split(":", 1)
            safe = f"<b>{title}:</b>{rest}"
        paragraphs.append(f'<p style="margin:0 0 8px 0">{safe or "&nbsp;"}</p>')
    return "".join(paragraphs)

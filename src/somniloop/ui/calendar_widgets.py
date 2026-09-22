from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, QLocale, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.dates import MONTHS
from somniloop.core.models import DayStatus

STATUS_COLORS = {
    DayStatus.DONE: "#349d78",
    DayStatus.PARTIAL: "#c89c36",
    DayStatus.MISSED: "#c3536f",
}


class DayButton(QPushButton):
    def __init__(self, day: date, displayed_month: int, parent=None) -> None:
        super().__init__(str(day.day), parent)
        self.day = day
        self.in_month = day.month == displayed_month
        self.selected = False
        self.status: DayStatus | None = None
        self.setMinimumSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(day.isoformat())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 7
        circle = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        color = STATUS_COLORS.get(self.status)
        if color or self.selected or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color or ("#806def" if self.selected else "#806def33")))
            painter.drawEllipse(circle)
        if self.day == date.today():
            painter.setPen(QPen(QColor("#9f8aff"), 2.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle.adjusted(-2, -2, 2, 2))
        foreground = QColor("#ffffff") if color or self.selected else self.palette().text().color()
        if not self.in_month and not self.selected and not color:
            foreground.setAlphaF(0.38)
        painter.setPen(foreground)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.day.day))
        if self.hasFocus():
            painter.setPen(QPen(QColor("#806def"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle.adjusted(3, 3, -3, -3))


class RoundCalendar(QWidget):
    clicked = Signal(QDate)
    currentPageChanged = Signal(int, int)

    def __init__(self, selected: QDate | None = None, parent=None) -> None:
        super().__init__(parent)
        self.selected = selected or QDate.currentDate()
        self.year = self.selected.year()
        self.month = self.selected.month()
        self.statuses = {}
        self.buttons: list[DayButton] = []
        self.setMinimumSize(410, 370)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        navigation = QHBoxLayout()
        previous = QPushButton("‹")
        previous.clicked.connect(lambda: self._move_month(-1))
        following = QPushButton("›")
        following.clicked.connect(lambda: self._move_month(1))
        self.month_label = QLabel()
        self.month_label.setObjectName("sectionTitle")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        navigation.addWidget(previous)
        navigation.addWidget(self.month_label, 1)
        navigation.addWidget(following)
        root.addLayout(navigation)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(5)
        root.addLayout(self.grid, 1)
        self._render()

    def yearShown(self) -> int:
        return self.year

    def monthShown(self) -> int:
        return self.month

    def _move_month(self, offset: int) -> None:
        target = QDate(self.year, self.month, 1).addMonths(offset)
        self.year, self.month = target.year(), target.month()
        self._render()
        self.currentPageChanged.emit(self.year, self.month)

    def set_statuses(self, statuses: dict) -> None:
        self.statuses = statuses
        for button in self.buttons:
            button.status = statuses.get(button.day)
            button.update()

    def _render(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.buttons = []
        month = (
            QLocale("en_GB").monthName(self.month, QLocale.FormatType.ShortFormat)
            if QApplication.instance().property("language") == "en"
            else MONTHS[self.month - 1]
        )
        self.month_label.setText(f"{month} {self.year}")
        weekdays = (
            ("№", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
            if QApplication.instance().property("language") == "en"
            else ("№", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
        )
        for column, name in enumerate(weekdays):
            label = QLabel(name)
            label.setObjectName("muted")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, 0, column)
        first = date(self.year, self.month, 1)
        cursor = first - timedelta(days=first.weekday())
        for row in range(1, 7):
            number = QLabel(str(cursor.isocalendar().week))
            number.setObjectName("weekNumber")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setFixedWidth(32)
            self.grid.addWidget(number, row, 0)
            for column in range(1, 8):
                button = DayButton(cursor, self.month)
                button.selected = cursor == self.selected.toPython()
                button.status = self.statuses.get(cursor)
                button.clicked.connect(lambda checked=False, day=cursor: self._select(day))
                self.grid.addWidget(button, row, column)
                self.buttons.append(button)
                cursor += timedelta(days=1)

    def _select(self, day: date) -> None:
        self.selected = QDate(day.year, day.month, day.day)
        for button in self.buttons:
            button.selected = button.day == day
            button.update()
        self.clicked.emit(self.selected)

    def wheelEvent(self, event) -> None:
        self._move_month(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()

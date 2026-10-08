"""Compact date property popup shared by task rows and the task editor."""

from PySide6.QtCore import QDate, QLocale, QPoint, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
)


class TaskDatePopup(QFrame):
    chosen = Signal(str, object)

    def __init__(self, anchor, language, day="", clock="", *, preserve_time=False):
        super().__init__(anchor, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("taskDatePopup")
        self.anchor = anchor
        self.language = language
        self.day = day
        self.preserve_time = preserve_time
        self.time_touched = False
        self.locale = QLocale("ru_RU" if language == "ru" else "en_GB")
        self.month = (QDate.fromString(day, "yyyy-MM-dd") if day else QDate.currentDate())
        self.month = QDate(self.month.year(), self.month.month(), 1)
        dark = anchor.palette().window().color().lightness() < 128
        # Inherit the application's explicit theme even inside a colored task row.
        from PySide6.QtWidgets import QApplication
        theme = QApplication.instance().property("somniloopTheme")
        if theme:
            dark = theme == "dark"
        bg, fg, border, hover = (("#202936", "#e5edf9", "#46566c", "#34445c") if dark
                                else ("#ffffff", "#243247", "#d3dce8", "#eaf0fa"))
        self.setStyleSheet(f"""
            QFrame#taskDatePopup {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}
            QFrame#taskDatePopup QLabel, QFrame#taskDatePopup QCheckBox {{ background: transparent; color: {fg}; }}
            QFrame#taskDatePopup QPushButton {{ background: transparent; color: {fg}; border: none; border-radius: 6px; padding: 4px; }}
            QFrame#taskDatePopup QPushButton:hover {{ background: {hover}; }}
            QFrame#taskDatePopup QPushButton:focus {{ border: 1px solid #7866df; }}
            QFrame#taskDatePopup QPushButton:checked {{ background: #6754ce; color: white; }}
            QFrame#taskDatePopup QPushButton[adjacent="true"] {{ color: #8996a8; }}
            QFrame#taskDatePopup QLineEdit, QFrame#taskDatePopup QTimeEdit {{ background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 6px; padding: 5px; }}
            QFrame#taskDatePopup QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border}; border-radius: 4px; background: {bg}; }}
            QFrame#taskDatePopup QCheckBox::indicator:checked {{ background: #6754ce; border-color: #6754ce; }}
        """)
        self.setFixedWidth(320)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(self.tr("ДД.ММ.ГГГГ", "DD.MM.YYYY"))
        self.input.setAccessibleName(self.tr("Дата", "Date"))
        self.input.setText(QDate.fromString(day, "yyyy-MM-dd").toString("dd.MM.yyyy") if day else "")
        self.input.returnPressed.connect(self.commit_input)
        self.input.editingFinished.connect(self.commit_changed_input)
        root.addWidget(self.input)
        self.error = QLabel(self.tr("Введите дату: ДД.ММ.ГГГГ", "Enter a date: DD.MM.YYYY"))
        self.error.hide()
        root.addWidget(self.error)
        navigation = QHBoxLayout()
        self.month_label = QLabel()
        navigation.addWidget(self.month_label, 1)
        for label, offset in (("‹", -1), ("›", 1)):
            button = QPushButton(label)
            button.setFixedSize(30, 28)
            button.setAccessibleName(self.tr("Предыдущий месяц", "Previous month") if offset < 0 else self.tr("Следующий месяц", "Next month"))
            button.clicked.connect(lambda _, step=offset: self.move_month(step))
            navigation.addWidget(button)
        root.addLayout(navigation)
        grid = QGridLayout()
        grid.setSpacing(2)
        self.days = []
        for column in range(7):
            label = QLabel(self.locale.dayName(column + 1, QLocale.FormatType.ShortFormat))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(label, 0, column)
        for index in range(42):
            button = QPushButton()
            button.setFixedHeight(30)
            button.setCheckable(True)
            button.clicked.connect(lambda _, slot=index: self.select_day(self.days[slot].property("date")))
            self.days.append(button)
            grid.addWidget(button, index // 7 + 1, index % 7)
        root.addLayout(grid)
        quick = QHBoxLayout()
        for ru, en, offset in (("Сегодня", "Today", 0), ("Завтра", "Tomorrow", 1)):
            button = QPushButton(self.tr(ru, en))
            button.clicked.connect(lambda _, step=offset: self.select_day(QDate.currentDate().addDays(step)))
            quick.addWidget(button)
        root.addLayout(quick)
        time_row = QHBoxLayout()
        self.include_time = QCheckBox(self.tr("Указать время", "Include time"))
        self.include_time.setChecked(bool(clock))
        self.clock = QTimeEdit(QTime.fromString(clock, "HH:mm") if clock else QTime(9, 0))
        self.clock.setDisplayFormat("HH:mm")
        self.clock.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.clock.setFixedWidth(80)
        self.clock.setVisible(bool(clock))
        self.include_time.toggled.connect(self.toggle_time)
        self.clock.editingFinished.connect(self.commit_time)
        time_row.addWidget(self.include_time, 1)
        time_row.addWidget(self.clock)
        root.addLayout(time_row)
        self.clear_button = QPushButton(self.tr("Очистить дату", "Clear date"))
        self.clear_button.clicked.connect(self.clear_date)
        root.addWidget(self.clear_button)
        self.render_month()

    def tr(self, ru, en):
        return ru if self.language == "ru" else en

    def render_month(self):
        self.month_label.setText(f"{self.locale.standaloneMonthName(self.month.month()).capitalize()} {self.month.year()}")
        start = self.month.addDays(1 - self.month.dayOfWeek())
        for index, button in enumerate(self.days):
            day = start.addDays(index)
            button.setProperty("date", day)
            button.setProperty("adjacent", day.month() != self.month.month())
            button.setText(str(day.day()))
            button.setAccessibleName(day.toString("yyyy-MM-dd"))
            button.setChecked(day.toString("yyyy-MM-dd") == self.day)
            button.style().unpolish(button)
            button.style().polish(button)
        self.adjustSize()

    def move_month(self, offset):
        self.month = self.month.addMonths(offset)
        self.render_month()

    def select_day(self, day):
        self.day = day.toString("yyyy-MM-dd")
        self.month = QDate(day.year(), day.month(), 1)
        self.input.setText(day.toString("dd.MM.yyyy"))
        self.error.hide()
        self.render_month()
        self.publish()

    def commit_input(self):
        for format in ("dd.MM.yyyy", "yyyy-MM-dd", "dd/MM/yyyy"):
            day = QDate.fromString(self.input.text().strip(), format)
            if day.isValid():
                self.select_day(day)
                return
        self.error.show()
        self.adjustSize()

    def commit_changed_input(self):
        existing = QDate.fromString(self.day, "yyyy-MM-dd").toString("dd.MM.yyyy") if self.day else ""
        if self.input.text().strip() and self.input.text().strip() != existing:
            self.commit_input()

    def publish(self):
        clock = self.clock.time().toString("HH:mm") if self.include_time.isChecked() else ""
        if self.preserve_time and not self.time_touched:
            clock = None
        self.chosen.emit(self.day, clock)

    def toggle_time(self, enabled):
        self.time_touched = True
        self.clock.setVisible(enabled)
        if not self.day:
            self.select_day(QDate.currentDate())
        else:
            self.publish()
        self.adjustSize()

    def commit_time(self):
        if self.day and self.include_time.isChecked():
            self.time_touched = True
            self.publish()

    def clear_date(self):
        self.day = ""
        self.chosen.emit("", "")
        self.close()

    def show_at_anchor(self):
        self.adjustSize()
        point = self.anchor.mapToGlobal(QPoint(0, self.anchor.height() + 4))
        screen = self.anchor.screen().availableGeometry()
        point.setX(max(screen.left(), min(point.x(), screen.right() - self.width() + 1)))
        if point.y() + self.height() > screen.bottom():
            point.setY(self.anchor.mapToGlobal(QPoint()).y() - self.height() - 4)
        point.setY(max(screen.top(), min(point.y(), screen.bottom() - self.height() + 1)))
        self.move(point)
        # Bind native popups to the real host, including embedded modal forms.
        self.winId()
        host = self.anchor.window().windowHandle()
        if host is not None:
            self.windowHandle().setTransientParent(host)
        self.show()
        self.input.setFocus()


class TaskDateField(QPushButton):
    def __init__(self, language, day="", clock="", parent=None):
        super().__init__(parent)
        self.language = language
        self.setObjectName("taskDateField")
        self.set_value(day, clock)
        self.clicked.connect(self.open_picker)

    def set_value(self, day, clock):
        self.day, self.clock = day, clock or ""
        label = QDate.fromString(day, "yyyy-MM-dd").toString("dd.MM.yyyy") if day else ("Без срока" if self.language == "ru" else "No date")
        self.setText(label + (" · " + self.clock if self.clock else ""))

    def open_picker(self):
        self.popup = TaskDatePopup(self, self.language, self.day, self.clock)
        self.popup.chosen.connect(self.set_value)
        self.popup.show_at_anchor()

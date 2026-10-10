"""A viewport-painted, due-date timeline with no per-day widgets or render loop."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from math import ceil

from PySide6.QtCore import QDate, QLocale, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.dates import birthday_in_year
from somniloop.knowledge.people import has_birth_conflict

from .controls import RoundedDialog
from .planner import PlannerDialog


class TimelineTaskDelegate(QStyledItemDelegate):
    """Keep project surfaces visible even under global item-selection styles."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        painter.setBrush(index.data(Qt.ItemDataRole.BackgroundRole))
        active = option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        painter.setPen(QPen(option.palette.highlight().color(), 2) if active else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 9, 9)
        painter.setFont(option.font)
        painter.setPen(index.data(Qt.ItemDataRole.ForegroundRole).color())
        painter.drawText(
            rect.adjusted(12, 9, -12, -9),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            index.data(Qt.ItemDataRole.DisplayRole),
        )
        painter.restore()

    def sizeHint(self, option, index):
        width = max(100, self.parent().viewport().width() - 32)
        bounds = option.fontMetrics.boundingRect(
            QRect(0, 0, width, 10000),
            Qt.TextFlag.TextWordWrap,
            index.data(Qt.ItemDataRole.DisplayRole),
        )
        return QSize(width + 32, bounds.height() + 26)


@dataclass(frozen=True)
class TimelineTask:
    identifier: int
    title: str
    due: date | None
    time: str
    done: bool
    project: str
    color: str
    project_id: int | None = None

    def overdue(self, now):
        if self.done or self.due is None:
            return False
        if self.time:
            return datetime.fromisoformat(f"{self.due}T{self.time}") < now
        return self.due < now.date()


def timeline_tasks(repository):
    """Include completion history, but not unfinished tasks explicitly archived."""
    rows = repository.connection.execute(
        "SELECT p.id,p.title,p.due_date,p.due_time,p.completed,"
        "j.name AS project,j.color,j.id AS project_id FROM planner_tasks p "
        "LEFT JOIN work_items w ON w.kind='planner' AND w.item_id=p.id "
        "LEFT JOIN work_projects j ON j.id=w.project_id "
        "WHERE p.archived=0 OR p.completed=1 ORDER BY p.id"
    )
    return tuple(
        TimelineTask(
            row["id"],
            row["title"],
            date.fromisoformat(row["due_date"]) if row["due_date"] else None,
            row["due_time"] or "",
            bool(row["completed"]),
            row["project"] or "",
            row["color"] or "#8493a8",
            row["project_id"],
        )
        for row in rows
    )


class TimelineCanvas(QWidget):
    day_clicked = Signal(object)
    scroll_requested = Signal(int)
    geometry_changed = Signal()
    GAP = 14

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.locale = QLocale("ru_RU" if language == "ru" else "en_GB")
        self.language = language
        self.tasks = {}
        self.people = ()
        self._birthday_years = {}
        self.start = date.today().replace(day=1)
        self.end = self.start
        self.offset = 0
        self.show_completed = True
        self.selected = None
        self.hovered = None
        self.maximum = 1
        self.setMinimumWidth(180)
        self.setFixedHeight(320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(self.tr_text("Задачи по дням", "Tasks by day"))

    def tr_text(self, ru, en):
        return ru if self.language == "ru" else en

    @property
    def cell(self):
        return max(7.0, min(28.0, (self.width() - self.GAP) / 31))

    def day_x(self, day):
        months = (day.year - self.start.year) * 12 + day.month - self.start.month
        return (day - self.start).days * self.cell + months * self.GAP

    def day_at(self, x):
        target = x + self.offset
        low, high = self.start.toordinal(), self.end.toordinal()
        while low < high:
            mid = (low + high + 1) // 2
            if self.day_x(date.fromordinal(mid)) <= target:
                low = mid
            else:
                high = mid - 1
        day = date.fromordinal(low)
        return day if 0 <= target - self.day_x(day) < self.cell else None

    def visible_days(self):
        # At most one extra month is needed to skip a separator at the left edge.
        first = self.day_at(0) or self.day_at(self.GAP + self.cell) or self.start
        day = max(self.start, first - timedelta(days=1))
        while day <= self.end and self.day_x(day) - self.offset < self.width():
            yield day
            day += timedelta(days=1)

    def entries(self, day):
        return [t for t in self.tasks.get(day, ()) if self.show_completed or not t.done]

    def birthday_names(self, day):
        if day.year not in self._birthday_years:
            grouped = defaultdict(list)
            for person in self.people:
                birthday = birthday_in_year(person.birth_date, day.year)
                if birthday:
                    grouped[birthday].append(person.name)
            self._birthday_years[day.year] = dict(grouped)
        return self._birthday_years[day.year].get(day, [])

    def crown_rect(self, day):
        x = self.day_x(day) - self.offset
        width = min(14, self.cell - 2)
        return QRectF(x + (self.cell - width) / 2, self.height() - 17, width, 12)

    def birthday_tooltip(self, day):
        return (
            "<b>"
            + self.tr_text("Дни рождения", "Birthdays")
            + "</b><br>"
            + "<br>".join(escape(name) for name in self.birthday_names(day))
        )

    @property
    def tick_step(self):
        return max(1, ceil(self.maximum / 5))

    @property
    def scale_maximum(self):
        return ceil(self.maximum / self.tick_step) * self.tick_step

    @property
    def plot_height(self):
        return self.height() - 110

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = self.palette().windowText().color()
        faint = QColor(ink)
        faint.setAlpha(13)
        now = datetime.now()
        days = list(self.visible_days())
        bottom = self.height() - 58
        unit = self.plot_height / self.scale_maximum
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QPen(faint, 1))
        for value in range(0, self.scale_maximum + 1, self.tick_step):
            y = round(bottom - value * unit)
            painter.drawLine(0, y, self.width(), y)
        previous_month = None
        for day in days:
            x = self.day_x(day) - self.offset
            if x + self.cell <= 0:
                continue
            area = QRectF(x, 23, self.cell, self.height() - 23)
            if day.weekday() >= 5:
                painter.fillRect(QRectF(x, bottom + 2, self.cell, 22), faint)
            if day == self.hovered:
                painter.fillRect(area, faint)
            if day == now.date():
                painter.fillRect(QRectF(x, bottom + 2, self.cell, 22), QColor("#3778bd"))
            if day == self.selected:
                painter.setPen(QPen(QColor("#3778bd"), 1))
                painter.drawRoundedRect(area.adjusted(1, 0, -1, -1), 3, 3)
            month = (day.year, day.month)
            if month != previous_month:
                painter.setPen(ink)
                label = f"{self.locale.standaloneMonthName(day.month)} {day.year}"
                next_month = QDate(day.year, day.month, 1).addMonths(1).toPython()
                label_x = max(2, x)
                label_width = self.day_x(next_month) - self.offset - self.GAP - label_x
                painter.save()
                painter.setClipRect(QRectF(label_x, 0, max(0, label_width), 22))
                painter.drawText(QRectF(label_x, 0, 190, 21), Qt.AlignmentFlag.AlignLeft, label)
                painter.restore()
                previous_month = month
            if day.day == 1:
                painter.setPen(QPen(faint, 1))
                painter.drawLine(int(x - self.GAP / 2), 2, int(x - self.GAP / 2), self.height())
            groups = defaultdict(int)
            for task in self.entries(day):
                groups[(task.done, task.project, task.color, task.overdue(now))] += 1
            y = float(bottom)
            for (done, _project, color, overdue), count in sorted(groups.items()):
                height = count * unit
                rect = QRectF(x + 0.5, y - height, self.cell - 1, height)
                fill = QColor("#ff303e" if overdue else color)
                if not fill.isValid():
                    fill = QColor("#8493a8")
                painter.fillRect(rect, fill)
                if done:
                    painter.fillRect(rect, QBrush(ink, Qt.BrushStyle.BDiagPattern))
                y -= height
            painter.setPen(ink)
            total = len(self.entries(day))
            if total and self.cell >= painter.fontMetrics().horizontalAdvance(str(total)) + 3:
                painter.drawText(
                    QRectF(x, y - 20, self.cell, 18), Qt.AlignmentFlag.AlignCenter, str(total)
                )
            if day == now.date():
                painter.setPen(QColor("#ffffff"))
            if self.cell >= 15 or day.day % 5 == 0 or day == now.date():
                painter.drawText(
                    QRectF(x, bottom + 3, self.cell, 20), Qt.AlignmentFlag.AlignCenter, str(day.day)
                )
            painter.setPen(ink)
            weekday = self.locale.dayName(day.isoweekday(), QLocale.FormatType.ShortFormat)
            painter.drawText(
                QRectF(x, bottom + 21, self.cell, 18), Qt.AlignmentFlag.AlignCenter, weekday
            )
            if self.birthday_names(day):
                rect = self.crown_rect(day)
                painter.save()
                painter.translate(rect.topLeft())
                painter.scale(rect.width() / 14, rect.height() / 12)
                painter.setPen(QPen(QColor("#9b680b"), 1))
                painter.setBrush(QColor("#edbd4b"))
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(1, 2),
                            QPointF(4, 5),
                            QPointF(7, 1),
                            QPointF(10, 5),
                            QPointF(13, 2),
                            QPointF(11, 10),
                            QPointF(3, 10),
                        ]
                    )
                )
                painter.restore()
        painter.end()

    def mouseMoveEvent(self, event):
        day = self.day_at(event.position().x())
        if day != self.hovered:
            self.hovered = day
            self.update()
        if day is None:
            QToolTip.hideText()
            return
        if self.birthday_names(day) and self.crown_rect(day).adjusted(-2, -2, 2, 2).contains(
            event.position()
        ):
            QToolTip.showText(event.globalPosition().toPoint(), self.birthday_tooltip(day), self)
            return
        entries = self.tasks.get(day, ())
        done = sum(t.done for t in entries)
        title = self.locale.toString(QDate(day.year, day.month, day.day), "d MMMM yyyy")
        lines = [
            f"<b>{title}</b>",
            self.tr_text(
                f"Осталось: {len(entries) - done} · Выполнено: {done}",
                f"Remaining: {len(entries) - done} · Done: {done}",
            ),
        ]
        for task in entries[:12]:
            project = escape(task.project or self.tr_text("Без проекта", "No project"))
            color = QColor(task.color).name()
            lines.append(
                f'<span style="color:{color}">●</span> {project}: '
                f"{'✓ ' if task.done else ''}{escape(task.title)}"
            )
        if len(entries) > 12:
            lines.append(f"+ {len(entries) - 12}")
        QToolTip.showText(event.globalPosition().toPoint(), "<br>".join(lines), self)

    def leaveEvent(self, event):
        self.hovered = None
        QToolTip.hideText()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            day = self.day_at(event.position().x())
            if day:
                if self.birthday_names(day) and self.crown_rect(day).adjusted(
                    -2, -2, 2, 2
                ).contains(event.position()):
                    QToolTip.showText(
                        event.globalPosition().toPoint(), self.birthday_tooltip(day), self
                    )
                    return
                self.selected = day
                self.update()
                self.day_clicked.emit(day)

    def wheelEvent(self, event):
        delta = event.pixelDelta().x() or event.pixelDelta().y()
        if not delta:
            delta = (event.angleDelta().x() or event.angleDelta().y()) / 120 * self.cell * 3
        self.scroll_requested.emit(-round(delta))
        event.accept()

    def resizeEvent(self, event):
        self.geometry_changed.emit()
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 1 if event.key() == Qt.Key.Key_Right else -1
            current = self.selected or self.day_at(self.width() / 2) or date.today()
            self.selected = min(self.end, max(self.start, current + timedelta(days=step)))
            x = self.day_x(self.selected) - self.offset
            if x < 0 or x + self.cell > self.width():
                self.scroll_requested.emit(round(x - self.width() / 2))
            self.update()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.day_clicked.emit(self.selected or self.day_at(self.width() / 2) or date.today())
        else:
            super().keyPressEvent(event)


class TimelineAxis(QWidget):
    """A fixed count axis independent of horizontal date scrolling."""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.setFixedSize(36, canvas.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        for value in range(0, self.canvas.scale_maximum + 1, self.canvas.tick_step):
            y = (
                self.canvas.height()
                - 58
                - value * self.canvas.plot_height / self.canvas.scale_maximum
            )
            painter.drawText(
                QRectF(0, y - 9, self.width() - 8, 18), Qt.AlignmentFlag.AlignRight, str(value)
            )
        painter.end()


class TaskTimeline(QWidget):
    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.tasks = ()
        self._generation = None
        self._initialized = False
        self._left_day = date.today()
        self.captures = []
        self._sidebar_signature = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        self.completed = QPushButton(workspace.tr("✓ Выполненные", "✓ Completed"))
        self.completed.setCheckable(True)
        self.completed.setChecked(True)
        self.completed.toggled.connect(self.toggle_completed)
        controls.addWidget(self.completed)
        controls.addStretch()
        self.undated = QPushButton()
        self.undated.clicked.connect(lambda: self.open_details(None))
        controls.addWidget(self.undated)
        self.today = QPushButton(workspace.tr("Сегодня", "Today"))
        self.today.clicked.connect(self.go_today)
        controls.addWidget(self.today)
        layout.addLayout(controls)
        self.canvas = TimelineCanvas(workspace.i18n.language)
        self.canvas.day_clicked.connect(self.open_details)
        plot = QHBoxLayout()
        plot.setContentsMargins(0, 0, 0, 0)
        plot.setSpacing(0)
        self.axis = TimelineAxis(self.canvas)
        plot.addWidget(self.axis)
        plot.addWidget(self.canvas, 1)
        layout.addLayout(plot)
        self.scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.scroll.setObjectName("timelineScroll")
        self.scroll.setStyleSheet("""
            QScrollBar:horizontal { background: rgba(120, 135, 155, 30); height: 10px;
                border: none; border-radius: 5px; margin: 0; }
            QScrollBar::handle:horizontal { background: #8399b7;
                min-width: 32px; border-radius: 5px; }
            QScrollBar::handle:horizontal:hover { background: #3778bd; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0; height: 0; border: none; background: transparent; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent; }
        """)
        self.scroll.setAccessibleName(workspace.tr("Прокрутка месяцев", "Scroll months"))
        self.scroll.valueChanged.connect(self.scrolled)
        self.canvas.scroll_requested.connect(
            lambda delta: self.scroll.setValue(self.scroll.value() + delta)
        )
        self.canvas.geometry_changed.connect(self.update_range)
        layout.addWidget(self.scroll)
        self.legend = QLabel(
            workspace.tr(
                "Красный — просрочено · Штриховка — выполнено",
                "Red — overdue · Hatching — completed",
            )
        )
        self.legend.setObjectName("muted")
        layout.addWidget(self.legend)
        layout.addSpacing(16)
        self.project_range = QLabel()
        self.project_range.setObjectName("muted")
        self.project_range.setWordWrap(True)
        self.summary_columns = QHBoxLayout()
        self.summary_columns.setSpacing(24)
        self.table_panel = QWidget()
        self.table_panel.setObjectName("timelineTablePanel")
        self.table_panel.setStyleSheet("QWidget#timelineTablePanel { background: transparent; }")
        table_panel_layout = QVBoxLayout(self.table_panel)
        table_panel_layout.setContentsMargins(0, 0, 0, 0)
        table_panel_layout.addWidget(self.project_range)
        self.project_table = QWidget()
        self.project_table.setObjectName("timelineProjectTable")
        self.project_table.setStyleSheet(
            "QWidget#timelineProjectTable { background: transparent; border: none; }"
        )
        self.table_layout = QGridLayout(self.project_table)
        self.table_layout.setContentsMargins(0, 0, 0, 0)
        self.table_layout.setSpacing(0)
        self.table_layout.setColumnStretch(0, 1)
        self.table_layout.setColumnMinimumWidth(1, 100)
        self._table_signature = None
        self.project_rows = []
        table_panel_layout.addWidget(self.project_table)
        table_panel_layout.addStretch()
        self.sidebar = QWidget()
        self.sidebar.setObjectName("timelineSidebar")
        self.sidebar.setStyleSheet("QWidget#timelineSidebar { background: transparent; }")
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_layout.setSpacing(10)
        self.summary_columns.addWidget(self.table_panel, 5)
        self.summary_columns.addWidget(self.sidebar, 2)
        layout.addLayout(self.summary_columns)

    def refresh(self):
        repo = self.workspace.repository
        key = (repo.connection.total_changes, date.today())
        if key != self._generation:
            self._generation = key
            self.tasks = timeline_tasks(repo)
            self.captures = repo.work_inbox()
            self.canvas.people = tuple(
                person
                for person in repo.list_people()
                if not has_birth_conflict({"conflicts": person.conflicts})
            )
            self.canvas._birthday_years.clear()
            grouped = defaultdict(list)
            for task in self.tasks:
                if task.due:
                    grouped[task.due].append(task)
            self.canvas.tasks = dict(grouped)
            current = QDate.currentDate()
            start = min([current.addMonths(-12).toPython(), *grouped]).replace(day=1)
            end = max([current.addMonths(24).toPython(), *grouped])
            self.canvas.start = start
            self.canvas.end = QDate(end.year, end.month, 1).addMonths(1).addDays(-1).toPython()
            self.update_range()
            if not self._initialized:
                self.go_default()
                self._initialized = True
            count = sum(t.due is None and not t.done for t in self.tasks)
            self.undated.setText(self.workspace.tr("Без срока", "No date") + f" · {count}")
            self.update_scale()
        self.canvas.update()
        self.update_project_table()
        self.update_sidebar()

    def update_range(self):
        anchor = self._left_day
        self.scroll.blockSignals(True)
        self.scroll.setRange(
            0,
            max(
                0,
                round(self.canvas.day_x(self.canvas.end) + self.canvas.cell - self.canvas.width()),
            ),
        )
        self.scroll.setPageStep(self.canvas.width())
        self.scroll.setSingleStep(round(self.canvas.cell))
        self.scroll.setValue(round(self.canvas.day_x(anchor)))
        self.scroll.blockSignals(False)
        self.scrolled(self.scroll.value())

    def go_today(self):
        self.scroll.setValue(ceil(self.canvas.day_x(date.today())))

    def go_default(self):
        now = datetime.now()
        day = min((task.due for task in self.tasks if task.overdue(now)), default=now.date())
        self.scroll.setValue(ceil(self.canvas.day_x(day)))

    def scrolled(self, value):
        self.canvas.offset = value
        self._left_day = (
            self.canvas.day_at(1)
            or self.canvas.day_at(self.canvas.GAP + self.canvas.cell)
            or self.canvas.start
        )
        self.canvas.update()
        self.update_project_table()
        self.update_sidebar()

    def update_project_table(self):
        if not hasattr(self, "project_table"):
            return
        days = [
            day
            for day in self.canvas.visible_days()
            if self.canvas.day_x(day) - self.canvas.offset + self.canvas.cell > 0
        ]
        if not days:
            return
        grouped = {}
        for day in days:
            for task in self.canvas.tasks.get(day, ()):
                if task.done:
                    continue
                key = task.project_id
                if key not in grouped:
                    grouped[key] = [
                        task.project or self.workspace.tr("Без проекта", "No project"),
                        task.color,
                        0,
                    ]
                grouped[key][2] += 1
        keys = sorted(grouped, key=lambda key: (-grouped[key][2], grouped[key][0].casefold()))
        rows = [grouped[key] for key in keys]
        signature = (days[0], days[-1], tuple(tuple(row) for row in rows))
        if signature == self._table_signature:
            return
        self._table_signature = signature
        self.project_rows = rows

        def format_day(day):
            return self.canvas.locale.toString(QDate(day.year, day.month, day.day), "d MMM yyyy")

        self.project_range.setText(f"{format_day(days[0])} — {format_day(days[-1])}")
        while self.table_layout.count():
            widget = self.table_layout.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        header = [
            self.workspace.tr("Проект", "Project"),
            self.workspace.tr("Осталось", "Remaining"),
        ]
        values = [header, *[[name, str(count)] for name, _color, count in rows]]
        if not rows:
            values.append([self.workspace.tr("Нет задач", "No tasks"), "0"])
        for row, cells in enumerate(values):
            for column, value in enumerate(cells):
                label = QLabel()
                label.setWordWrap(True)
                if row and rows and column == 0:
                    color = QColor(rows[row - 1][1]).name()
                    label.setText(f'<span style="color:{color}">●</span>  {escape(value)}')
                else:
                    label.setTextFormat(Qt.TextFormat.PlainText)
                    label.setText(value)
                if column:
                    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    label.setWordWrap(False)
                border = "rgba(128, 144, 164, 65)"
                css = "background: transparent; border: none; padding: 10px 12px;"
                if row < len(values) - 1:
                    css += f"border-bottom: 1px solid {border};"
                if column < len(cells) - 1:
                    css += f"border-right: 1px solid {border};"
                if row == 0:
                    css += "font-weight: 600;"
                label.setStyleSheet(css)
                self.table_layout.addWidget(label, row, column)

    def update_sidebar(self):
        if not hasattr(self, "sidebar"):
            return
        now = datetime.now()
        overdue = sorted(
            (task for task in self.tasks if task.overdue(now)),
            key=lambda task: (task.due, task.time, task.identifier),
        )
        birthdays = tuple(
            (day, name)
            for day in self.canvas.visible_days()
            if self.canvas.day_x(day) - self.canvas.offset + self.canvas.cell > 0
            for name in self.canvas.birthday_names(day)
        )
        signature = (tuple(overdue), tuple((c["id"], c["title"]) for c in self.captures), birthdays)
        if signature == self._sidebar_signature:
            return
        self._sidebar_signature = signature
        self.overdue_ids = [task.identifier for task in overdue]
        self.visible_birthdays = birthdays
        while self.sidebar_layout.count():
            item = self.sidebar_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        def heading(title, count):
            label = QLabel(f"{title} · {count}")
            label.setStyleSheet("font-weight: 600; background: transparent;")
            self.sidebar_layout.addWidget(label)

        def link(title, subtitle, color, action):
            label = QLabel()
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            ink = self.palette().windowText().color().name()
            label.setText(
                f'<span style="color:{color}">●</span> '
                f'<a href="open" style="color:{ink}; text-decoration:none">{escape(title)}</a>'
                + (f"<br><small>{escape(subtitle)}</small>" if subtitle else "")
            )
            label.linkActivated.connect(lambda _url: action())
            self.sidebar_layout.addWidget(label)

        heading(self.workspace.tr("Просрочено", "Overdue"), len(overdue))
        if not overdue:
            self.sidebar_layout.addWidget(
                QLabel(self.workspace.tr("Нет просроченных дел", "No overdue tasks"))
            )
        for task in overdue:
            day = self.canvas.locale.toString(
                QDate(task.due.year, task.due.month, task.due.day), "d MMM yyyy"
            )
            link(
                task.title,
                f"{day} {task.time}",
                "#ff303e",
                lambda identifier=task.identifier: self.edit_task(identifier, self),
            )
        self.sidebar_layout.addSpacing(12)
        heading(self.workspace.tr("На разбор", "To sort"), len(self.captures))
        if not self.captures:
            self.sidebar_layout.addWidget(
                QLabel(self.workspace.tr("Всё разобрано", "Nothing to sort"))
            )
        for capture in self.captures:
            link(
                capture["title"],
                "",
                "#c29234",
                lambda value=capture: self.workspace.schedule_capture(value),
            )
        self.sidebar_layout.addSpacing(12)
        heading(self.workspace.tr("Дни рождения", "Birthdays"), len(birthdays))
        if not birthdays:
            self.sidebar_layout.addWidget(
                QLabel(self.workspace.tr("Нет в показанном периоде", "None in the visible period"))
            )
        for day, name in birthdays:
            formatted = self.canvas.locale.toString(
                QDate(day.year, day.month, day.day), "d MMM yyyy"
            )
            label = QLabel(f"{name}\n{formatted}")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            self.sidebar_layout.addWidget(label)
        self.sidebar_layout.addStretch()

    def edit_task(self, identifier, parent):
        repo = self.workspace.repository
        task = next(
            (
                t
                for t in repo.list_planner_tasks() + repo.list_planner_tasks(True)
                if t.id == identifier
            ),
            None,
        )
        if task and PlannerDialog(repo, self.workspace.i18n, task, parent).exec():
            self.workspace.changed.emit()
            self.refresh()
            return True
        return False

    def toggle_completed(self, checked):
        self.canvas.show_completed = checked
        self.update_scale()
        self.canvas.update()

    def update_scale(self):
        self.canvas.maximum = (
            max((len(self.canvas.entries(day)) for day in self.canvas.tasks), default=1) or 1
        )
        self.axis.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.go_default()

    def open_details(self, day):
        dialog = RoundedDialog(self)
        title = (
            self.canvas.locale.toString(QDate(day.year, day.month, day.day), "d MMMM yyyy")
            if day
            else self.workspace.tr("Без срока", "No date")
        )
        dialog.setWindowTitle(title)
        dialog.resize(620, 420)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        listing.setItemDelegate(TimelineTaskDelegate(listing))
        listing.setWordWrap(True)
        listing.setMouseTracking(True)
        listing.setSpacing(3)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(listing)
        tasks = [
            t for t in self.tasks if t.due == day and (self.completed.isChecked() or not t.done)
        ]
        if not tasks:
            layout.addWidget(QLabel(self.workspace.tr("Нет задач", "No tasks")))
        dark = self.workspace.repository.get_setting("theme", "light") == "dark"
        base = QColor("#1d2938" if dark else "#ffffff")
        amount = 0.48 if dark else 0.42
        for task in sorted(tasks, key=lambda t: (t.done, t.time or "24:00", t.title)):
            project = task.project or self.workspace.tr("Без проекта", "No project")
            item = QListWidgetItem(
                f"{'✓ ' if task.done else ''}{task.title}\n{project}  {task.time}"
            )
            item.setData(Qt.ItemDataRole.UserRole, task.identifier)
            color = QColor(task.color)
            if not color.isValid():
                color = QColor("#8493a8")
            surface = QColor(
                *(
                    round(base.getRgb()[i] * (1 - amount) + color.getRgb()[i] * amount)
                    for i in range(3)
                )
            )
            channels = [v / 255 for v in surface.getRgb()[:3]]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
            luminance = sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
            item.setForeground(QColor("#111827" if luminance > 0.24 else "#ffffff"))
            item.setBackground(surface)
            listing.addItem(item)

        def edit(item):
            identifier = item.data(Qt.ItemDataRole.UserRole)
            if self.edit_task(identifier, dialog):
                dialog.accept()

        listing.itemClicked.connect(edit)
        listing.itemActivated.connect(edit)
        dialog.exec()
        dialog.deleteLater()

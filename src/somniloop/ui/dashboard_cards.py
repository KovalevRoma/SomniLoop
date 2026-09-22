"""Compact reusable cards and accessible quick marks without destructive row actions."""

from __future__ import annotations

import re
from datetime import date

from PySide6.QtCore import QLocale, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.models import ScheduleType, TaskState, TrackerMode

from .dashboard_data import local_date, tracker_snapshot


class WrapLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        # Allow long URLs/identifiers to wrap without changing the stored title.
        super().setText(
            re.sub(
                r"\S{30,}",
                lambda match: "\u200b".join(
                    match[0][i : i + 24] for i in range(0, len(match[0]), 24)
                ),
                text,
            )
        )


class VisibleCheckBox(QCheckBox):
    """Keep the unchecked outline legible in both themes without losing checkbox semantics."""

    def sizeHint(self):
        return QSize(28 + self.fontMetrics().horizontalAdvance(self.text()), 32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        light = QApplication.instance().property("somniloopTheme") == "light"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - 18) / 2
        painter.setPen(QPen(QColor("#707990" if light else "#9da5bf"), 1.2))
        painter.setBrush(
            QColor("#7561cc" if self.isChecked() else "#ffffff" if light else "#242a3b")
        )
        painter.drawRoundedRect(QRectF(2, y, 18, 18), 4, 4)
        if self.isChecked():
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawPolyline(
                QPolygonF([QPointF(6, y + 9), QPointF(10, y + 13), QPointF(17, y + 5)])
            )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#9d8ade"), 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(QRectF(0, y - 2, 23, 23), 5, 5)
        painter.setFont(self.font())
        painter.setPen(QColor("#283647" if light else "#e8edf5"))
        painter.drawText(
            self.rect().adjusted(28, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text()
        )


def icon_button(text, tooltip, callback=None):
    button = QPushButton(text)
    button.setFixedSize(32, 32)
    button.setStyleSheet("padding: 0; border-radius: 8px;")
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    if callback:
        button.clicked.connect(callback)
    return button


class QuickTaskRow(QWidget):
    state_changed = Signal(object)

    def __init__(self, text, state, i18n, parent=None):
        super().__init__(parent)
        self.setObjectName("flat")
        self.i18n = i18n
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(8)
        self.done = QPushButton()
        self.done.setObjectName("completionToggle")
        self.done.setCheckable(True)
        self.done.setFixedHeight(32)
        self.done.setMinimumWidth(96)
        self.done.setAccessibleName(i18n.t("done") + ": " + text)
        self.done.setToolTip(i18n.t("done"))
        self.label = WrapLabel(text)
        row.addWidget(self.label, 1)
        row.addWidget(self.done)
        self.partial = icon_button("◐", i18n.t("home_partial_hint"))
        for button in (self.partial,):
            button.setCheckable(True)
            row.addWidget(button)
        self.partial.hide()
        self.done.toggled.connect(
            lambda value: self.state_changed.emit(TaskState.DONE if value else TaskState.NOT_DONE)
        )
        self.partial.clicked.connect(
            lambda value: self.state_changed.emit(TaskState.PARTIAL if value else TaskState.UNSET)
        )
        self.set_state(state)

    def set_state(self, state):
        self.state = state
        for button, value in (
            (self.done, TaskState.DONE),
            (self.partial, TaskState.PARTIAL),
        ):
            button.blockSignals(True)
            button.setChecked(state == value)
            button.blockSignals(False)
        self.done.setText(
            "✓ " + self.i18n.t("done") if state == TaskState.DONE
            else self.i18n.t("home_mark_done")
        )
        self.done.setAccessibleName(self.done.text() + ": " + self.label.text())
        self.done.setToolTip(self.i18n.t("home_undo_done" if state == TaskState.DONE else "home_mark_done"))
        self.label.setToolTip(
            self.i18n.t(
                {
                    TaskState.UNSET: "unset",
                    TaskState.DONE: "done",
                    TaskState.PARTIAL: "partial",
                    TaskState.NOT_DONE: "not_done",
                }[state]
            )
        )


class TaskRows(QWidget):
    changed = Signal(int, object)

    def __init__(self, i18n, parent=None):
        super().__init__(parent)
        self.setObjectName("flat")
        self.i18n = i18n
        self.rows = {}
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)

    def update_rows(self, items, hide_done=False, allow_partial=False):
        wanted = {identifier for identifier, _, _ in items}
        for key in list(self.rows):
            if key not in wanted:
                row = self.rows.pop(key)
                self.box.removeWidget(row)
                row.hide()
                row.deleteLater()
        for position, (identifier, text, state) in enumerate(items):
            row = self.rows.get(identifier)
            if row is None:
                row = QuickTaskRow(text, state, self.i18n, self)
                row.state_changed.connect(
                    lambda value, key=identifier: self.changed.emit(key, value)
                )
                self.rows[identifier] = row
            row.label.setText(text)
            row.set_state(state)
            # Only a whole task without checklist items supports a manual partial mark.
            row.partial.setVisible(allow_partial)
            row.setVisible(not hide_done or state != TaskState.DONE)
            if self.box.indexOf(row) != position:
                self.box.insertWidget(position, row)


class TrackerCard(QFrame):
    open_requested = Signal(int)
    edit_requested = Signal(int)
    calendar_requested = Signal(int)
    tracker_changed = Signal(int)
    data_changed = Signal()

    def __init__(self, repository, tracker, i18n, parent=None, snapshot=None):
        super().__init__(parent)
        self.repository, self.i18n, self.tracker = repository, i18n, tracker
        self.snapshot = None
        self.compact = False
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = WrapLabel()
        self.title.setObjectName("cardTitle")
        top.addWidget(self.title, 1)
        self.attention = QLabel("!")
        self.attention.setObjectName("homePriority")
        self.attention.setToolTip(i18n.t("home_attention"))
        top.addWidget(self.attention)
        self.streak = QLabel()
        self.streak.setObjectName("muted")
        top.addWidget(self.streak)
        menu = QMenu(self)
        menu.addAction(i18n.t("edit"), lambda: self.edit_requested.emit(self.tracker.id))
        menu.addAction(i18n.t("archive_action"), self._archive)
        more = icon_button("⋯", i18n.t("home_actions"))
        more.setMenu(menu)
        top.addWidget(more)
        root.addLayout(top)
        info = QHBoxLayout()
        self.schedule = WrapLabel()
        self.schedule.setObjectName("muted")
        info.addWidget(self.schedule, 1)
        self.expand = icon_button("⌄", i18n.t("home_details"))
        self.expand.setCheckable(True)
        self.expand.toggled.connect(self._expand)
        info.addWidget(self.expand)
        info.addWidget(
            icon_button(
                "▦", i18n.t("calendar"), lambda: self.calendar_requested.emit(self.tracker.id)
            )
        )
        info.addWidget(
            icon_button("↗", i18n.t("open"), lambda: self.open_requested.emit(self.tracker.id))
        )
        root.addLayout(info)
        self.rows = TaskRows(i18n)
        self.rows.changed.connect(self._mark)
        root.addWidget(self.rows)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        root.addWidget(self.progress)
        self.description = WrapLabel()
        self.description.setObjectName("muted")
        self.description.hide()
        root.addWidget(self.description)
        self.update_snapshot(snapshot or tracker_snapshot(repository, tracker, date.today()))

    def _expand(self, expanded):
        self.description.setVisible(expanded)
        self.rows.setVisible(not self.compact or expanded)
        self.progress.setVisible(
            (not self.compact or expanded)
            and (bool(self.snapshot.tasks) or self.snapshot.meta.quota_target is not None)
        )
        self.expand.setText("⌃" if expanded else "⌄")

    def set_compact(self, compact):
        self.compact = compact
        self.rows.setVisible(not compact or self.expand.isChecked())
        self.progress.setVisible(
            (not compact or self.expand.isChecked())
            and (bool(self.snapshot.tasks) or self.snapshot.meta.quota_target is not None)
        )

    def _archive(self):
        self.repository.archive_tracker(self.tracker.id)
        self.tracker_changed.emit(self.tracker.id)
        self.data_changed.emit()

    def _mark(self, task_id, state):
        self.repository.set_task_state(self.tracker.id, task_id, date.today(), state)
        self.update_snapshot(tracker_snapshot(self.repository, self.tracker, date.today()))
        self.tracker_changed.emit(self.tracker.id)
        self.data_changed.emit()

    def update_snapshot(self, snapshot, hide_done=False):
        if self.snapshot == snapshot and getattr(self, "_hide_done", None) == hide_done:
            return
        self.snapshot, self.tracker, self._hide_done = snapshot, snapshot.tracker, hide_done
        tracker, meta = snapshot.tracker, snapshot.meta
        accent = "#7f6ac6" if tracker.mode == TrackerMode.REGULAR else "#538ebd"
        overdue = (
            tracker.mode == TrackerMode.MANUAL
            and snapshot.next_date
            and snapshot.next_date < date.today()
        )
        if overdue:
            accent = "#bd7981"
        self.setStyleSheet(f"QFrame#card {{ border-left: 3px solid {accent}; }}")
        self.title.setText(tracker.name)
        self.attention.setVisible(meta.needs_attention)
        self.streak.setText(f"↗ {meta.streak}")
        self.streak.setToolTip(
            self.i18n.t("streak", value=f"{meta.streak} {self.i18n.t(meta.streak_unit)}")
        )
        schedule = self._schedule_text(tracker, meta, self.i18n)
        if snapshot.next_date and tracker.mode == TrackerMode.MANUAL:
            stamp = local_date(snapshot.next_date, self.i18n)
            schedule += " · " + (self.i18n.t("home_overdue", date=stamp) if overdue else stamp)
        self.schedule.setText(schedule)
        self.description.setText(tracker.description or self.i18n.t("home_details"))
        self.rows.update_rows(
            [(item.task.id, item.task.name, item.state) for item in snapshot.tasks], hide_done
        )
        self.progress.setVisible(bool(snapshot.tasks) or meta.quota_target is not None)
        self.progress.setText(
            self.i18n.t("quota", done=meta.quota_done, target=meta.quota_target)
            if meta.quota_target is not None
            else self.i18n.t(
                "home_progress",
                done=sum(item.state == TaskState.DONE for item in snapshot.tasks),
                total=len(snapshot.tasks),
            )
        )

    @staticmethod
    def _schedule_text(tracker, meta, i18n):
        if tracker.mode == TrackerMode.MANUAL:
            return i18n.t("home_date_plans")
        kind, payload = tracker.schedule_type, tracker.schedule
        if kind == ScheduleType.INTERVAL:
            return i18n.t("interval", days=payload.get("days", 1))
        if kind == ScheduleType.WEEKLY_QUOTA:
            return i18n.t("weekly_quota", count=payload.get("count", 1))
        if kind == ScheduleType.MONTHLY:
            return i18n.t("monthly", day=payload.get("day", 1))
        if kind == ScheduleType.YEARLY:
            month = QLocale("ru_RU" if i18n.language == "ru" else "en_GB").monthName(
                int(payload.get("month", 1)), QLocale.FormatType.ShortFormat
            )
            return i18n.t("yearly", day=payload.get("day", 1), month=month)
        return i18n.t(kind.value)


class PlannerCard(QFrame):
    changed = Signal()
    edit_requested = Signal(object)

    def __init__(self, repository, task, i18n, parent=None):
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.task = None
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        self.title = WrapLabel()
        self.title.setObjectName("cardTitle")
        top.addWidget(self.title, 1)
        more = icon_button("⋯", i18n.t("home_actions"))
        menu = QMenu(self)
        menu.addAction(i18n.t("edit"), lambda: self.edit_requested.emit(self.task))
        menu.addAction(i18n.t("archive_action"), self._archive)
        more.setMenu(menu)
        top.addWidget(more)
        root.addLayout(top)
        self.subtitle = WrapLabel()
        self.subtitle.setObjectName("muted")
        root.addWidget(self.subtitle)
        self.rows = TaskRows(i18n)
        self.rows.changed.connect(self._mark)
        root.addWidget(self.rows)
        self.expand = QPushButton(i18n.t("home_details"))
        self.expand.setCheckable(True)
        self.expand.setStyleSheet(
            "text-align:left; padding:4px; border:none; background:transparent;"
        )
        self.description = WrapLabel()
        self.description.setObjectName("muted")
        self.expand.toggled.connect(self.description.setVisible)
        root.addWidget(self.expand)
        root.addWidget(self.description)
        self.description.hide()
        self.update_task(task)

    def update_task(self, task, hide_done=False):
        if self.task == task and getattr(self, "_hide_done", None) == hide_done:
            return
        self.task, self._hide_done = task, hide_done
        overdue = date.fromisoformat(task.due_date) < date.today() and not task.completed
        self.setStyleSheet(
            f"QFrame#card {{ border-left:3px solid {'#bc767c' if overdue else '#569c83'}; }}"
        )
        self.title.setText(task.title)
        stamp = local_date(task.due_date, self.i18n)
        items = [
            (
                item["id"],
                item["title"],
                TaskState.DONE if item["done"] else TaskState(item.get("state", "unset")),
            )
            for item in task.items
        ]
        if not items:
            items = [(0, self.i18n.t("mark_habit"), task.state)]
        progress = self.i18n.t(
            "home_progress",
            done=sum(state == TaskState.DONE for _, _, state in items),
            total=len(items),
        )
        self.subtitle.setText(
            (self.i18n.t("home_overdue", date=stamp) if overdue else stamp) + " · " + progress
        )
        self.rows.update_rows(items, hide_done, allow_partial=not task.items)
        self.description.setText(task.description)
        self.expand.setVisible(bool(task.description))

    def _mark(self, identifier, state):
        if identifier:
            self.repository.set_planner_item_state(identifier, state)
        else:
            self.repository.set_planner_task_state(self.task.id, state)
        self.changed.emit()

    def _archive(self):
        self.repository.archive_planner_task(self.task.id)
        self.changed.emit()

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from somniloop.core.i18n import I18n
from somniloop.core.models import TaskState


class SmartPlainTextEdit(QPlainTextEdit):
    """Moves Down to the real end when the cursor is already on the last line."""

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Down:
            cursor = self.textCursor()
            layout = cursor.block().layout()
            line = layout.lineForTextPosition(cursor.positionInBlock())
            last_visual_line = not line.isValid() or line.lineNumber() == layout.lineCount() - 1
            if (
                cursor.block() == self.document().lastBlock()
                and last_visual_line
                and not (
                    event.modifiers()
                    & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
                )
            ):
                mode = (
                    QTextCursor.MoveMode.KeepAnchor
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    else QTextCursor.MoveMode.MoveAnchor
                )
                cursor.movePosition(QTextCursor.MoveOperation.End, mode)
                self.setTextCursor(cursor)
                event.accept()
                return
        super().keyPressEvent(event)


class StateSelector(QWidget):
    state_changed = Signal(object)

    def __init__(self, i18n: I18n, state: TaskState = TaskState.UNSET, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[TaskState, QPushButton] = {}
        specs = (
            (TaskState.DONE, i18n.t("done"), "doneButton"),
            (TaskState.NOT_DONE, i18n.t("not_done"), "notDoneButton"),
            (TaskState.UNSET, i18n.t("unset"), "unsetButton"),
        )
        for value, label, object_name in specs:
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, v=value: self.state_changed.emit(v))
            self.group.addButton(button)
            self.buttons[value] = button
            layout.addWidget(button)
        self.set_state(state)

    def set_state(self, state: TaskState) -> None:
        # Legacy partial item marks remain stored, but are shown as incomplete.
        if state == TaskState.PARTIAL:
            state = TaskState.NOT_DONE
        self.buttons[state].setChecked(True)

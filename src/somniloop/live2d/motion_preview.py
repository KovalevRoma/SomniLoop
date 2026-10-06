"""Temporary, removable controls for reviewing unused official motion clips."""

from pathlib import PurePosixPath

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from somniloop.ui.activity_scrollbar import ActivityScrollBar


class MotionPreviewPanel(QWidget):
    requested = Signal(str, int)

    def __init__(self, parent, motions, language="en"):
        super().__init__(parent)
        self.buttons = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        title = QLabel("Движения · тест" if language == "ru" else "Motions · test")
        title.setStyleSheet("color: #77758a; font-size: 11px; background: transparent;")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBar(ActivityScrollBar(scroll))
        scroll.setStyleSheet("QScrollArea {background: transparent; border: none;}")
        body = QWidget()
        body.setObjectName("motionPreviewBody")
        body.setStyleSheet("QWidget#motionPreviewBody {background: transparent;}")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 2, 0)
        column.setSpacing(4)
        for group, clips in motions.items():
            for index, clip in enumerate(clips):
                if group == "Idle" or (group == "Tap" and index == 0):
                    continue
                button = QPushButton(f"{group} / {index}")
                button.setCheckable(True)
                button.setFixedHeight(28)
                button.setMinimumWidth(0)
                button.setToolTip(PurePosixPath(clip["File"]).name)
                button.setAccessibleName(f"Play {group}, index {index}")
                button.setStyleSheet("""
                    QPushButton {background: #2d5575; color: #f1f6ff; border-radius: 11px;
                        border: 1px solid #416e91; padding: 2px 8px; font-size: 13px;}
                    QPushButton:hover {background: #37698d;}
                    QPushButton:checked {background: #507ea3; border-color: #8bc9f2;}
                    QPushButton:focus {border: 2px solid #a8dcff;}
                    QPushButton:pressed {background: #23445f;}
                """)
                button.clicked.connect(
                    lambda _checked=False, group=group, index=index: self.requested.emit(group, index)
                )
                column.addWidget(button)
                self.buttons[(group, index)] = button
        column.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.preferred_height = 24 + len(self.buttons) * 32
        self.hide()

    def set_active(self, key=None):
        for candidate, button in self.buttons.items():
            button.setChecked(candidate == key)

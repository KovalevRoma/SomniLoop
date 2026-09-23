"""A stable-width scrollbar that fades without shifting or rebuilding content."""

from PySide6.QtCore import QEvent, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QScrollBar


class ActivityScrollBar(QScrollBar):
    def __init__(self, area):
        super().__init__(Qt.Orientation.Vertical, area)
        self.area = area
        self.setObjectName("activityBar")
        self.setStyleSheet("""
            QScrollBar#activityBar:vertical {
                background: transparent; border: none; width: 10px; margin: 0;
            }
            QScrollBar#activityBar::handle:vertical {
                background: #92949d; min-height: 32px; border-radius: 3px;
                margin: 0 2px;
            }
            QScrollBar#activityBar::handle:vertical:hover { background: #777b86; }
            QScrollBar#activityBar::add-line:vertical,
            QScrollBar#activityBar::sub-line:vertical { height: 0; border: none; }
            QScrollBar#activityBar::up-arrow:vertical,
            QScrollBar#activityBar::down-arrow:vertical { image: none; width: 0; height: 0; }
            QScrollBar#activityBar::add-page:vertical,
            QScrollBar#activityBar::sub-page:vertical { background: transparent; }
        """)
        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(0)
        self.setGraphicsEffect(self.opacity)
        self.fade = QPropertyAnimation(self.opacity, b"opacity", self)
        self.fade.setDuration(180)
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(1000)
        self.idle.timeout.connect(self._fade_out)
        self.valueChanged.connect(self.reveal)
        self.rangeChanged.connect(self._range_changed)
        self.sliderPressed.connect(self.reveal)
        self.sliderReleased.connect(self.reveal)
        area.viewport().setMouseTracking(True)
        area.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # Hover events propagate through the viewport, so no application-wide
        # filter is needed (especially important with cached, hidden pages).
        area.installEventFilter(self)
        area.viewport().installEventFilter(self)
        self.installEventFilter(self)

    def reveal(self, *_):
        if self.maximum() <= self.minimum() or not self.area.isVisible():
            return
        self.fade.stop()
        self.opacity.setOpacity(1)
        self.idle.start()

    def _range_changed(self, *_):
        if self.maximum() <= self.minimum():
            self.idle.stop()
            self.fade.stop()
            self.opacity.setOpacity(0)

    def _fade_out(self):
        if self.isSliderDown() or self.underMouse():
            self.idle.start()
            return
        self.fade.setStartValue(self.opacity.opacity())
        self.fade.setEndValue(0)
        self.fade.start()

    def eventFilter(self, watched, event):
        if watched is self.area and event.type() == QEvent.Type.Hide:
            self.idle.stop()
            self.fade.stop()
            self.opacity.setOpacity(0)
        elif event.type() in (
            QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Wheel,
            QEvent.Type.KeyPress, QEvent.Type.TouchUpdate,
        ) and self.area.isEnabled():
            self.reveal()
        return False

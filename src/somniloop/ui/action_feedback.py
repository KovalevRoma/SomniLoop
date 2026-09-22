"""Non-blocking feedback for every save/cancel button, including keyboard activation."""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialogButtonBox, QWidget

from somniloop.core.i18n import I18n


class ActionPulse(QWidget):
    def __init__(self, target, text, cancelled):
        super().__init__(target)
        if target is None:
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(270, 56)
        if target:
            self.move(max(8, (target.width() - self.width()) // 2), max(8, target.height() - 80))
        self.text, self.cancelled = text, cancelled
        self.elapsed = QElapsedTimer()
        self.elapsed.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(20)
        self.show()
        self.raise_()

    def _tick(self):
        if self.elapsed.elapsed() > 650:
            self.timer.stop()
            self.close()
            self.deleteLater()
        else:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fraction = self.elapsed.elapsed() / 650
        painter.setOpacity(min(1, fraction * 8, (1 - fraction) * 4))
        light = QApplication.instance().property("somniloopTheme") == "light"
        painter.setPen(QColor("#8190a5" if self.cancelled else "#927ed9"))
        painter.setBrush(QColor("#ffffff" if light else "#282c3c"))
        painter.drawRoundedRect(QRectF(2, 4 + 6 * (1 - min(1, fraction * 5)), 266, 44), 12, 12)
        painter.setPen(QColor("#283647" if light else "#f1f3fa"))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            ("↶  " if self.cancelled else "·  ") + self.text,
        )


class ActionFeedback(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.pulses = []
        app.installEventFilter(self)

    def watch(self, button):
        if button.property("actionFeedbackConnected"):
            return
        button.setProperty("actionFeedbackConnected", True)
        button.clicked.connect(lambda checked=False, current=button: self._clicked(current))

    def eventFilter(self, watched, event):
        if isinstance(watched, QAbstractButton) and event.type() in (
            QEvent.Type.Polish,
            QEvent.Type.Show,
        ):
            self.watch(watched)
        return False  # Feedback never consumes the action or mouse event.

    def _clicked(self, button):
        text = button.text().replace("&", "").strip().casefold()
        box = button.parentWidget()
        standard = box.standardButton(button) if isinstance(box, QDialogButtonBox) else None
        cancelled = standard == QDialogButtonBox.StandardButton.Cancel or text in (
            "отмена",
            "отменить",
            "cancel",
            "остановить",
            "stop",
        )
        saved = standard == QDialogButtonBox.StandardButton.Save or text in (
            "сохранить",
            "save",
            "save changes",
        )
        if not (cancelled or saved):
            return
        # Resolve the target after all clicked slots: the dialog may already be closed.
        QTimer.singleShot(0, lambda: self._show(button, cancelled))

    def _show(self, button, cancelled):
        target = None
        try:
            target = button.window()
            while target and not target.isVisible():
                parent = target.parentWidget()
                target = parent.window() if parent else None
        except RuntimeError:
            target = QApplication.activeWindow()
        language = QApplication.instance().property("language") or "ru"
        pulse = ActionPulse(
            target, I18n(language).t("cancel" if cancelled else "home_saving"), cancelled
        )
        self.pulses.append(pulse)
        pulse.destroyed.connect(lambda: self.pulses.remove(pulse) if pulse in self.pulses else None)


def install_action_feedback():
    app = QApplication.instance()
    if not hasattr(app, "_action_feedback"):
        app._action_feedback = ActionFeedback(app)
    return app._action_feedback

"""Embed existing modal forms without changing their accept/reject contracts."""

from PySide6.QtCore import QEvent, QEventLoop, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid


class ModalOverlay(QWidget):
    def __init__(self, dialog, host):
        super().__init__(host)
        self.host, self.dialog = host, dialog
        self.original_parent, self.original_flags = dialog.parentWidget(), dialog.windowFlags()
        # A Wayland surface may not yet be active; retain its local focus target.
        self.previous_focus = host.focusWidget()
        self.loop = QEventLoop()
        self.closed = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.disabled = [
            (child, child.isEnabled())
            for child in host.findChildren(
                QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly
            )
            if child is not self and not child.isWindow()
        ]
        for child, _enabled in self.disabled:
            child.setEnabled(False)
        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(12, 8, 12, 12)
        title_row = QHBoxLayout()
        title = QLabel(dialog.windowTitle())
        title.setObjectName("sectionTitle")
        title.setWordWrap(True)
        title_row.addWidget(title, 1)
        close = QPushButton("×")
        close.setFixedSize(32, 32)
        close.setAccessibleName("Закрыть / Close")
        close.clicked.connect(dialog.reject)
        title_row.addWidget(close)
        layout.addLayout(title_row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.scroll, 1)
        self.preferred = dialog.sizeHint().expandedTo(dialog.minimumSize())
        if dialog.testAttribute(Qt.WidgetAttribute.WA_Resized):
            self.preferred = self.preferred.expandedTo(dialog.size())
        dialog.setParent(self.scroll, Qt.WindowType.Widget)
        self.scroll.setWidget(dialog)
        stack = getattr(host, "_modal_overlays", [])
        host._modal_overlays = stack
        stack.append(self)
        QApplication.instance().installEventFilter(self)
        self.setGeometry(host.rect())
        self.arrange()
        self.show()
        self.raise_()
        dialog.show()
        dialog.setFocus(Qt.FocusReason.OtherFocusReason)
        dialog.focusNextChild()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(65, 67, 73, 145))

    def arrange(self):
        width = max(1, min(self.preferred.width() + 24, self.host.width() - 32))
        height = max(1, min(self.preferred.height() + 56, self.host.height() - 32))
        self.panel.setGeometry(
            (self.width() - width) // 2, (self.height() - height) // 2, width, height
        )

    def eventFilter(self, watched, event):
        if self.closed:
            return False
        if watched is self.host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
            self.arrange()
        if not self.host._modal_overlays or self.host._modal_overlays[-1] is not self:
            return False
        if watched is self.host and event.type() == QEvent.Type.Close:
            self.dialog.reject()
            event.ignore()
            return True
        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.Shortcut,
            QEvent.Type.ShortcutOverride,
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
        ):
            owner = watched
            while owner is not None and not isinstance(owner, QWidget):
                owner = owner.parent()
            if owner is not None and (owner is self.host or self.host.isAncestorOf(owner)):
                return owner is not self and not self.isAncestorOf(owner)
        return False

    def release(self):
        if self.closed:
            return
        self.closed = True
        QApplication.instance().removeEventFilter(self)
        self.host._modal_overlays.remove(self)
        self.scroll.takeWidget()
        if isValid(self.dialog):
            parent = (
                self.original_parent
                if self.original_parent and isValid(self.original_parent)
                else self.host
            )
            self.dialog.setParent(parent, self.original_flags)
        for child, enabled in self.disabled:
            if isValid(child):
                child.setEnabled(enabled)
        self.hide()
        if self.previous_focus and isValid(self.previous_focus) and self.previous_focus.isEnabled():
            self.previous_focus.setFocus(Qt.FocusReason.OtherFocusReason)
        self.loop.quit()
        self.deleteLater()


def exec_embedded(dialog):
    host = dialog.parentWidget().window()
    popup = QApplication.activePopupWidget()
    if popup:
        popup.close()
    dialog.setResult(0)
    overlay = ModalOverlay(dialog, host)
    dialog._modal_overlay = overlay
    try:
        overlay.loop.exec()
        return dialog.result()
    finally:
        overlay.release()
        dialog._modal_overlay = None

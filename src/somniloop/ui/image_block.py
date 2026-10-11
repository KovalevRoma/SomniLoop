"""Self-contained image blocks with a bounded, aspect-preserving resize handle."""

import base64

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from .task_images import image_preview


class ImageBlock(QWidget):
    def __init__(self, owner, data, width=320):
        super().__init__(owner)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Image exceeds 10 MB")
        self.pixmap = image_preview(data)
        self.owner, self.data = owner, data
        self.preferred_width = max(40, min(1600, int(width)))
        self.read_only = False
        self.drag_start = None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Image; drag the bottom-right corner to resize")
        self.remove_button = QToolButton(self)
        self.remove_button.setText("×")
        self.remove_button.setToolTip("Remove image")
        self.remove_button.clicked.connect(self.remove)
        self.remove_button.setFixedSize(24, 24)
        self._layout_image()

    def source(self):
        encoded = base64.b64encode(self.data).decode("ascii")
        return f'<somniloop-image width="{self.preferred_width}" data="{encoded}" />'

    def toPlainText(self):
        return "[Image]"

    def setReadOnly(self, value):
        self.read_only = value
        self.remove_button.setVisible(not value)
        self.update()

    def _layout_image(self):
        width = min(self.preferred_width, max(1, self.width()))
        height = max(1, round(width * self.pixmap.height() / self.pixmap.width()))
        self.image_rect = QRectF(0, 0, width, height)
        self.handle_rect = QRectF(max(0, width - 20), max(0, height - 20), 20, 20)
        if self.height() != height + 2:
            self.setFixedHeight(height + 2)
        self.remove_button.move(max(0, width - 26), 2)
        self.update()

    def resizeEvent(self, event):
        self._layout_image()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.image_rect, self.pixmap, QRectF(self.pixmap.rect()))
        if not self.read_only:
            painter.setPen(QPen(QColor("#438bed"), 3))
            right, bottom = self.image_rect.right() - 2, self.image_rect.bottom() - 2
            painter.drawLine(int(right - 12), int(bottom), int(right), int(bottom))
            painter.drawLine(int(right), int(bottom - 12), int(right), int(bottom))

    def mousePressEvent(self, event):
        if (not self.read_only and event.button() == Qt.MouseButton.LeftButton
                and self.handle_rect.contains(event.position())):
            self.drag_start = event.globalPosition()
            self.start_width = self.image_rect.width()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            delta = event.globalPosition() - self.drag_start
            self.preferred_width = round(max(40, min(self.width(), self.start_width + delta.x())))
            self._layout_image()
            self.owner.changed()
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if self.drag_start is not None
                       or not self.read_only and self.handle_rect.contains(event.position())
                       else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if not self.read_only and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove()
        else:
            super().keyPressEvent(event)

    def remove(self):
        if self.read_only:
            return
        self.owner.blocks.remove(self)
        self.owner.column.removeWidget(self)
        self.hide()
        self.deleteLater()
        self.owner.changed()

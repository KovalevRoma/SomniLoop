"""Small vector-painted icons independent of installed fonts and emoji support."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication


def interface_icon(name):
    return _icon(name, QApplication.instance().property("somniloopTheme") == "light")


@lru_cache(maxsize=20)
def _icon(name, light):
    icon = QIcon()
    color = QColor("#53416e" if light else "#eee5ff")
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        if name == "settings":
            painter.drawEllipse(QRectF(6, 6, 12, 12))
            painter.drawEllipse(QRectF(9.5, 9.5, 5, 5))
            painter.translate(12, 12)
            for _ in range(8):
                painter.drawLine(QPointF(0, -6), QPointF(0, -9))
                painter.rotate(45)
        elif name == "birthday":
            painter.drawRoundedRect(QRectF(4, 11, 16, 9), 2, 2)
            painter.drawLine(3, 21, 21, 21)
            painter.drawLine(4, 15, 20, 15)
            for x in (7, 12, 17):
                painter.drawLine(x, 8, x, 11)
                painter.drawLine(x, 4, x, 5)
        elif name == "calendar":
            painter.drawRoundedRect(QRectF(3, 5, 18, 16), 2, 2)
            painter.drawLine(3, 10, 21, 10)
            painter.drawLine(8, 3, 8, 7)
            painter.drawLine(16, 3, 16, 7)
            painter.drawPoint(8, 14)
            painter.drawPoint(12, 14)
            painter.drawPoint(16, 14)
            painter.drawPoint(8, 17)
            painter.drawPoint(12, 17)
        elif name == "open":
            painter.drawRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
            for y in (8, 12, 16):
                painter.drawLine(8, y, 16, y)
        elif name == "more":
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            for y in (5, 12, 19):
                painter.drawEllipse(QPointF(12, y), 1.6, 1.6)
        else:
            raise ValueError(f"Unknown interface icon: {name}")
        painter.end()
        icon.addPixmap(pixmap)
    return icon

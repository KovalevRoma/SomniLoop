"""Small vector-painted icons independent of installed fonts and emoji support."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication


def interface_icon(name):
    return _icon(name, QApplication.instance().property("somniloopTheme") == "light")


@lru_cache(maxsize=32)
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
        if name == "bold":
            path = QPainterPath(QPointF(7, 4))
            path.lineTo(7, 20)
            path.lineTo(13, 20)
            path.cubicTo(20, 20, 20, 12, 13, 12)
            path.lineTo(7, 12)
            path.lineTo(12, 12)
            path.cubicTo(18, 12, 18, 4, 12, 4)
            path.closeSubpath()
            painter.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
        elif name == "italic":
            painter.drawLine(10, 4, 19, 4)
            painter.drawLine(5, 20, 14, 20)
            painter.drawLine(15, 4, 9, 20)
        elif name == "strike":
            path = QPainterPath(QPointF(17, 6))
            path.cubicTo(15, 2, 7, 3, 7, 7)
            path.cubicTo(7, 10, 11, 11, 14, 12)
            path.cubicTo(20, 15, 16, 22, 7, 18)
            painter.drawPath(path)
            painter.drawLine(3, 12, 21, 12)
        elif name == "link":
            painter.translate(12, 12)
            painter.rotate(45)
            path = QPainterPath(QPointF(-3, -1))
            path.lineTo(-3, -6)
            path.cubicTo(-3, -10, 3, -10, 3, -6)
            path.lineTo(3, -1)
            painter.drawPath(path)
            painter.rotate(180)
            painter.drawPath(path)
            painter.drawLine(0, -4, 0, 4)
        elif name == "add":
            painter.drawLine(12, 5, 12, 19)
            painter.drawLine(5, 12, 19, 12)
        elif name == "settings":
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
        elif name in {"undo", "redo"}:
            if name == "redo":
                painter.translate(24, 0)
                painter.scale(-1, 1)
            path = QPainterPath(QPointF(4, 9))
            path.cubicTo(15, 2, 22, 9, 19, 18)
            painter.drawPath(path)
            painter.drawLine(4, 4, 4, 9)
            painter.drawLine(4, 9, 9, 10)
        elif name == "cut":
            painter.drawEllipse(QRectF(3, 14, 6, 6))
            painter.drawEllipse(QRectF(15, 14, 6, 6))
            painter.drawLine(8, 15, 18, 4)
            painter.drawLine(16, 15, 6, 4)
        elif name == "copy":
            painter.drawRoundedRect(QRectF(8, 8, 12, 13), 2, 2)
            path = QPainterPath(QPointF(5, 16))
            path.lineTo(3, 16)
            path.lineTo(3, 3)
            path.lineTo(15, 3)
            path.lineTo(15, 5)
            painter.drawPath(path)
        elif name == "paste":
            painter.drawRoundedRect(QRectF(5, 5, 14, 16), 2, 2)
            painter.drawRoundedRect(QRectF(9, 2, 6, 5), 1, 1)
            painter.drawLine(9, 12, 15, 12)
            painter.drawLine(9, 16, 15, 16)
        elif name == "delete":
            painter.drawLine(4, 6, 20, 6)
            painter.drawLine(9, 3, 15, 3)
            path = QPainterPath(QPointF(6, 9))
            path.lineTo(7, 21)
            path.lineTo(17, 21)
            path.lineTo(18, 9)
            painter.drawPath(path)
            painter.drawLine(10, 10, 10, 17)
            painter.drawLine(14, 10, 14, 17)
        elif name == "select_all":
            painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(3, 3, 18, 18))
            painter.setPen(QPen(color, 1.8))
            for y in (8, 12, 16):
                painter.drawLine(7, y, 17, y)
        else:
            raise ValueError(f"Unknown interface icon: {name}")
        painter.end()
        icon.addPixmap(pixmap)
    return icon

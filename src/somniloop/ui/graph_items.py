"""Cached graph geometry and theme-aware node/edge painting."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsLineItem,
    QGraphicsObject,
    QGraphicsSimpleTextItem,
)

CATEGORY_STYLE = {
    "people": ("#668fbd", "ellipse"),
    "places": ("#509888", "rounded"),
    "habits": ("#9480b8", "hexagon"),
    "groups": ("#b19663", "rounded"),
}


def colors():
    light = QApplication.instance().property("somniloopTheme") == "light"
    return {
        "light": light,
        "background": "#f7f8fb" if light else "#141923",
        "panel": "#ffffff" if light else "#202735",
        "text": "#283647" if light else "#e4eaf2",
        "muted": "#586c80" if light else "#a5b5c9",
        "edge": "#adb9c8" if light else "#46546a",
        "grid": "#e3e8ef" if light else "#253042",
        "warning": "#98620d" if light else "#e4b86c",
    }


class GraphNodeItem(QGraphicsObject):
    clicked = Signal(object)
    moved = Signal()
    released = Signal(object)
    hover_changed = Signal(object, bool)

    def __init__(self, node, degree=0):
        super().__init__()
        self.node = node
        self.degree = degree
        self.pinned = False
        self.hovered = False
        self.status = ""
        self._press_pos = QPointF()
        growth = min(16, 4 * math.log2(degree + 1))
        self.rect = QRectF(-90 - growth / 2, -36 - growth / 2, 180 + growth, 72 + growth)
        self._path = QPainterPath()
        category = node.category
        if category == "people":
            self._path.addRoundedRect(self.rect, self.rect.height() / 2, self.rect.height() / 2)
        elif category == "habits":
            r = self.rect
            self._path.addPolygon(
                QPolygonF(
                    [
                        QPointF(r.left() + 18, r.top()),
                        QPointF(r.right() - 18, r.top()),
                        QPointF(r.right(), 0),
                        QPointF(r.right() - 18, r.bottom()),
                        QPointF(r.left() + 18, r.bottom()),
                        QPointF(r.left(), 0),
                    ]
                )
            )
            self._path.closeSubpath()
        else:
            self._path.addRoundedRect(self.rect, 13, 13)
        self.setFlags(
            self.GraphicsItemFlag.ItemIsMovable
            | self.GraphicsItemFlag.ItemIsSelectable
            | self.GraphicsItemFlag.ItemSendsGeometryChanges
            | self.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setCacheMode(self.CacheMode.DeviceCoordinateCache)
        self.setToolTip(f"{node.label}\nСвязей: {degree}\nПеретащите, чтобы закрепить позицию")

    def boundingRect(self):
        return self.rect.adjusted(-10, -10, 10, 10)

    def shape(self):
        return self._path

    def paint(self, painter, option, widget=None):
        palette = colors()
        color = QColor(CATEGORY_STYLE.get(self.node.category, ("#8090a4", "rounded"))[0])
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isSelected():
            glow = QColor(color)
            glow.setAlpha(35)
            painter.setPen(QPen(glow, 14))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self._path)
        painter.setPen(QPen(color, 2.4 if self.isSelected() or self.hovered else 1.3))
        background = QColor(palette["panel"])
        painter.setBrush(background)
        painter.drawPath(self._path)
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        x = self.rect.left() + 23
        if self.node.category == "people":
            painter.drawEllipse(QPointF(x, -5), 4, 4)
            painter.drawArc(QRectF(x - 7, 0, 14, 10), 0, 180 * 16)
        elif self.node.category == "places":
            painter.drawEllipse(QPointF(x, -4), 6, 6)
            painter.drawLine(QPointF(x - 5, 0), QPointF(x, 8))
            painter.drawLine(QPointF(x + 5, 0), QPointF(x, 8))
        elif self.node.category == "habits":
            painter.drawEllipse(QPointF(x, 0), 8, 8)
            painter.drawPolyline(
                QPolygonF([QPointF(x - 4, 0), QPointF(x - 1, 3), QPointF(x + 5, -4)])
            )
        else:
            painter.drawEllipse(QPointF(x - 3, -3), 4, 4)
            painter.drawEllipse(QPointF(x + 4, 3), 4, 4)
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        if lod >= 0.35 or self.isSelected() or self.node.category == "groups":
            font = QFont()
            font.setPointSizeF(9.5)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(palette["text"]))
            label = self.node.label if len(self.node.label) < 55 else self.node.label[:52] + "…"
            painter.drawText(
                self.rect.adjusted(42, 9, -12, -9),
                Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                label,
            )
        if self.status:
            dot = {"new": "#508eb3", "changed": "#c59a4e", "stale": "#8c98a8"}.get(
                self.status, "#8c98a8"
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(dot))
            painter.drawEllipse(QPointF(self.rect.right() - 12, self.rect.top() + 10), 3, 3)
        if self.node.metadata.get("conflicts"):
            painter.setPen(QColor(palette["warning"]))
            painter.drawText(
                self.rect.adjusted(0, 0, -10, 0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                "!",
            )
        if self.pinned:
            painter.setPen(QPen(QColor(palette["muted"]), 1.5))
            r = self.rect
            painter.drawLine(
                QPointF(r.right() - 18, r.bottom() - 12), QPointF(r.right() - 10, r.bottom() - 12)
            )
            painter.drawLine(
                QPointF(r.right() - 14, r.bottom() - 16), QPointF(r.right() - 14, r.bottom() - 7)
            )

    def mousePressEvent(self, event):
        self._press_pos = self.pos()
        self.clicked.emit(self.node)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (self.pos() - self._press_pos).manhattanLength() > 1:
            self.released.emit(self)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        self.hover_changed.emit(self.node.id, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        self.hover_changed.emit(self.node.id, False)
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self.moved.emit()
        return result


class EdgeVisual(QGraphicsLineItem):
    def __init__(self, source, target, relation, scene):
        super().__init__()
        self.source, self.target, self.relation = source, target, relation
        self.line = self  # Kept for consumers of the previous canvas API.
        self.label = QGraphicsSimpleTextItem(relation)
        self.label.setFont(QFont("", 8))
        self.label.setBrush(QColor(colors()["muted"]))
        self.label.setZValue(-0.5)
        self.label.hide()
        self.setZValue(-1)
        self.setAcceptHoverEvents(True)
        self.setToolTip(relation or "Связано с")
        self.active = False
        self.lod_visible = False
        self.hovered = False
        self.hover_callback = None
        scene.addItem(self)
        scene.addItem(self.label)
        self.refresh_style()

    def refresh_style(self):
        pen = QPen(
            QColor(colors()["muted"] if self.active or self.hovered else colors()["edge"]),
            2 if self.active or self.hovered else 1,
        )
        pen.setCosmetic(True)
        if self.relation.startswith("Возможно знакомы · "):
            pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.label.setVisible(self.isVisible() and (self.lod_visible or self.hovered))

    def update_position(self):
        self.setLine(self.source.x(), self.source.y(), self.target.x(), self.target.y())
        midpoint = (self.source.pos() + self.target.pos()) / 2
        bounds = self.label.boundingRect()
        self.label.setPos(midpoint.x() - bounds.width() / 2, midpoint.y() - bounds.height() / 2 - 5)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.refresh_style()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.refresh_style()
        super().hoverLeaveEvent(event)

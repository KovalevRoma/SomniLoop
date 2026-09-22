"""Interactive canvas, overview map and persistent navigation state."""

from __future__ import annotations

import math
from collections import defaultdict

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QLabel, QMenu, QWidget

from somniloop.core.models import KnowledgeNode
from somniloop.knowledge.people import normalized

from .graph_data import GraphViewState
from .graph_items import CATEGORY_STYLE, EdgeVisual, GraphNodeItem, colors
from .graph_layout import Body, ForceLayout


def person_group(metadata):
    if str(metadata.get("group", "")).strip():
        return str(metadata["group"])
    relation = normalized(str(metadata.get("relationship", "")))
    if any(word in relation for word in ("мама", "папа", "брат", "сестр", "семь", "родств")):
        return "Семья"
    if any(word in relation for word in ("друг", "подруг", "приятел")):
        return "Друзья"
    if any(word in relation for word in ("коллег", "работ", "начальник", "клиент")):
        return "Работа"
    return "Контакты"


class MiniMap(QWidget):
    def __init__(self, view):
        super().__init__(view.viewport())
        self.view = view
        self.setFixedSize(168, 112)
        self.setToolTip("Обзор графа · нажмите для перемещения")
        self.setAccessibleName("Мини-карта графа")
        self._bounds = QRectF()
        self._scale = 1.0
        self._offset = QPointF()
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(180)
        self._refresh.timeout.connect(self.update)

    def schedule(self):
        if not self._refresh.isActive():
            self._refresh.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = colors()
        painter.setPen(QColor(palette["edge"]))
        painter.setBrush(QColor(palette["panel"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        items = [
            item
            for item in [*self.view.nodes.values(), *self.view.clusters.values()]
            if item.isVisible()
        ]
        if not items:
            return
        bounds = self.view.visible_bounds().adjusted(-80, -80, 80, 80)
        self._bounds = bounds
        self._scale = min(
            (self.width() - 20) / max(1, bounds.width()),
            (self.height() - 20) / max(1, bounds.height()),
        )
        self._offset = QPointF(
            (self.width() - bounds.width() * self._scale) / 2,
            (self.height() - bounds.height() * self._scale) / 2,
        )

        def point(value):
            return (value - bounds.topLeft()) * self._scale + self._offset

        painter.setPen(Qt.PenStyle.NoPen)
        for item in items:
            painter.setBrush(QColor(CATEGORY_STYLE.get(item.node.category, ("#8090a4", ""))[0]))
            painter.drawEllipse(point(item.pos()), 2.3, 2.3)
        viewport = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        painter.setPen(QPen(QColor(palette["text"]), 1.3))
        tint = QColor(palette["muted"])
        tint.setAlpha(20)
        painter.setBrush(tint)
        painter.drawRect(
            QRectF(point(viewport.topLeft()), point(viewport.bottomRight())).intersected(
                QRectF(self.rect()).adjusted(5, 5, -5, -5)
            )
        )

    def mousePressEvent(self, event):
        if not self._bounds.isEmpty():
            self.view.auto_fit = False
            self.view.centerOn(
                (event.position() - self._offset) / self._scale + self._bounds.topLeft()
            )
            self.view.schedule_save()
            self.update()


class GraphView(QGraphicsView):
    node_clicked = Signal(object)
    pin_changed = Signal(str, bool)
    neighborhood_requested = Signal(str)
    selection_cleared = Signal()

    def __init__(self, parent=None, repository=None):
        super().__init__(parent)
        self.state = GraphViewState(repository)
        self.graph_scene = QGraphicsScene(self)
        self.setScene(self.graph_scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(self.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(self.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(self.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(colors()["background"]))
        self.setAccessibleName("Интерактивный граф знаний")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.nodes, self.edges = {}, []
        self.clusters, self.cluster_members, self.cluster_edges = {}, {}, []
        self.positions = {}
        self.adjacency = defaultdict(set)
        self.incident = defaultdict(list)
        self.iterations = 0
        self.auto_fit = not bool(self.state.viewport)
        self.engine = ForceLayout({}, [])
        self._moving_batch = False
        self._updating_clusters = False
        self._selected = None
        self._hovered = None
        self._highlighted = None
        self._collapsed = False
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._physics_step)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save_state)
        self._zoom = QVariantAnimation(self)
        self._zoom.setDuration(160)
        self._zoom.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._zoom.valueChanged.connect(self._zoom_frame)
        self._zoom.finished.connect(self.schedule_save)
        self._anchor = QPointF()
        self._anchor_scene = QPointF()
        self._pan = QVariantAnimation(self)
        self._pan.setDuration(180)
        self._pan.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pan.valueChanged.connect(self.centerOn)
        self._pan.finished.connect(self.schedule_save)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(140)
        self._fade.valueChanged.connect(self._fade_frame)
        self._fade_targets = []
        self.minimap = MiniMap(self)
        self.legend = QLabel("○ Люди    ▢ Места    ⬡ Привычки", self.viewport())
        self.legend.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.legend.setStyleSheet(
            f"background: {colors()['panel']}; color: {colors()['muted']}; padding: 7px 11px; border-radius: 8px; font-size: 11px;"
        )
        self.hint = QLabel("Колесо — масштаб · перетаскивание — перемещение", self.viewport())
        self.hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hint.setStyleSheet(
            f"color: {colors()['muted']}; background: transparent; font-size: 11px;"
        )
        self.empty = QLabel(
            "Здесь появятся ваши связи\nДобавьте сведения о людях и обновите граф", self.viewport()
        )
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet(
            f"color: {colors()['muted']}; background: transparent; font-size: 15px;"
        )

    def _overlays(self):
        width, height = self.viewport().width(), self.viewport().height()
        self.minimap.move(
            max(12, width - self.minimap.width() - 14), max(12, height - self.minimap.height() - 14)
        )
        self.legend.adjustSize()
        self.legend.move(14, max(14, height - self.legend.height() - 14))
        self.hint.adjustSize()
        self.hint.move(16, 14)
        self.empty.setGeometry(20, max(0, height // 2 - 42), max(0, width - 40), 84)
        self.minimap.setVisible(bool(self.nodes) and width > 450 and height > 260)
        self.legend.setVisible(width > 430)
        self.hint.setVisible(width > 420)
        self.empty.setVisible(not self.nodes)

    def set_graph(self, nodes, edges):
        self.timer.stop()
        self._fade.stop()
        self._pan.stop()
        self._zoom.stop()
        self._capture_positions()
        self.graph_scene.clear()
        self.nodes, self.edges = {}, []
        self.clusters, self.cluster_members, self.cluster_edges = {}, {}, []
        self.adjacency, self.incident = defaultdict(set), defaultdict(list)
        self._collapsed = False
        degree = defaultdict(int)
        for edge in edges:
            degree[edge.source] += 1
            degree[edge.target] += 1
            self.adjacency[edge.source].add(edge.target)
            self.adjacency[edge.target].add(edge.source)
        bodies = {}
        # Include every restored anchor before placing new nodes, irrespective of sort order.
        occupied = defaultdict(list)
        for node in nodes:
            if node.id in self.state.positions:
                point = self.state.positions[node.id]
                occupied[(math.floor(point[0] / 240), math.floor(point[1] / 120))].append(point)
        slot = 0
        for index, node in enumerate(
            sorted(nodes, key=lambda node: (not node.metadata.get("is_owner"), node.id))
        ):
            item = GraphNodeItem(node, degree[node.id])
            restored = node.id in self.state.positions
            point = self.state.positions.get(node.id)
            if point is None:
                while True:
                    point = ForceLayout.initial(slot)
                    slot += 1
                    cx, cy = math.floor(point[0] / 240), math.floor(point[1] / 120)
                    if not any(
                        abs(point[0] - x) < 225 and abs(point[1] - y) < 110
                        for sx in (-1, 0, 1)
                        for sy in (-1, 0, 1)
                        for x, y in occupied.get((cx + sx, cy + sy), ())
                    ):
                        occupied[(cx, cy)].append(point)
                        break
            item.setPos(*point)
            item.pinned = node.id in self.state.pinned
            item.status = node.metadata.get("view_status", "")
            if not restored and self.isVisible() and len(nodes) < 500:
                item.setOpacity(0)
            item.clicked.connect(self._clicked)
            item.moved.connect(lambda identifier=node.id: self._node_moved(identifier))
            item.released.connect(self._dragged)
            item.hover_changed.connect(self._hover)
            self.graph_scene.addItem(item)
            self.nodes[node.id] = item
            bodies[node.id] = Body(
                *point, item.rect.width(), item.rect.height(), restored or item.pinned
            )
        for edge in edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                continue
            visual = EdgeVisual(
                self.nodes[edge.source], self.nodes[edge.target], edge.relation, self.graph_scene
            )
            self.edges.append(visual)
            self.incident[edge.source].append(visual)
            self.incident[edge.target].append(visual)
        self.engine = ForceLayout(bodies, [(edge.source, edge.target) for edge in edges])
        self.iterations = 0
        grouped = defaultdict(list)
        for item in self.nodes.values():
            if item.node.category == "people" and not item.node.metadata.get("is_owner"):
                grouped[person_group(item.node.metadata)].append(item)
        owner = next(
            (item for item in self.nodes.values() if item.node.metadata.get("is_owner")), None
        )
        group_of = {}
        for index, (name, members) in enumerate(sorted(grouped.items())):
            if len(members) < 2:
                continue
            identifier = "group-" + normalized(name)
            node = KnowledgeNode(
                identifier,
                f"{name} · {len(members)}",
                "groups",
                "\n".join(item.node.label for item in members),
                {"members": [item.node.id for item in members]},
            )
            cluster = GraphNodeItem(node)
            angle = index * 2 * math.pi / max(1, len(grouped))
            center = owner.pos() if owner else QPointF()
            cluster.setPos(center + QPointF(math.cos(angle) * 430, math.sin(angle) * 280))
            cluster.clicked.connect(self._clicked)
            cluster.moved.connect(lambda: self._update_edges())
            self.graph_scene.addItem(cluster)
            cluster.hide()
            self.clusters[identifier] = cluster
            self.cluster_members[identifier] = members
            group_of.update({member.node.id: identifier for member in members})
        grouped_edges = {}
        for edge in edges:
            a, b = group_of.get(edge.source, edge.source), group_of.get(edge.target, edge.target)
            if a != b and (a in self.clusters or b in self.clusters):
                grouped_edges.setdefault(tuple(sorted((a, b))), set()).add(edge.relation)
        items = {**self.nodes, **self.clusters}
        for (a, b), relations in grouped_edges.items():
            if a in items and b in items:
                visual = EdgeVisual(
                    items[a],
                    items[b],
                    next(iter(relations)) if len(relations) == 1 else "Связи групп",
                    self.graph_scene,
                )
                visual.hide()
                self.cluster_edges.append(visual)
        self._update_edges()
        bounds = self.visible_bounds().adjusted(-800, -800, 800, 800)
        self.graph_scene.setSceneRect(bounds)
        if self.state.viewport and not self.auto_fit:
            viewport = self.state.viewport
            self.setTransform(
                QTransform.fromScale(
                    max(0.08, min(3.5, viewport["scale"])), max(0.08, min(3.5, viewport["scale"]))
                )
            )
            self.centerOn(viewport["x"], viewport["y"])
        elif nodes:
            self.fit_nodes()
        self._update_cluster_visibility()
        if self._selected in self.nodes:
            self.nodes[self._selected].setSelected(True)
        self._apply_emphasis(animate=self.isVisible())
        self._overlays()
        if self.isVisible() and not self.engine.settled and not self._collapsed:
            self.timer.start()

    def visible_bounds(self):
        bounds = QRectF()
        for item in [*self.nodes.values(), *self.clusters.values()]:
            if item.isVisible():
                bounds = bounds.united(item.sceneBoundingRect())
        return bounds

    def _capture_positions(self):
        for key, item in self.nodes.items():
            self.positions[key] = item.pos()
            self.state.positions[key] = (round(item.x(), 3), round(item.y(), 3))

    def schedule_save(self):
        self._save_timer.start()
        self.minimap.schedule()

    def save_state(self):
        self._save_timer.stop()
        self._capture_positions()
        center = self.mapToScene(self.viewport().rect().center())
        self.state.viewport = {"x": center.x(), "y": center.y(), "scale": self.transform().m11()}
        self.state.save()

    def showEvent(self, event):
        super().showEvent(event)
        self._overlays()
        if self.auto_fit:
            QTimer.singleShot(0, self.fit_nodes)
        if self.nodes and not self.engine.settled and not self._collapsed:
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        self._zoom.stop()
        self._pan.stop()
        self._fade.stop()
        self.save_state()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlays()
        if self.auto_fit:
            self.fit_nodes()

    def fit_nodes(self):
        if not self.nodes:
            return
        self._zoom.stop()
        self.auto_fit = True
        # Fit the underlying layout, not the LOD overview: otherwise repeated fits
        # alternate between tiny clusters and the expanded graph.
        bounds = QRectF()
        for item in self.nodes.values():
            bounds = bounds.united(item.boundingRect().translated(item.pos()))
        bounds = bounds.adjusted(-70, -85, 70, 85)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        scale = max(0.08, min(1.2, self.transform().m11()))
        if scale != self.transform().m11():
            self.setTransform(QTransform.fromScale(scale, scale))
            self.centerOn(bounds.center())
        self._update_cluster_visibility()
        self.schedule_save()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            self.zoom(math.exp(delta / 700), event.position())
        event.accept()

    def zoom(self, factor, anchor=None):
        self.auto_fit = False
        self._anchor = anchor or QPointF(self.viewport().rect().center())
        self._anchor_scene = self.mapToScene(self._anchor.toPoint())
        current = self.transform().m11()
        target = max(0.08, min(3.5, current * factor))
        self._zoom.stop()
        self._zoom.setStartValue(current)
        self._zoom.setEndValue(target)
        self._zoom.start()

    def _zoom_frame(self, scale):
        self.setTransform(QTransform.fromScale(scale, scale))
        actual = self.mapToScene(self._anchor.toPoint())
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center + self._anchor_scene - actual)
        self._update_cluster_visibility()
        self.minimap.schedule()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "minimap"):
            self.minimap.schedule()
            self._edge_labels()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not isinstance(
            self.itemAt(event.position().toPoint()), GraphNodeItem
        ):
            self.auto_fit = False
            self.clear_selection()
        super().mousePressEvent(event)

    def clear_selection(self):
        self._selected = self._hovered = self._highlighted = None
        self.graph_scene.clearSelection()
        self._apply_emphasis()
        self.selection_cleared.emit()

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, GraphNodeItem) and item.node.id in self.clusters:
            members = self.cluster_members[item.node.id]
            self.focus_node(members[0].node.id)
            self.node_clicked.emit(members[0].node)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.schedule_save()

    def _clicked(self, node):
        self._selected = node.id
        self.graph_scene.clearSelection()
        item = self.nodes.get(node.id) or self.clusters.get(node.id)
        if item:
            item.setSelected(True)
        self._apply_emphasis()
        self.node_clicked.emit(node)

    def _hover(self, identifier, entered):
        self._hovered = identifier if entered else None
        self._apply_emphasis(animate=False)

    def _apply_emphasis(self, animate=True):
        identifier = self._hovered or self._selected
        focus = self._highlighted
        if identifier in self.nodes:
            focus = {identifier} | self.adjacency[identifier]
        elif identifier in self.clusters:
            focus = {identifier, *(member.node.id for member in self.cluster_members[identifier])}
            for edge in self.cluster_edges:
                if identifier in (edge.source.node.id, edge.target.node.id):
                    focus.update((edge.source.node.id, edge.target.node.id))
        self._fade.stop()
        self._fade_targets = []
        for key, item in self.nodes.items():
            target = 1.0 if focus is None or key in focus else 0.18
            self._fade_targets.append((item, item.opacity(), target))
        for key, item in self.clusters.items():
            target = (
                1.0
                if focus is None
                or any(member.node.id in focus for member in self.cluster_members[key])
                else 0.2
            )
            self._fade_targets.append((item, item.opacity(), target))
        for edge in [*self.edges, *self.cluster_edges]:
            edge.active = identifier in (edge.source.node.id, edge.target.node.id)
            target = (
                1.0
                if focus is None
                or (edge.source.node.id in focus and edge.target.node.id in focus)
                or edge.active
                else 0.15
            )
            edge.setOpacity(target)
            edge.label.setOpacity(target)
            edge.refresh_style()
        if animate and len(self.nodes) < 500 and self.isVisible():
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._fade_frame(1.0)
        self._edge_labels()

    def _fade_frame(self, value):
        for item, start, target in self._fade_targets:
            item.setOpacity(start + (target - start) * value)

    def highlight(self, identifiers):
        self._highlighted = identifiers
        self._selected = None
        self.graph_scene.clearSelection()
        self._apply_emphasis()

    def focus_node(self, identifier):
        item = self.nodes.get(identifier) or self.clusters.get(identifier)
        if not item:
            return
        self.auto_fit = False
        if identifier in self.nodes and self.transform().m11() < 0.7:
            self.setTransform(QTransform.fromScale(0.85, 0.85))
            self._update_cluster_visibility()
        self._selected = identifier
        self.graph_scene.clearSelection()
        item.setSelected(True)
        self._pan.stop()
        self._pan.setStartValue(self.mapToScene(self.viewport().rect().center()))
        self._pan.setEndValue(item.pos())
        self._pan.start()
        self._apply_emphasis()

    def set_pinned(self, identifier, pinned):
        item = self.nodes.get(identifier)
        if not item:
            return
        item.pinned = pinned
        if pinned:
            self.state.pinned.add(identifier)
        else:
            self.state.pinned.discard(identifier)
        body = self.engine.bodies[identifier]
        body.fixed = pinned
        body.x, body.y = item.x(), item.y()
        item.update()
        self.pin_changed.emit(identifier, pinned)
        self.schedule_save()

    def _dragged(self, item):
        self.set_pinned(item.node.id, True)
        self._update_edges()

    def _node_moved(self, identifier):
        if self._moving_batch:
            return
        item = self.nodes.get(identifier)
        if item and identifier in self.engine.bodies:
            body = self.engine.bodies[identifier]
            body.x, body.y = item.x(), item.y()
        for edge in self.incident.get(identifier, []):
            edge.update_position()
        self.minimap.schedule()

    def _physics_step(self):
        if not self.isVisible() or self._collapsed or self.engine.settled:
            self.timer.stop()
            return
        grabbed = self.graph_scene.mouseGrabberItem()
        if grabbed in self.nodes.values():
            return  # Never move a node underneath an active pointer drag.
        for _ in range(3):
            running = self.engine.step()
            if not running:
                break
        self._moving_batch = True
        for key, body in self.engine.bodies.items():
            self.nodes[key].setPos(body.x, body.y)
        self._moving_batch = False
        self.iterations = self.engine.iterations
        self._update_edges()
        if not running:
            self.timer.stop()
            self.schedule_save()

    def _update_edges(self):
        if self._updating_clusters:
            return
        for edge in [*self.edges, *self.cluster_edges]:
            edge.update_position()
        self._edge_labels()
        self.minimap.schedule()

    def _edge_labels(self):
        scale = self.transform().m11()
        occupied = defaultdict(list)
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        # Labels must not collide with node bodies either.
        for item in [*self.nodes.values(), *self.clusters.values()]:
            bounds = item.sceneBoundingRect()
            if item.isVisible() and bounds.intersects(visible):
                for x in range(
                    math.floor(bounds.left() / 160), math.floor(bounds.right() / 160) + 1
                ):
                    for y in range(
                        math.floor(bounds.top() / 80), math.floor(bounds.bottom() / 80) + 1
                    ):
                        occupied[(x, y)].append(bounds)
        for edge in sorted([*self.edges, *self.cluster_edges], key=lambda edge: not edge.active):
            show = (
                edge.isVisible()
                and (scale >= 0.95 or (edge.active and scale >= 0.5))
                and edge.opacity() > 0.5
            )
            bounds = edge.label.sceneBoundingRect().adjusted(-5, -3, 5, 3)
            cells = (
                [
                    (x, y)
                    for x in range(
                        math.floor(bounds.left() / 160), math.floor(bounds.right() / 160) + 1
                    )
                    for y in range(
                        math.floor(bounds.top() / 80), math.floor(bounds.bottom() / 80) + 1
                    )
                ]
                if show
                else []
            )
            if show:
                show = bounds.intersects(visible) and not any(
                    bounds.intersects(other) for cell in cells for other in occupied[cell]
                )
            if show:
                for cell in cells:
                    occupied[cell].append(bounds)
            edge.lod_visible = show
            edge.refresh_style()

    def _update_cluster_visibility(self):
        scale = self.transform().m11()
        collapsed = scale < 0.32 and bool(self.clusters)
        self._collapsed = collapsed
        member_ids = {
            member.node.id for members in self.cluster_members.values() for member in members
        }
        # Overview nodes retain readable screen-space size. Their temporary layout
        # never replaces the persistent coordinates of the individual people.
        self._updating_clusters = True
        owner = next(
            (item for item in self.nodes.values() if item.node.metadata.get("is_owner")), None
        )
        center = owner.pos() if owner else QPointF()
        count = len(self.clusters)
        for index, item in enumerate(self.clusters.values()):
            item.setVisible(collapsed)
            item.setScale(0.85 / scale if collapsed else 1)
            if collapsed:
                angle = index * 2 * math.pi / count
                item.setPos(
                    center
                    + QPointF(
                        math.cos(angle) * max(250, count * 35) / scale,
                        math.sin(angle) * max(160, count * 22) / scale,
                    )
                )
        if owner:
            owner.setScale(0.85 / scale if collapsed else 1)
        self._updating_clusters = False
        for identifier in member_ids:
            self.nodes[identifier].setVisible(not collapsed)
        for edge in self.edges:
            edge.setVisible(edge.source.isVisible() and edge.target.isVisible())
        for edge in self.cluster_edges:
            edge.setVisible(collapsed)
        self._update_edges()
        if collapsed:
            self.timer.stop()
        elif self.isVisible() and not self.engine.settled:
            self.timer.start()

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if not isinstance(item, GraphNodeItem) or item.node.id not in self.nodes:
            return
        menu = QMenu(self)
        pin = menu.addAction("Открепить узел" if item.pinned else "Закрепить узел")
        nearby = menu.addAction("Показать окружение")
        action = menu.exec(event.globalPos())
        if action == pin:
            self.set_pinned(item.node.id, not item.pinned)
        elif action == nearby:
            self.neighborhood_requested.emit(item.node.id)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom(1.2)
        elif key == Qt.Key.Key_Minus:
            self.zoom(1 / 1.2)
        elif key == Qt.Key.Key_0:
            self.fit_nodes()
        elif key == Qt.Key.Key_Escape:
            self.clear_selection()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                dx = -80 if key == Qt.Key.Key_Left else 80 if key == Qt.Key.Key_Right else 0
                dy = -80 if key == Qt.Key.Key_Up else 80 if key == Qt.Key.Key_Down else 0
                self.centerOn(self.mapToScene(self.viewport().rect().center()) + QPointF(dx, dy))
            else:
                items = {**self.nodes, **self.clusters}
                keys = sorted(key for key, item in items.items() if item.isVisible())
                if keys:
                    index = keys.index(self._selected) if self._selected in keys else -1
                    identifier = keys[
                        (index + (-1 if key in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1)) % len(keys)
                    ]
                    self.focus_node(identifier)
                    self.node_clicked.emit(items[identifier].node)
        elif key == Qt.Key.Key_P and self._selected in self.nodes:
            self.set_pinned(self._selected, not self.nodes[self._selected].pinned)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._selected in self.clusters:
            item = self.cluster_members[self._selected][0]
            self.focus_node(item.node.id)
            self.node_clicked.emit(item.node)
        else:
            super().keyPressEvent(event)

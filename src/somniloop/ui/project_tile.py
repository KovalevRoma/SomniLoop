"""Project accent surfaces and explicit, keyboard-accessible reordering."""

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QCursor, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QScrollArea,
    QWidget,
)


def project_accent(widget, color, dark=False):
    accent = QColor(color)
    if not accent.isValid():
        accent = QColor("#3778bd")
    base = QColor("#1d2938" if dark else "#ffffff")
    amount = .48 if dark else .42
    surface = QColor(*(round(base.getRgb()[i] * (1 - amount) + accent.getRgb()[i] * amount) for i in range(3)))
    channels = [v / 255 for v in surface.getRgb()[:3]]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    luminance = sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    foreground = "#111827" if luminance > .24 else "#ffffff"
    text_base = QColor(foreground)
    title_color = text_base
    widget.setStyleSheet(
        f"QFrame#workRow {{ background: {surface.name()}; border: none; border-radius: 12px; }}"
        f"QLabel#cardTitle, QLabel#muted, QLabel#projectText, QLabel#taskTitle {{ color: {foreground}; background: transparent; }}"
        f"QLabel#cardTitle {{ color: {title_color.name()}; }}"
        f"QPushButton#projectChip {{ border-bottom: 2px solid {accent.name()}; }}"
    )


def start_project_drag(source, tile, origin):
    drag = QDrag(source)
    data = QMimeData()
    data.setData("application/x-somniloop-project", str(tile.identifier).encode())
    drag.setMimeData(data)
    drag.setPixmap(tile.grab())
    drag.setHotSpot(source.mapTo(tile, origin))
    grid = tile.grid
    if grid:
        grid.begin(tile.identifier)
    try:
        drag.exec(Qt.DropAction.MoveAction)
    finally:
        if grid:
            grid.cancel()
        drag.deleteLater()


class ProjectTile(QFrame):
    def __init__(self, owner, identifier):
        super().__init__(owner)
        self.owner, self.identifier = owner, identifier
        self.grid = None
        self.origin = None
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.origin = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if (self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self.origin).manhattanLength() >= QApplication.startDragDistance()):
            origin, self.origin = self.origin, None
            start_project_drag(self, self, origin)
        else:
            super().mouseMoveEvent(event)

    def accepts_source(self, source):
        return isinstance(source, ProjectTile) and source.owner is self.owner

    def dragEnterEvent(self, event):
        if self.accepts_source(event.source()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)
        if self.grid and event.isAccepted():
            self.grid.preview(self.mapTo(self.grid, event.position().toPoint()))

    def dropEvent(self, event):
        if not self.accepts_source(event.source()):
            return
        if self.grid:
            self.grid.preview(self.mapTo(self.grid, event.position().toPoint()))
            self.grid.commit()
            event.acceptProposedAction()
            return
        source = event.source().identifier
        after = event.position().y() > self.height() / 2
        event.acceptProposedAction()
        # Rebuild only after the native drag operation has unwound.
        QTimer.singleShot(0, lambda: self.owner.move_project(source, self.identifier, after))


class ProjectGrid(QWidget):
    """A responsive grid with a real tile drag image and a live insertion slot."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.tiles = []
        self.drag_id = None
        self.preview_ids = []
        self.columns = 1
        self.cell_size = 280
        self.cell_height = 280
        self._geometry_key = None
        self._layout_key = None
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(150)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(1.0)
        self.motion.valueChanged.connect(self._advance_tiles)
        self._moving = []
        self.setObjectName("projectGrid")
        dark = owner.repository.get_setting("theme", "light") == "dark"
        self.setStyleSheet("QWidget#projectGrid {background:" + ("#141c27" if dark else "#f2f5f9") + ";}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.placeholder = QLabel(owner.tr("Отпустить здесь", "Drop here"), self)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(
            "background:" + ("#243347" if dark else "#e3eaf4")
            + "; color:" + ("#b9c8e8" if dark else "#4b6286")
            + "; border: 2px dashed #7395c9; border-radius: 12px;"
        )
        self.placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.placeholder.hide()
        self.setAcceptDrops(True)
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setInterval(40)
        self.scroll_timer.timeout.connect(self.scroll_at_edge)

    def minimumSizeHint(self):
        # The previous column count must not prevent shrinking the parent window.
        return QSize(260, self.minimumHeight())

    def add_tile(self, tile):
        tile.grid = self
        tile.setParent(self)
        self.tiles.append(tile)
        tile.hide()

    def arrange(self, animate=False):
        # Only this component owns tile positions: no layout moves animated widgets.
        ids = self.preview_ids if self.drag_id is not None else [t.identifier for t in self.tiles]
        geometry_key = (self.width(), len(self.tiles))
        if self._geometry_key != geometry_key:
            self.columns = max(1, self.width() // 300)
            self.cell_size = max(260, (self.width() - 12 * (self.columns - 1)) // self.columns)
            self.cell_height = max([210] + [max(t.minimumSizeHint().height(),
                t.layout().heightForWidth(self.cell_size)) for t in self.tiles])
            self._geometry_key = geometry_key
        layout_key = (geometry_key, tuple(ids), self.drag_id)
        if self._layout_key == layout_key:
            return
        self._layout_key = layout_key
        self.motion.stop()
        self._moving = []
        old_positions = {tile: tile.pos() for tile in self.tiles if not tile.isHidden()}
        self.setUpdatesEnabled(False)
        lookup = {t.identifier: t for t in self.tiles}
        for index, identifier in enumerate(ids):
            tile = lookup[identifier]
            widget = self.placeholder if identifier == self.drag_id else tile
            tile.setVisible(identifier != self.drag_id)
            widget.resize(self.cell_size, self.cell_height)
            destination = QPoint(index % self.columns * (self.cell_size + 12),
                                 index // self.columns * (self.cell_height + 12))
            previous = old_positions.get(tile)
            if (animate and widget is tile and previous is not None and previous != destination
                    and self.isVisible() and not tile.visibleRegion().isEmpty()):
                self._moving.append((tile, previous, destination))
            else:
                widget.move(destination)
            widget.show()
        self.placeholder.setVisible(self.drag_id is not None)
        self.placeholder.raise_()
        rows = (len(ids) + self.columns - 1) // self.columns
        self.setMinimumHeight(max(0, rows * (self.cell_height + 12) - 12))
        if self._moving:
            self.motion.start()
        self.setUpdatesEnabled(True)

    def _advance_tiles(self, fraction):
        for tile, start, end in self._moving:
            tile.move(QPoint(round(start.x() + (end.x() - start.x()) * fraction),
                             round(start.y() + (end.y() - start.y()) * fraction)))

    def resizeEvent(self, event):
        if event.size().width() != event.oldSize().width():
            self.arrange()
        super().resizeEvent(event)

    def begin(self, identifier):
        self.drag_id = identifier
        self.preview_ids = [tile.identifier for tile in self.tiles]
        self.arrange()
        self.scroll_timer.start()

    def scroll_at_edge(self):
        parent = self.parentWidget()
        while parent and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is None:
            return
        point = parent.viewport().mapFromGlobal(QCursor.pos())
        if not parent.viewport().rect().contains(point):
            return
        delta = -18 if point.y() < 48 else 18 if point.y() > parent.viewport().height() - 48 else 0
        if delta:
            bar = parent.verticalScrollBar()
            bar.setValue(bar.value() + delta)
            self.preview(self.mapFromGlobal(QCursor.pos()))

    def preview(self, point):
        if self.drag_id is None:
            return
        height = self.cell_height + 12
        slot = max(0, min(len(self.tiles) - 1,
                         max(0, point.y()) // height * self.columns
                         + min(self.columns - 1, max(0, point.x()) // (self.cell_size + 12))))
        ids = [identifier for identifier in self.preview_ids if identifier != self.drag_id]
        ids.insert(slot, self.drag_id)
        if ids != self.preview_ids:
            self.preview_ids = ids
            self.arrange(animate=True)

    def dragEnterEvent(self, event):
        tile = event.source()
        if isinstance(tile, ProjectTile) and tile.grid is self:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)
        if event.isAccepted():
            self.preview(event.position().toPoint())

    def dropEvent(self, event):
        self.dragEnterEvent(event)
        if event.isAccepted():
            self.preview(event.position().toPoint())
            self.commit()

    def commit(self):
        if self.drag_id is None:
            return
        identifiers = self.preview_ids[:]
        self.owner.repository.reorder_work_projects(identifiers)
        lookup = {tile.identifier: tile for tile in self.tiles}
        self.tiles = [lookup[identifier] for identifier in identifiers]
        self.owner.projects = {
            identifier: {**self.owner.projects[identifier], "sort_order": index}
            for index, identifier in enumerate(identifiers)
        }
        self.owner._project_signature = self.owner.project_signature()
        self.cancel()
        QTimer.singleShot(0, self.owner.changed.emit)

    def cancel(self):
        if self.drag_id is None:
            return
        self.scroll_timer.stop()
        self.drag_id = None
        self.preview_ids = []
        self.arrange(animate=True)

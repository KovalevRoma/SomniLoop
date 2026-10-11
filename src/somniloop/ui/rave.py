"""A bounded, click-through celebration with one audio player and no strobing."""

import logging
import math
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from somniloop.ui.rave_motion import cat_pose, light_motes, projected_scale

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "rave"
logger = logging.getLogger(__name__)


class RaveOverlay(QWidget):
    activeChanged = Signal(bool)

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cat = QPixmap(str(ASSETS / "cat.png"))
        if not self.cat.isNull():
            self.cat = self.cat.scaledToHeight(720, Qt.TransformationMode.SmoothTransformation)
        self.glows = self._create_glows()
        self._light_cache = QPixmap()
        self._light_stamp = -1
        self._light_logical_size = QSize()
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.65)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.durationChanged.connect(self._ready, Qt.ConnectionType.QueuedConnection)
        self.player.errorOccurred.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        self.clock = QElapsedTimer()
        self._audio_position = 0
        self._position_seen_at = 0
        self.fraction = 0.0
        self.duration_ms = 0
        self.pending = False
        self.active = False
        self.disposed = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._frame)
        self.load_timeout = QTimer(self)
        self.load_timeout.setSingleShot(True)
        self.load_timeout.setInterval(10000)
        self.load_timeout.timeout.connect(self.stop)
        self.controls = QWidget(host)
        layout = QHBoxLayout(self.controls)
        layout.setContentsMargins(8, 4, 8, 4)
        ru = QApplication.instance().property("language") != "en"
        mute = QPushButton("Без звука · Esc" if ru else "Mute · Esc")
        stop = QPushButton("Закончить рейв" if ru else "End celebration")
        mute.clicked.connect(self.mute)
        stop.clicked.connect(self.stop)
        layout.addWidget(mute)
        layout.addWidget(stop)
        self.controls.hide()
        self.hide()
        QApplication.instance().installEventFilter(self)

    @staticmethod
    def _create_glows():
        sprites = []
        for hue in range(8):
            sprite = QPixmap(96, 96)
            sprite.fill(Qt.GlobalColor.transparent)
            painter = QPainter(sprite)
            gradient = QRadialGradient(48, 48, 48)
            gradient.setColorAt(0, QColor(255, 255, 255))
            gradient.setColorAt(0.08, QColor(255, 255, 255, 250))
            gradient.setColorAt(0.22, QColor.fromHsvF(hue / 8, 0.65, 1, 0.95))
            gradient.setColorAt(0.5, QColor.fromHsvF(hue / 8, 0.95, 1, 0.55))
            gradient.setColorAt(1, QColor.fromHsvF(hue / 8, 0.9, 1, 0))
            painter.fillRect(sprite.rect(), gradient)
            painter.end()
            sprites.append(sprite)
        return sprites

    def start(self, fraction=1.0):
        if self.disposed or self.cat.isNull() or not (ASSETS / "track.mp3").is_file():
            logger.warning("Celebration assets are unavailable")
            return
        self.audio.setMuted(False)
        self.timer.stop()
        self.load_timeout.stop()
        self.fraction = min(1.0, max(0.0, fraction))
        if not self.fraction:
            self.stop()
            return
        self.pending = True
        self.load_timeout.start()
        if self.player.source().isEmpty():
            self.player.setSource(QUrl.fromLocalFile(str(ASSETS / "track.mp3")))
        self._ready(self.player.duration())

    def _ready(self, duration):
        if not self.pending or duration <= 0:
            return
        self.pending = False
        self.load_timeout.stop()
        self.duration_ms = max(1, round(duration * self.fraction))
        self.setGeometry(self.host.rect())
        self.clock.start()
        self._audio_position = 0
        self._position_seen_at = 0
        self.player.setPosition(0)
        self._light_stamp = -1
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
        self.show()
        self.raise_()
        self.controls.adjustSize()
        self.controls.move(12, max(0, self.host.height() - self.controls.height() - 12))
        self.controls.show()
        self.controls.raise_()
        self.timer.start()
        self.active = True
        self.activeChanged.emit(True)

    def mute(self):
        self.audio.setMuted(True)

    def stop(self):
        was_active = self.active
        self.active = False
        self.pending = False
        self.load_timeout.stop()
        self.timer.stop()
        self.player.stop()
        self.hide()
        self.controls.hide()
        self._light_cache = QPixmap()
        self._light_stamp = -1
        if was_active:
            self.activeChanged.emit(False)

    def dispose(self):
        self.stop()
        self.disposed = True
        QApplication.instance().removeEventFilter(self)
        self.player.setSource(QUrl())
        self.controls.deleteLater()

    def _failed(self, error, message):
        logger.warning("Celebration audio unavailable: %s", message)
        self.stop()

    def _frame(self):
        if (self.playback_ms() >= self.duration_ms
                or self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia):
            self.stop()
        elif not self.host.isMinimized():
            self.update()

    def playback_ms(self):
        position = self.player.position()
        now = self.clock.elapsed()
        if position != self._audio_position:
            self._audio_position = position
            self._position_seen_at = now
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        stalled = self.player.mediaStatus() == QMediaPlayer.MediaStatus.StalledMedia
        # Bridge Qt's position notifications, but never run ahead during a stall.
        extra = min(60, max(0, now - self._position_seen_at)) if playing and not stalled else 0
        return position + extra

    def eventFilter(self, watched, event):
        if watched is self.host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
            self.controls.move(12, max(0, self.host.height() - self.controls.height() - 12))
        if (self.timer.isActive() or self.pending) and event.type() in (
            QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress,
        ) and event.key() == Qt.Key.Key_Escape:
            if isinstance(watched, QWidget) and watched.window() is self.host:
                if event.type() == QEvent.Type.KeyPress:
                    self.mute()
                event.accept()
                return True
        return False

    def _lighting_frame(self, seconds):
        factor = min(1, 768 / max(1, self.width()), 432 / max(1, self.height()))
        size = QSize(max(1, round(self.width() * factor)),
                     max(1, round(self.height() * factor)))
        stamp = int(seconds * 20)
        if self._light_cache.size() != size or self._light_logical_size != self.size():
            self._light_cache = QPixmap(size)
            self._light_stamp = -1
            self._light_logical_size = self.size()
        if stamp != self._light_stamp:
            self._light_cache.fill(Qt.GlobalColor.transparent)
            painter = QPainter(self._light_cache)
            painter.scale(factor, factor)
            self._paint_lighting(painter, seconds, self.width(), self.height())
            painter.end()
            self._light_stamp = stamp
        return self._light_cache

    def _paint_lighting(self, painter, t, w, h):
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.fillRect(QRectF(0, 0, w, h), QColor(12, 8, 35, 205))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        # Constant-opacity beams move continuously; brightness never strobes.
        for i in range(16):
            hue = (i / 16 + t * 0.035) % 1
            color = QColor.fromHsvF(hue, 0.95, 1.0, 0.32)
            painter.setBrush(color)
            origin = QPointF(w * (i % 2), h)
            x = w * (0.5 + 0.7 * math.sin(t * 0.65 + i * 1.7))
            painter.drawPolygon(QPolygonF([origin, QPointF(x - w * 0.09, 0),
                                           QPointF(x + w * 0.09, 0)]))
            painter.setBrush(QColor.fromHsvF(hue, 0.65, 1, 0.85))
            painter.drawPolygon(QPolygonF([origin, QPointF(x - w * 0.006, 0),
                                           QPointF(x + w * 0.006, 0)]))
            painter.setBrush(QColor(235, 250, 255, 220))
            painter.drawPolygon(QPolygonF([origin, QPointF(x - w * 0.001, 0),
                                           QPointF(x + w * 0.001, 0)]))
        for i in range(180):
            x = ((i * 0.618 + t * (0.022 + i % 4 * 0.008)) % 1) * w
            y = ((i * 0.383 - t * (0.06 + i % 3 * 0.015)) % 1) * h
            painter.setBrush(QColor.fromHsvF((i / 180 + t * 0.03) % 1, 0.65, 1, 0.7))
            painter.drawEllipse(QPointF(x, y), 2 + i % 4, 2 + i % 4)
        for gx, gy, color, radius, opacity in light_motes(t):
            radius *= 1.8
            painter.setOpacity(min(1, opacity * 2))
            painter.drawPixmap(QRectF(gx * w - radius, gy * h - radius,
                                     radius * 2, radius * 2),
                               self.glows[color], QRectF(0, 0, 96, 96))

    def paintEvent(self, event):
        if not self.clock.isValid() or not self.timer.isActive():
            return
        position = self.playback_ms()
        t = position / 1000
        remaining = (self.duration_ms - position) / 1000
        fade = min(1.0, t / 0.45, max(0.0, remaining / 0.45))
        w, h = self.width(), self.height()
        lighting = self._lighting_frame(t)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setOpacity(fade)
        painter.drawPixmap(self.rect(), lighting)
        pose = cat_pose(t)
        size = min(w, h) * 0.43
        radius = size * 0.72
        x = w / 2 + max(0, w / 2 - radius) * pose.x
        y = h / 2 + max(0, h / 2 - radius) * pose.y
        painter.translate(x, y)
        painter.setOpacity(fade * pose.opacity)
        painter.rotate(pose.angle)
        painter.scale(pose.scale, pose.scale)
        depth_x, depth_y = projected_scale(pose)
        painter.scale(depth_x, depth_y)
        painter.shear(0.12 * math.sin(math.radians(pose.yaw)), 0)
        ratio = self.cat.width() / self.cat.height()
        painter.drawPixmap(QRectF(-size * ratio / 2, -size / 2, size * ratio, size),
                           self.cat, QRectF(self.cat.rect()))

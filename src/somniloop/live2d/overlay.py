"""Transparent, bounded Live2D widget and its public animation controller."""

import logging
import math
import random
import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBitmap, QCursor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from .interaction import PART_IDS, StrokeGesture, TouchState, hit_zone
from .reactions import LocalSpeech, ReactionController
from .renderer import NativeRenderer, render_size
from .resources import CharacterConfig, ModelResources, epsilon_manifest
from .status import EmotionBadge

logger = logging.getLogger(__name__)


class Live2DOverlay(QWidget):
    loaded = Signal()
    failed = Signal(str)

    def __init__(self, host, config: CharacterConfig):
        super().__init__(host)
        self.host, self.config = host, config
        self.renderer = self.resources = None
        self.error = ""
        self.disposed = False
        self.requested_visible = config.enabled
        self.image = QImage()
        self.last_frame = time.monotonic()
        self.last_effect = self.last_frame
        self.next_motion = self.last_frame + random.uniform(20, 40)
        self.frames = 0
        self.reaction_started = 0.0
        self.reaction_strength = 0.0
        self.effect_duration = 5.0
        self.touch = TouchState()
        self.gesture = StrokeGesture()
        self.touch_priority_until = 0.0
        self.status = EmotionBadge(host)
        self.reactions = ReactionController(self)
        self.reactions.requested.connect(self._react)
        self.speech = LocalSpeech(self)
        self.speech.failed.connect(self._voice_failed)
        self.caption = QLabel(host)
        self.caption.setWordWrap(True)
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption.setStyleSheet(
            "QLabel { background: #eee7ff; color: #29223e; border: 1px solid #a493d6;"
            "border-radius: 14px; padding: 10px; font-size: 14px; }"
        )
        self.caption.hide()
        self.caption_timer = QTimer(self)
        self.caption_timer.setSingleShot(True)
        self.caption_timer.timeout.connect(self.caption.hide)
        self.setObjectName("live2dOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not config.interaction)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._frame)
        # This cheap state check also keeps the character below modal dialogs.
        self.visibility_timer = QTimer(self)
        self.visibility_timer.setInterval(200)
        self.visibility_timer.timeout.connect(self._sync)
        self.visibility_timer.start()
        self.host.installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.dispose)
        QWidget.setVisible(self, False)
        QTimer.singleShot(0, self._sync)

    @property
    def motions(self):
        return self.resources.motions if self.resources else {}

    @property
    def expressions(self):
        return tuple(self.resources.expressions) if self.resources else ()

    def _initialize(self):
        if QApplication.platformName() in ("offscreen", "minimal"):
            raise RuntimeError("Live2D needs an OpenGL-capable Qt platform (Wayland or X11)")
        self.resources = ModelResources(epsilon_manifest())
        self.renderer = NativeRenderer(self.resources)
        self.destroyed.connect(lambda _obj=None, renderer=self.renderer: renderer.close())
        self.renderer.lib.sl_idle(self.renderer.handle, int(self.config.idle))
        self.loaded.emit()
        # Epsilon has no group called Greeting: use an actual Tap clip as the welcome.
        if "Tap" in self.motions:
            self.playMotion("Tap", 0)
        happy = self.resources.expression_named("Smile")
        if happy:
            self.setExpression(happy)

    def _sync(self):
        if self.disposed:
            return
        visible = (
            self.requested_visible
            and not self.error
            and self.host.isVisible()
            and not self.host.isMinimized()
            and not getattr(self.host, "_modal_overlays", [])
        )
        if visible and self.renderer is None:
            try:
                self._initialize()
            except Exception as error:
                self._fail(error)
                return
        if visible:
            self._arrange()
            QWidget.setVisible(self, True)
            self.raise_()
            self.status.show()
            self.status.raise_()
            if not self.timer.isActive():
                self.last_frame = time.monotonic()
                self.timer.start()
        else:
            self.timer.stop()
            self.reactions.cancel()
            self.caption.hide()
            self.status.hide()
            self.gesture.cancel()
            self.speech.stop()
            QWidget.setVisible(self, False)

    def _arrange(self):
        footer = self.status.height() + 6
        height = max(1, min(round(340 * self.config.scale), int(self.host.height() * 0.62),
                            self.host.height() - footer))
        width = max(1, min(round(height * 0.72), int(self.host.width() * 0.4)))
        x = max(0, min(self.host.width() - width, self.host.width() - width - self.config.offset_x))
        y = max(
            0, min(self.host.height() - height - footer,
                   self.host.height() - height - footer - self.config.offset_y)
        )
        self.setGeometry(x, y, width, height)
        badge_width = min(max(160, width), max(1, self.host.width() - 16))
        self.status.setGeometry(
            max(0, min(round(x + (width - badge_width) / 2), self.host.width() - badge_width)),
            min(y + height + 6, max(0, self.host.height() - self.status.height())),
            badge_width, self.status.height(),
        )
        self.caption.setFixedWidth(min(260, max(1, self.host.width() - 24)))
        self.caption.adjustSize()
        self.caption.move(
            max(0, min(x, self.host.width() - self.caption.width())),
            max(0, y - self.caption.height() - 8),
        )
        if self.caption.isVisible():
            self.caption.raise_()

    def _frame(self):
        if self.disposed or not self.renderer:
            return
        if (
            getattr(self.host, "_modal_overlays", [])
            or not self.host.isVisible()
            or self.host.isMinimized()
        ):
            self._sync()
            return
        now = time.monotonic()
        try:
            elapsed = now - self.reaction_started
            if 0 <= elapsed < 1.4:
                self.lookAt(0, self.reaction_strength * math.sin(elapsed / 1.4 * math.tau))
            elif self.config.interaction:
                point = self.host.mapFromGlobal(QCursor.pos())
                self.lookAt(
                    point.x() / max(1, self.host.width()) * 2 - 1,
                    1 - point.y() / max(1, self.host.height()) * 2,
                )
            elif self.reaction_started:
                self.lookAt(0, 0)
                self.reaction_started = 0.0
            if self.config.idle and now >= self.next_motion:
                if "Idle" in self.motions:
                    self.playRandomMotion("Idle")
                self.next_motion = now + random.uniform(20, 40)
            if self.last_effect and now - self.last_effect > self.effect_duration:
                self.resetExpression()
                self.last_effect = 0
            size = render_size(self.width(), self.height(), self.devicePixelRatioF())
            self.image = self.renderer.frame(size, now - self.last_frame, self.config.opacity)
            self.last_frame = now
            self.frames += 1
            if self.config.interaction and self.frames % 3 == 1:
                self._update_hit_mask()
            self.update()
        except Exception as error:
            self._fail(error)

    def _update_hit_mask(self):
        # Only the character silhouette takes input. Empty corners remain click-through.
        logical = self.image.scaled(self.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        region = QRegion(QBitmap.fromImage(logical.createAlphaMask(
            Qt.ImageConversionFlag.ThresholdDither | Qt.ImageConversionFlag.AvoidDither
        )))
        # Pad the hit region so its binary boundary cannot cut antialiased edges.
        padded = QRegion(region)
        for dx in (-2, 0, 2):
            for dy in (-2, 0, 2):
                padded |= region.translated(dx, dy)
        self.setMask(padded)

    def paintEvent(self, event):
        if not self.image.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.rect(), self.image)

    def eventFilter(self, watched, event):
        if watched is self.host and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.WindowStateChange,
        ):
            QTimer.singleShot(0, self._sync)
        return False

    def mousePressEvent(self, event):
        if self.config.interaction and event.button() == Qt.MouseButton.LeftButton:
            point = event.position()
            self.gesture.begin(self._zone_at(point), point.x(), point.y())
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self.config.interaction and event.buttons() & Qt.MouseButton.LeftButton:
            point = event.position()
            self.gesture.move(self._zone_at(point), point.x(), point.y())
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if self.config.interaction and event.button() == Qt.MouseButton.LeftButton:
            point = event.position()
            zone, stroke = self.gesture.finish(
                self._zone_at(point), point.x(), point.y(), max(12, self.width() * 0.06)
            )
            self._touch_reaction(zone, stroke)
            event.accept()
        else:
            self.gesture.cancel()
            event.ignore()

    def _zone_at(self, point):
        if not self.renderer or self.image.isNull() or not self.rect().contains(point.toPoint()):
            return None
        x, y = point.x() / max(1, self.width()), point.y() / max(1, self.height())
        px = min(self.image.width() - 1, max(0, int(x * self.image.width())))
        py = min(self.image.height() - 1, max(0, int(y * self.image.height())))
        if self.image.pixelColor(px, py).alpha() < 10:
            return None
        parts = {
            zone: self.renderer.part_bounds(part, self.width(), self.height())
            for zone, part in PART_IDS.items()
        }
        return hit_zone(x, y, parts)

    def _touch_reaction(self, zone, stroke):
        if not self.renderer or not self.config.interaction:
            return
        emotion = self.touch.react(zone, stroke, time.monotonic())
        if emotion is None:
            return
        self.reactions.cancel()
        self.caption.hide()
        self.speech.stop()
        self.touch_priority_until = time.monotonic() + 5
        expression = self.resources.expression_named(emotion)
        if expression:
            try:
                self.setExpression(expression)
            except Exception as error:
                logger.warning("Touch reaction skipped: %s", error)

    def taskCompleted(self, all_done=False):
        if self.config.reactions and self.isVisible() and not self.disposed:
            self.reactions.submit(all_done)

    def _react(self, all_done):
        if (not self.renderer or not self.isVisible()
                or getattr(self.host, "_modal_overlays", [])
                or time.monotonic() < self.touch_priority_until):
            return
        try:
            # Use a verified positive expression, not a guessed gesture from a Tap filename.
            happy = self.resources.expression_named("Smile")
            if happy:
                self.setExpression(happy)
                self.effect_duration = 6.0 if all_done else 3.0
            self.reaction_started = time.monotonic()
            self.reaction_strength = 0.35 if all_done else 0.18
            ru = getattr(getattr(self.host, "i18n", None), "language", "en") == "ru"
            text = (
                ("На сегодня всё выполнено. Можно отдохнуть!" if ru else "All done for today. Time for a break!")
                if all_done else
                ("Ещё один шаг сделан. Здорово!" if ru else "Another step done. Nice work!")
            )
            if self.config.captions:
                self.caption.setText(text)
                self._arrange()
                self.caption.show()
                self.caption.raise_()
                self.caption_timer.start(5500)
            if self.config.voice:
                self.speech.say(text, "ru" if ru else "en")
        except Exception as error:
            logger.warning("Character reaction skipped: %s", error)

    def _voice_failed(self, message):
        QApplication.instance().setProperty("live2dVoiceError", message)

    def playMotion(self, group, index):
        if not self.renderer:
            return False
        if group not in self.motions or not 0 <= index < len(self.motions[group]):
            raise ValueError(f"Unknown motion: {group}/{index}")
        self.renderer.check(
            self.renderer.lib.sl_motion(self.renderer.handle, group.encode(), index)
        )
        return True

    def playRandomMotion(self, group):
        if group not in self.motions or not self.motions[group]:
            return False
        return self.playMotion(group, random.randrange(len(self.motions[group])))

    def setExpression(self, name):
        if not self.renderer:
            return False
        if name not in self.expressions:
            raise ValueError(f"Unknown expression: {name}")
        self.renderer.check(self.renderer.lib.sl_expression(self.renderer.handle, name.encode()))
        self.last_effect = time.monotonic()
        self.effect_duration = 5.0
        self.touch.emotion = name.removesuffix(".exp3.json")
        self.status.set_emotion(self.touch.emotion)
        return True

    def resetExpression(self):
        if self.renderer:
            self.renderer.check(self.renderer.lib.sl_expression(self.renderer.handle, b""))
        self.touch.emotion = "Normal"
        self.status.set_emotion("Normal")

    def lookAt(self, x, y):
        if self.renderer:
            self.renderer.lib.sl_look(self.renderer.handle, max(-1, min(1, x)), max(-1, min(1, y)))

    def setParameter(self, identifier, value):
        if self.renderer:
            self.renderer.check(
                self.renderer.lib.sl_parameter(
                    self.renderer.handle, identifier.encode(), float(value)
                )
            )

    def startIdle(self):
        self.config.idle = True
        if self.renderer:
            self.renderer.lib.sl_idle(self.renderer.handle, 1)

    def stopIdle(self):
        self.config.idle = False
        if self.renderer:
            self.renderer.lib.sl_idle(self.renderer.handle, 0)

    def setVisible(self, visible):
        self.requested_visible = bool(visible)
        self._sync()

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def _fail(self, error):
        self.error = str(error)
        QApplication.instance().setProperty("live2dError", self.error)
        logger.warning("Live2D disabled: %s", self.error)
        self.timer.stop()
        self.reactions.cancel()
        self.caption.hide()
        self.status.hide()
        self.speech.stop()
        QWidget.setVisible(self, False)
        if self.renderer:
            self.renderer.close()
            self.renderer = None
        self.failed.emit(self.error)

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        self.timer.stop()
        self.visibility_timer.stop()
        self.reactions.cancel()
        self.caption_timer.stop()
        self.caption.hide()
        self.caption.deleteLater()
        self.status.hide()
        self.status.deleteLater()
        self.gesture.cancel()
        self.speech.stop()
        self.host.removeEventFilter(self)
        QWidget.setVisible(self, False)
        if self.renderer:
            self.renderer.close()
            self.renderer = None
        self.image = QImage()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)


Live2DCharacter = Live2DOverlay

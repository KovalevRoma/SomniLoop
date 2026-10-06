"""Transparent, bounded Live2D widget and its public animation controller."""

import json
import logging
import math
import random
import time

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBitmap, QCursor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from .interaction import PART_IDS, TapGesture, TouchState, hit_zone
from .motion_preview import MotionPreviewPanel
from .reactions import LocalSpeech, ReactionController
from .renderer import NativeRenderer, render_size
from .resources import CharacterConfig, ModelResources, epsilon_manifest
from .smoothing import SmoothGaze
from .status import EmotionBadge

logger = logging.getLogger(__name__)

# Temporary review UI: disable this flag to remove the panel and restore placement.
SHOW_MOTION_PREVIEW = False


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
        self.next_motion = self.last_frame + random.uniform(6, 10)
        self.motion_remaining = 0.0
        self.motion_priority = 0
        self.motion_durations = {}
        self.pending_activity = None
        self.hover_zone = None
        self.hover_position = None
        self.last_hover = 0.0
        self.frames = 0
        self.reaction_started = 0.0
        self.reaction_strength = 0.0
        self.effect_duration = 5.0
        self.touch = TouchState()
        self.gesture = TapGesture()
        self.gaze = SmoothGaze()
        self.touch_priority_until = 0.0
        self.status = EmotionBadge(host)
        self.motion_panel = None
        self.preview_remaining = 0.0
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
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
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
        if SHOW_MOTION_PREVIEW:
            language = getattr(getattr(self.host, "i18n", None), "language", "en")
            self.motion_panel = MotionPreviewPanel(self.host, self.motions, language)
            self.motion_panel.requested.connect(self.previewMotion)
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
            if self.motion_panel:
                self.motion_panel.show()
                self.motion_panel.raise_()
            if not self.timer.isActive():
                self.last_frame = time.monotonic()
                self.timer.start()
        else:
            self.timer.stop()
            self.reactions.cancel()
            self.caption.hide()
            self.status.hide()
            if self.motion_panel:
                self.motion_panel.hide()
            self.gesture.cancel()
            self.speech.stop()
            QWidget.setVisible(self, False)

    def _arrange(self):
        footer = self.status.height() + 6
        height = max(1, min(round(340 * self.config.scale), int(self.host.height() * 0.62),
                            self.host.height() - footer))
        width = max(1, min(round(height * 0.72), int(self.host.width() * 0.4)))
        panel_width = min(144, max(1, self.host.width() // 3)) if self.motion_panel else 0
        panel_space = panel_width + 12 if self.motion_panel else 0
        x = max(0, min(self.host.width() - width - panel_space,
                       self.host.width() - width - panel_space - self.config.offset_x))
        y = max(
            0, min(self.host.height() - height - footer,
                   self.host.height() - height - footer - self.config.offset_y)
        )
        self.setGeometry(x, y, width, height)
        if self.motion_panel:
            panel_height = min(self.motion_panel.preferred_height, max(1, self.host.height() - 24))
            self.motion_panel.setGeometry(
                min(x + width + 12, self.host.width() - panel_width),
                max(12, min(y + height + footer - panel_height,
                            self.host.height() - panel_height - 12)),
                panel_width, panel_height,
            )
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
            self.motion_remaining = max(0, self.motion_remaining - min(.1, now - self.last_frame))
            if self.preview_remaining > 0:
                self.preview_remaining = max(0, self.preview_remaining - min(.1, now - self.last_frame))
                if self.preview_remaining == 0:
                    self.resetExpression()
                    if self.motion_panel:
                        self.motion_panel.set_active()
                    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                                      not self.config.interaction)
            elapsed = now - self.reaction_started
            if self.preview_remaining > 0:
                self.lookAt(0, 0)
            elif 0 <= elapsed < 1.4:
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
            self._process_activity(now)
            self._hover(now)
            if (self.config.idle and now >= self.next_motion and not self.preview_remaining
                    and not self.motion_remaining and now >= self.touch_priority_until):
                self._event_motion("Flick3", random.randrange(2), 1)
                self.next_motion = now + random.uniform(6, 10)
            if (not self.preview_remaining and self.last_effect
                    and now - self.last_effect > self.effect_duration):
                self.resetExpression()
                self.last_effect = 0
            size = render_size(self.width(), self.height(), self.devicePixelRatioF())
            x, y = self.gaze.advance(now - self.last_frame)
            self.renderer.lib.sl_look(self.renderer.handle, x, y)
            dpr = max(1.0, self.devicePixelRatioF())
            output_size = QSize(min(size.width(), max(1, round(self.width() * dpr))),
                                min(size.height(), max(1, round(self.height() * dpr))))
            self.image = self.renderer.frame(size, now - self.last_frame, self.config.opacity,
                                             output_size=output_size)
            self.last_frame = now
            self.frames += 1
            if self.config.interaction and not self.preview_remaining and self.frames % 6 == 1:
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
            zone = self.gesture.finish(self._zone_at(point), point.x(), point.y())
            self._touch_reaction(zone)
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

    def _touch_reaction(self, zone):
        if not self.renderer or not self.config.interaction or self.preview_remaining > 0:
            return
        emotion = self.touch.react(zone, time.monotonic())
        if emotion is None:
            return
        self.reactions.cancel()
        self.caption.hide()
        self.speech.stop()
        self.touch_priority_until = time.monotonic() + 5
        # Disgust is contextual UI state, not an expression shipped by Epsilon.
        expression = self.resources.expression_named("Angry" if emotion == "Disgust" else emotion)
        try:
            if self.touch.motion:
                self._event_motion(*self.touch.motion, 3)
            if expression:
                self.setExpression(expression)
            self._set_status(emotion)
        except Exception as error:
            logger.warning("Touch reaction skipped: %s", error)

    def _duration(self, group, index):
        key = (group, index)
        if key not in self.motion_durations:
            clip = self.motions[group][index]
            data = json.loads(self.resources.resolve(clip["File"]).read_text(encoding="utf-8-sig"))
            duration = float(data["Meta"]["Duration"])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("Invalid motion duration")
            self.motion_durations[key] = duration + .2
        return self.motion_durations[key]

    def _event_motion(self, group, index, priority):
        if self.preview_remaining or (self.motion_remaining and priority < self.motion_priority):
            return False
        if priority < 3 and self.reactions.pending.isActive():
            return False
        if (priority < 3 and self.reaction_started
                and time.monotonic() - self.reaction_started < self.effect_duration):
            return False
        duration = self._duration(group, index)
        self.resetExpression()
        self.reactions.cancel()
        self.reaction_started = 0.0
        self.playMotion(group, index)
        self.motion_remaining, self.motion_priority = duration, priority
        self._set_status("Normal", duration)
        return True

    def _set_status(self, emotion, duration=5.0):
        """Keep contextual feedback independent from the model's expression filenames."""
        self.touch.emotion = emotion
        self.status.set_emotion(emotion)
        self.last_effect = time.monotonic()
        self.effect_duration = duration

    def applicationEvent(self, event):
        if (self.config.reactions and not self.disposed and self.config.enabled
                and event in ("not_done", "created", "settings_saved", "archived")):
            # Coalesce bulk changes; never replay a backlog of stale notifications.
            self.pending_activity = (event, time.monotonic())

    def _process_activity(self, now):
        if not self.pending_activity:
            return
        event, started = self.pending_activity
        if now - started > 30 or not self.config.reactions:
            self.pending_activity = None
            return
        if self.preview_remaining or (self.motion_remaining and self.motion_priority >= 3):
            return
        motion = {
            "created": ("FlickUp", 0), "settings_saved": ("FlickUp", 0),
            "archived": ("FlickUp", 1),
        }.get(event)
        if event == "not_done":
            motion = random.choice((("Tap", 1), ("FlickDown", 0), ("FlickDown", 1)))
        if self._event_motion(*motion, 3):
            emotion = "Sad" if event == "not_done" else "Normal" if event == "archived" else "Smile"
            self._set_status(emotion, max(3, self.motion_remaining))
        self.pending_activity = None

    def _hover(self, now):
        if (not self.config.interaction or self.preview_remaining
                or QApplication.mouseButtons() != Qt.MouseButton.NoButton):
            return
        position = QCursor.pos()
        if position == self.hover_position:
            return
        self.hover_position = position
        zone = self._zone_at(QPointF(self.mapFromGlobal(position)))
        zone = "lower" if zone in ("hips", "legs") else zone
        entered = zone != self.hover_zone
        self.hover_zone = zone
        if (not entered or now - self.last_hover < 2
                or now < self.touch_priority_until):
            return
        motion = {"head": ("FlickUp", 0), "chest": ("Flick", 0), "lower": ("Shake", 0)}.get(zone)
        if motion and self._event_motion(*motion, 2):
            self.last_hover = now
            self._set_status("Smile" if zone == "head" else "Surprised",
                             max(3, self.motion_remaining))

    def taskCompleted(self, all_done=False):
        if self.config.reactions and self.isVisible() and not self.disposed:
            self.reactions.submit(all_done)

    def _react(self, all_done):
        if (not self.renderer or not self.isVisible()
                or getattr(self.host, "_modal_overlays", [])
                or self.preview_remaining > 0
                or (self.motion_remaining > 0 and self.motion_priority >= 3)
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

    def previewMotion(self, group, index):
        if not self.renderer or self.disposed:
            return
        try:
            duration = self._duration(group, index)
            self.reactions.cancel()
            self.gesture.cancel()
            self.caption.hide()
            self.speech.stop()
            self.resetExpression()
            self.last_effect = self.reaction_started = 0.0
            self.lookAt(0, 0)
            self.playMotion(group, index)
            self.preview_remaining = duration
            self._set_status("Preview", duration)
            self.motion_remaining = 0.0
            # A stale silhouette must not clip a clip's larger arm/hair movements.
            self.clearMask()
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            if self.motion_panel:
                self.motion_panel.set_active((group, index))
        except Exception as error:
            logger.warning("Motion preview failed: %s", error)
            if self.motion_panel:
                self.motion_panel.set_active()
                self.motion_panel.setToolTip(str(error))

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
        emotion = name.removesuffix(".exp3.json")
        self._set_status(emotion if emotion in EmotionBadge.LABELS else "Normal")
        return True

    def resetExpression(self):
        if self.renderer:
            self.renderer.check(self.renderer.lib.sl_expression(self.renderer.handle, b""))
        self.touch.emotion = "Normal"
        self.status.set_emotion("Normal")

    def lookAt(self, x, y):
        self.gaze.aim(x, y)

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
        if self.motion_panel:
            self.motion_panel.hide()
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
        if self.motion_panel:
            self.motion_panel.hide()
            self.motion_panel.deleteLater()
            self.motion_panel = None
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

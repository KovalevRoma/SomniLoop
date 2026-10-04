"""Click-through, translucent hexagonal emotion badge drawn at the screen's DPI."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget


class EmotionBadge(QWidget):
    LABELS = {
        "Normal": ("Спокойна", "Relaxed", "#b4a5d6"),
        "Smile": ("Рада", "Happy", "#83cdb1"),
        "Surprised": ("Удивлена", "Surprised", "#e4c17d"),
        "Angry": ("Сердится", "Annoyed", "#df929b"),
        "Blushing": ("Смущена", "Blushing", "#d6a0c2"),
        "Sad": ("Грустит", "Sad", "#96b4d9"),
    }

    def __init__(self, host):
        super().__init__(host)
        self.emotion = "Normal"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(34)
        self.hide()
        self.set_emotion("Normal")

    def label(self):
        ru = getattr(getattr(self.parentWidget(), "i18n", None), "language", "en") == "ru"
        return self.LABELS.get(self.emotion, self.LABELS["Normal"])[0 if ru else 1]

    def set_emotion(self, emotion):
        self.emotion = emotion
        self.setAccessibleName(self.label())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        tip = min(17.0, rect.width() / 5)
        polygon = QPolygonF([
            QPointF(rect.left(), rect.center().y()),
            QPointF(rect.left() + tip, rect.top()),
            QPointF(rect.right() - tip, rect.top()),
            QPointF(rect.right(), rect.center().y()),
            QPointF(rect.right() - tip, rect.bottom()),
            QPointF(rect.left() + tip, rect.bottom()),
        ])
        accent = QColor(self.LABELS.get(self.emotion, self.LABELS["Normal"])[2])
        theme = QApplication.instance().property("somniloopTheme")
        dark = theme == "dark" if theme else self.palette().window().color().lightness() < 128
        base = QColor("#292438" if dark else "#f0e8df")
        base.setAlpha(210)
        tint = accent.darker(190) if dark else QColor(accent)
        tint.setAlpha(185)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, base)
        gradient.setColorAt(1, tint)
        painter.setBrush(gradient)
        painter.setPen(QPen(accent, 1))
        painter.drawPolygon(polygon)
        painter.setPen(QColor("#fff6f0" if dark else "#342c45"))
        font = self.font()
        font.setPointSizeF(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(tip + 4, 0, -tip - 4, 0),
                         Qt.AlignmentFlag.AlignCenter, self.label())

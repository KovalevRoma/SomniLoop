"""Bounded decoding for embedded document images."""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap


def image_preview(data):
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000:
        raise ValueError("Invalid image or image larger than 40 megapixels")
    reader.setAutoTransform(True)
    reader.setScaledSize(size.scaled(QSize(1600, 1200), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError("Image could not be decoded")
    return QPixmap.fromImage(image)

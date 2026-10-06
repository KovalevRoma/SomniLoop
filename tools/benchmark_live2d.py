"""Measure real Cubism rendering and Qt compositing without opening the user database."""

import argparse
import statistics
import time

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from somniloop.live2d.renderer import NativeRenderer
from somniloop.live2d.resources import ModelResources, epsilon_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=180)
    parser.add_argument("--gpu-downsample", action="store_true")
    args = parser.parse_args()
    app = QApplication([])
    renderer = NativeRenderer(ModelResources(epsilon_manifest()))
    try:
        for width, height in ((245, 340), (490, 680)):
            target = QSize(width, height)
            size = QSize(width * 2, height * 2)
            canvas = QImage(target, QImage.Format.Format_ARGB32_Premultiplied)
            timings = []
            for index in range(args.samples + 30):
                start = time.perf_counter()
                options = {"output_size": target} if args.gpu_downsample else {}
                frame = renderer.frame(size, 1 / 60, 1, **options)
                read = time.perf_counter()
                canvas.fill(0)
                painter = QPainter(canvas)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawImage(QRect(0, 0, width, height), frame)
                painter.end()
                end = time.perf_counter()
                if index >= 30:
                    timings.append(((read - start) * 1000, (end - read) * 1000,
                                    (end - start) * 1000))
            print(f"Render {size.width()}x{size.height()} -> display {width}x{height}")
            for column, name in enumerate(("render/readback", "Qt paint", "total")):
                values = sorted(row[column] for row in timings)
                print(f"  {name}: median {statistics.median(values):.3f} ms; "
                      f"p95 {values[int((len(values) - 1) * .95)]:.3f} ms")
    finally:
        renderer.close()
        app.quit()


if __name__ == "__main__":
    main()

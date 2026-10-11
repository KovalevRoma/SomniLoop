"""Measure raster celebration rendering without audio or a live database."""

import argparse
import json
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from somniloop.ui.rave import RaveOverlay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step-ms", type=int, default=33)
    args = parser.parse_args()
    app = QApplication([])
    host = QWidget()
    host.resize(1920, 1080)
    overlay = RaveOverlay(host)
    overlay.resize(host.size())
    overlay.clock.start()
    overlay.duration_ms = 44000
    overlay.timer.start()
    target = QImage(host.size(), QImage.Format.Format_ARGB32_Premultiplied)
    milliseconds = [12000]
    overlay.playback_ms = lambda: milliseconds[0]
    try:
        for _ in range(5):
            target.fill(Qt.GlobalColor.transparent)
            overlay.render(target)
        wall = time.perf_counter()
        cpu = time.process_time()
        for frame in range(120):
            milliseconds[0] = 12000 + frame * args.step_ms
            target.fill(Qt.GlobalColor.transparent)
            overlay.render(target)
        print(json.dumps({"frames": 120, "size": "1920x1080", "step_ms": args.step_ms,
                          "wall_ms_per_frame": (time.perf_counter() - wall) * 1000 / 120,
                          "cpu_ms_per_frame": (time.process_time() - cpu) * 1000 / 120}))
    finally:
        overlay.dispose()
        host.close()
        app.processEvents()


if __name__ == "__main__":
    main()

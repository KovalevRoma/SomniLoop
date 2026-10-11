"""Exercise celebrations in a real window using a disposable database."""

import argparse
import tempfile
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", action="store_true")
    args = parser.parse_args()
    app = QApplication([])
    output = Path(tempfile.mkdtemp(prefix="somniloop-rave-"))
    with tempfile.TemporaryDirectory() as directory:
        repo = Repository(Path(directory) / "smoke.db")
        repo.set_setting("live2d_config", '{"enabled":true}' if args.character else '{"enabled":false}')
        repo.set_setting("theme", "dark")
        task = repo.save_planner_task("Все дела на сегодня сделаны!", date.today())
        window = MainWindow(repo)
        window.show()
        try:
            QTest.qWait(300)
            repo.complete_planner_task(task)
            window.dashboard.refresh()
            QTest.qWait(1500)
            assert window.rave.timer.isActive()
            assert window.rave.player.isPlaying()
            if args.character:
                assert not window.character.error, window.character.error
                assert window.character.rave_active
                assert window.character.status.emotion == "Dancing"
                assert window.character.timer.interval() == 33
            print(f"Track duration: {window.rave.player.duration()} ms")
            window.grab().save(str(output / "intro.png"))
            QTest.keyClick(window, Qt.Key.Key_Escape)
            assert window.rave.audio.isMuted() and window.rave.timer.isActive()
            window.resize(1050, 720)
            QTest.qWait(12000)
            assert window.rave.size() == window.size()
            window.grab().save(str(output / "travel.png"))
            QTest.qWait(18000)
            assert window.rave.timer.isActive()
            assert window.rave.playback_ms() >= 29000
            window.grab().save(str(output / "outro.png"))
            if args.character:
                assert window.character.rave_active
                assert window.character.renderer.lib.sl_motion_group(
                    window.character.renderer.handle) == b"Shake"
            window.rave.stop()
            assert not window.character.rave_active
            if args.character:
                assert window.character.timer.interval() == 16
                assert window.character.status.emotion == "Normal"
        finally:
            window.close()
            assert not window.rave.timer.isActive()
            app.processEvents()
    print(output)


if __name__ == "__main__":
    main()

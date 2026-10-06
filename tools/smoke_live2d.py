"""Exercise the actual SomniLoop window and Cubism renderer on a temporary database.

Run with QT_QPA_PLATFORM=xcb under xvfb-run, or QT_QPA_PLATFORM=wayland on Ubuntu.
No production data, downloads or LLM calls are used.
"""

import argparse
import hashlib
import tempfile
import time
import traceback
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from somniloop.core.database import Repository
from somniloop.core.models import ScheduleType, TaskState, TrackerMode
from somniloop.live2d.interaction import TouchState
from somniloop.ui.main_window import MainWindow
from somniloop.ui.modal_overlay import ModalOverlay
from somniloop.ui.planner import PlannerDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(tempfile.mkdtemp(prefix="somniloop-live2d-"))
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    errors, checks = [], []
    with tempfile.TemporaryDirectory(prefix="somniloop-smoke-db-") as directory:
        repository = Repository(Path(directory) / "test.db")
        repository.set_setting("theme", "light")
        tracker_id = repository.create_tracker(
            "Тестовая привычка",
            "",
            TrackerMode.REGULAR,
            ScheduleType.DAILY,
            {},
            ["Первый пункт", "Второй пункт"],
        )
        window = MainWindow(repository)
        window.show()
        state = {}

        def step(action):
            try:
                action()
            except Exception as error:
                traceback.print_exc()
                errors.append(repr(error))
                finish()

        def initial():
            character = window.character
            assert not character.error, character.error
            assert character.frames > 10
            image = character.image
            transparent = sum(
                image.pixelColor(x, y).alpha() == 0
                for x in range(0, image.width(), 8)
                for y in range(0, image.height(), 8)
            )
            opaque = sum(
                image.pixelColor(x, y).alpha() > 200
                for x in range(0, image.width(), 8)
                for y in range(0, image.height(), 8)
            )
            assert transparent > 20 and opaque > 20
            state["hash"] = hashlib.sha256(bytes(image.constBits())).hexdigest()
            image.save(str(args.output / "epsilon-initial.png"))
            window.grab().save(str(args.output / "somniloop-epsilon.png"))
            assert character.geometry().right() < window.width()
            assert character.geometry().bottom() < window.height()
            probe = QPushButton("Click-through probe", window)
            probe.setGeometry(character.geometry())
            probe.clicked.connect(lambda: checks.append("click-through"))
            probe.show()
            character.raise_()
            QTest.mouseClick(
                window.windowHandle(), Qt.MouseButton.LeftButton, pos=probe.geometry().center()
            )
            assert "click-through" in checks
            probe.hide()
            probe.deleteLater()
            character.playMotion("Tap", 0)
            character.setExpression(character.resources.expression_named("Smile"))
            character.lookAt(0.7, 0.3)
            state["breath"] = character.renderer.parameter("PARAM_BREATH")
            checks.extend(["rendering", "transparency", "manifest-resources"])
            QTimer.singleShot(1700, lambda: step(animated))

        def animated():
            character = window.character
            assert not character.error, character.error
            assert hashlib.sha256(bytes(character.image.constBits())).hexdigest() != state["hash"]
            assert character.renderer.parameter("PARAM_BREATH") != state["breath"]
            character.image.save(str(args.output / "epsilon-smile.png"))
            character.setExpression(character.resources.expression_named("Blushing"))
            character.setParameter("PARAM_ANGLE_Z", 5)
            character.config.interaction = True
            character.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            window.resize(980, 680)
            checks.extend(["motion", "expression", "breathing", "parameter-control"])
            QTimer.singleShot(1000, lambda: step(resized))

        def resized():
            character = window.character
            assert window.rect().contains(character.geometry())
            assert not character.mask().isEmpty()
            character.image.save(str(args.output / "epsilon-blushing.png"))
            window.grab().save(str(args.output / "somniloop-resized.png"))
            state["dialog"] = PlannerDialog(repository, window.i18n, parent=window)
            state["modal"] = ModalOverlay(state["dialog"], window)
            checks.extend(["resize", "interaction-mask"])
            QTimer.singleShot(350, lambda: step(modal))

        def modal():
            character = window.character
            assert not character.isVisible() and not character.timer.isActive()
            state["modal"].release()
            state["dialog"].close()
            character.hide()
            state["frames"] = character.frames
            QTimer.singleShot(350, lambda: step(hidden))

        def hidden():
            character = window.character
            assert character.frames == state["frames"]
            character.show()
            checks.extend(["modal-dialog", "hidden-no-render"])
            QTimer.singleShot(350, lambda: step(completed))

        def completed():
            character = window.character
            character.config.captions = True
            for item in repository.list_tasks(tracker_id):
                repository.set_task_state(tracker_id, item.id, date.today(), TaskState.DONE)
                window.dashboard.refresh(changed_tracker=tracker_id)
            assert character.reactions.pending.isActive()
            QTimer.singleShot(1300, lambda: step(reacted))

        def reacted():
            character = window.character
            assert character.caption.isVisible()
            assert character.effect_duration == 6.0
            assert character.renderer.fbo.height() >= character.height() * 2
            assert character.image.height() >= character.height()
            assert window.rect().contains(character.caption.geometry())
            window.grab().save(str(args.output / "somniloop-reaction.png"))
            checks.extend(["supersampling", "task-reaction", "optional-caption"])
            touch_checks()

        def touch_checks():
            character = window.character
            character.resetExpression()
            assert character.status.isVisible()
            assert window.rect().contains(character.status.geometry())
            assert character.status.y() > character.geometry().bottom()

            def point(part, x, y):
                bounds = character.renderer.part_bounds(part, character.width(), character.height())
                assert bounds is not None, part
                x0, y0, x1, y1 = bounds
                return QPoint(round((x0 + (x1 - x0) * x) * character.width()),
                              round((y0 + (y1 - y0) * y) * character.height()))

            head = point("PARTS_01_HAIR_FRONT_002", .5, .35)
            cheek = point("PARTS_01_HOHO", .18, .5)
            chest = point("PARTS_01_CLOTHES", .5, .2)
            hips = point("PARTS_01_CLOTHES", .5, .86)
            legs = point("PARTS_01_FOOT", .27, .85)
            for name, location in (("head", head), ("cheek", cheek), ("chest", chest),
                                   ("hips", hips), ("legs", legs)):
                assert character._zone_at(QPointF(location)) == name, (
                    name, character._zone_at(QPointF(location)), location
                )

            def tap(location):
                QTest.mouseClick(character, Qt.MouseButton.LeftButton, pos=location)

            for _ in range(4):
                tap(head)
                assert character.status.emotion == "Smile"
            tap(head)
            assert character.status.emotion == "Smile"
            character.touch = TouchState()
            for _ in range(4):
                tap(cheek)
                assert character.status.emotion == "Smile"
            tap(cheek)
            assert character.status.emotion == "Smile"
            character.touch = TouchState()
            QTest.mouseClick(character, Qt.MouseButton.LeftButton, pos=chest)
            assert character.status.emotion == "Angry"
            character.touch = TouchState()
            tap(head)
            QTest.mouseClick(character, Qt.MouseButton.LeftButton, pos=chest)
            assert character.status.emotion == "Blushing"
            character.touch = TouchState()
            tap(head)
            QTest.mouseClick(character, Qt.MouseButton.LeftButton, pos=hips)
            assert character.status.emotion == "Blushing"
            character.touch = TouchState()
            tap(head)
            QTest.mouseClick(character, Qt.MouseButton.LeftButton, pos=legs)
            assert character.status.emotion == "Angry"
            character.touch.last_touch = time.monotonic() - 61
            character.touch.recent_taps.clear()
            waist = point("PARTS_01_CLOTHES", .5, .55)
            assert character._zone_at(QPointF(waist)) == "other"
            QTest.mouseClick(character, Qt.MouseButton.LeftButton, pos=waist)
            assert character.status.emotion == "Surprised"
            character.touch = TouchState()
            for _ in range(5):
                character._touch_reaction("legs")
            assert character.status.emotion == "Disgust"
            checks.extend(["geometry-hit-areas", "head-taps", "repeated-affection-smiles",
                           "cheek-taps", "quiet-surprise", "smile-to-blushing", "emotion-status"])
            QTimer.singleShot(1300, lambda: step(touch_finished))

        def touch_finished():
            character = window.character
            window.grab().save(str(args.output / "somniloop-touch.png"))
            character.last_effect -= 6
            character._frame()
            assert character.status.emotion == "Normal"
            character.config.interaction = False
            character._touch_reaction("chest")
            assert character.status.emotion == "Normal"
            panel = character.motion_panel
            assert panel is None
            assert character.x() == window.width() - character.width() - character.config.offset_x
            clips = [(group, index) for group, motions in character.motions.items()
                     for index in range(len(motions))
                     if group != "Idle" and (group, index) != ("Tap", 0)]
            assert len(clips) == 13
            for group, index in clips:
                character.previewMotion(group, index)
                assert character.renderer.lib.sl_motion_group(character.renderer.handle).decode() == group
                assert character.preview_remaining > 0
                assert character.status.emotion == "Preview"
                character._frame()
            # Reach the end using the same bounded delta as the SDK, without wall-clock waiting.
            while character.preview_remaining > 0:
                character.last_frame = time.monotonic() - .1
                character._frame()
            checks.extend(["no-preview-panel", "all-13-motion-clips"])
            for event, group in (("created", "FlickUp"), ("settings_saved", "FlickUp"),
                                 ("archived", "FlickUp"), ("not_done", None)):
                character.motion_remaining = 0
                character.applicationEvent(event)
                character._frame()
                active = character.renderer.lib.sl_motion_group(character.renderer.handle).decode()
                assert active == group if group else active in ("Tap", "FlickDown")
                assert character.motion_remaining > 0
            character.motion_remaining = 0
            character.touch_priority_until = 0
            character.next_motion = 0
            character._frame()
            assert character.renderer.lib.sl_motion_group(character.renderer.handle) == b"Flick3"
            assert 5.8 <= character.next_motion - time.monotonic() <= 10
            checks.extend(["activity-motion-routing", "ambient-flick3"])
            window.grab().save(str(args.output / "somniloop-motion-preview.png"))
            character.hide()
            assert not character.status.isVisible()
            finish()

        def finish():
            character = window.character
            window.close()
            assert character.disposed and character.renderer is None
            assert not character.timer.isActive() and not character.visibility_timer.isActive()
            checks.append("cleanup")
            app.quit()

        QTimer.singleShot(4000, lambda: step(initial))
        QTimer.singleShot(
            20000,
            lambda: step(
                lambda: (_ for _ in ()).throw(TimeoutError("Live2D smoke test timed out"))
            ),
        )
        app.exec()
    print("Checks:", ", ".join(checks))
    print("Screenshots:", args.output)
    if errors:
        raise SystemExit("Live2D smoke test failed: " + "; ".join(errors))


if __name__ == "__main__":
    main()

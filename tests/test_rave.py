from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from somniloop.core.database import Repository
from somniloop.core.models import ScheduleType, TaskState, TrackerMode
from somniloop.ui.rave import RaveOverlay


def test_animation_time_tracks_audio_and_bounds_interpolation():
    state = {"position": 12000, "elapsed": 15000, "stalled": False}
    overlay = SimpleNamespace(
        _audio_position=0, _position_seen_at=0,
        clock=SimpleNamespace(elapsed=lambda: state["elapsed"]),
        player=SimpleNamespace(
            position=lambda: state["position"],
            playbackState=lambda: QMediaPlayer.PlaybackState.PlayingState,
            mediaStatus=lambda: (QMediaPlayer.MediaStatus.StalledMedia if state["stalled"]
                                 else QMediaPlayer.MediaStatus.BufferedMedia),
        ),
    )
    assert RaveOverlay.playback_ms(overlay) == 12000
    state["elapsed"] += 16
    assert RaveOverlay.playback_ms(overlay) == 12016
    state["elapsed"] += 1000
    assert RaveOverlay.playback_ms(overlay) == 12060
    state["stalled"] = True
    assert RaveOverlay.playback_ms(overlay) == 12000
    state.update(position=0, stalled=False)
    assert RaveOverlay.playback_ms(overlay) == 0


def test_lighting_cache_is_bounded_reused_and_invalidated():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    overlay = RaveOverlay(host)
    try:
        overlay.resize(3840, 2160)
        first = overlay._lighting_frame(12)
        assert first.width() <= 768 and first.height() <= 432
        assert first.devicePixelRatio() == 1
        key = first.cacheKey()
        assert overlay._lighting_frame(12.02).cacheKey() == key
        assert overlay._lighting_frame(12.06).cacheKey() != key
        overlay.resize(800, 800)
        square = overlay._lighting_frame(12.06)
        assert square.width() == square.height() == 432
        overlay.stop()
        assert overlay._light_cache.isNull()
        assert overlay.timer.interval() == 33
    finally:
        overlay.dispose()
        host.close()
        app.processEvents()


def test_minimized_window_skips_render_updates_but_checks_audio_end():
    events = []
    overlay = SimpleNamespace(
        playback_ms=lambda: 100, duration_ms=1000,
        player=SimpleNamespace(mediaStatus=lambda: QMediaPlayer.MediaStatus.BufferedMedia),
        host=SimpleNamespace(isMinimized=lambda: True),
        update=lambda: events.append("paint"), stop=lambda: events.append("stop"),
    )
    RaveOverlay._frame(overlay)
    assert events == []
    overlay.duration_ms = 50
    RaveOverlay._frame(overlay)
    assert events == ["stop"]


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "rave.db")
    yield repository
    repository.close()


def test_only_last_due_today_task_triggers_and_can_repeat(repo):
    events = []
    repo.celebrations.subscribe(events.append)
    today = date.today()
    for due in (None, today - timedelta(days=1), today + timedelta(days=1)):
        repo.save_planner_task("Other", due)
    first = repo.save_planner_task("First", today)
    last = repo.save_planner_task("Last", today)
    repo.complete_planner_task(first)
    assert events == []
    repo.complete_planner_task(last)
    assert events == [1.0]
    repo.complete_planner_task(last)
    assert events == [1.0]
    repo.set_planner_task_state(last, TaskState.UNSET)
    repo.complete_planner_task(last)
    assert events == [1.0, 1.0]


def test_archive_and_future_completion_do_not_trigger(repo):
    events = []
    repo.celebrations.subscribe(events.append)
    task = repo.save_planner_task("Today", date.today())
    repo.archive_planner_task(task)
    future = repo.save_planner_task("Later", date.today() + timedelta(days=1))
    repo.complete_planner_task(future)
    assert events == []


def test_last_checklist_item_triggers(repo):
    events = []
    repo.celebrations.subscribe(events.append)
    repo.save_planner_task("Today", date.today(), items=["A", "B"])
    items = repo.list_planner_tasks()[0].items
    repo.set_planner_item_done(items[0]["id"], True)
    assert events == []
    repo.set_planner_item_done(items[1]["id"], True)
    assert events == [1.0]


@pytest.mark.parametrize("days", [1, 7, 30, 35])
def test_habit_fraction_and_repeat(repo, days):
    today = date.today()
    tracker = repo.create_tracker("Habit", "", TrackerMode.REGULAR, ScheduleType.DAILY,
                                  {}, ["A", "B"], created_on=today - timedelta(days=days))
    tasks = repo.list_tasks(tracker)
    events = []
    repo.celebrations.subscribe(events.append)
    for offset in range(1, days):
        for task in tasks:
            repo.set_task_state(tracker, task.id, today - timedelta(days=offset), TaskState.DONE)
    assert events == []
    repo.set_task_state(tracker, tasks[0].id, today, TaskState.DONE)
    assert events == []
    repo.set_task_state(tracker, tasks[1].id, today, TaskState.DONE)
    fraction = min(days / 30, 1)
    assert events == [fraction]
    repo.set_task_state(tracker, tasks[1].id, today, TaskState.DONE)
    assert events == [fraction]
    repo.set_task_state(tracker, tasks[1].id, today, TaskState.UNSET)
    repo.set_task_state(tracker, tasks[1].id, today, TaskState.DONE)
    assert events == [fraction, fraction]


def test_overlay_duration_mute_restart_resize_and_dispose():
    def wait(milliseconds):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(900, 650)
    host.show()
    overlay = RaveOverlay(host)
    transitions = []
    overlay.activeChanged.connect(transitions.append)
    try:
        overlay.start(0.5)
        for _ in range(100):
            if overlay.timer.isActive():
                break
            wait(20)
        assert overlay.timer.isActive()
        assert overlay.duration_ms == round(overlay.player.duration() * 0.5)
        assert overlay.cat.hasAlphaChannel()
        assert len(overlay.glows) == 8
        for glow in overlay.glows:
            center = glow.toImage().pixelColor(48, 48)
            assert min(center.red(), center.green(), center.blue(), center.alpha()) >= 250
        QTest.keyClick(host, Qt.Key.Key_Escape)
        assert overlay.audio.isMuted() and overlay.timer.isActive()
        player = overlay.player
        overlay.start(1)
        assert overlay.player is player and not overlay.audio.isMuted()
        host.resize(1000, 700)
        app.processEvents()
        assert overlay.size() == host.size()
        overlay.duration_ms = 1
        wait(40)
        assert not overlay.timer.isActive() and overlay.isHidden()
        assert transitions == [True, True, False]
        assert not overlay.active
    finally:
        overlay.dispose()
        assert not overlay.timer.isActive() and not overlay.load_timeout.isActive()
        host.close()

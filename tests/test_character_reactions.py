"""Feedback must never change task data or celebrate passive screen refreshes."""

from datetime import date, timedelta
from types import SimpleNamespace

from somniloop.core.models import TaskState
from somniloop.live2d.reactions import CompletionMonitor


def snapshot(done=False, *, day=None, identifier=1):
    day = day or date.today()
    item = SimpleNamespace(task=SimpleNamespace(id=identifier), state=(
        TaskState.DONE if done else TaskState.UNSET
    ))
    return SimpleNamespace(
        today=day, planner=[], completed=[], trackers={1: SimpleNamespace(
            tracker=SimpleNamespace(id=1), occurrences=[(day, [item])]
        )},
    )


def test_only_real_completions_and_no_repeat_after_undo():
    monitor = CompletionMonitor()
    assert monitor.observe(snapshot()) is None
    assert monitor.observe(snapshot()) is None
    assert monitor.observe(snapshot(True)) is True
    assert not monitor.invalidated
    assert monitor.observe(snapshot(True)) is None
    assert monitor.observe(snapshot()) is None
    assert monitor.invalidated
    assert monitor.observe(snapshot(True)) is None
    tomorrow = date.today() + timedelta(days=1)
    assert monitor.observe(snapshot(day=tomorrow)) is None
    assert monitor.observe(snapshot(True, day=tomorrow)) is True


def test_new_completed_items_and_removed_items_do_not_trigger():
    monitor = CompletionMonitor()
    monitor.observe(snapshot())
    assert monitor.observe(snapshot(True, identifier=2)) is None
    empty = snapshot()
    empty.trackers = {}
    assert monitor.observe(empty) is None


def test_planner_completion_and_future_tasks_do_not_block_today():
    monitor = CompletionMonitor()
    data = snapshot()
    future = SimpleNamespace(id=2, due_date=(date.today() + timedelta(days=2)).isoformat(),
                             items=[], state=TaskState.UNSET)
    data.planner = [future]
    monitor.observe(data)
    data = snapshot(True)
    data.planner = [future]
    assert monitor.observe(data) is True
    future.state = TaskState.DONE
    assert monitor.observe(data) is False


def test_supersampling_is_hidpi_aware_and_bounded():
    from somniloop.live2d.renderer import render_size

    assert render_size(245, 340, 1).height() == 680
    assert render_size(245, 340, 2).height() == 1360
    size = render_size(1000, 2000, 3)
    assert size.height() == 1536 and size.width() == 768


def test_disappearing_overdue_plan_uses_actual_state_not_disappearance():
    monitor = CompletionMonitor()
    yesterday = date.today() - timedelta(days=1)
    data = snapshot(day=yesterday)
    data.today = date.today()
    assert monitor.observe(data) is None
    item = data.trackers[1].occurrences[0][1][0]
    data.trackers[1].occurrences = []
    data.repository = SimpleNamespace(day_summary=lambda *_: SimpleNamespace(tasks=[item]))
    assert monitor.observe(data) is None
    item.state = TaskState.DONE
    assert monitor.observe(data) is True

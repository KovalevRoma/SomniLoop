"""Period boundaries preserve history and refresh the visible quick marks."""

import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import ScheduleType, TaskState, TrackerMode
from somniloop.ui.activity_scrollbar import ActivityScrollBar
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.dashboard_data import tracker_snapshot
from somniloop.ui.personal_dialogs import MergePersonDialog, PeopleDialog


@pytest.fixture
def repo(tmp_path):
    value = Repository(tmp_path / "periods.db")
    yield value
    value.close()


@pytest.mark.parametrize("kind,payload,first,next_day", [
    (ScheduleType.DAILY, {}, date(2026, 9, 30), date(2026, 10, 1)),
    (ScheduleType.INTERVAL, {"days": 3}, date(2026, 9, 28), date(2026, 10, 1)),
    (ScheduleType.WEEKDAYS, {"weekdays": [0]}, date(2026, 9, 21), date(2026, 9, 28)),
    (ScheduleType.MONTHLY, {"day": 31}, date(2026, 1, 31), date(2026, 2, 28)),
    (ScheduleType.YEARLY, {"month": 2, "day": 29}, date(2024, 2, 29), date(2025, 2, 28)),
])
def test_next_occurrence_is_unset_without_erasing_history(repo, kind, payload, first, next_day):
    identifier = repo.create_tracker("Habit", "", TrackerMode.REGULAR, kind, payload, ["Item"], created_on=first)
    tracker = repo.get_tracker(identifier)
    task = repo.list_tasks(identifier)[0]
    repo.set_task_state(identifier, task.id, first, TaskState.DONE)
    assert tracker_snapshot(repo, tracker, first).tasks[0].state == TaskState.DONE
    assert tracker_snapshot(repo, tracker, next_day).tasks[0].state == TaskState.UNSET
    assert repo.day_summary(tracker, first).tasks[0].state == TaskState.DONE


def test_weekly_quota_resets_on_monday(repo):
    monday = date(2026, 9, 21)
    identifier = repo.create_tracker("Quota", "", TrackerMode.REGULAR, ScheduleType.WEEKLY_QUOTA, {"count": 3}, ["Item"], created_on=monday)
    tracker = repo.get_tracker(identifier)
    task = repo.list_tasks(identifier)[0]
    for offset in (0, 2, 4):
        repo.set_task_state(identifier, task.id, monday + timedelta(days=offset), TaskState.DONE)
    assert repo.weekly_progress(tracker, monday + timedelta(days=6)) == (3, 3)
    following = tracker_snapshot(repo, tracker, monday + timedelta(days=7))
    assert following.meta.quota_done == 0
    assert following.tasks[0].state == TaskState.UNSET
    assert repo.weekly_progress(tracker, monday) == (3, 3)


def test_midnight_refresh_restores_hidden_habit_and_stale_click_does_not_write(repo, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from somniloop.ui import dashboard_cards, dashboard_data, dashboard_sections
    class Clock(date):
        current = date(2026, 9, 25)
        @classmethod
        def today(cls):
            return cls.current
    monkeypatch.setattr(dashboard_data, "date", Clock)
    monkeypatch.setattr(dashboard_sections, "date", Clock)
    monkeypatch.setattr(dashboard_cards, "date", Clock)
    identifier = repo.create_tracker("Daily", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["Item"], created_on=Clock.current)
    page = Dashboard(repo, I18n("ru"))
    page.filters.hide_done.setChecked(True)
    old_day = Clock.current
    occurrence = page.today.widgets[("tracker", identifier, old_day)]
    task = repo.list_tasks(identifier)[0]
    repo.set_task_state(identifier, task.id, old_day, TaskState.DONE)
    page.refresh(changed_tracker=identifier)
    assert page.cards[identifier].isHidden()
    Clock.current += timedelta(days=1)
    occurrence._mark(task.id, TaskState.NOT_DONE)
    app.processEvents()
    assert not page.cards[identifier].isHidden()
    assert page.data.trackers[identifier].tasks[0].state == TaskState.UNSET
    assert repo.day_summary(identifier, old_day).tasks[0].state == TaskState.DONE
    # The expanded library card has the same midnight protection.
    card = page.cards[identifier]
    Clock.current += timedelta(days=1)
    card._mark(task.id, TaskState.DONE)
    assert page.data.trackers[identifier].tasks[0].state == TaskState.UNSET
    assert repo.day_summary(identifier, Clock.current).tasks[0].state == TaskState.UNSET
    page.close()


def test_nested_merge_confirmation_restores_people_editor(repo):
    app = QApplication.instance() or QApplication([])
    first, second = repo.create_person("Anna"), repo.create_person("Anna duplicate")
    host = QMainWindow()
    host.resize(980, 700)
    host.show()
    people = PeopleDialog(repo, I18n("ru"), host, select_person_id=first)
    errors = []
    def choose():
        dialog = host._modal_overlays[-1].dialog
        try:
            assert isinstance(dialog, MergePersonDialog)
            assert len(host._modal_overlays) == 2
            assert not dialog.isWindow()
            assert dialog.isEnabled() and not people.isEnabled()
            dialog.people.setCurrentRow(0)
            assert dialog.selected_id() == second
            dialog.confirm.click()
        except Exception as error:
            errors.append(error)
            dialog.reject()
    def open_merge():
        try:
            QTimer.singleShot(30, choose)
            people._merge_person()
            assert people.isEnabled()
            assert len(host._modal_overlays) == 1
        except Exception as error:
            errors.append(error)
        finally:
            people.reject()
    QTimer.singleShot(30, open_merge)
    people.exec()
    assert not errors
    assert [person.id for person in repo.list_people(managed_only=True)] == [first]
    host.close()
    app.processEvents()


def test_merge_picker_is_embedded_searchable_and_cancel_is_safe(repo):
    app = QApplication.instance() or QApplication([])
    first, second = repo.create_person("Anna"), repo.create_person("Anna duplicate")
    host = QMainWindow()
    host.resize(980, 700)
    host.show()
    people = PeopleDialog(repo, I18n("ru"), host)
    assert isinstance(people.person_list.verticalScrollBar(), ActivityScrollBar)
    assert isinstance(people.editor_scroll.verticalScrollBar(), ActivityScrollBar)
    dialog = MergePersonDialog(repo.get_person(first), [repo.get_person(second)], I18n("ru"), host)
    errors = []
    def check():
        try:
            assert not dialog.isWindow()
            assert dialog._modal_overlay.panel.width() < host.width()
            dialog.search.setText("nobody")
            assert dialog.people.item(0).isHidden()
            assert not dialog.confirm.isEnabled()
            dialog.search.clear()
            dialog.people.setCurrentRow(0)
            assert dialog.selected_id() == second
            assert dialog.confirm.isEnabled()
            assert dialog.people.currentItem().data(Qt.ItemDataRole.UserRole) == second
        except Exception as error:
            errors.append(error)
        finally:
            dialog.reject()
    QTimer.singleShot(20, check)
    assert dialog.exec() == dialog.DialogCode.Rejected
    assert not errors
    assert len(repo.list_people(managed_only=True)) == 2
    people.close()
    host.close()
    app.processEvents()

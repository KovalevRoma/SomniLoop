import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from somniloop.core.database import Repository
from somniloop.core.dates import (
    age_on,
    birthday_in_year,
    display_date,
    normalize_birth_date,
    one_month_before,
)
from somniloop.core.models import ScheduleType, TaskState, TrackerMode
from somniloop.reminders import show_desktop_notifications


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "planner.db")
    yield repository
    repository.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("28 Jul 2026", "2026-07-28"),
        ("28 JUL 2026", "2026-07-28"),
        ("28.07.2026", "2026-07-28"),
        ("--02-29", "--02-29"),
        ("29 Feb", "--02-29"),
        ("31 Feb 2001", ""),
        ("", ""),
    ],
)
def test_normalize_dates(raw, expected):
    assert normalize_birth_date(raw) == expected


def test_display_and_calendar_arithmetic():
    assert display_date("2026-07-28") == "28 июл 2026"
    assert display_date("--07-28") == "28 июл"
    assert one_month_before(date(2026, 3, 31)) == date(2026, 2, 28)
    assert one_month_before(date(2027, 1, 15)) == date(2026, 12, 15)
    assert age_on("2000-07-28", date(2026, 7, 27)) == 25
    assert age_on("2000-07-28", date(2026, 7, 28)) == 26
    assert age_on("--07-28", date(2026, 7, 28)) is None
    assert birthday_in_year("2000-02-29", 2026) == date(2026, 2, 28)
    assert age_on("2000-02-29", date(2026, 2, 28)) == 26


def test_manual_subtasks_belong_to_one_date(repo):
    tracker_id = repo.create_tracker(
        "Встречи",
        "Общее описание",
        TrackerMode.MANUAL,
        ScheduleType.MANUAL,
        {},
        ["Подготовиться"],
        created_on=date(2026, 1, 1),
    )
    first, second = date(2026, 9, 1), date(2026, 10, 1)
    assert repo.add_manual_occurrence(tracker_id, first, ["Забронировать https://example.org"])
    assert repo.add_manual_occurrence(tracker_id, second, ["Взять документы"])
    assert not repo.add_manual_occurrence(tracker_id, second, ["Дубликат"])
    tracker = repo.get_tracker(tracker_id)
    first_tasks = repo.scheduled_tasks(tracker, first)
    second_tasks = repo.scheduled_tasks(tracker, second)
    assert {task.name for task in first_tasks} == {
        "Подготовиться",
        "Забронировать https://example.org",
    }
    assert {task.name for task in second_tasks} == {"Подготовиться", "Взять документы"}
    specific = next(task for task in first_tasks if task.occurrence_date)
    repo.set_task_state(tracker_id, specific.id, first, TaskState.DONE)
    repo.remove_manual_date(tracker_id, first)
    assert {task.name for task in repo.scheduled_tasks(tracker, second)} == {
        "Подготовиться",
        "Взять документы",
    }
    assert (
        repo.connection.execute(
            "SELECT COUNT(*) FROM task_entries WHERE task_id=?", (specific.id,)
        ).fetchone()[0]
        == 0
    )


def test_completed_planner_is_archived_and_restore_resets_checks(repo):
    task_id = repo.save_planner_task("Документы", date(2026, 8, 20), items=["Собрать", "Отправить"])
    task = repo.list_planner_tasks()[0]
    repo.set_planner_item_done(task.items[0]["id"], True)
    assert repo.list_planner_tasks()[0].id == task_id
    repo.set_planner_item_done(task.items[1]["id"], True)
    assert repo.list_planner_tasks() == []
    assert repo.list_planner_tasks(True)[0].completed
    repo.archive_planner_task(task_id, False)
    restored = repo.list_planner_tasks()[0]
    assert not restored.completed
    assert all(not item["done"] for item in restored.items)
    assert restored.due_date == "2026-08-20"


def test_planner_edit_preserves_only_matching_checks(repo):
    task_id = repo.save_planner_task("Задача", date(2026, 8, 20), items=["A", "B"])
    repo.set_planner_item_done(repo.list_planner_tasks()[0].items[0]["id"], True)
    repo.save_planner_task("Обновлена", date(2026, 9, 1), items=["B", "A", "C"], task_id=task_id)
    assert [(item["title"], item["done"]) for item in repo.list_planner_tasks()[0].items] == [
        ("B", 0),
        ("A", 1),
        ("C", 0),
    ]


def test_planner_time_sort_edit_archive_and_export(repo):
    day = date(2026, 9, 25)
    untimed = repo.save_planner_task("Без времени", day)
    late = repo.save_planner_task("Вечер", day, due_time="19:30")
    early = repo.save_planner_task("Утро", day, due_time="09:05")
    assert [task.id for task in repo.list_planner_tasks()] == [early, late, untimed]
    repo.save_planner_task("Вечер обновлён", day, task_id=late)
    assert repo.list_planner_tasks()[1].due_time == "19:30"
    repo.archive_planner_task(late)
    repo.restore_payload(repo.export_payload())
    assert repo.list_planner_tasks(True)[0].due_time == "19:30"
    repo.archive_planner_task(late, False)
    repo.save_planner_task("Без времени теперь", day, task_id=late, due_time="")
    assert next(task for task in repo.list_planner_tasks() if task.id == late).due_time == ""
    old_export = repo.export_payload()
    for task in old_export["tables"]["planner_tasks"]:
        task.pop("due_time")
    repo.restore_payload(old_export)
    assert all(task.due_time == "" for task in repo.list_planner_tasks())


@pytest.mark.parametrize("value", ["24:00", "12:60", "9:30", "noon", "12:30:00"])
def test_planner_rejects_invalid_time(repo, value):
    with pytest.raises(ValueError):
        repo.save_planner_task("Invalid", date.today(), due_time=value)
    assert not repo.list_planner_tasks()


def test_planner_time_migrates_old_database_without_losing_task(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE planner_tasks (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, due_date TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', completed INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)""")
        connection.execute("INSERT INTO planner_tasks(id,title,due_date,updated_at) VALUES (1,'Old','2026-09-25','2026-09-23')")
    repository = Repository(path)
    task = repository.list_planner_tasks()[0]
    assert task.title == "Old" and task.due_time == ""
    repository.save_planner_task(task.title, date(2026, 9, 25), task_id=1, due_time="00:00")
    repository.close()
    repository = Repository(path)
    assert repository.list_planner_tasks()[0].due_time == "00:00"
    repository.close()


def test_archive_keeps_tracker_history(repo):
    tracker_id = repo.create_tracker(
        "Спорт", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["Тренировка"]
    )
    task_id = repo.list_tasks(tracker_id)[0].id
    repo.set_task_state(tracker_id, task_id, date.today(), TaskState.DONE)
    repo.archive_tracker(tracker_id)
    assert not repo.list_trackers()
    assert repo.list_trackers(True)[0].archived
    repo.archive_tracker(tracker_id, False)
    assert (
        repo.day_summary(repo.get_tracker(tracker_id), date.today()).tasks[0].state
        == TaskState.DONE
    )


def test_birthday_month_window_deduplication_and_year_rollover(repo):
    person_id = repo.create_person("Ирина")
    repo.save_person_input(person_id, "Ирина", "подруга", "", birth_date="2000-01-15")
    repo.sync_birthday_notifications(date(2026, 12, 14))
    assert not repo.list_notifications()
    repo.sync_birthday_notifications(date(2026, 12, 15))
    reminder = repo.list_notifications()[0]
    assert reminder["birthday"] == "2027-01-15"
    assert "27" in reminder["title"]
    changes = repo.connection.total_changes
    repo.sync_birthday_notifications(date(2026, 12, 16))
    assert repo.connection.total_changes == changes
    repo.dismiss_notification(reminder["id"])
    repo.sync_birthday_notifications(date(2027, 1, 15))
    assert not repo.list_notifications()
    repo.sync_birthday_notifications(date(2027, 12, 15))
    assert repo.list_notifications()[0]["birthday"] == "2028-01-15"


def test_desktop_birthday_notification_is_sent_only_once(repo, monkeypatch):
    birthday = date.today() + timedelta(days=10)
    person_id = repo.create_person("Ирина")
    repo.save_person_input(
        person_id,
        "Ирина",
        "подруга",
        "",
        birth_date=f"2000-{birthday.month:02d}-{birthday.day:02d}",
    )
    calls = []
    monkeypatch.setattr("somniloop.reminders.shutil.which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(
        "somniloop.reminders.subprocess.run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )

    assert show_desktop_notifications(repo) == 1
    assert show_desktop_notifications(repo) == 0
    assert len(calls) == 1


def test_birth_conflict_never_generates_uncertain_reminder(repo):
    person_id = repo.create_person("Анна")
    repo.save_person_analysis(
        person_id, {"birth_date": "2000-09-28", "conflicts": ["Дата рождения противоречит записи"]}
    )
    repo.sync_birthday_notifications(date(2026, 8, 28))
    assert not repo.list_notifications()
    repo.save_person_analysis(person_id, {"birth_date": "--09-28"})
    repo.sync_birthday_notifications(date(2026, 8, 28))
    assert "исполняется" not in repo.list_notifications()[0]["title"]
    repo.save_person_analysis(person_id, {"birth_date": "--11-28"})
    repo.sync_birthday_notifications(date(2026, 8, 28))
    assert not repo.list_notifications()


def test_noop_diary_save_keeps_modification_date(repo):
    note_id = repo.save_note("День", "Текст", entry_date="2026-08-01")
    original = repo.list_notes()[0].updated_at
    changes = repo.connection.total_changes
    repo.save_note("День", "Текст", entry_date="2026-08-01", note_id=note_id)
    assert repo.list_notes()[0].updated_at == original
    assert repo.connection.total_changes == changes


def test_migration_creates_backup_without_losing_user_data(tmp_path):
    path = tmp_path / "legacy.db"
    original = Repository(path)
    original.save_profile("Роман", "Моё био")
    original.connection.execute("PRAGMA user_version=2")
    original.close()
    migrated = Repository(path)
    assert migrated.get_profile() == ("Роман", "Моё био")
    assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 3
    backup = path.with_suffix(".db.pre-v3.bak")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT bio FROM profile").fetchone()[0] == "Моё био"
    migrated.close()


def test_long_streak_uses_bounded_database_reads(repo):
    start = date(2020, 1, 1)
    tracker_id = repo.create_tracker(
        "Длинная серия", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["Шаг"], created_on=start
    )
    task_id = repo.list_tasks(tracker_id)[0].id
    repo.connection.executemany(
        "INSERT INTO task_entries(tracker_id, task_id, entry_date, state) VALUES (?, ?, ?, 'done')",
        [
            (tracker_id, task_id, (start + timedelta(days=index)).isoformat())
            for index in range(2000)
        ],
    )
    repo.connection.commit()
    statements = []
    repo.connection.set_trace_callback(statements.append)
    assert repo.streak(repo.get_tracker(tracker_id), start + timedelta(days=2000)) == (
        2000,
        "occurrences",
    )
    assert sum(sql.startswith("SELECT") for sql in statements) < 10

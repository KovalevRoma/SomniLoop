from datetime import date

import pytest

from somniloop.core.database import Repository
from somniloop.core.models import DayStatus, ScheduleType, TaskState, TrackerMode


@pytest.fixture()
def repository(tmp_path):
    repo = Repository(tmp_path / "test.db")
    yield repo
    repo.close()


def create_tracker(
    repository,
    schedule_type=ScheduleType.DAILY,
    schedule=None,
    mode=TrackerMode.REGULAR,
):
    tracker_id = repository.create_tracker(
        "Test",
        "",
        mode,
        schedule_type,
        schedule or {},
        ["First", "Second"],
        created_on=date(2026, 8, 1),
    )
    return repository.get_tracker(tracker_id)


def mark_day(repository, tracker, day, states):
    for task, state in zip(repository.list_tasks(tracker.id), states):
        repository.set_task_state(tracker.id, task.id, day, state)


def test_people_can_be_edited_and_merged_without_losing_history(repository):
    primary = repository.create_person("Ирина Ковалёва")
    duplicate = repository.create_person("Ковалёва Ирина")
    repository.save_person_input(
        primary,
        "Ирина Ковалёва",
        "подруга",
        "Живёт в Берлине.",
        contact="@irina",
        group_name="Друзья",
    )
    repository.save_person_input(
        duplicate,
        "Ковалёва Ирина",
        "",
        "Работает архитектором.",
    )
    repository.save_person_analysis(primary, {"facts": ["Любит джаз"]})
    repository.save_person_analysis(duplicate, {"facts": ["Была в Риме"]})

    repository.merge_people(primary, duplicate)

    person = repository.get_person(primary)
    assert "Живёт в Берлине" in person.raw_notes
    assert "Работает архитектором" in person.raw_notes
    assert person.facts == ["Любит джаз", "Была в Риме"]
    assert person.contact == "@irina"
    assert person.group_name == "Друзья"
    with pytest.raises(KeyError):
        repository.get_person(duplicate)


def test_manual_person_details_survive_graph_analysis(repository):
    person_id = repository.create_person("Анна")
    repository.save_person_details(
        person_id,
        biography="Исправленная биография",
        education="МГУ",
        occupation="Архитектор",
        facts=["Факт вручную"],
    )
    repository.save_person_analysis(
        person_id,
        {
            "biography": "Версия модели",
            "education": "Другое",
            "occupation": "Другое",
            "facts": ["Факт модели"],
        },
    )
    person = repository.get_person(person_id)
    assert person.biography == "Исправленная биография"
    assert person.education == "МГУ"
    assert person.occupation == "Архитектор"
    assert person.facts == ["Факт вручную"]


def test_day_statuses(repository):
    tracker = create_tracker(repository)
    mark_day(repository, tracker, date(2026, 8, 1), [TaskState.DONE, TaskState.DONE])
    mark_day(repository, tracker, date(2026, 8, 2), [TaskState.DONE, TaskState.NOT_DONE])
    mark_day(repository, tracker, date(2026, 8, 3), [TaskState.NOT_DONE, TaskState.NOT_DONE])
    assert (
        repository.day_summary(tracker, date(2026, 8, 1), date(2026, 8, 4)).status == DayStatus.DONE
    )
    assert (
        repository.day_summary(tracker, date(2026, 8, 2), date(2026, 8, 4)).status
        == DayStatus.PARTIAL
    )
    assert (
        repository.day_summary(tracker, date(2026, 8, 3), date(2026, 8, 4)).status
        == DayStatus.MISSED
    )
    assert (
        repository.day_summary(tracker, date(2026, 8, 4), date(2026, 8, 4)).status
        == DayStatus.UNSET
    )


def test_partial_day_preserves_streak(repository):
    tracker = create_tracker(repository)
    mark_day(repository, tracker, date(2026, 8, 1), [TaskState.DONE, TaskState.DONE])
    mark_day(repository, tracker, date(2026, 8, 2), [TaskState.DONE, TaskState.NOT_DONE])
    assert repository.streak(tracker, date(2026, 8, 3)) == (2, "occurrences")


def test_attention_remains_until_every_item_is_marked(repository):
    tracker = create_tracker(repository)
    first = repository.list_tasks(tracker.id)[0]
    repository.set_task_state(tracker.id, first.id, date(2026, 8, 3), TaskState.DONE)
    assert repository.dashboard_meta(tracker, date(2026, 8, 3)).needs_attention


def test_missed_day_breaks_streak(repository):
    tracker = create_tracker(repository)
    mark_day(repository, tracker, date(2026, 8, 1), [TaskState.DONE, TaskState.DONE])
    mark_day(repository, tracker, date(2026, 8, 2), [TaskState.NOT_DONE, TaskState.NOT_DONE])
    assert repository.streak(tracker, date(2026, 8, 3)) == (0, "occurrences")


def test_manual_tracker_accepts_multiple_future_dates(repository):
    tracker = create_tracker(repository, ScheduleType.MANUAL, {}, TrackerMode.MANUAL)
    assert repository.add_manual_date(tracker.id, date(2026, 9, 1))
    assert repository.add_manual_date(tracker.id, date(2026, 10, 1))
    assert not repository.add_manual_date(tracker.id, date(2026, 10, 1))
    assert repository.list_manual_dates(tracker.id) == [
        date(2026, 9, 1),
        date(2026, 10, 1),
    ]


def test_manual_overdue_is_attention_until_every_task_is_explicit(repository):
    tracker = create_tracker(repository, ScheduleType.MANUAL, {}, TrackerMode.MANUAL)
    repository.add_manual_date(tracker.id, date(2026, 8, 20))
    assert repository.dashboard_meta(tracker, date(2026, 8, 27)).needs_attention
    mark_day(repository, tracker, date(2026, 8, 20), [TaskState.NOT_DONE, TaskState.NOT_DONE])
    assert not repository.dashboard_meta(tracker, date(2026, 8, 27)).needs_attention


def test_item_specific_annual_dates(repository):
    tracker_id = repository.create_tracker(
        "Birthdays",
        "",
        TrackerMode.REGULAR,
        ScheduleType.ITEM_DATES,
        {},
        [],
        created_on=date(2026, 1, 1),
    )
    repository.add_task(
        tracker_id,
        "Alice",
        schedule_type=ScheduleType.YEARLY,
        schedule={"month": 8, "day": 27},
    )
    repository.add_task(
        tracker_id,
        "Bob",
        schedule_type=ScheduleType.YEARLY,
        schedule={"month": 9, "day": 1},
    )
    tracker = repository.get_tracker(tracker_id)
    assert [task.name for task in repository.scheduled_tasks(tracker, date(2026, 8, 27))] == [
        "Alice"
    ]


def test_weekly_quota_progress_and_streak(repository):
    tracker = create_tracker(repository, ScheduleType.WEEKLY_QUOTA, {"count": 3})
    for day in (
        date(2026, 8, 17),
        date(2026, 8, 18),
        date(2026, 8, 19),
        date(2026, 8, 24),
        date(2026, 8, 25),
        date(2026, 8, 26),
    ):
        mark_day(repository, tracker, day, [TaskState.DONE, TaskState.DONE])
    assert repository.weekly_progress(tracker, date(2026, 8, 27)) == (3, 3)
    assert repository.streak(tracker, date(2026, 8, 27)) == (2, "weeks")


def test_weekly_quota_attention_only_when_needed(repository):
    tracker = create_tracker(repository, ScheduleType.WEEKLY_QUOTA, {"count": 3})
    assert not repository.dashboard_meta(tracker, date(2026, 8, 27)).needs_attention
    assert repository.dashboard_meta(tracker, date(2026, 8, 28)).needs_attention


def test_json_payload_contains_all_local_data(repository):
    create_tracker(repository)
    person_id = repository.create_person("Анна")
    repository.save_person_input(person_id, "Анна", "подруга", "Училась в МГУ.")
    payload = repository.export_payload()
    assert payload["format"] == "SomniLoop export"
    assert payload["version"] == 3
    assert len(payload["tables"]["trackers"]) == 1
    assert len(payload["tables"]["people"]) == 1


def test_export_payload_can_restore_all_data_and_creates_backup(repository):
    tracker = create_tracker(repository)
    repository.save_note("До экспорта", "Важный текст", entry_date="2026-08-20")
    payload = repository.export_payload()
    repository.delete_tracker(tracker.id)
    repository.save_note("Лишнее", "Будет удалено", entry_date="2026-08-21")

    backup = repository.restore_payload(payload)

    assert backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600
    assert [tracker.name for tracker in repository.list_trackers()] == ["Test"]
    assert [note.title for note in repository.list_notes()] == ["До экспорта"]


def test_diary_entries_have_their_own_date(repository):
    note_id = repository.save_note("День у моря", "Сегодня было спокойно.", entry_date="2026-08-20")
    note = next(item for item in repository.list_notes() if item.id == note_id)
    assert note.entry_date == "2026-08-20"


def test_people_input_and_processed_facts_are_kept_separately(repository):
    person_id = repository.create_person("Виктор")
    repository.save_person_input(person_id, "Ковалёв Виктор", "дедушка", "Работал инженером.")
    repository.save_person_analysis(
        person_id,
        {
            "biography": "Виктор работал инженером.",
            "birth_date": "",
            "education": "",
            "occupation": "Инженер",
            "facts": ["Работал инженером"],
        },
    )
    person = repository.get_person(person_id)
    assert person.raw_notes == "Работал инженером."
    assert person.biography == "Виктор работал инженером."
    assert person.facts == ["Работал инженером"]


def test_legacy_derived_graph_is_cleared_without_touching_profile(tmp_path):
    path = tmp_path / "legacy.db"
    repository = Repository(path)
    repository.save_profile("Роман", "Старое био сохраняется")
    repository.connection.execute(
        """INSERT INTO knowledge_nodes(node_id, label, category, details)
           VALUES ('old-event', 'Событие', 'events', '{}')"""
    )
    repository.connection.execute("DELETE FROM settings WHERE key='knowledge_graph_schema'")
    repository.connection.commit()
    repository.close()

    migrated = Repository(path)
    assert migrated.load_knowledge_graph() == ([], [])
    assert migrated.get_profile() == ("Роман", "Старое био сохраняется")
    migrated.close()

"""Render UI previews using disposable sample data, never the user's database."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.core.models import ScheduleType, TaskState, TrackerMode
from somniloop.knowledge.pipeline import KnowledgeBuilder
from somniloop.ui.calendar_dialog import CalendarDialog
from somniloop.ui.main_window import MainWindow
from somniloop.ui.personal_dialogs import DiaryDialog, PeopleDialog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory(prefix="somniloop-preview-") as directory:
        repo = Repository(Path(directory) / "preview.db")
        repo.set_setting("theme", "light")
        repo.save_profile("Алексей", "Люблю настольный теннис. Хочу выучить испанский язык.")
        person_id = repo.create_person("Анна Морозова")
        repo.save_person_input(
            person_id,
            "Анна Морозова",
            "подруга",
            "Раньше училась в МГУ. Сейчас работает архитектором.",
            birth_date="2000-09-15",
            interests="Плавание, кино и путешествия",
        )
        repo.save_note(
            "Встреча с Анной",
            "Анна Морозова работает архитектором.\nЛюблю долгие прогулки по городу.\nХочу больше времени уделять спорту.",
            entry_date="2026-08-27",
        )
        tracker = repo.create_tracker(
            "Движение каждый день",
            "Немного времени для себя",
            TrackerMode.REGULAR,
            ScheduleType.DAILY,
            {},
            ["Разминка", "Прогулка"],
            created_on=date(2026, 8, 1),
        )
        for day in range(1, 28):
            for task in repo.list_tasks(tracker):
                state = TaskState.DONE if day % 7 else TaskState.NOT_DONE
                repo.set_task_state(tracker, task.id, date(2026, 8, day), state)
        manual = repo.create_tracker(
            "Личные встречи",
            "Место и общие пожелания",
            TrackerMode.MANUAL,
            ScheduleType.MANUAL,
            {},
            [],
            created_on=date(2026, 8, 1),
        )
        repo.add_manual_occurrence(
            manual, date(2026, 9, 1), ["Забронировать столик https://example.org", "Взять книгу"]
        )
        repo.save_planner_task(
            "Отправить документы",
            date(2026, 8, 30),
            "Подготовить всё заранее",
            ["Проверить анкету", "Загрузить файлы"],
        )
        repo.apply_knowledge_result(KnowledgeBuilder().build(repo.knowledge_source()))
        window = MainWindow(repo)
        window.resize(1400, 850)
        window.show()
        app.processEvents()
        window.grab().save(str(args.output / "dashboard.png"))
        window.notifications_button.click()
        app.processEvents()
        window.grab().save(str(args.output / "notifications.png"))
        window.notifications_button.click()
        window.pages.setCurrentWidget(window.graph_page)
        for _ in range(180):
            window.graph_page.graph_view._physics_step()
        window.graph_page._show_node(
            next(node for node in window.graph_page.all_nodes if node.label == "Анна Морозова")
        )
        app.processEvents()
        window.grab().save(str(args.output / "graph.png"))
        for name, dialog in (
            ("calendar", CalendarDialog(repo, tracker, window.i18n, window)),
            ("diary", DiaryDialog(repo, window.i18n, window)),
            ("people", PeopleDialog(repo, window.i18n, window)),
        ):
            dialog.show()
            QTest.qWait(50)
            dialog.grab().save(str(args.output / f"{name}.png"))
            dialog.close()
        window.close()


if __name__ == "__main__":
    main()

"""Render task attachments, project dates and birthdays using disposable data."""

import argparse
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.ui.main_window import MainWindow
from somniloop.ui.planner import PlannerDialog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", action="store_true")
    args = parser.parse_args()
    app = QApplication([])
    output = Path(tempfile.mkdtemp(prefix="somniloop-task-extras-"))
    with tempfile.TemporaryDirectory() as directory:
        repo = Repository(Path(directory) / "smoke.db")
        repo.set_setting("live2d_config", '{"enabled":true}' if args.character else '{"enabled":false}')
        repo.set_setting("theme", "light")
        project = repo.save_work_project("Преподавание")
        task_id = repo.save_planner_task("Подготовить занятие", date.today(), due_time="14:30")
        repo.save_work_item("planner", task_id, project_id=project)
        for name, offset in (("Анна", 0), ("Марк", 4), ("София", 19)):
            person = repo.create_person(name)
            repo.connection.execute("UPDATE people SET birth_date=? WHERE id=?",
                                    ((date.today() + timedelta(days=offset)).strftime("--%m-%d"), person))
        repo.connection.commit()
        window = MainWindow(repo)
        window.resize(1100, 790)
        window.show()
        QTest.qWait(100)
        window.dashboard.workspace.project_view(project)
        window.grab().save(str(output / "project.png"))
        for _ in range(10):
            window.notification_drawer.toggle_at(window.notifications_button)
            QTest.qWait(50)
            assert not window.notification_drawer.isWindow()
            window.notification_drawer.hide()
        window.notification_drawer.toggle_at(window.notifications_button)
        window.notification_drawer.grab().save(str(output / "birthdays.png"))
        window.notification_drawer.hide()
        dialog = PlannerDialog(repo, window.i18n, repo.list_planner_tasks()[0], window)
        image = Path(__file__).resolve().parents[1] / "src/somniloop/assets/rave/cat.png"
        if image.exists():
            dialog.description_edit.insert_image(image.read_bytes())

        def inspect():
            window.grab().save(str(output / "editor.png"))
            dialog.date_field.open_picker()
            dialog.date_field.popup.grab().save(str(output / "dates.png"))
            dialog.date_field.popup.close()
            dialog.reject()

        QTimer.singleShot(150, inspect)
        dialog.exec()
        window.resize(1000, 700)
        QTest.qWait(200)
        window.close()
        app.processEvents()
    print(output)


if __name__ == "__main__":
    main()

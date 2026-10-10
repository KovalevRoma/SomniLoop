"""Exercise the timeline on Linux with disposable, non-personal task data."""

import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.ui.controls import RoundedDialog
from somniloop.ui.main_window import MainWindow


def main():
    app = QApplication([])
    output = Path(tempfile.mkdtemp(prefix="somniloop-timeline-"))
    with tempfile.TemporaryDirectory() as directory:
        repo = Repository(Path(directory) / "smoke.db")
        repo.set_setting("live2d_config", '{"enabled":false}')
        projects = [
            repo.save_work_project(name, color=color)
            for name, color in (("Работа", "#438bed"), ("Дом", "#36b6a0"), ("Учёба", "#b379df"))
        ]
        for offset in range(-12, 70):
            for number in range((offset * 7 % 5) + 1):
                identifier = repo.save_planner_task(
                    f"Задача {offset + 13}.{number + 1}", date.today() + timedelta(days=offset)
                )
                repo.save_work_item("planner", identifier, project_id=projects[number % 3])
                if number == 0 and offset % 3 == 0:
                    repo.complete_planner_task(identifier)
        repo.save_planner_task("Идея без срока", None)
        repo.capture_work("Разобраться с документами для отпуска")
        for name, offset in (("Анна", 0), ("Марк", 0), ("София", 4)):
            person = repo.create_person(name)
            birthday = date.today() + timedelta(days=offset)
            repo.connection.execute(
                "UPDATE people SET birth_date=? WHERE id=?", (f"--{birthday:%m-%d}", person)
            )
        repo.connection.commit()
        repo.close()
        for theme in ("light", "dark"):
            repo = Repository(Path(directory) / "smoke.db")
            repo.set_setting("theme", theme)
            window = MainWindow(repo)
            window.resize(1280, 800)
            window.show()
            window.dashboard.workspace.tabs.setCurrentIndex(4)
            QTest.qWait(100)
            chart = window.dashboard.workspace.timeline
            window.grab().save(str(output / f"{theme}.png"))
            month = QDate.currentDate()
            boundary = QDate(month.year(), month.month(), 1).addMonths(1).toPython()
            chart.scroll.setValue(round(chart.canvas.day_x(boundary - timedelta(days=8))))
            QTest.qWait(50)
            window.grab().save(str(output / f"{theme}-boundary.png"))

            def inspect_day():
                dialog = next(
                    w for w in app.allWidgets() if isinstance(w, RoundedDialog) and w.isVisible()
                )
                dialog.grab().save(str(output / f"{theme}-day.png"))
                dialog.reject()

            QTimer.singleShot(100, inspect_day)
            chart.open_details(date.today() + timedelta(days=2))

            window.dashboard.workspace.tabs.setCurrentIndex(0)
            QTest.qWait(100)
            assert not chart.isVisible()
            assert any(row.isVisible() for row in window.dashboard.workspace.rows.values())
            window.grab().save(str(output / f"{theme}-tasks.png"))
            window.close()
            window.deleteLater()
            app.processEvents()
    print(output)


if __name__ == "__main__":
    main()

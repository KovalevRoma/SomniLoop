"""Render the real workspace on a temporary database, without personal data."""

import argparse
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.core.models import ScheduleType, TrackerMode
from somniloop.ui.main_window import MainWindow
from somniloop.ui.planner import PlannerDialog
from somniloop.ui.project_tile import ProjectGrid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--width", type=int, default=1100)
    args = parser.parse_args()
    app = QApplication([])
    output = Path(tempfile.mkdtemp(prefix="somniloop-workspace-"))
    with tempfile.TemporaryDirectory() as directory:
        repo = Repository(Path(directory) / "smoke.db")
        repo.set_setting("live2d_config", '{"enabled":false}')
        repo.set_setting("theme", args.theme)
        project = repo.save_work_project("Преподавание детям", "Подготовить и провести четыре занятия", color="#278b71")
        repo.save_work_project("Отпуск", "Спланировать поездку", color="#a45db2")
        for i, title in enumerate(("Подготовить занятие по дробям", "Проверить домашние работы", "Забронировать билеты")):
            identifier = repo.save_planner_task(title, date.today() + timedelta(days=i - 1), items=["Первый шаг", "Проверить результат"])
            repo.save_work_item("planner", identifier, project_id=project if i < 2 else None,
                                priority=1 if i == 0 else 0, next_action="Открыть конспект и выбрать три примера" if i == 0 else "")
        repo.create_tracker("Разминка", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["10 минут"])
        repo.capture_work("Уточнить даты отпуска")
        window = MainWindow(repo)
        window.resize(args.width, 790)
        window.show()
        QTest.qWait(250)
        assert window.width() == args.width, (window.width(), args.width)
        workspace = window.dashboard.workspace
        for view, name in ((0, "tasks"), (1, "habits"), (2, "projects"), (3, "inbox")):
            workspace.tabs.setCurrentIndex(view)
            QTest.qWait(150)
            assert window.dashboard.scroll.horizontalScrollBar().maximum() == 0
            window.grab().save(str(output / f"{name}.png"))
            if name == "projects":
                grid = next(w for w in workspace.extra_widgets if isinstance(w, ProjectGrid))
                grid.begin(grid.tiles[0].identifier)
                grid.preview(QPoint(grid.width() - 1, 10))
                QTest.qWait(50)
                window.grab().save(str(output / "drag-preview.png"))
                grid.cancel()
        workspace.tabs.setCurrentIndex(0)
        QTest.qWait(100)
        dialog = PlannerDialog(repo, window.i18n, parent=window)
        dialog.description_edit.set_source(
            "## Подготовка занятия\n\n**Главное:** объяснить дроби на примерах.\n\n"
            "<details>\n<summary>Материалы</summary>\n\n"
            "- Рабочая тетрадь\n- [Ссылка](https://example.com)\n\n</details>"
        )
        def inspect_editor():
            window.grab().save(str(output / "task-editor.png"))
            QTest.mouseClick(dialog.date_field, Qt.MouseButton.LeftButton)
            popup = dialog.date_field.popup
            assert popup.isVisible()
            popup.grab().save(str(output / "date-picker.png"))
            popup.select_day(popup.month.addDays(10))
            assert dialog.date_field.day
            popup.close()
            dialog.reject()
        QTimer.singleShot(150, inspect_editor)
        dialog.exec()
        window.close()
        app.processEvents()
        repo.close()
    print(output)


if __name__ == "__main__":
    main()

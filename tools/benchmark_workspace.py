"""Measure workspace updates on synthetic data; never open the user's database."""

import json
import statistics
import tempfile
import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.ui.main_window import MainWindow
from somniloop.ui.project_tile import ProjectGrid


def main():
    app = QApplication([])
    output = Path(tempfile.mkdtemp(prefix="somniloop-render-benchmark-"))
    repo = Repository(output / "synthetic.db")
    repo.set_setting("live2d_config", '{"enabled":false}')
    projects = [repo.save_work_project(f"Project {index + 1}") for index in range(24)]
    for index in range(120):
        task = repo.save_planner_task(f"Task {index + 1}", date.today())
        repo.save_work_item("planner", task, project_id=projects[index % len(projects)])
    window = MainWindow(repo)
    window.resize(1280, 790)
    window.show()
    QTest.qWait(150)
    work = window.dashboard.workspace
    queries = []
    repo.connection.set_trace_callback(queries.append)
    start = time.perf_counter()
    for _ in range(100):
        work.render()
    task_updates_ms = (time.perf_counter() - start) * 1000
    task_queries = len(queries)
    work.tabs.setCurrentIndex(2)
    QTest.qWait(100)
    grid = next(w for w in work.extra_widgets if isinstance(w, ProjectGrid))
    queries.clear()
    start = time.perf_counter()
    for _ in range(100):
        work.render()
    project_updates_ms = (time.perf_counter() - start) * 1000
    project_queries = len(queries)
    grid.begin(projects[0])
    samples = []
    for index in range(120):
        start = time.perf_counter()
        grid.preview(QPoint((index % grid.columns) * (grid.cell_size + 12) + 20, 20))
        samples.append((time.perf_counter() - start) * 1000)
        QTest.qWait(8)
        if index in (4, 5, 6):
            window.grab().save(str(output / f"transition-{index}.png"))
    grid.cancel()
    QTest.qWait(220)
    window.grab().save(str(output / "settled.png"))
    report = {
        "projects": 24, "tasks": 120, "live2d_enabled": False,
        "100_task_refreshes_ms": round(task_updates_ms, 2), "task_refresh_queries": task_queries,
        "100_project_refreshes_ms": round(project_updates_ms, 2), "project_refresh_queries": project_queries,
        "drag_update_p50_ms": round(statistics.median(samples), 3),
        "drag_update_p95_ms": round(sorted(samples)[int(len(samples) * .95)], 3),
        "animation_active_after_settle": grid.motion.state() != grid.motion.State.Stopped,
        "scroll_timer_active_after_settle": grid.scroll_timer.isActive(),
        "artifacts": str(output),
    }
    repo.connection.set_trace_callback(None)
    window.close()
    app.processEvents()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

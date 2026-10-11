import json
from datetime import date, timedelta

import pytest
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QPushButton

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.image_block import ImageBlock
from somniloop.ui.planner import NotificationDrawer, PlannerDialog
from somniloop.ui.task_date_picker import TaskDatePopup


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    value = Repository(tmp_path / "extras.db")
    yield value
    value.close()


def test_today_is_distinct_from_selected_date(app):
    anchor = QPushButton()
    popup = TaskDatePopup(anchor, "en", QDate.currentDate().addDays(1).toString("yyyy-MM-dd"))
    popup.month = QDate(QDate.currentDate().year(), QDate.currentDate().month(), 1)
    popup.render_month()
    today = next(b for b in popup.days if b.property("date") == QDate.currentDate())
    assert today.property("today") and not today.isChecked()
    assert "Today" in today.toolTip()
    popup.close()


def test_project_calendar_filters_and_lists_times(app, repo):
    project = repo.save_work_project("Work")
    other = repo.save_work_project("Home")
    for title, clock, group in (("Meeting", "10:30", project), ("Read", "", project),
                                ("Hidden", "12:00", other)):
        identifier = repo.save_planner_task(title, date.today(), due_time=clock)
        repo.save_work_item("planner", identifier, project_id=group)
    dialog = PlannerDialog(repo, I18n("en"))
    dialog.project.setCurrentIndex(dialog.project.findData(project))
    dialog.date_field.open_picker()
    popup = dialog.date_field.popup
    button = next(b for b in popup.days if b.property("date") == QDate.currentDate())
    assert "·" in button.text()
    assert "10:30 — Meeting" in button.toolTip()
    assert "No time — Read" in button.toolTip()
    assert "Hidden" not in button.toolTip()
    popup.close()
    dialog.close()


def test_project_view_adds_task_in_current_project(app, repo, monkeypatch):
    project = repo.save_work_project("Work")
    page = Dashboard(repo, I18n("en"), productivity=True)
    workspace = page.workspace
    workspace.project_view(project)
    assert not workspace.add_project_task.isHidden()

    def save(dialog):
        assert dialog.project.currentData() == project
        dialog.title_edit.setText("New task")
        dialog._save()
        return 1

    monkeypatch.setattr(PlannerDialog, "exec", save)
    workspace.add_project_task.click()
    task = repo.list_planner_tasks()[0]
    assert repo.work_metadata()[("planner", task.id)]["project_id"] == project
    assert workspace.project_filter.currentData() == project
    page.close()


def test_image_attachments_survive_source_removal_and_cancel(app, repo, tmp_path):
    source = tmp_path / "example.png"
    image = QImage(30, 20, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(source))
    dialog = PlannerDialog(repo, I18n("en"))
    dialog.title_edit.setText("With picture")
    app.clipboard().setImage(image)
    dialog.description_edit.active.paste()
    assert repo.list_planner_tasks() == []
    dialog._save()
    task = repo.list_planner_tasks()[0]
    source.unlink()
    saved = task.description
    assert "<somniloop-image" in saved
    editor = PlannerDialog(repo, I18n("en"), task)
    block = next(b for b in editor.description_edit.blocks if isinstance(b, ImageBlock))
    assert not block.pixmap.isNull()
    block.remove()
    editor.reject()
    assert repo.list_planner_tasks()[0].description == saved
    payload = json.loads(json.dumps(repo.export_payload()))
    repo.save_task_images(task.id, [])
    repo.restore_payload(payload)
    assert repo.list_planner_tasks()[0].description == saved
    repo.connection.execute("DELETE FROM planner_tasks WHERE id=?", (task.id,))
    repo.connection.commit()
    assert repo.task_images(task.id) == []


def test_invalid_attachment_does_not_modify_staged_images(app, repo, tmp_path):
    source = tmp_path / "not-an-image.png"
    source.write_bytes(b"invalid")
    dialog = PlannerDialog(repo, I18n("en"))
    with pytest.raises(ValueError):
        dialog.description_edit.insert_image(source.read_bytes())
    assert not any(isinstance(b, ImageBlock) for b in dialog.description_edit.blocks)
    dialog.close()


def test_birthday_popup_orders_upcoming_and_excludes_stale_notices(app, repo):
    for name, offset in (("Later", 15), ("Now", 0), ("Soon", 3)):
        person = repo.create_person(name)
        day = date.today() + timedelta(days=offset)
        repo.connection.execute("UPDATE people SET birth_date=? WHERE id=?",
                                (day.strftime("--%m-%d"), person))
    repo.connection.commit()
    anchor = QPushButton()
    popup = NotificationDrawer(repo, I18n("en"), anchor)
    assert not popup.isWindow()
    labels = [popup.list.item(i).text() for i in range(popup.list.count())]
    assert "Now" in labels[0] and "Today" in labels[0]
    assert "Soon" in labels[1] and "Later" in labels[2]
    popup.close()

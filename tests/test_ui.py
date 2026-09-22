import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import ScheduleType, TrackerMode
from somniloop.ui.dashboard import Dashboard, TrackerCard
from somniloop.ui.dialogs import CreateTrackerDialog
from somniloop.ui.personal_dialogs import BioDialog
from somniloop.ui.widgets import SmartPlainTextEdit


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def test_created_tracker_immediately_appears_on_dashboard(tmp_path, application):
    repository = Repository(tmp_path / "ui.db")
    dialog = CreateTrackerDialog(I18n("ru"))
    dialog.name_edit.setText("Спорт")
    dialog.tasks_edit.setPlainText("Разминка\nТренировка")
    values = dialog.values()
    assert isinstance(values["mode"], TrackerMode)
    assert isinstance(values["schedule_type"], ScheduleType)
    assert values["mode"] == TrackerMode.REGULAR
    assert values["schedule_type"] == ScheduleType.DAILY

    dashboard = Dashboard(repository, I18n("ru"))
    repository.create_tracker(**values)
    dashboard.refresh()
    application.processEvents()

    cards = dashboard.findChildren(TrackerCard)
    assert len(cards) == 1
    assert any(label.text() == "Спорт" for label in cards[0].findChildren(type(dialog.tasks_label)))
    repository.close()


def test_cancelling_bio_discards_draft_and_save_closes(tmp_path, application):
    repository = Repository(tmp_path / "bio.db")
    dialog = BioDialog(repository, I18n("ru"))
    dialog.name_edit.setText("Роман")
    dialog.bio_edit.setPlainText("Живу в Бремене")
    dialog.reject()
    assert repository.get_profile() == ("", "")

    second = BioDialog(repository, I18n("ru"))
    second.name_edit.setText("Роман")
    second.bio_edit.setPlainText("Обновлённое био")
    second._save_and_close()
    assert second.result() == second.DialogCode.Accepted
    assert repository.get_profile() == ("Роман", "Обновлённое био")
    repository.close()


def test_down_on_last_line_moves_cursor_to_document_end(application):
    editor = SmartPlainTextEdit()
    editor.setPlainText("первая строка\nпоследняя строка")
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
    editor.setTextCursor(cursor)
    editor.show()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_Down)
    assert editor.textCursor().position() == len(editor.toPlainText())

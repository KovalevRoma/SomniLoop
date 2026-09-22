"""Embedded input routing, constrained resizing, and compact workspace regressions."""

import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import ScheduleType, TrackerMode
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.personal_dialogs import PeopleDialog
from somniloop.ui.planner import PlannerDialog
from somniloop.ui.theme import stylesheet


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    value = Repository(tmp_path / "ui.db")
    yield value
    value.close()


def drive(dialog, callback):
    errors = []

    def act():
        try:
            callback()
        except Exception as exc:
            errors.append(exc)
        finally:
            if dialog.isVisible():
                dialog.reject()

    QTimer.singleShot(40, act)
    result = dialog.exec()
    if errors:
        raise errors[0]
    return result


def host_window():
    host = QMainWindow()
    body = QWidget()
    layout = QVBoxLayout(body)
    edit = QLineEdit("unchanged")
    button = QPushButton("Background")
    layout.addWidget(edit)
    layout.addWidget(button)
    host.setCentralWidget(body)
    host.resize(980, 700)
    host.show()
    return host, edit, button


def test_overlay_blocks_background_centers_resizes_and_restores_focus(app, repo):
    host, edit, button = host_window()
    clicked = []
    button.clicked.connect(lambda: clicked.append("click"))
    shortcut = QShortcut(QKeySequence("Ctrl+K"), host)
    shortcut.activated.connect(lambda: clicked.append("shortcut"))
    edit.setFocus()
    dialog = PlannerDialog(repo, I18n("ru"), parent=host)

    def check():
        overlay = dialog._modal_overlay
        assert not dialog.isWindow()
        assert dialog.window() is host
        assert not host.centralWidget().isEnabled()
        assert dialog.isEnabled()
        QTest.mouseClick(
            host.windowHandle(),
            Qt.MouseButton.LeftButton,
            pos=button.mapTo(host, button.rect().center()),
        )
        QTest.keyClicks(edit, "bad")
        QTest.keyClick(host, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        assert edit.text() == "unchanged"
        assert not clicked
        for width, height in [(980, 700), (820, 560), (1280, 850)]:
            host.resize(width, height)
            app.processEvents()
            assert overlay.geometry() == host.rect()
            assert host.rect().contains(overlay.panel.geometry())
            assert (overlay.panel.geometry().center() - host.rect().center()).manhattanLength() <= 2
        dialog.title_edit.setText("saved")
        box = dialog.findChild(QDialogButtonBox)
        save = box.button(QDialogButtonBox.StandardButton.Save)
        overlay.scroll.ensureWidgetVisible(save)
        QTest.mouseClick(
            host.windowHandle(),
            Qt.MouseButton.LeftButton,
            pos=save.mapTo(host, save.rect().center()),
        )
        assert not dialog.isVisible()

    assert drive(dialog, check) == dialog.DialogCode.Accepted
    assert host.centralWidget().isEnabled()
    assert host.focusWidget() is edit
    assert len(repo.list_planner_tasks()) == 1
    host.close()


def test_nested_modal_keeps_outer_modal_active_and_escape_discards(app, repo):
    host, _, _ = host_window()
    outer = PlannerDialog(repo, I18n("ru"), parent=host)

    def check_outer():
        inner = PlannerDialog(repo, I18n("ru"), parent=outer)

        def check_inner():
            assert len(host._modal_overlays) == 2
            assert inner.isEnabled()
            assert not outer.isEnabled()
            QTest.keyClick(inner.title_edit, Qt.Key.Key_Escape)
            assert not inner.isVisible()

        assert drive(inner, check_inner) == inner.DialogCode.Rejected
        assert outer.isEnabled() and outer.isVisible()
        assert not host.centralWidget().isEnabled()
        QTest.keyClick(outer.title_edit, Qt.Key.Key_Escape)

    assert drive(outer, check_outer) == outer.DialogCode.Rejected
    assert host.centralWidget().isEnabled()
    assert not repo.list_planner_tasks()
    host.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(980, 700), (1280, 720)])
def test_small_dashboard_fits_and_large_dashboard_still_scrolls(app, repo, theme, size):
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet(theme))
    repo.create_tracker(
        "Прогулка", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["Пройтись", "Выпить воды"]
    )
    repo.save_planner_task("Позвонить", date.today(), "", [])
    page = Dashboard(repo, I18n("ru"))
    # Reserve the main window's navigation/header height.
    page.resize(size[0] - 32, size[1] - 100)
    page.show()
    # Wayland configures surfaces asynchronously, unlike the offscreen backend.
    for _ in range(20):
        QTest.qWait(50)
        if page.scroll.verticalScrollBar().maximum() == 0:
            break
    assert page.scroll.verticalScrollBar().maximum() == 0, (
        page.size(),
        page.columns.size(),
        page.columns.wide,
        page.today.columns,
        page.scroll.verticalScrollBar().maximum(),
    )
    assert page.scroll.horizontalScrollBar().maximum() == 0
    for index in range(20):
        repo.create_tracker(
            f"Привычка {index}", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["Пункт"]
        )
    page.refresh()
    QTest.qWait(40)
    assert page.scroll.verticalScrollBar().maximum() > 0
    assert page.scroll.horizontalScrollBar().maximum() == 0
    page.close()
    app.setStyleSheet(previous)


@pytest.mark.parametrize("size", [(980, 680), (1180, 820)])
def test_people_fields_do_not_collapse_or_overlap(app, repo, size):
    repo.create_person("Анна")
    dialog = PeopleDialog(repo, I18n("ru"))
    dialog.resize(*size)
    dialog.show()
    app.processEvents()
    fields = [
        dialog.name_edit,
        dialog.relationship_edit,
        dialog.contact_edit,
        dialog.group_edit,
        dialog.interests_edit,
    ]
    assert len({field.x() for field in fields}) == 1
    assert all(field.height() >= 34 for field in fields)
    assert 200 <= dialog.person_list.width() <= 240
    assert dialog.editor_scroll.horizontalScrollBar().maximum() == 0
    assert dialog.birthday_edit.picker.y() >= dialog.birthday_edit.known.geometry().bottom()
    assert dialog.story_edit.width() > dialog.name_edit.width()
    assert dialog.findChild(QDialogButtonBox).isVisible()
    dialog.close()

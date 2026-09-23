"""Exercise window hit-testing and modal menu workflows, not button.click()."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.ui.action_feedback import ActionPulse
from somniloop.ui.dialogs import CreateTrackerDialog, SettingsDialog, TaskEditDialog
from somniloop.ui.main_window import MainWindow
from somniloop.ui.personal_dialogs import BioDialog, ClarificationDialog, PersonDetailsDialog
from somniloop.ui.planner import PlannerDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def routed_click(window, widget):
    window = window.window()
    QTest.mouseClick(
        window.windowHandle(),
        Qt.MouseButton.LeftButton,
        pos=widget.mapTo(window, widget.rect().center()),
    )


@pytest.mark.parametrize("action", ["save", "cancel"])
@pytest.mark.parametrize("kind", ["habit", "plan", "task"])
def test_add_menu_modal_workflow_with_window_routed_clicks(app, tmp_path, kind, action):
    repo = Repository(tmp_path / "workflow.db")
    window = MainWindow(repo)
    window.show()
    QTest.qWait(30)
    menu = window.dashboard.add.menu()
    menu.popup(window.dashboard.add.mapToGlobal(window.dashboard.add.rect().bottomLeft()))
    QTest.qWait(20)
    observations = []

    def act():
        overlays = getattr(window, "_modal_overlays", [])
        dialog = overlays[-1].dialog if overlays else app.activeModalWidget()
        if not isinstance(dialog, (PlannerDialog, CreateTrackerDialog)):
            observations.append("no modal dialog")
            return
        # Native decorations must not alter the form's input region.
        observations.append(dialog.mask().isEmpty())
        observations.append(not dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        field = dialog.title_edit if kind == "task" else dialog.name_edit
        field.setText("Проверка " + kind)
        standard = (
            QDialogButtonBox.StandardButton.Save
            if action == "save"
            else QDialogButtonBox.StandardButton.Cancel
        )
        button = dialog._modal_overlay.buttons.button(standard)
        routed_click(dialog, button)
        observations.append(not dialog.isVisible())

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(
        lambda: (
            window._modal_overlays[-1].dialog.reject()
            if getattr(window, "_modal_overlays", [])
            else None
        )
    )
    watchdog.start(2000)
    QTimer.singleShot(50, act)
    item = menu.actions()[["habit", "plan", "task"].index(kind)]
    QTest.mouseClick(
        menu.windowHandle(), Qt.MouseButton.LeftButton, pos=menu.actionGeometry(item).center()
    )
    QTest.qWait(80)
    watchdog.stop()
    tasks = repo.list_planner_tasks() if kind == "task" else repo.list_trackers()
    window.close()
    assert observations == [True, True, True]
    assert len(tasks) == (1 if action == "save" else 0)


@pytest.mark.parametrize("kind", ["task", "habit"])
def test_invalid_save_explains_problem_and_cancel_remains_clickable(app, tmp_path, kind):
    repo = Repository(tmp_path / "validation.db")
    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    dialog = (
        PlannerDialog(repo, I18n("ru"), parent=parent)
        if kind == "task"
        else CreateTrackerDialog(I18n("ru"), parent)
    )
    dialog.show()
    QTest.qWait(20)
    box = dialog.findChild(QDialogButtonBox)
    routed_click(dialog, box.button(QDialogButtonBox.StandardButton.Save))
    app.processEvents()
    assert dialog.isVisible()
    assert dialog.validation_message.isVisible()
    assert "название" in dialog.validation_message.text()
    routed_click(dialog, box.button(QDialogButtonBox.StandardButton.Cancel))
    assert not dialog.isVisible()
    parent.close()
    repo.close()


@pytest.mark.parametrize("save", [True, False])
@pytest.mark.parametrize("kind", ["settings", "bio", "item", "clarification", "person"])
def test_other_editor_actions_close_and_animate_via_window_input(app, tmp_path, save, kind):
    from types import SimpleNamespace

    repo = Repository(tmp_path / "other-dialogs.db")
    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    language = I18n("ru")
    makers = {
        "settings": lambda: SettingsDialog(repo, language, parent),
        "bio": lambda: BioDialog(repo, language, parent),
        "item": lambda: TaskEditDialog(language, False, parent=parent),
        "clarification": lambda: ClarificationDialog("Вопрос", "Ответ", language, parent),
        "person": lambda: PersonDetailsDialog(
            SimpleNamespace(biography="Био", education="", occupation="", facts=[]),
            language,
            parent,
        ),
    }
    dialog = makers[kind]()
    if hasattr(dialog, "name_edit"):
        dialog.name_edit.setText("Тест")
    dialog.show()
    QTest.qWait(20)
    role = QDialogButtonBox.StandardButton.Save if save else QDialogButtonBox.StandardButton.Cancel
    routed_click(dialog, dialog.findChild(QDialogButtonBox).button(role))
    app.processEvents()
    assert not dialog.isVisible()
    assert dialog.result() == (dialog.DialogCode.Accepted if save else dialog.DialogCode.Rejected)
    pulses = parent.findChildren(ActionPulse)
    assert pulses and pulses[-1].isVisible()
    assert pulses[-1].testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    parent.close()
    repo.close()

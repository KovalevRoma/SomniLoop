import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import KnowledgeEdge, KnowledgeNode, ScheduleType, TaskState, TrackerMode
from somniloop.ui.calendar_widgets import RoundCalendar
from somniloop.ui.controls import (
    BirthdayEdit,
    MonthSpinBox,
    ScrollDateEdit,
    linked_text,
    open_in_firefox,
    rich_details,
    show_saved,
)
from somniloop.ui.dashboard import Dashboard, TrackerCard
from somniloop.ui.dialogs import SettingsDialog, TelegramMappingDialog
from somniloop.ui.knowledge_graph import GraphProgressDialog, GraphView, KnowledgeGraphPage
from somniloop.ui.main_window import MainWindow
from somniloop.ui.personal_dialogs import DiaryDialog, PeopleDialog
from somniloop.ui.widgets import SmartPlainTextEdit


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "ui.db")
    yield repository
    repository.close()


def test_scroll_dates_clamp_days_and_disallow_typing(app):
    editor = ScrollDateEdit(QDate(2026, 1, 31))
    editor.month_combo.setCurrentIndex(1)
    assert editor.date() == QDate(2026, 2, 28)
    assert editor.day_spin.lineEdit().isReadOnly()
    assert editor.year_spin.lineEdit().isReadOnly()
    assert not editor.month_combo.isEditable()
    assert editor.month_combo.currentText() == "фев"
    month = MonthSpinBox()
    month.setValue(7)
    assert month.text() == "июл"
    assert editor.calendar_button.text() == "Выбрать дату"


def test_birthday_can_omit_year(app):
    editor = BirthdayEdit("--02-29")
    assert editor.value() == "--02-29"
    editor.set_value("2000-07-28")
    assert editor.value() == "2000-07-28"
    editor.year_known.setChecked(False)
    assert editor.value() == "--07-28"
    editor.known.setChecked(False)
    assert editor.value() == ""


def test_telegram_mapping_buttons_accept_and_cancel_mouse_clicks(app, repo):
    scan = {
        "chats": 1,
        "messages": 11,
        "identities": [
            {
                "telegram_id": "user42",
                "name": "Ирина Ковалёва",
                "messages": 7,
                "last_message_date": "2026-09-15",
            }
        ],
        "personal_chats": [
            {
                "telegram_id": "user42",
                "name": "Ирина Ковалёва",
                "messages": 11,
                "last_message_date": "2026-09-15",
            }
        ],
    }
    load_dialog = TelegramMappingDialog(repo, scan, I18n("ru"))
    load_dialog.show()
    QTest.mouseClick(load_dialog.load_all_button, Qt.MouseButton.LeftButton)
    assert load_dialog.result() == QDialog.DialogCode.Accepted

    cancel_dialog = TelegramMappingDialog(repo, scan, I18n("ru"))
    cancel_dialog.show()
    QTest.mouseClick(cancel_dialog.cancel_import_button, Qt.MouseButton.LeftButton)
    assert cancel_dialog.result() == QDialog.DialogCode.Rejected


def test_load_all_button_runs_the_complete_telegram_import(app, repo, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    scan = {
        "path": "/tmp/result.json",
        "size": 100,
        "mtime_ns": 1,
        "owner_id": "user1",
        "owner_name": "Роман",
        "chats": 1,
        "messages": 11,
        "identities": [
            {
                "telegram_id": "user42",
                "name": "Ирина Ковалёва",
                "messages": 6,
                "chats": ["42"],
                "first_date": "2026-09-01",
                "last_date": "2026-09-15",
                "last_message_date": "2026-09-15",
            }
        ],
        "personal_chats": [
            {
                "chat_id": "42",
                "chat_ids": ["42"],
                "telegram_id": "user42",
                "name": "Ирина Ковалёва",
                "messages": 11,
                "last_message_date": "2026-09-15",
            }
        ],
    }
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    settings = SettingsDialog(repo, I18n("ru"))

    def click_load_all():
        mapping = QApplication.activeModalWidget()
        assert isinstance(mapping, TelegramMappingDialog)
        QTest.mouseClick(mapping.load_all_button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, click_load_all)
    settings._telegram_scanned(scan)

    manifest = repo.telegram_manifest()
    assert manifest["identity_map"]["user42"]["person_id"]
    assert "Связано людей: 1" in settings.telegram_status.text()
    settings.reject()


def test_people_collapse_into_named_groups_when_zoomed_out(app):
    view = GraphView()
    nodes = [
        KnowledgeNode("me", "Я", "people", "", {"is_owner": True}),
        KnowledgeNode("anna", "Анна", "people", "", {"group": "Друзья"}),
        KnowledgeNode("ira", "Ирина", "people", "", {"group": "Друзья"}),
    ]
    view.set_graph(
        nodes,
        [KnowledgeEdge("me", "anna", "знает"), KnowledgeEdge("me", "ira", "знает")],
    )
    view.resetTransform()
    view.scale(0.2, 0.2)
    view._update_cluster_visibility()
    assert any(
        item.isVisible() and item.node.label == "Друзья · 2" for item in view.clusters.values()
    )
    assert not view.nodes["anna"].isVisible()


def test_annual_date_picker_supports_leap_day(app):
    editor = ScrollDateEdit(QDate(2026, 2, 28))
    editor.setDisplayFormat("dd.MM")
    editor.day_spin.setValue(29)
    assert editor.date() == QDate(2000, 2, 29)


def test_calendar_has_six_weeks_and_monday_first(app):
    calendar = RoundCalendar(QDate(2026, 8, 28))
    assert len(calendar.buttons) == 42
    assert calendar.buttons[0].day.weekday() == 0
    assert sum(button.selected for button in calendar.buttons) == 1
    assert calendar.month_label.text() == "авг 2026"
    calendar._move_month(1)
    assert calendar.monthShown() == 9


def test_diary_autosave_registers_first_entry_and_keeps_cursor(app, repo):
    diary = DiaryDialog(repo, I18n("ru"))
    diary.show()
    diary.content_edit.setPlainText("Не потерять этот текст")
    cursor = diary.content_edit.textCursor()
    cursor.setPosition(3)
    diary.content_edit.setTextCursor(cursor)
    diary._save_current(refresh=False)
    assert diary.entry_list.count() == 1
    assert diary.current_note_id is not None
    assert diary.content_edit.textCursor().position() == 3
    assert repo.list_notes()[0].content == "Не потерять этот текст"
    assert "Изменено" in diary.updated_label.text() or "изменени" in diary.updated_label.text()
    diary.reject()


def test_diary_switching_and_closing_keeps_unsaved_edits(app, repo):
    repo.save_note("Первый", "A", entry_date="2026-08-01")
    repo.save_note("Второй", "B", entry_date="2026-08-02")
    diary = DiaryDialog(repo, I18n("ru"))
    first_id = diary.current_note_id
    diary.content_edit.setPlainText("Новая версия")
    diary.entry_list.setCurrentRow(1)
    assert next(note for note in repo.list_notes() if note.id == first_id).content == "Новая версия"
    second_id = diary.current_note_id
    diary.content_edit.setPlainText("Закрыл случайно")
    diary.reject()
    assert (
        next(note for note in repo.list_notes() if note.id == second_id).content
        == "Закрыл случайно"
    )


def test_noop_person_save_does_not_mark_graph_stale(app, repo):
    person_id = repo.create_person("Анна")
    repo.save_person_input(
        person_id, "Анна", "подруга", "Текст", birth_date="2000-07-28", interests="Шахматы"
    )
    dialog = PeopleDialog(repo, I18n("ru"))
    emissions = []
    dialog.data_changed.connect(lambda: emissions.append(True))
    dialog._save_current()
    assert not emissions
    dialog.interests_edit.setText("Шахматы и плавание")
    dialog.reject()
    assert repo.get_person(person_id).interests_input == "Шахматы и плавание"


def test_graph_search_matches_facts_not_just_names(app, repo):
    repo.replace_knowledge_graph(
        [
            KnowledgeNode("anna", "Анна", "people", "Училась в МГУ. Любит шахматы."),
            KnowledgeNode("city", "Бремен", "places", "Город"),
        ],
        [],
    )
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page.search.setText("мгу шахматы")
    page._search_changed()
    assert page.results.count() == 1
    assert "Анна" in page.results.item(0).text()
    page._result_selected(page.results.item(0))
    assert page.node_title.text() == "Анна"
    assert "events" not in page.filter_buttons
    page.close()


def test_graph_animation_stops_when_hidden(app):
    view = GraphView()
    view.set_graph([KnowledgeNode("a", "Анна", "people", "")], [])
    view.show()
    app.processEvents()
    assert view.timer.isActive()
    view.hide()
    assert not view.timer.isActive()


def test_save_effect_is_short_lived_and_does_not_steal_clicks(app):
    parent = SmartPlainTextEdit()
    parent.resize(600, 400)
    parent.show()
    show_saved(parent)
    effect = parent._save_celebration
    assert effect.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    QTest.qWait(1000)
    assert not parent.findChildren(type(effect))
    parent.close()


def test_wrapped_last_block_down_moves_one_visual_line(app):
    editor = SmartPlainTextEdit()
    editor.resize(160, 150)
    editor.setPlainText("Одна длинная строка " * 20)
    editor.show()
    app.processEvents()
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_Down)
    assert 0 < editor.textCursor().position() < len(editor.toPlainText())
    editor.close()


def test_links_are_escaped_and_only_open_web_urls(app, monkeypatch):
    from somniloop.ui import controls

    calls = []
    monkeypatch.setattr(
        controls.QDesktopServices,
        "openUrl",
        lambda url: calls.append(url.toString()) or True,
    )
    assert open_in_firefox("https://example.org/a?x=1&y=2")
    assert calls == ["https://example.org/a?x=1&y=2"]
    assert not open_in_firefox("file:///etc/passwd")
    assert not open_in_firefox("javascript:alert(1)")
    markup = linked_text('<script> https://example.org/?x="test"')
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "text-decoration:underline" in rich_details("⚠ Даты противоречат друг другу")


def test_main_window_has_archive_drawer_and_planner(app, tmp_path):
    repository = Repository(tmp_path / "main.db")
    window = MainWindow(repository)
    window.show()
    app.processEvents()
    assert not window.mask().isEmpty()
    assert window.grab().toImage().pixelColor(0, window.height() - 1).alpha() == 0
    assert window.dashboard.planner is not None
    assert window.notification_drawer.isHidden()
    assert any(button.text() == "Архив" for button in window.findChildren(QPushButton))
    window.notifications_button.click()
    assert window.notification_drawer.isVisible()
    window.close()


def test_dashboard_marks_today_without_opening_tracker(app, repo):
    tracker_id = repo.create_tracker(
        "Вода", "", TrackerMode.REGULAR, ScheduleType.DAILY, {}, ["Стакан воды"]
    )
    dashboard = Dashboard(repo, I18n("ru"))
    card = dashboard.findChild(TrackerCard)
    checkbox = next(iter(card.rows.rows.values())).done

    checkbox.click()
    app.processEvents()

    summary = repo.day_summary(tracker_id, QDate.currentDate().toPython())
    assert summary.tasks[0].state == TaskState.DONE


def test_graph_category_filter_keeps_connected_people(app, repo):
    repo.replace_knowledge_graph(
        [
            KnowledgeNode("me", "Я", "people"),
            KnowledgeNode("music", "Музыка", "interests"),
            KnowledgeNode("city", "Берлин", "places"),
        ],
        [
            KnowledgeEdge("me", "music", "любит"),
            KnowledgeEdge("me", "city", "живёт в"),
        ],
    )
    page = KnowledgeGraphPage(repo, I18n("ru"))

    page._set_category("interests")

    assert set(page.graph_view.nodes) == {"me", "music"}
    assert len(page.graph_view.edges) == 1
    assert page.graph_view.edges[0].label.text() == "любит"
    page.close()


def test_graph_worker_applies_results_and_cache_on_ui_thread(app, repo, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[-1]))
    repo.save_profile("Роман", "Хочу изучить испанский.")
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page._rebuild(offline=True)
    for _ in range(500):
        QTest.qWait(10)
        if not page.worker.isRunning():
            break
    app.processEvents()
    assert not page.worker.isRunning()
    assert not errors
    assert repo.load_knowledge_cache()
    assert all(
        node.category not in {"goals", "interests"} for node in repo.load_knowledge_graph()[0]
    )
    page.close()


def test_graph_progress_dialog_shows_stage_counts_and_can_be_reopened(app):
    dialog = GraphProgressDialog()
    cancelled = []
    dialog.cancel_requested.connect(lambda: cancelled.append(True))
    dialog.update_progress(
        {
            "phase": "analyze",
            "phase_index": 2,
            "phase_total": 5,
            "percent": 42.7,
            "title": "Рассказ об Анне",
            "changed_documents": 2,
            "pending_changes": 7,
            "processed_changes": 3,
            "planned_cached": 12,
            "model_calls": 3,
            "chunks": 19,
        }
    )

    assert dialog.bar.value() == 427
    assert "42,7%" == dialog.bar.format()
    assert "Этап 2 из 5" in dialog.phase_label.text()
    assert "3/7" in dialog.counts_label.text()
    dialog.show()
    dialog.close()
    assert dialog.isHidden()
    dialog.show()
    QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
    assert cancelled == [True]
    dialog.complete(False, "Остановлено")
    assert dialog.cancel_button.isEnabled()
    dialog.close()


def test_graph_eta_does_not_grow_when_no_work_completes(app, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("somniloop.ui.knowledge_graph.time.monotonic", lambda: now[0])
    dialog = GraphProgressDialog()
    event = {"phase": "analyze", "percent": 15, "processed_changes": 0, "pending_changes": 3}
    dialog.update_progress(event)
    now[0] = 300
    assert dialog._eta_seconds() is None
    # A fresh run: estimate from completed work, then count down within the phase.
    dialog.complete(False, "Остановлено")
    dialog.close()
    now[0] = 0
    dialog = GraphProgressDialog()
    dialog.update_progress(event)
    now[0] = 10
    dialog.update_progress({**event, "percent": 35, "processed_changes": 1})
    assert dialog._eta_seconds() == 20
    now[0] = 15
    assert dialog._eta_seconds() == 15
    now[0] = 31
    assert dialog._eta_seconds() is None
    dialog.complete(False, "Остановлено")
    dialog.close()


def test_graph_progress_uses_exact_plan_and_people_counts_without_retry_progress(app):
    dialog = GraphProgressDialog()
    event = {
        "phase": "connections",
        "phase_index": 4,
        "phase_total": 5,
        "percent": 91.6,
        "work_done": 207,
        "work_total": 399,
        "stage_done": 8,
        "stage_total": 198,
        "title": "Обработка человека",
        "model_calls": 54,
    }
    dialog.update_progress(event)
    assert "8/198 человек" in dialog.stage_bar.format()
    assert "4,04%" in dialog.stage_bar.format()
    assert "51,88%" in dialog.bar.format()
    assert "0/0" not in dialog.counts_label.text()
    progress = dialog.bar.value()
    dialog.update_progress({**event, "activity": "Повторяю меньший фрагмент", "model_calls": 55})
    assert dialog.bar.value() == progress
    dialog.complete(False, "Часть фрагментов требует повторной обработки")
    assert dialog.bar.value() == progress
    dialog.close()


def test_partial_connections_save_core_graph_and_offer_resume_without_offline_fallback(
    app, repo, monkeypatch
):
    import json

    from PySide6.QtWidgets import QMessageBox

    from somniloop.knowledge.pipeline import KnowledgeBuilder

    repo.save_profile("Тест", "")
    result = KnowledgeBuilder().build(repo.knowledge_source())
    result.stats.update(
        connections_done=197,
        connections_total=198,
        connection_failures=[
            {"id": "test", "name": "Проблемный фрагмент", "error": "Обрыв", "fragments": 1}
        ],
        work_done=397,
        work_total=399,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_: pytest.fail("Must not offer offline fallback for optional-skill failure"),
    )
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page.progress_dialog = GraphProgressDialog()
    page._build_done(result)
    assert repo.load_knowledge_graph()[0]
    assert "197/198" in page.build_status.text()
    assert page.rebuild.text() == "Продолжить поиск связей"
    assert page.progress_dialog.bar.value() < page.progress_dialog.bar.maximum()
    assert json.loads(repo.get_setting("graph_connections_report"))["failures"]
    page.progress_dialog.close()
    page.close()
    reopened = KnowledgeGraphPage(repo, I18n("ru"))
    assert "197/198" in reopened.build_status.text()
    reopened.close()


def test_person_editor_only_saves_source_data(app, repo):
    person_id = repo.create_person("Анна")
    repo.save_person_input(person_id, "Анна", "подруга", "Училась в МГУ.")
    repo.save_person_analysis(person_id, {"occupation": "Архитектор"})
    dialog = PeopleDialog(repo, I18n("ru"))
    dialog.story_edit.setPlainText("Теперь работает дизайнером.")
    dialog._save_current()

    person = repo.get_person(person_id)
    assert person.raw_notes == "Теперь работает дизайнером."
    assert person.occupation == "Архитектор"
    assert not any(
        button.text() == "Обработать информацию" for button in dialog.findChildren(QPushButton)
    )
    dialog.reject()

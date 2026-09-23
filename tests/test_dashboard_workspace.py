import os
from datetime import date, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Qt, QTime, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QScrollArea, QWidget

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import DayStatus, ScheduleType, TaskState, TrackerMode
from somniloop.ui.action_feedback import ActionPulse, install_action_feedback
from somniloop.ui.dashboard import Dashboard
from somniloop.ui.dashboard_data import DashboardData, planner_in_next_24_hours
from somniloop.ui.dialogs import CreateTrackerDialog, SettingsDialog, TaskEditDialog
from somniloop.ui.personal_dialogs import BioDialog
from somniloop.ui.planner import PlannerDialog
from somniloop.ui.theme import stylesheet


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "dashboard.db")
    yield repository
    repository.close()


def habit(repo, name="Прогулка", tasks=None):
    return repo.create_tracker(
        name, "Описание", TrackerMode.REGULAR, ScheduleType.DAILY, {}, tasks or [name]
    )


@pytest.mark.parametrize("width,wide", [(980, True), (1280, True), (1920, True)])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_responsive_layout_uses_one_scroll_and_no_horizontal_overflow(
    app, repo, width, wide, theme
):
    previous = app.styleSheet()
    previous_theme = app.property("somniloopTheme")
    app.setProperty("somniloopTheme", theme)
    app.setStyleSheet(stylesheet(theme))
    habit(repo, "Очень длинное название привычки " * 8, ["ОченьДлинноеНазваниеБезПробелов" * 12])
    repo.save_planner_task(
        "Очень длинная разовая задача " * 10,
        date.today() + timedelta(days=1),
        "Описание" * 90,
        ["Пункт " * 40],
    )
    page = Dashboard(repo, I18n("ru"))
    page.resize(width, 800)
    page.show()
    for _ in range(4):
        app.processEvents()
    assert page.columns.wide == wide
    assert len(page.findChildren(QScrollArea)) == 1
    assert page.scroll.horizontalScrollBar().maximum() == 0
    assert page.container.width() <= page.scroll.viewport().width()
    assert all(
        not widget.isWindow()
        for widget in [
            *page.cards.values(),
            *page.today.widgets.values(),
            *page.planner.widgets.values(),
        ]
    )
    assert page.today.y() < page.columns.y()
    if wide:
        assert 0.95 < page.library.width() / page.planner.width() < 1.05
    else:
        assert page.planner.y() > page.library.y() + page.library.height()
    assert not page.grab().isNull()
    page.close()
    app.setStyleSheet(previous)
    app.setProperty("somniloopTheme", previous_theme)


def test_empty_sections_stay_compact(app, repo):
    page = Dashboard(repo, I18n("ru"))
    page.resize(1400, 900)
    page.show()
    app.processEvents()
    assert (
        page.today.empty.isVisible() and page.empty.isVisible() and page.planner.empty.isVisible()
    )
    assert page.today.height() < 200
    assert page.planner.height() < 180
    assert page.library.height() < 300
    assert page.scroll.verticalScrollBar().maximum() == 0
    page.close()


def test_equal_columns_keep_filters_and_schedule_readable_on_resize(app, repo):
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet("light"))
    identifier = habit(repo)
    page = Dashboard(repo, I18n("ru"))
    page.show()
    for width in (980, 1920, 760, 980):
        page.resize(width, 800)
        for _ in range(6):
            app.processEvents()
        card = page.cards[identifier]
        assert card.schedule.width() >= 180
        assert page.filters.search.width() >= 180
        assert not card.schedule.geometry().intersects(card.actions.geometry())
        assert not page.filters.search.geometry().intersects(page.filters.order.geometry())
        assert page.scroll.horizontalScrollBar().maximum() == 0
        if width == 980:
            assert page.filters.search.width() >= 300
            assert card.actions.y() > card.schedule.y()
        if width == 760:
            assert not page.columns.wide
    page.close()
    app.setStyleSheet(previous)


@pytest.mark.parametrize("day,time,expected", [
    ("2026-09-22", "18:00", True),
    ("2026-09-23", "23:59", True),
    ("2026-09-24", "11:59", True),
    ("2026-09-24", "12:00", True),
    ("2026-09-24", "12:01", False),
    ("2026-09-24", "", True),
    ("2026-09-25", "", False),
])
def test_rolling_24_hour_boundary(day, time, expected):
    task = SimpleNamespace(due_date=day, due_time=time)
    assert planner_in_next_24_hours(task, datetime(2026, 9, 23, 12)) is expected


def test_upcoming_task_enters_on_minute_tick_without_history_reload(app, repo, monkeypatch):
    from somniloop.ui import dashboard_sections
    from somniloop.ui.main_window import MainWindow

    tomorrow = date.today() + timedelta(days=1)
    identifier = repo.save_planner_task("Завтра вечером", tomorrow, due_time="18:00")
    now = datetime.combine(date.today(), datetime.min.time()).replace(hour=17, minute=59, second=59)
    clock = SimpleNamespace(now=lambda: now)
    monkeypatch.setattr(dashboard_sections, "datetime", clock)
    page = Dashboard(repo, I18n("ru"))
    assert ("planner", identifier) not in page.today.visible_keys
    clock.now = lambda: now + timedelta(seconds=1)
    statements = []
    repo.connection.set_trace_callback(statements.append)
    MainWindow._check_day(SimpleNamespace(_current_day=date.today(), dashboard=page))
    assert ("planner", identifier) in page.today.visible_keys
    assert not statements
    repo.connection.set_trace_callback(None)
    page.today.widgets[("planner", identifier)].rows.rows[0].done.click()
    assert repo.list_planner_tasks(True)[0].due_date == tomorrow.isoformat()
    assert ("planner", identifier) not in page.today.visible_keys
    page.today.hide_done.setChecked(False)
    assert ("planner", identifier) in page.today.visible_keys
    assert not page.findChildren(QLabel, "pageTitle")
    assert any(label.text() == "Ближайшее" for label in page.findChildren(QLabel))
    page.close()


def test_hide_done_hides_whole_habit_and_restores_same_card(app, repo):
    identifier = habit(repo, tasks=["Первое", "Второе"])
    page = Dashboard(repo, I18n("ru"))
    page.show()
    page.filters.hide_done.setChecked(True)
    card = page.cards[identifier]
    tasks = repo.list_tasks(identifier)
    repo.set_task_state(identifier, tasks[0].id, date.today(), TaskState.DONE)
    page.refresh(changed_tracker=identifier)
    assert not card.isHidden()
    repo.set_task_state(identifier, tasks[1].id, date.today(), TaskState.DONE)
    page.refresh(changed_tracker=identifier)
    assert card.isHidden() and page.card_layout.count() == 0
    assert not page.empty.isHidden()
    page.filters.hide_done.setChecked(False)
    assert page.cards[identifier] is card and not card.isHidden()
    assert page.card_layout.count() == 1
    page.close()


def test_plans_and_oneoffs_share_agenda_without_moving_habits(app, repo):
    identifier = habit(repo)
    plan = repo.create_tracker("Поездка", "", TrackerMode.MANUAL, ScheduleType.MANUAL, {}, [])
    day = date.today() + timedelta(days=2)
    repo.add_manual_occurrence(plan, day, ["Билеты"])
    task = repo.save_planner_task("Позвонить", day, due_time="10:00")
    page = Dashboard(repo, I18n("ru"))
    page.show()
    assert set(page.cards) == {identifier}
    assert set(page.planner.widgets) == {("plan", plan), task}
    assert page.planner.cards.itemAt(1).widget() is page.planner.widgets[task]
    opened = []
    page.open_requested.connect(opened.append)
    page.planner.widgets[("plan", plan)].open_requested.emit(plan)
    assert opened == [plan]
    page.planner.search.setText("Поездка")
    assert page.planner.widgets[task].isHidden()
    assert not page.planner.widgets[("plan", plan)].isHidden()
    page.planner.search.clear()
    assert not page.planner.widgets[task].isHidden()
    page.close()


def test_scrollbar_fades_without_layout_shift_and_reveals_on_movement(app, repo):
    from PySide6.QtCore import QPoint

    for index in range(20):
        habit(repo, f"Привычка {index}")
    page = Dashboard(repo, I18n("ru"))
    page.resize(980, 700)
    page.show()
    app.processEvents()
    bar = page.scroll.verticalScrollBar()
    assert bar.maximum() > 0
    width = page.scroll.viewport().width()
    bar.idle.setInterval(40)
    bar.fade.setDuration(20)
    bar.setValue(40)
    assert bar.opacity.opacity() == 1
    QTest.qWait(120)
    assert bar.opacity.opacity() == 0
    assert page.scroll.viewport().width() == width
    QTest.mouseMove(page.scroll.viewport(), QPoint(20, 20))
    assert bar.opacity.opacity() == 1
    bar.setSliderDown(True)
    QTest.qWait(120)
    assert bar.opacity.opacity() == 1
    bar.setSliderDown(False)
    page.close()
    assert not bar.idle.isActive()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_today_cards_compact_tinted_and_reflow_without_spanning(app, repo, theme):
    old_style, old_theme = app.styleSheet(), app.property("somniloopTheme")
    app.setProperty("somniloopTheme", theme)
    app.setStyleSheet(stylesheet(theme))
    for title in ("Занятия спортом", "Чтение", "Прогулки"):
        habit(repo, title, ["100 приседаний", "100 отжиманий", "100 на пресс"])
    page = Dashboard(repo, I18n("ru"))
    page.show()
    try:
        for width, columns in ((980, 2), (1280, 3), (1920, 3), (720, 1), (980, 2)):
            page.resize(width, 800)
            for _ in range(5):
                app.processEvents()
            assert page.today.columns == columns
            assert page.scroll.horizontalScrollBar().maximum() == 0
            for card in page.today.widgets.values():
                assert 280 <= card.width() <= 520
                assert card.height() <= 170
                assert page.today.grid.getItemPosition(page.today.grid.indexOf(card))[3] == 1
                for row in card.rows.rows.values():
                    assert row.label.x() - row.done.geometry().right() <= 12
                    assert row.label.width() >= 100
                    assert row.height() <= 38
                # Sample an empty interior corner: it must be tinted, not plain white.
                color = card.grab().toImage().pixelColor(card.width() - 20, card.height() - 8)
                assert max(color.red(), color.green(), color.blue()) - min(
                    color.red(), color.green(), color.blue()
                ) >= 8
    finally:
        page.close()
        app.setStyleSheet(old_style)
        app.setProperty("somniloopTheme", old_theme)


@pytest.mark.parametrize("language", ["ru", "en"])
def test_checklist_binary_control_keyboard_and_legacy_marks(app, repo, language):
    from somniloop.ui.widgets import StateSelector

    identifier = habit(repo, tasks=["Первое", "Второе"])
    item = repo.list_tasks(identifier)[0]
    repo.set_task_state(identifier, item.id, date.today(), TaskState.PARTIAL)
    page = Dashboard(repo, I18n(language))
    page.resize(980, 700)
    page.show()
    app.processEvents()
    row = page.today.widgets[("tracker", identifier, date.today())].rows.rows[item.id]
    assert not hasattr(row, "partial")
    assert not row.done.isChecked()
    assert row.done.text() == I18n(language).t("home_mark_done")
    assert repo.day_summary(identifier, date.today()).tasks[0].state == TaskState.PARTIAL
    selector = StateSelector(I18n(language), TaskState.PARTIAL)
    assert TaskState.PARTIAL not in selector.buttons
    assert selector.buttons[TaskState.NOT_DONE].isChecked()
    row.done.setFocus()
    QTest.keyClick(row.done, Qt.Key.Key_Space)
    assert repo.day_summary(identifier, date.today()).tasks[0].state == TaskState.DONE
    assert repo.day_summary(identifier, date.today()).status == DayStatus.PARTIAL
    QTest.keyClick(row.done, Qt.Key.Key_Space)
    assert repo.day_summary(identifier, date.today()).tasks[0].state == TaskState.NOT_DONE
    page.close()
    selector.close()


def test_planner_checklist_has_no_partial_item_control(app, repo):
    identifier = repo.save_planner_task("Сборы", date.today(), items=["Документы", "Билеты"])
    page = Dashboard(repo, I18n("ru"))
    rows = page.today.widgets[("planner", identifier)].rows.rows
    assert all(not hasattr(row, "partial") for row in rows.values())
    next(iter(rows.values())).done.click()
    task = repo.list_planner_tasks()[0]
    assert task.state == TaskState.PARTIAL
    assert sum(item["done"] for item in task.items) == 1
    page.close()


def test_timed_tasks_show_time_and_keep_chronological_order(app, repo):
    late = repo.save_planner_task("Вечер", date.today(), due_time="19:30")
    early = repo.save_planner_task("Утро", date.today(), due_time="08:00")
    page = Dashboard(repo, I18n("ru"))
    assert page.today.visible_keys == [("planner", early), ("planner", late)]
    assert "19:30" in page.today.widgets[("planner", late)].subtitle.text()
    assert page.today.widgets[("planner", late)].property("oneOffTask") is True
    page.close()


def test_date_picker_keeps_wheel_and_keyboard_without_spin_arrows(app):
    from PySide6.QtCore import QDate, QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QAbstractSpinBox

    from somniloop.ui.controls import ScrollDateEdit

    picker = ScrollDateEdit(QDate(2026, 9, 23))
    picker.show()
    app.processEvents()
    assert picker.day_spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert picker.year_spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    pos = picker.day_spin.rect().center()
    event = QWheelEvent(QPointF(pos), QPointF(picker.day_spin.mapToGlobal(pos)), QPoint(),
                        QPoint(0, 120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(picker.day_spin, event)
    assert picker.date() == QDate(2026, 9, 24)
    QTest.keyClick(picker.day_spin, Qt.Key.Key_Down)
    assert picker.date() == QDate(2026, 9, 23)
    picker.close()


def test_today_contains_habit_overdue_plan_and_one_off_and_marks_real_occurrence(app, repo):
    identifier = habit(repo)
    plan = repo.create_tracker("Поездка", "", TrackerMode.MANUAL, ScheduleType.MANUAL, {}, [])
    yesterday = date.today() - timedelta(days=1)
    repo.add_manual_occurrence(plan, yesterday, ["Документы", "Билеты"])
    oneoff = repo.save_planner_task("Позвонить", date.today())
    page = Dashboard(repo, I18n("ru"))
    assert ("tracker", identifier, date.today()) in page.today.widgets
    overdue = page.today.widgets[("tracker", plan, yesterday)]
    row = next(iter(overdue.rows.rows.values()))
    assert not hasattr(row, "partial")
    row.done.click()
    assert repo.day_summary(plan, yesterday).status == DayStatus.PARTIAL
    assert repo.day_summary(plan, date.today()).status == DayStatus.UNSCHEDULED
    row.done.click()
    assert repo.day_summary(plan, yesterday).tasks[0].state == TaskState.NOT_DONE
    widget = page.today.widgets[("planner", oneoff)]
    assert not hasattr(widget.rows.rows[0], "partial")
    widget.rows.rows[0].done.click()
    assert not repo.list_planner_tasks()
    assert repo.list_planner_tasks(True)[0].completed
    page.today.hide_done.setChecked(False)
    assert ("planner", oneoff) in page.today.visible_keys
    page.close()


def test_sort_search_and_filter_reuse_cards(app, repo):
    a, b = habit(repo, "Бег"), habit(repo, "Английский")
    page = Dashboard(repo, I18n("ru"))
    cards = dict(page.cards)
    page.filters.order.setCurrentIndex(page.filters.order.findData("name"))
    assert page.card_layout.itemAt(0).widget() is cards[b]
    page.filters.search.setText("бег")
    assert page.card_layout.count() == 1
    assert page.card_layout.itemAt(0).widget() is cards[a]
    page.filters.search.clear()
    assert page.cards == cards
    page.filters.search.setText("нет совпадений")
    assert not page.empty.isHidden()
    assert page.card_layout.count() == 0
    page.close()


def test_attention_date_and_streak_sorting(repo):
    today = date.today()
    active, complete = habit(repo, "Нужно отметить"), habit(repo, "Готово")
    repo.set_task_state(complete, repo.list_tasks(complete)[0].id, today, TaskState.DONE)
    plan = repo.create_tracker("План", "", TrackerMode.MANUAL, ScheduleType.MANUAL, {}, [])
    repo.add_manual_occurrence(plan, today + timedelta(days=4), ["Пункт"])
    data = DashboardData(repo)
    data.refresh()
    assert data.filtered(order="attention")[0].tracker.id == active
    assert data.filtered(order="streak")[0].tracker.id == complete
    assert data.filtered(order="date")[-1].tracker.id == plan


def test_quick_mark_keeps_unrelated_snapshot_widget_and_scroll_position(app, repo, monkeypatch):
    identifiers = [habit(repo, f"Привычка {i}", tasks=["Первое", "Второе"]) for i in range(15)]
    page = Dashboard(repo, I18n("ru"))
    page.resize(1280, 750)
    page.show()
    app.processEvents()
    first, other = identifiers[:2]
    snapshot = page.data.trackers[other]
    other_card = page.cards[other]
    calls = []
    original = repo.dashboard_meta
    monkeypatch.setattr(
        repo,
        "dashboard_meta",
        lambda tracker, today=None: (calls.append(tracker.id), original(tracker, today))[1],
    )
    page.scroll.verticalScrollBar().setValue(100)
    card = page.cards[first]
    row = next(iter(card.rows.rows.values()))
    row.done.click()
    app.processEvents()
    assert repo.day_summary(first, date.today()).status == DayStatus.PARTIAL
    assert page.data.trackers[other] is snapshot
    assert page.cards[other] is other_card
    assert set(calls) == {first}
    assert page.scroll.verticalScrollBar().value() == 100
    page.close()


def test_today_collapse_and_clear_search_preserve_widgets(app, repo):
    identifier = habit(repo)
    page = Dashboard(repo, I18n("ru"))
    key = ("tracker", identifier, date.today())
    occurrence = page.today.widgets[key]
    next(iter(occurrence.rows.rows.values())).done.click()
    assert key not in page.today.visible_keys
    page.today.hide_done.setChecked(False)
    assert page.today.widgets[key] is occurrence and key in page.today.visible_keys
    page.close()


def test_month_cache_and_aggregate_streak_survive_unrelated_quick_marks(repo):
    identifier = repo.create_tracker(
        "История",
        "",
        TrackerMode.REGULAR,
        ScheduleType.DAILY,
        {},
        ["Шаг"],
        created_on=date(2020, 1, 1),
    )
    task = repo.list_tasks(identifier)[0].id
    repo.set_task_state(identifier, task, date(2020, 1, 1), TaskState.DONE)
    repo.day_summary(identifier, date(2020, 1, 1))
    statements = []
    repo.connection.set_trace_callback(statements.append)
    repo.set_task_state(identifier, task, date.today(), TaskState.PARTIAL)
    repo.day_summary(identifier, date(2020, 1, 1))
    assert not any(sql.startswith("SELECT task_id") and "2020-01" in sql for sql in statements)
    statements.clear()
    repo.day_summary(identifier, date.today())
    assert all(
        "entry_date>=" in sql and "entry_date<" in sql
        for sql in statements
        if sql.startswith("SELECT task_id")
    )


def test_partial_states_roundtrip_and_legacy_restore(repo):
    identifier = habit(repo)
    repo.set_task_state(
        identifier, repo.list_tasks(identifier)[0].id, date.today(), TaskState.PARTIAL
    )
    planner = repo.save_planner_task("Задача", date.today(), items=["Первый", "Второй"])
    item = repo.list_planner_tasks()[0].items[0]["id"]
    repo.set_planner_item_state(item, TaskState.PARTIAL)
    payload = repo.export_payload()
    repo.restore_payload(payload)
    assert repo.day_summary(identifier, date.today()).status == DayStatus.PARTIAL
    assert repo.list_planner_tasks()[0].items[0]["state"] == "partial"
    repo.save_planner_task("Задача", date.today(), items=["Первый", "Второй"], task_id=planner)
    assert repo.list_planner_tasks()[0].items[0]["state"] == "partial"
    for row in payload["tables"]["task_entries"]:
        row.pop("partial")
    for table in ("planner_tasks", "planner_items"):
        for row in payload["tables"][table]:
            row.pop("state")
    repo.restore_payload(payload)
    assert repo.list_planner_tasks()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_dashboard_language_and_creation_menu(app, repo, language):
    page = Dashboard(repo, I18n(language))
    actions = page.add.menu().actions()
    assert len(actions) == 3
    values = []
    page.create_requested.connect(values.append)
    actions[0].trigger()
    actions[1].trigger()
    assert values == ["habit", "plan"]
    assert page.filters.search.placeholderText() == I18n(language).t("home_search")
    assert "20" in page.date_label.text()
    if language == "en":
        assert not any("А" <= char <= "я" for char in page.date_label.text())
    page.close()


@pytest.mark.parametrize("kind", ["planner", "create", "bio", "settings", "task"])
def test_cancel_click_discards_draft_and_always_animates(app, repo, kind):
    parent = QWidget()
    parent.resize(800, 600)
    parent.show()
    language = I18n("ru")
    makers = {
        "planner": lambda: PlannerDialog(repo, language, parent=parent),
        "create": lambda: CreateTrackerDialog(language, parent),
        "bio": lambda: BioDialog(repo, language, parent),
        "settings": lambda: SettingsDialog(repo, language, parent),
        "task": lambda: TaskEditDialog(language, collection=False, parent=parent),
    }
    dialog = makers[kind]()
    if kind == "planner":
        dialog.title_edit.setText("Не сохранять")
        dialog.items_edit.setPlainText("Черновик")
    if kind == "bio":
        dialog.bio_edit.setPlainText("Не сохранять")
    dialog.show()
    app.processEvents()
    button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel)
    feedback = install_action_feedback()
    previous = len(feedback.pulses)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert not dialog.isVisible()
    assert dialog.result() == dialog.DialogCode.Rejected
    assert not repo.list_planner_tasks()
    assert repo.get_profile() == ("", "")
    assert len(feedback.pulses) > previous
    pulse = feedback.pulses[-1]
    assert pulse.isVisible()
    assert pulse.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    parent.close()


def test_planner_save_and_cancel_edit_using_keyboard(app, repo):
    parent = QWidget()
    parent.show()
    dialog = PlannerDialog(repo, I18n("ru"), parent=parent)
    dialog.title_edit.setText("Сохранить задачу")
    dialog.has_time.setChecked(True)
    dialog.time_edit.setTime(QTime(19, 45))
    dialog.show()
    app.processEvents()
    save = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
    QTest.mouseClick(save, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert len(repo.list_planner_tasks()) == 1
    assert parent.findChildren(ActionPulse)
    task = repo.list_planner_tasks()[0]
    assert task.due_time == "19:45"
    edit = PlannerDialog(repo, I18n("ru"), task, parent)
    edit.title_edit.setText("Не сохранять правку")
    assert edit.time_edit.time() == QTime(19, 45)
    edit.has_time.setChecked(False)
    edit.show()
    app.processEvents()
    cancel = edit.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel)
    cancel.setFocus()
    QTest.keyClick(cancel, Qt.Key.Key_Space)
    app.processEvents()
    assert not edit.isVisible()
    assert repo.list_planner_tasks()[0].title == task.title
    assert repo.list_planner_tasks()[0].due_time == "19:45"
    parent.close()


def test_invalid_save_still_has_feedback_without_false_success(app, repo):
    dialog = PlannerDialog(repo, I18n("ru"))
    dialog.show()
    app.processEvents()
    save = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
    save.click()
    app.processEvents()
    assert dialog.isVisible()
    assert dialog.findChildren(ActionPulse)
    assert not repo.list_planner_tasks()
    before = len(dialog.findChildren(ActionPulse))
    save.click()
    app.processEvents()
    assert len(dialog.findChildren(ActionPulse)) > before
    dialog.reject()


def test_settings_cancel_requests_worker_stop_without_blocking_modal_warning(app, repo):
    class Worker(QObject):
        finished = Signal()
        running = True
        interrupted = False

        def isRunning(self):
            return self.running

        def requestInterruption(self):
            self.interrupted = True

    dialog = SettingsDialog(repo, I18n("ru"))
    worker = Worker()
    dialog.telegram_thread = worker
    dialog.show()
    app.processEvents()
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
    assert worker.interrupted and dialog._cancel_pending
    assert dialog.isVisible()
    worker.running = False
    worker.finished.emit()
    app.processEvents()
    assert not dialog.isVisible()

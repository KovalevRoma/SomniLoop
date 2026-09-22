from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import (
    QDialog as QtDialog,
)

from somniloop.core.database import Repository
from somniloop.core.dates import display_date
from somniloop.core.dossier_import import load_dossier_file
from somniloop.core.exporter import export_json, import_json
from somniloop.core.i18n import I18n
from somniloop.core.models import ScheduleType, Task, TrackerMode
from somniloop.core.telegram_import import MIN_PERSONAL_MESSAGES, scan_telegram_export

from .controls import RoundedDialog as QDialog
from .controls import ScrollDateEdit as QDateEdit
from .controls import polish_dialog_buttons
from .widgets import SmartPlainTextEdit

MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true"


class ModelDownloadThread(QThread):
    progress = Signal(int)
    downloaded = Signal(str)
    failed = Signal(str)

    def __init__(self, target: Path) -> None:
        super().__init__()
        self.target = target

    def run(self) -> None:
        import urllib.request

        temporary = self.target.with_suffix(self.target.suffix + ".part")
        try:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "SomniLoop/0.1"})
            with (
                urllib.request.urlopen(request, timeout=15) as response,
                temporary.open("wb") as output,
            ):
                total = int(response.headers.get("Content-Length", 0))
                if not total:
                    self.progress.emit(-1)
                read = 0
                while True:
                    if self.isInterruptionRequested():
                        raise InterruptedError()
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    read += len(chunk)
                    if total:
                        self.progress.emit(min(100, int(read * 100 / total)))
            if self.isInterruptionRequested():
                raise InterruptedError()
            temporary.replace(self.target)
            self.downloaded.emit(str(self.target))
        except Exception as exc:
            if temporary.exists():
                temporary.unlink()
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class TelegramScanThread(QThread):
    scanned = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        def report(percent, title):
            if self.isInterruptionRequested():
                raise InterruptedError()
            self.progress.emit(percent, title)

        try:
            result = scan_telegram_export(self.path, report)
            if not self.isInterruptionRequested():
                self.scanned.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class TelegramMappingDialog(QtDialog):
    def __init__(self, repository: Repository, scan: dict, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.scan = scan
        self.setWindowTitle("Сопоставление личных чатов Telegram")
        self.setMinimumSize(1120, 700)
        root = QVBoxLayout(self)
        intro = QLabel(
            f"Найдено {scan['chats']} чатов и {scan['messages']} сообщений за всё время. "
            f"В таблице показаны личные чаты с более чем {MIN_PERSONAL_MESSAGES} сообщениями. "
            "Все чаты будут обработаны. Для личных диалогов проверь, кому они принадлежат. "
            "Участники групп будут добавлены автоматически и объединены по Telegram ID и имени."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти личный чат…")
        self.search.setClearButtonEnabled(True)
        root.addWidget(self.search)
        navigation = QHBoxLayout()
        self.previous_button = QPushButton("↑ Предыдущий человек")
        self.next_button = QPushButton("Следующий человек ↓")
        self.previous_button.clicked.connect(lambda: self._move_row(-1))
        self.next_button.clicked.connect(lambda: self._move_row(1))
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        navigation.addStretch()
        navigation.addWidget(QLabel("Стрелки также работают прямо в таблице"))
        root.addLayout(navigation)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            (
                "Имя и фамилия",
                "Дата рождения",
                "Последнее сообщение",
                "Сообщений",
                "Сопоставить",
                "Категория",
            )
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.currentCellChanged.connect(lambda *_: self._update_navigation())
        root.addWidget(self.table, 1)

        people = repository.list_people(managed_only=True)

        def name_key(value: str) -> str:
            words = value.casefold().replace("ё", "е").split()
            return " ".join(sorted(words)) if 2 <= len(words) <= 3 else " ".join(words)

        by_name = {name_key(person.name): person.id for person in people}
        old_map = repository.telegram_manifest().get("identity_map", {})
        self.people_by_id = {person.id: person for person in people}
        self.action_combos: list[QComboBox] = []
        self.group_combos: list[QComboBox] = []
        personal = {}
        for chat in scan.get("personal_chats", []):
            if int(chat.get("messages", 0)) <= MIN_PERSONAL_MESSAGES:
                continue
            personal.setdefault(chat["telegram_id"], chat)
        self.table.setRowCount(len(personal))
        identities_by_id = {item["telegram_id"]: item for item in scan.get("identities", [])}
        for row, chat in enumerate(personal.values()):
            identity = identities_by_id.get(chat["telegram_id"], {})
            name_options = {
                str(chat.get("name", "")).strip(),
                str(identity.get("name", "")).strip(),
            }
            name = (
                max(name_options, key=lambda value: (len(value.split()), len(value)))
                or "Неизвестный контакт"
            )
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, chat["telegram_id"])
            self.table.setItem(row, 0, name_item)
            previous = old_map.get(chat["telegram_id"], {}).get("person_id")
            last_date = chat.get("last_message_date") or identity.get("last_message_date", "")
            self.table.setItem(
                row, 2, QTableWidgetItem(display_date(last_date) if last_date else "—")
            )
            self.table.setItem(row, 3, QTableWidgetItem(str(chat["messages"])))
            combo = QComboBox()
            combo.addItem("Создать или объединить по имени", "create")
            combo.addItem("Пропустить этот личный чат", "skip")
            for person in people:
                combo.addItem(f"Связать с: {person.name}", person.id)
            default_id = previous or by_name.get(name_key(name))
            selected_person = self.people_by_id.get(default_id)
            birth = "—"
            if selected_person:
                birth_value = selected_person.birth_date_input or selected_person.birth_date
                birth = display_date(birth_value) if birth_value else "—"
            self.table.setItem(row, 1, QTableWidgetItem(birth))
            if default_id:
                index = combo.findData(default_id)
                if index >= 0:
                    combo.setCurrentIndex(index)
            self.table.setCellWidget(row, 4, combo)
            group_combo = QComboBox()
            group_combo.setEditable(True)
            groups = ["Контакты", "Семья", "Друзья", "Работа", "Telegram"]
            groups.extend(
                sorted(
                    {
                        person.group_name
                        for person in people
                        if person.group_name and person.group_name not in groups
                    }
                )
            )
            group_combo.addItems(groups)
            group_combo.setCurrentText(
                selected_person.group_name
                if selected_person and selected_person.group_name
                else "Контакты"
            )
            self.table.setCellWidget(row, 5, group_combo)
            self.action_combos.append(combo)
            self.group_combos.append(group_combo)
            combo.currentIndexChanged.connect(
                lambda _index, row=row: self._update_person_preview(row)
            )
            group_combo.currentIndexChanged.connect(
                lambda _index, row=row: self._update_person_preview(row)
            )
        if self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_navigation()
        self.search.textChanged.connect(self._filter)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_import_button = QPushButton(i18n.t("cancel"))
        self.cancel_import_button.setObjectName("secondary")
        self.cancel_import_button.setMinimumSize(104, 38)
        self.load_all_button = QPushButton("Загрузить всё")
        self.load_all_button.setObjectName("primary")
        self.load_all_button.setMinimumSize(140, 38)
        self.cancel_import_button.clicked.connect(self.reject)
        self.load_all_button.clicked.connect(self.accept)
        actions.addWidget(self.cancel_import_button)
        actions.addWidget(self.load_all_button)
        root.addLayout(actions)

    def _filter(self, query: str) -> None:
        words = query.casefold().split()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().casefold()
            self.table.setRowHidden(row, not all(word in name for word in words))
        self._update_navigation()

    def _update_navigation(self) -> None:
        row = self.table.currentRow()
        visible_rows = [
            index for index in range(self.table.rowCount()) if not self.table.isRowHidden(index)
        ]
        if row not in visible_rows:
            row = visible_rows[0] if visible_rows else -1
        self.previous_button.setEnabled(
            row > 0 and any(not self.table.isRowHidden(index) for index in range(row - 1, -1, -1))
        )
        self.next_button.setEnabled(
            row >= 0
            and any(
                not self.table.isRowHidden(index) for index in range(row + 1, self.table.rowCount())
            )
        )

    def _move_row(self, direction: int) -> None:
        row = self.table.currentRow()
        step = row + direction
        while 0 <= step < self.table.rowCount() and self.table.isRowHidden(step):
            step += direction
        if 0 <= step < self.table.rowCount():
            self.table.setCurrentCell(step, 0)
            self.table.scrollToItem(self.table.item(step, 0))

    def _update_person_preview(self, row: int) -> None:
        if not 0 <= row < len(self.action_combos):
            return
        value = self.action_combos[row].currentData()
        person = self.people_by_id.get(value) if isinstance(value, int) else None
        birth = "—"
        if person:
            birth_value = person.birth_date_input or person.birth_date
            birth = display_date(birth_value) if birth_value else "—"
        self.table.item(row, 1).setText(birth)

    def decisions(self) -> dict[str, object]:
        result = {}
        for row in range(self.table.rowCount()):
            telegram_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            result[telegram_id] = {
                "action": self.table.cellWidget(row, 4).currentData(),
                "group_name": self.table.cellWidget(row, 5).currentText(),
            }
        return result


class CreateTrackerDialog(QDialog):
    def __init__(self, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(i18n.t("new_tracker"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.name_edit = QLineEdit()
        self.validation_message = QLabel()
        self.validation_message.setObjectName("attention")
        self.validation_message.setWordWrap(True)
        self.validation_message.hide()
        self.name_edit.textChanged.connect(lambda: self.validation_message.hide())
        self.description_edit = SmartPlainTextEdit()
        self.description_edit.setMaximumHeight(90)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(i18n.t("regular"), TrackerMode.REGULAR)
        self.mode_combo.addItem(i18n.t("manual_mode"), TrackerMode.MANUAL)
        self.schedule_combo = QComboBox()
        for key, value in (
            ("daily", ScheduleType.DAILY),
            ("interval", ScheduleType.INTERVAL),
            ("weekdays", ScheduleType.WEEKDAYS),
            ("weekly_quota", ScheduleType.WEEKLY_QUOTA),
            ("monthly", ScheduleType.MONTHLY),
            ("yearly", ScheduleType.YEARLY),
            ("item_dates", ScheduleType.ITEM_DATES),
        ):
            self.schedule_combo.addItem(i18n.t(key, days="N", count="N", day="N", month="N"), value)

        form.addRow(i18n.t("name"), self.name_edit)
        form.addRow("", self.validation_message)
        form.addRow(i18n.t("description"), self.description_edit)
        form.addRow(i18n.t("mode"), self.mode_combo)
        locked = QLabel(i18n.t("mode_locked"))
        locked.setObjectName("muted")
        locked.setWordWrap(True)
        form.addRow("", locked)
        form.addRow(i18n.t("schedule"), self.schedule_combo)

        self.option_stack = QStackedWidget()
        root.addWidget(self.option_stack)
        self.option_pages: dict[ScheduleType, int] = {}
        self._build_option_pages()

        self.tasks_label = QLabel(i18n.t("tasks"))
        self.tasks_label.setObjectName("sectionTitle")
        root.addWidget(self.tasks_label)
        self.tasks_edit = SmartPlainTextEdit()
        self.tasks_edit.setPlaceholderText(i18n.t("one_task_per_line"))
        self.tasks_edit.setMaximumHeight(130)
        root.addWidget(self.tasks_edit)
        self.collection_hint = QLabel(i18n.t("collection_task_hint"))
        self.collection_hint.setWordWrap(True)
        self.collection_hint.setObjectName("muted")
        self.collection_hint.hide()
        root.addWidget(self.collection_hint)

        self.color = "#8267e8"
        color_button = QPushButton("●")
        color_button.setToolTip("Цвет трекера")
        color_button.clicked.connect(self._choose_color)
        root.addWidget(color_button, 0, Qt.AlignmentFlag.AlignLeft)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.schedule_combo.currentIndexChanged.connect(self._schedule_changed)
        self._mode_changed()

    def _simple_page(self, widget: QWidget | None = None) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        if widget is not None:
            layout.addRow(widget)
        return page

    def _add_page(self, kind: ScheduleType, page: QWidget) -> None:
        self.option_pages[kind] = self.option_stack.addWidget(page)

    def _build_option_pages(self) -> None:
        self._add_page(ScheduleType.DAILY, self._simple_page())

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 365)
        self.interval_spin.setValue(2)
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(self.i18n.t("interval_days"), self.interval_spin)
        self._add_page(ScheduleType.INTERVAL, page)

        page = QWidget()
        layout = QHBoxLayout(page)
        self.weekday_checks: list[QCheckBox] = []
        for key in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ):
            check = QCheckBox(self.i18n.t(key))
            self.weekday_checks.append(check)
            layout.addWidget(check)
        self._add_page(ScheduleType.WEEKDAYS, page)

        self.quota_spin = QSpinBox()
        self.quota_spin.setRange(1, 7)
        self.quota_spin.setValue(3)
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(self.i18n.t("times_week"), self.quota_spin)
        self._add_page(ScheduleType.WEEKLY_QUOTA, page)

        self.month_day_spin = QSpinBox()
        self.month_day_spin.setRange(1, 31)
        self.month_day_spin.lineEdit().setReadOnly(True)
        self.month_day_spin.setValue(1)
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(self.i18n.t("day_month"), self.month_day_spin)
        self._add_page(ScheduleType.MONTHLY, page)

        self.year_date = QDateEdit(QDate.currentDate())
        self.year_date.setCalendarPopup(True)
        self.year_date.setDisplayFormat("dd.MM")
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(self.i18n.t("annual_date"), self.year_date)
        self._add_page(ScheduleType.YEARLY, page)
        self._add_page(ScheduleType.ITEM_DATES, self._simple_page())

    def _mode_changed(self) -> None:
        manual = TrackerMode(self.mode_combo.currentData()) == TrackerMode.MANUAL
        self.schedule_combo.setEnabled(not manual)
        self.option_stack.setEnabled(not manual)
        self._schedule_changed()

    def _schedule_changed(self) -> None:
        kind = ScheduleType(self.schedule_combo.currentData())
        self.option_stack.setCurrentIndex(self.option_pages.get(kind, 0))
        collection = (
            kind == ScheduleType.ITEM_DATES
            and TrackerMode(self.mode_combo.currentData()) == TrackerMode.REGULAR
        )
        self.collection_hint.setVisible(collection)
        self.tasks_label.setVisible(not collection)
        self.tasks_edit.setVisible(not collection)

    def _choose_color(self) -> None:
        chosen = QColorDialog.getColor(parent=self)
        if chosen.isValid():
            self.color = chosen.name()

    def _validate(self) -> None:
        if not self.name_edit.text().strip():
            self.validation_message.setText(self.i18n.t("name_required"))
            self.validation_message.show()
            self.name_edit.setFocus()
            return
        if (
            TrackerMode(self.mode_combo.currentData()) == TrackerMode.REGULAR
            and ScheduleType(self.schedule_combo.currentData()) == ScheduleType.WEEKDAYS
            and not any(check.isChecked() for check in self.weekday_checks)
        ):
            self.validation_message.setText(self.i18n.t("select_weekdays"))
            self.validation_message.show()
            return
        self.accept()

    def values(self) -> dict:
        mode = TrackerMode(self.mode_combo.currentData())
        kind = (
            ScheduleType.MANUAL
            if mode == TrackerMode.MANUAL
            else ScheduleType(self.schedule_combo.currentData())
        )
        payload: dict = {}
        if kind == ScheduleType.INTERVAL:
            payload = {
                "days": self.interval_spin.value(),
                "anchor": date.today().isoformat(),
            }
        elif kind == ScheduleType.WEEKDAYS:
            payload = {
                "weekdays": [i for i, check in enumerate(self.weekday_checks) if check.isChecked()]
            }
        elif kind == ScheduleType.WEEKLY_QUOTA:
            payload = {"count": self.quota_spin.value()}
        elif kind == ScheduleType.MONTHLY:
            payload = {"day": self.month_day_spin.value()}
        elif kind == ScheduleType.YEARLY:
            selected = self.year_date.date()
            payload = {"month": selected.month(), "day": selected.day()}
        task_names = self.tasks_edit.toPlainText().splitlines()
        if mode == TrackerMode.REGULAR and kind != ScheduleType.ITEM_DATES:
            task_names = task_names or [self.name_edit.text().strip()]
        return {
            "name": self.name_edit.text(),
            "description": self.description_edit.toPlainText(),
            "mode": mode,
            "schedule_type": kind,
            "schedule": payload,
            "task_names": task_names,
            "color": self.color,
        }


class EditTrackerDialog(CreateTrackerDialog):
    def __init__(self, i18n: I18n, tracker, parent=None) -> None:
        super().__init__(i18n, parent)
        self.tracker = tracker
        self.setWindowTitle(i18n.t("edit"))
        self.name_edit.setText(tracker.name)
        self.description_edit.setPlainText(tracker.description)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(tracker.mode)))
        self.mode_combo.setEnabled(False)
        self.tasks_label.hide()
        self.tasks_edit.hide()
        self.collection_hint.hide()
        if tracker.mode == TrackerMode.REGULAR:
            self.schedule_combo.setCurrentIndex(
                max(0, self.schedule_combo.findData(tracker.schedule_type))
            )
            payload = tracker.schedule
            if tracker.schedule_type == ScheduleType.INTERVAL:
                self.interval_spin.setValue(int(payload.get("days", 1)))
            elif tracker.schedule_type == ScheduleType.WEEKDAYS:
                selected = {int(x) for x in payload.get("weekdays", [])}
                for i, check in enumerate(self.weekday_checks):
                    check.setChecked(i in selected)
            elif tracker.schedule_type == ScheduleType.WEEKLY_QUOTA:
                self.quota_spin.setValue(int(payload.get("count", 1)))
            elif tracker.schedule_type == ScheduleType.MONTHLY:
                self.month_day_spin.setValue(int(payload.get("day", 1)))
            elif tracker.schedule_type == ScheduleType.YEARLY:
                self.year_date.setDate(
                    QDate(2000, int(payload.get("month", 1)), int(payload.get("day", 1)))
                )
        self.color = tracker.color
        self._mode_changed()
        self.tasks_label.hide()
        self.tasks_edit.hide()
        self.collection_hint.hide()


class TaskEditDialog(QDialog):
    def __init__(
        self,
        i18n: I18n,
        collection: bool,
        task: Task | None = None,
        parent=None,
        allow_details: bool = True,
    ) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.collection = collection
        self.setWindowTitle(i18n.t("edit_task") if task else i18n.t("add_task"))
        self.setMinimumWidth(430)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.name_edit = QLineEdit(task.name if task else "")
        self.details_edit = SmartPlainTextEdit(task.details if task else "")
        self.details_edit.setMaximumHeight(90)
        form.addRow(i18n.t("name"), self.name_edit)
        form.addRow(i18n.t("description"), self.details_edit)
        form.setRowVisible(self.details_edit, allow_details)

        self.schedule_combo = QComboBox()
        self.schedule_combo.addItem(i18n.t("monthly", day="N"), ScheduleType.MONTHLY)
        self.schedule_combo.addItem(i18n.t("yearly", day="N", month="N"), ScheduleType.YEARLY)
        from .controls import MonthSpinBox

        self.month_spin = MonthSpinBox()
        self.month_spin.setRange(1, 12)
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.month_spin.lineEdit().setReadOnly(True)
        self.day_spin.lineEdit().setReadOnly(True)
        self.month_label = QLabel(i18n.t("month"))
        if collection:
            form.addRow(i18n.t("task_schedule"), self.schedule_combo)
            form.addRow(self.month_label, self.month_spin)
            form.addRow(i18n.t("day_month"), self.day_spin)
            self.schedule_combo.currentIndexChanged.connect(self._schedule_visibility)
        if task and task.schedule_type:
            index = self.schedule_combo.findData(task.schedule_type)
            if index >= 0:
                self.schedule_combo.setCurrentIndex(index)
            self.month_spin.setValue(int(task.schedule.get("month", 1)))
            self.day_spin.setValue(int(task.schedule.get("day", 1)))
        self._schedule_visibility()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("name"))
            return
        self.accept()

    def _schedule_visibility(self) -> None:
        yearly = (
            self.collection
            and ScheduleType(self.schedule_combo.currentData()) == ScheduleType.YEARLY
        )
        self.month_label.setVisible(yearly)
        self.month_spin.setVisible(yearly)

    def values(self) -> tuple[str, str, ScheduleType | None, dict]:
        if not self.collection:
            return self.name_edit.text(), self.details_edit.toPlainText(), None, {}
        kind = ScheduleType(self.schedule_combo.currentData())
        payload = {"day": self.day_spin.value()}
        if kind == ScheduleType.YEARLY:
            payload["month"] = self.month_spin.value()
        return self.name_edit.text(), self.details_edit.toPlainText(), kind, payload


class SettingsDialog(QDialog):
    settings_saved = Signal()

    def __init__(self, repository: Repository, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.i18n = i18n
        self.download_thread: ModelDownloadThread | None = None
        self.telegram_thread: TelegramScanThread | None = None
        self._cancel_pending = False
        self.setWindowTitle(i18n.t("settings"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.theme_combo = QComboBox()
        self.language_combo = QComboBox()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(repository.get_setting("language", "ru")))
        )
        form.addRow(i18n.t("home_language"), self.language_combo)
        for key in ("dark", "light", "system"):
            self.theme_combo.addItem(i18n.t(key), key)
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(repository.get_setting("theme", "dark")))
        )
        self.model_edit = QLineEdit(repository.get_setting("model_path", ""))
        browse = QPushButton(i18n.t("choose_model"))
        browse.clicked.connect(self._browse_model)
        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self.model_edit, 1)
        model_layout.addWidget(browse)
        form.addRow(i18n.t("theme"), self.theme_combo)
        form.addRow(i18n.t("model_path"), model_row)
        self.download_button = QPushButton(i18n.t("download_model"))
        self.download_button.clicked.connect(self._download_model)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setFormat("%p%")
        self.download_progress.hide()
        root.addWidget(self.download_button)
        root.addWidget(self.download_progress)
        hint = QLabel(i18n.t("model_optional"))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)
        telegram_title = QLabel("Telegram")
        telegram_title.setObjectName("sectionTitle")
        root.addWidget(telegram_title)
        self.telegram_status = QLabel()
        self.telegram_status.setWordWrap(True)
        self.telegram_status.setObjectName("muted")
        manifest = repository.telegram_manifest()
        if manifest:
            self.telegram_status.setText(
                f"Подключено: {Path(manifest.get('path', '')).name} · "
                f"{manifest.get('chats', 0)} чатов · {manifest.get('messages', 0)} сообщений. "
                "Обработка происходит только при обновлении графа."
            )
        else:
            self.telegram_status.setText(
                "Подключи полный result.json из Telegram Desktop. Будут обработаны все чаты за всё время."
            )
        root.addWidget(self.telegram_status)
        self.telegram_button = QPushButton("Выбрать Telegram result.json")
        self.telegram_button.clicked.connect(self._choose_telegram)
        self.dossier_button = QPushButton("Импортировать готовые досье JSON")
        self.dossier_button.clicked.connect(self._import_dossiers)
        self.telegram_progress = QProgressBar()
        self.telegram_progress.setRange(0, 100)
        self.telegram_progress.setFormat("%p%")
        self.telegram_progress.hide()
        root.addWidget(self.telegram_button)
        root.addWidget(self.dossier_button)
        root.addWidget(self.telegram_progress)
        export_button = QPushButton(i18n.t("export"))
        export_button.clicked.connect(self._export_json)
        import_button = QPushButton(i18n.t("import"))
        import_button.clicked.connect(self._import_json)
        data_buttons = QHBoxLayout()
        data_buttons.addWidget(export_button)
        data_buttons.addWidget(import_button)
        root.addLayout(data_buttons)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.i18n.t("choose_model"), str(Path.home()), "GGUF (*.gguf)"
        )
        if path:
            self.model_edit.setText(path)

    def _download_model(self) -> None:
        if self.download_thread and self.download_thread.isRunning():
            return
        target = self.repository.path.parent / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
        self.download_button.setEnabled(False)
        self.download_progress.setValue(0)
        self.download_progress.show()
        self.download_thread = ModelDownloadThread(target)
        self.download_thread.progress.connect(self._model_download_progress)
        self.download_thread.downloaded.connect(self._model_downloaded)
        self.download_thread.failed.connect(self._model_download_failed)
        self.download_thread.start()

    def _model_download_progress(self, percent: int) -> None:
        if percent < 0:
            self.download_progress.setRange(0, 0)
            self.download_progress.setFormat("Загрузка…")
            return
        self.download_progress.setRange(0, 100)
        self.download_progress.setFormat("%p%")
        self.download_progress.setValue(percent)

    def _model_downloaded(self, path: str) -> None:
        if self._cancel_pending:
            return
        self.model_edit.setText(path)
        self._model_download_progress(100)
        self.download_button.setEnabled(True)
        QMessageBox.information(self, self.i18n.t("model"), self.i18n.t("model_downloaded"))

    def _model_download_failed(self, error: str) -> None:
        if self._cancel_pending:
            return
        self.download_progress.hide()
        self.download_button.setEnabled(True)
        QMessageBox.warning(
            self,
            self.i18n.t("model"),
            self.i18n.t("model_download_failed", error=error),
        )

    def _choose_telegram(self) -> None:
        if self.telegram_thread and self.telegram_thread.isRunning():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать экспорт Telegram", str(Path.home()), "Telegram JSON (result.json *.json)"
        )
        if not path:
            return
        self.telegram_button.setEnabled(False)
        self.telegram_progress.setRange(0, 100)
        self.telegram_progress.setValue(0)
        self.telegram_progress.setFormat("%p%")
        self.telegram_progress.show()
        self.telegram_status.setText("Читаю структуру полного экспорта…")
        self.telegram_thread = TelegramScanThread(path)
        self.telegram_thread.progress.connect(self._telegram_scan_progress)
        self.telegram_thread.scanned.connect(self._telegram_scanned)
        self.telegram_thread.failed.connect(self._telegram_failed)
        self.telegram_thread.start()

    def _telegram_scan_progress(self, percent: int, title: str) -> None:
        if self._cancel_pending:
            return
        self.telegram_progress.setRange(0, 100)
        self.telegram_progress.setValue(percent)
        self.telegram_status.setText(f"{title} · {percent}%")

    def _telegram_scanned(self, scan: dict) -> None:
        if self._cancel_pending:
            return
        self.telegram_progress.hide()
        self.telegram_button.setEnabled(True)
        # The scan signal can arrive a fraction before QThread.run() returns.
        # Finish that worker before entering another modal event loop.
        if self.telegram_thread and self.telegram_thread.isRunning():
            self.telegram_thread.wait()
        self.telegram_thread = None
        dialog = TelegramMappingDialog(self.repository, scan, self.i18n, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.telegram_status.setText("Импорт Telegram отменён.")
            return
        identities_total = max(1, len(scan.get("identities", [])))
        import_progress = QProgressDialog(
            "Подготавливаю импорт Telegram…", "", 0, identities_total, self
        )
        import_progress.setWindowTitle("Импорт Telegram")
        import_progress.setCancelButton(None)
        import_progress.setAutoClose(False)
        import_progress.setMinimumDuration(0)
        import_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        import_progress.show()
        QApplication.processEvents()

        def update_import_progress(current: int, total: int, title: str) -> None:
            import_progress.setLabelText(title)
            import_progress.setRange(0, max(1, total))
            import_progress.setValue(current)
            QApplication.processEvents()

        try:
            result = self.repository.register_telegram_export(
                scan, dialog.decisions(), progress=update_import_progress
            )
        except Exception as exc:
            import_progress.close()
            self._telegram_failed(str(exc))
            return
        import_progress.setValue(identities_total)
        import_progress.setLabelText("Импорт Telegram завершён")
        QApplication.processEvents()
        import_progress.close()
        self.telegram_status.setText(
            f"Подключено {result['chats']} чатов и {result['messages']} сообщений. "
            f"Связано людей: {result['linked']}; создано новых: {result['created']}."
        )
        QMessageBox.information(
            self,
            "Telegram импортирован",
            "Архив подключён целиком. Тексты пока не отправлялись в LLM. "
            "Нажми «Обновить граф», чтобы составить досье.",
        )
        self.settings_saved.emit()

    def _telegram_failed(self, error: str) -> None:
        if self._cancel_pending:
            return
        self.telegram_progress.hide()
        self.telegram_button.setEnabled(True)
        self.telegram_status.setText("Не удалось подключить Telegram export.")
        QMessageBox.warning(self, "Telegram", error)

    def _import_dossiers(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Импортировать готовые досье",
            str(Path.home()),
            "SomniLoop dossiers (somniloop_dossiers.json *.json)",
        )
        if not path:
            return
        progress = QProgressDialog("Читаю готовые досье…", "", 0, 100, self)
        progress.setWindowTitle("Импорт готовых досье")
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.show()

        def update(current: int, total: int, title: str) -> None:
            progress.setLabelText(title)
            progress.setRange(0, max(1, total))
            progress.setValue(current)
            QApplication.processEvents()

        try:
            payload = load_dossier_file(path, update)
            backup = self.repository.backup(label="before-dossier-import")
            result = self.repository.import_dossier_payload(payload, update)
        except Exception as exc:
            progress.close()
            QMessageBox.warning(self, "Импорт готовых досье", str(exc))
            return
        progress.close()
        self.telegram_status.setText(
            f"Готовые досье загружены: {result['people']} людей, "
            f"{result['connections']} связей, {result['places']} мест. "
            "Исходный Telegram JSON отключён; локальная LLM не запускалась."
        )
        QMessageBox.information(
            self,
            "Досье импортированы",
            f"Граф уже готов. Создано людей: {result['created']}; "
            f"обновлено: {result['updated']}.\nРезервная копия: {backup}",
        )
        self.settings_saved.emit()

    def _export_json(self) -> None:
        default = str(Path.home() / f"SomniLoop-export-{date.today().isoformat()}.json")
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("export"), default, "JSON (*.json)")
        if not path:
            return
        try:
            target = export_json(self.repository, path)
            QMessageBox.information(
                self,
                self.i18n.t("export"),
                self.i18n.t("export_success", path=target),
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                self.i18n.t("export"),
                self.i18n.t("export_failed", error=exc),
            )

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.i18n.t("import"), str(Path.home()), "JSON (*.json)"
        )
        if not path:
            return
        if (
            QMessageBox.question(self, self.i18n.t("import"), self.i18n.t("import_confirm"))
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            backup = import_json(self.repository, path)
        except Exception as exc:
            QMessageBox.warning(
                self, self.i18n.t("import"), self.i18n.t("import_failed", error=exc)
            )
            return
        QMessageBox.information(
            self, self.i18n.t("import"), self.i18n.t("import_success", backup=backup)
        )
        self.settings_saved.emit()
        self.accept()

    def _save(self) -> None:
        if self._cancel_pending:
            return
        if self.download_thread and self.download_thread.isRunning():
            QMessageBox.information(self, self.i18n.t("model"), self.i18n.t("wait_for_download"))
            return
        self.repository.set_setting("language", self.language_combo.currentData())
        self.repository.set_setting("theme", self.theme_combo.currentData())
        self.repository.set_setting("model_path", self.model_edit.text().strip())
        self.settings_saved.emit()
        self.accept()

    def reject(self) -> None:
        workers = [
            worker
            for worker in (self.download_thread, self.telegram_thread)
            if worker and worker.isRunning()
        ]
        if workers:
            if not self._cancel_pending:
                self._cancel_pending = True
                self.telegram_status.setText(
                    "Отменяю операцию…" if self.i18n.language == "ru" else "Cancelling…"
                )
                for worker in workers:
                    worker.finished.connect(self._finish_cancel)
                    worker.requestInterruption()
                QTimer.singleShot(0, self._finish_cancel)
            return
        super().reject()

    def _finish_cancel(self) -> None:
        if not any(
            worker and worker.isRunning() for worker in (self.download_thread, self.telegram_thread)
        ):
            super().reject()

    def closeEvent(self, event) -> None:
        if any(
            worker and worker.isRunning() for worker in (self.download_thread, self.telegram_thread)
        ):
            self.reject()
            event.ignore()
            return
        super().closeEvent(event)

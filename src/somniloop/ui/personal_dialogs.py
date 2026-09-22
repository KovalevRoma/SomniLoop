from __future__ import annotations

import html
from dataclasses import asdict
from datetime import datetime

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.database import Repository
from somniloop.core.dates import display_date, display_timestamp
from somniloop.core.i18n import I18n
from somniloop.knowledge.people import format_person_details

from .controls import BirthdayEdit, polish_dialog_buttons, rich_details, show_saved
from .controls import RoundedDialog as QDialog
from .controls import ScrollDateEdit as QDateEdit
from .widgets import SmartPlainTextEdit


def _display_timestamp(value: str) -> str:
    if not value:
        return "—"
    try:
        return display_timestamp(value)
    except ValueError:
        return value


class PersonDetailsDialog(QDialog):
    def __init__(self, person, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редактировать данные человека")
        self.setMinimumSize(620, 560)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.biography = SmartPlainTextEdit(person.biography)
        self.education = QLineEdit(person.education)
        self.occupation = QLineEdit(person.occupation)
        self.facts = SmartPlainTextEdit("\n".join(person.facts))
        self.biography.setMinimumHeight(130)
        self.facts.setMinimumHeight(150)
        form.addRow(i18n.t("biography"), self.biography)
        form.addRow(i18n.t("education"), self.education)
        form.addRow(i18n.t("occupation"), self.occupation)
        form.addRow("Факты — по одному на строке", self.facts)
        root.addLayout(form, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class ClarificationDialog(QDialog):
    def __init__(self, question: str, answer: str, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Уточнение для графа")
        self.setMinimumSize(560, 390)
        root = QVBoxLayout(self)
        intro = QLabel(
            "Граф нашёл сведения, которые могут противоречить друг другу. "
            "Объясни, какое из них верно или как они связаны во времени. "
            "Ответ будет учтён при следующем обновлении графа."
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        root.addWidget(intro)
        question_label = QLabel(question)
        question_label.setWordWrap(True)
        question_label.setObjectName("sectionTitle")
        root.addWidget(question_label)
        self.answer = SmartPlainTextEdit(answer)
        self.answer.setPlaceholderText(
            "Например: это один человек, но он сменил место работы в 2024 году…"
        )
        root.addWidget(self.answer, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class BioDialog(QDialog):
    data_changed = Signal()

    def __init__(self, repository: Repository, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.i18n = i18n
        self._original = repository.get_profile()
        self.setWindowTitle(i18n.t("bio"))
        self.setMinimumSize(620, 480)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(self._original[0])
        self.bio_edit = SmartPlainTextEdit(self._original[1])
        self.bio_edit.setPlaceholderText(i18n.t("bio_placeholder"))
        form.addRow(i18n.t("your_name"), self.name_edit)
        form.addRow(i18n.t("bio"), self.bio_edit)
        root.addLayout(form, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        polish_dialog_buttons(buttons)
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _persist(self) -> None:
        current = (self.name_edit.text().strip(), self.bio_edit.toPlainText().strip())
        if current == self._original:
            return
        self.repository.save_profile(*current)
        self._original = current
        self.data_changed.emit()

    def _save_and_close(self) -> None:
        self._persist()
        if self.parentWidget():
            show_saved(self.parentWidget(), self.i18n.t("saved"))
        super().accept()

    def reject(self) -> None:
        # Cancel must discard the draft, not silently save it.
        super().reject()


class DiaryDialog(QDialog):
    data_changed = Signal()

    def __init__(self, repository: Repository, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.i18n = i18n
        self.current_note_id: int | None = None
        self._loading = False
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(1200)
        self.autosave.timeout.connect(lambda: self._save_current(refresh=False))
        self.setWindowTitle(i18n.t("diary"))
        self.setMinimumSize(860, 590)

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        new_button = QPushButton(i18n.t("new_diary_entry"))
        new_button.setObjectName("primary")
        new_button.clicked.connect(self._new_entry)
        self.delete_button = QPushButton(i18n.t("delete"))
        self.delete_button.clicked.connect(self._delete_entry)
        toolbar.addWidget(new_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addStretch()
        root.addLayout(toolbar)

        splitter = QSplitter()
        self.entry_list = QListWidget()
        self.entry_list.setMinimumWidth(260)
        self.entry_list.currentItemChanged.connect(self._selection_changed)
        splitter.addWidget(self.entry_list)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        form = QFormLayout()
        self.entry_date = QDateEdit(QDate.currentDate())
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDisplayFormat("dd.MM.yyyy")
        self.title_edit = QLineEdit()
        form.addRow(i18n.t("entry_date"), self.entry_date)
        form.addRow(i18n.t("note_title"), self.title_edit)
        editor_layout.addLayout(form)
        self.content_edit = SmartPlainTextEdit()
        self.content_edit.setPlaceholderText(i18n.t("diary_placeholder"))
        editor_layout.addWidget(self.content_edit, 1)
        self.updated_label = QLabel()
        self.updated_label.setObjectName("timestamp")
        editor_layout.addWidget(self.updated_label)
        save_button = QPushButton(i18n.t("save"))
        save_button.clicked.connect(self._save_explicit)
        editor_layout.addWidget(save_button, 0, Qt.AlignmentFlag.AlignRight)
        splitter.addWidget(editor)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).setText(i18n.t("close"))
        polish_dialog_buttons(close_buttons)
        close_buttons.rejected.connect(self.accept)
        root.addWidget(close_buttons)
        self._reload_list()
        self.title_edit.textChanged.connect(self._queue_save)
        self.content_edit.textChanged.connect(self._queue_save)
        self.entry_date.dateChanged.connect(self._queue_save)

    def _queue_save(self) -> None:
        if not self._loading:
            self.autosave.start()

    def _save_explicit(self) -> None:
        self._save_current(refresh=True)
        show_saved(self, self.i18n.t("saved"))

    def _reload_list(self, select_id: int | None = None) -> None:
        self._loading = True
        self.entry_list.clear()
        selected_item: QListWidgetItem | None = None
        for note in self.repository.list_notes(include_content=False):
            try:
                day = display_date(note.entry_date)
            except ValueError:
                day = note.entry_date
            title = note.title or self.i18n.t("untitled_entry")
            item = QListWidgetItem(f"{day} — {title}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.entry_list.addItem(item)
            if note.id == select_id:
                selected_item = item
        self._loading = False
        if selected_item:
            self.entry_list.setCurrentItem(selected_item)
        elif self.entry_list.count():
            self.entry_list.setCurrentRow(0)
        else:
            self._clear_editor()

    def _clear_editor(self) -> None:
        self._loading = True
        self.current_note_id = None
        self.entry_date.setDate(QDate.currentDate())
        self.title_edit.clear()
        self.content_edit.clear()
        self.updated_label.clear()
        self.delete_button.setEnabled(False)
        self._loading = False

    def _selection_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if self._loading:
            return
        if previous is not None and self.current_note_id is not None:
            self._save_current(refresh=False)
        if current is None:
            self._clear_editor()
            return
        note_id = int(current.data(Qt.ItemDataRole.UserRole))
        try:
            note = self.repository.get_note(note_id)
        except KeyError:
            return
        self._loading = True
        self.current_note_id = note.id
        try:
            self.entry_date.setDate(QDate.fromString(note.entry_date, "yyyy-MM-dd"))
        except (TypeError, ValueError):
            self.entry_date.setDate(QDate.currentDate())
        self.title_edit.setText(note.title)
        self.content_edit.setPlainText(note.content)
        self.updated_label.setText(
            self.i18n.t("entry_modified", date=display_timestamp(note.updated_at))
        )
        self.delete_button.setEnabled(True)
        self._loading = False

    def _new_entry(self) -> None:
        self._save_current(refresh=False)
        today = QDate.currentDate().toString("yyyy-MM-dd")
        title = self.i18n.t(
            "default_diary_title", date=display_date(QDate.currentDate().toPython())
        )
        note_id = self.repository.save_note(title, "", entry_date=today)
        self.data_changed.emit()
        self._reload_list(note_id)
        self.content_edit.setFocus()

    def _save_current(self, refresh: bool = True) -> None:
        self.autosave.stop()
        if self._loading:
            return
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if self.current_note_id is None and not (title or content):
            return
        if not title:
            title = self.i18n.t(
                "default_diary_title",
                date=display_date(self.entry_date.date().toPython()),
            )
            self.title_edit.setText(title)
        before_changes = self.repository.connection.total_changes
        note_id = self.repository.save_note(
            title,
            content,
            entry_date=self.entry_date.date().toString("yyyy-MM-dd"),
            note_id=self.current_note_id,
        )
        self.current_note_id = note_id
        saved = self.repository.get_note(note_id)
        self.updated_label.setText(
            self.i18n.t("entry_modified", date=display_timestamp(saved.updated_at))
        )
        if self.repository.connection.total_changes != before_changes:
            self.data_changed.emit()
        if refresh:
            self._reload_list(note_id)
        else:
            self._loading = True
            selected = next(
                (
                    self.entry_list.item(index)
                    for index in range(self.entry_list.count())
                    if self.entry_list.item(index).data(Qt.ItemDataRole.UserRole) == note_id
                ),
                None,
            )
            if selected is None:
                selected = QListWidgetItem()
                selected.setData(Qt.ItemDataRole.UserRole, note_id)
                self.entry_list.insertItem(0, selected)
                self.entry_list.setCurrentItem(selected)
            selected.setText(f"{display_date(saved.entry_date)} — {saved.title}")
            self.delete_button.setEnabled(True)
            self._loading = False

    def _delete_entry(self) -> None:
        if self.current_note_id is None:
            return
        answer = QMessageBox.question(self, self.windowTitle(), self.i18n.t("delete_note"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_note(self.current_note_id)
        self.current_note_id = None
        self.data_changed.emit()
        self._reload_list()

    def accept(self) -> None:
        self._save_current(refresh=False)
        super().accept()

    def reject(self) -> None:
        self._save_current(refresh=False)
        super().reject()


class PeopleDialog(QDialog):
    data_changed = Signal()

    def __init__(
        self,
        repository: Repository,
        i18n: I18n,
        parent=None,
        *,
        select_person_id: int | None = None,
        clarification_index: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.i18n = i18n
        self.current_person_id: int | None = None
        self._loading = False
        self.setWindowTitle(i18n.t("people_manager"))
        self.setMinimumSize(760, 520)
        self.resize(1040, 760)

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        add_button = QPushButton(i18n.t("add_person"))
        self.add_button = add_button
        add_button.setObjectName("primary")
        add_button.clicked.connect(self._add_person)
        self.delete_button = QPushButton(i18n.t("delete"))
        self.delete_button.clicked.connect(self._delete_person)
        self.merge_button = QPushButton("Объединить дубли")
        self.merge_button.clicked.connect(self._merge_person)
        toolbar.addWidget(add_button)
        toolbar.addWidget(self.merge_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addStretch()
        root.addLayout(toolbar)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        self.person_list = QListWidget()
        self.person_list.setMinimumWidth(200)
        self.person_list.setMaximumWidth(240)
        self.person_list.currentItemChanged.connect(self._selection_changed)
        splitter.addWidget(self.person_list)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(8, 0, 8, 8)
        editor_layout.setSpacing(8)
        editor_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.name_edit = QLineEdit()
        self.relationship_edit = QLineEdit()
        self.contact_edit = QLineEdit()
        self.contact_edit.setPlaceholderText("Телефон, Telegram, email или другой способ связи")
        self.group_edit = QComboBox()
        self.group_edit.setEditable(True)
        self.group_edit.addItems(("Контакты", "Семья", "Друзья", "Работа"))
        self.birthday_edit = BirthdayEdit()
        self.birthday_edit.known.setText(i18n.t("birth_known"))
        self.birthday_edit.year_known.setText(i18n.t("birth_year_known"))
        self.interests_edit = QLineEdit()
        form.addRow(i18n.t("person_name"), self.name_edit)
        form.addRow(i18n.t("relationship"), self.relationship_edit)
        form.addRow(i18n.t("contact"), self.contact_edit)
        form.addRow(i18n.t("group"), self.group_edit)
        form.addRow(i18n.t("birth_date"), self.birthday_edit)
        form.addRow(i18n.t("interests"), self.interests_edit)
        for field in (
            self.name_edit,
            self.relationship_edit,
            self.contact_edit,
            self.group_edit,
            self.interests_edit,
        ):
            field.setMinimumHeight(max(34, field.sizeHint().height()))
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        editor_layout.addLayout(form)
        story_title = QLabel(i18n.t("person_story"))
        story_title.setObjectName("sectionTitle")
        editor_layout.addWidget(story_title)
        self.story_edit = SmartPlainTextEdit()
        self.story_edit.setPlaceholderText(i18n.t("person_story_placeholder"))
        self.story_edit.setMinimumHeight(130)
        editor_layout.addWidget(self.story_edit, 1)
        actions = QHBoxLayout()
        save_button = QPushButton(i18n.t("save"))
        save_button.setObjectName("primary")
        save_button.clicked.connect(
            lambda: (self._save_current(), show_saved(self, i18n.t("saved")))
        )
        actions.addStretch()
        actions.addWidget(save_button)
        editor_layout.addLayout(actions)

        facts_header = QHBoxLayout()
        facts_title = QLabel(i18n.t("processed_facts"))
        facts_title.setObjectName("sectionTitle")
        self.edit_facts_button = QPushButton("Редактировать данные")
        self.edit_facts_button.clicked.connect(self._edit_details)
        facts_header.addWidget(facts_title)
        facts_header.addStretch()
        facts_header.addWidget(self.edit_facts_button)
        editor_layout.addLayout(facts_header)
        facts_hint = QLabel(i18n.t("facts_refresh_hint"))
        facts_hint.setObjectName("muted")
        facts_hint.setWordWrap(True)
        editor_layout.addWidget(facts_hint)
        self.facts_view = QTextBrowser()
        self.facts_view.setMinimumHeight(130)
        editor_layout.addWidget(self.facts_view, 1)
        self.clarifications_label = QLabel()
        self.clarifications_label.setWordWrap(True)
        self.clarifications_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.clarifications_label.setOpenExternalLinks(False)
        self.clarifications_label.linkActivated.connect(self._show_clarification)
        editor_layout.addWidget(self.clarifications_label)
        self.updated_label = QLabel()
        self.updated_label.setObjectName("muted")
        editor_layout.addWidget(self.updated_label)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor_scroll.setWidget(editor)
        splitter.addWidget(self.editor_scroll)
        splitter.setSizes([220, 800])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).setText(i18n.t("close"))
        polish_dialog_buttons(close_buttons)
        close_buttons.rejected.connect(self.accept)
        root.addWidget(close_buttons)
        self._reload_list(select_person_id)
        if select_person_id is not None and clarification_index is not None:
            QTimer.singleShot(0, lambda: self._show_clarification(str(clarification_index)))

    def _reload_list(self, select_id: int | None = None) -> None:
        self._loading = True
        self.person_list.clear()
        selected_item: QListWidgetItem | None = None
        for person in self.repository.list_people(managed_only=True):
            item = QListWidgetItem(person.name)
            item.setData(Qt.ItemDataRole.UserRole, person.id)
            self.person_list.addItem(item)
            if person.id == select_id:
                selected_item = item
        self._loading = False
        if selected_item:
            self.person_list.setCurrentItem(selected_item)
        elif self.person_list.count():
            self.person_list.setCurrentRow(0)
        else:
            self._clear_editor()

    def _clear_editor(self) -> None:
        self._loading = True
        self.current_person_id = None
        self.name_edit.clear()
        self.relationship_edit.clear()
        self.contact_edit.clear()
        self.group_edit.setCurrentText("Контакты")
        self.birthday_edit.set_value("")
        self.interests_edit.clear()
        self.story_edit.clear()
        self.facts_view.clear()
        self.clarifications_label.clear()
        self.updated_label.clear()
        self.delete_button.setEnabled(False)
        self.merge_button.setEnabled(False)
        self.edit_facts_button.setEnabled(False)
        self._loading = False

    def _selection_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        if self._loading:
            return
        if previous is not None and self.current_person_id is not None:
            self._save_current(refresh=False)
        if current is None:
            self._clear_editor()
            return
        self._load_person(int(current.data(Qt.ItemDataRole.UserRole)))

    def _load_person(self, person_id: int) -> None:
        person = self.repository.get_person(person_id)
        self._loading = True
        self.current_person_id = person.id
        self.name_edit.setText(person.name)
        self.relationship_edit.setText(person.relationship)
        self.contact_edit.setText(person.contact)
        self.group_edit.setCurrentText(person.group_name or "Контакты")
        self._loaded_contact = self.contact_edit.text()
        self._loaded_group = self.group_edit.currentText()
        self.birthday_edit.set_value(person.birth_date_input or person.birth_date)
        self.interests_edit.setText(person.interests_input or person.interests)
        self._loaded_birth = self.birthday_edit.value()
        self._loaded_interests = self.interests_edit.text()
        self.story_edit.setPlainText(person.raw_notes)
        graph_date = self.repository.get_setting("graph_updated_at", "")[:10]
        as_of = datetime.fromisoformat(graph_date).date() if graph_date else None
        self.facts_view.setHtml(rich_details(format_person_details(asdict(person), as_of)))
        links = []
        for index, item in enumerate(person.clarifications):
            if not isinstance(item, dict):
                continue
            question = html.escape(str(item.get("question", "")))
            suffix = " — ответ сохранён" if str(item.get("answer", "")).strip() else ""
            links.append(f'<a href="{index}">Уточнить: {question}</a>{suffix}')
        self.clarifications_label.setText("<br><br>".join(links))
        self.clarifications_label.setVisible(bool(links))
        self.updated_label.setText(
            self.i18n.t("last_updated", date=_display_timestamp(person.updated_at))
        )
        self.delete_button.setEnabled(True)
        self.merge_button.setEnabled(self.person_list.count() > 1)
        self.edit_facts_button.setEnabled(True)
        self._loading = False

    def _add_person(self) -> None:
        self._save_current(refresh=False)
        person_id = self.repository.create_person(self.i18n.t("new_person_name"))
        self.data_changed.emit()
        self._reload_list(person_id)
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def _save_current(self, refresh: bool = True) -> None:
        if self._loading or self.current_person_id is None:
            return
        name = self.name_edit.text().strip() or self.i18n.t("new_person_name")
        changed = self.repository.save_person_input(
            self.current_person_id,
            name,
            self.relationship_edit.text(),
            self.story_edit.toPlainText(),
            birth_date=self.birthday_edit.value()
            if self.birthday_edit.value() != self._loaded_birth
            else None,
            interests=self.interests_edit.text()
            if self.interests_edit.text() != self._loaded_interests
            else None,
            contact=self.contact_edit.text()
            if self.contact_edit.text() != self._loaded_contact
            else None,
            group_name=self.group_edit.currentText()
            if self.group_edit.currentText() != self._loaded_group
            else None,
        )
        self.name_edit.setText(name)
        if changed:
            self.data_changed.emit()
        if refresh:
            self._reload_list(self.current_person_id)

    def _edit_details(self) -> None:
        if self.current_person_id is None:
            return
        self._save_current(refresh=False)
        person = self.repository.get_person(self.current_person_id)
        dialog = PersonDetailsDialog(person, self.i18n, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.repository.save_person_details(
            person.id,
            biography=dialog.biography.toPlainText(),
            education=dialog.education.text(),
            occupation=dialog.occupation.text(),
            facts=dialog.facts.toPlainText().splitlines(),
        )
        self.data_changed.emit()
        self._load_person(person.id)
        show_saved(self, self.i18n.t("saved"))

    def _show_clarification(self, value: str) -> None:
        if self.current_person_id is None:
            return
        try:
            index = int(value)
            person = self.repository.get_person(self.current_person_id)
            item = person.clarifications[index]
        except (ValueError, IndexError, KeyError):
            return
        dialog = ClarificationDialog(
            str(item.get("question", "")), str(item.get("answer", "")), self.i18n, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.repository.save_clarification(person.id, index, dialog.answer.toPlainText())
        self.data_changed.emit()
        self._load_person(person.id)
        show_saved(self, self.i18n.t("saved"))

    def _merge_person(self) -> None:
        if self.current_person_id is None:
            return
        self._save_current(refresh=False)
        candidates = [
            person
            for person in self.repository.list_people(managed_only=True)
            if person.id != self.current_person_id
        ]
        if not candidates:
            return
        labels = [
            f"{person.name} · {person.relationship or 'без описания'} · #{person.id}"
            for person in candidates
        ]
        selected, ok = QInputDialog.getItem(
            self,
            "Объединить дубли",
            "Выбери вторую запись. Она будет объединена с текущей, история сохранится:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        duplicate = candidates[labels.index(selected)]
        current = self.repository.get_person(self.current_person_id)
        answer = QMessageBox.question(
            self,
            "Объединить дубли",
            f"Объединить «{duplicate.name}» с «{current.name}»?\n"
            "Основной останется текущая запись; заметки и история будут сохранены.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        person_id = self.repository.merge_people(current.id, duplicate.id)
        self.data_changed.emit()
        self._reload_list(person_id)
        show_saved(self, "Записи объединены")

    def _delete_person(self) -> None:
        if self.current_person_id is None:
            return
        answer = QMessageBox.question(
            self,
            self.windowTitle(),
            self.i18n.t("person_delete_confirm", name=self.name_edit.text()),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repository.delete_person(self.current_person_id)
        self.current_person_id = None
        self.data_changed.emit()
        self._reload_list()

    def _can_close(self) -> bool:
        self._save_current(refresh=False)
        return True

    def accept(self) -> None:
        if self._can_close():
            super().accept()

    def reject(self) -> None:
        if self._can_close():
            super().reject()

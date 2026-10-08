"""Project management and inbox conversion forms."""

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .controls import RoundedDialog, ScrollDateEdit, polish_dialog_buttons


def text(i18n, ru, en):
    return ru if i18n.language == "ru" else en




class ProjectDialog(RoundedDialog):
    def __init__(self, repository, i18n, parent, project=None):
        super().__init__(parent)
        self.repository, self.project = repository, project
        self.i18n = i18n
        self.setWindowTitle(text(i18n, "Проект", "Project"))
        self.resize(500, 250)
        root = QVBoxLayout(self)
        self.name = QLineEdit(project["name"] if project else "")
        self.name.setPlaceholderText(text(i18n, "Название проекта", "Project name"))
        root.addWidget(self.name)
        self.color_value = project.get("color", "#3778bd") if project else repository.next_project_color()
        self.color_button = QPushButton(text(i18n, "Цвет проекта", "Project color"))
        self.color_button.clicked.connect(self.choose_color)
        root.addWidget(self.color_button)
        self.update_color_preview()
        self.error = QLabel(text(i18n, "Введите название", "Enter a name"))
        self.error.hide()
        root.addWidget(self.error)
        if project:
            self.archive_button = QPushButton(text(i18n, "Вернуть из архива" if project["archived"] else "В архив",
                                                   "Restore from archive" if project["archived"] else "Archive"))
            self.archive_button.clicked.connect(self.archive)
            root.addWidget(self.archive_button)
            self.delete_button = QPushButton(text(i18n, "Удалить проект", "Delete project"))
            self.delete_button.clicked.connect(self.delete)
            root.addWidget(self.delete_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        polish_dialog_buttons(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def update_color_preview(self):
        self.color_button.setText(self.color_button.text().split(" · ")[0] + " · " + self.color_value)

    def choose_color(self):
        dialog = QColorDialog(QColor(self.color_value), self)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if dialog.exec():
            self.color_value = dialog.selectedColor().name()
            self.update_color_preview()

    def save(self):
        if not self.name.text().strip():
            self.error.show()
            return
        self.repository.save_work_project(self.name.text(), self.project["outcome"] if self.project else "",
                                          self.project["id"] if self.project else None, color=self.color_value)
        self.accept()

    def archive(self):
        self.repository.archive_work_project(self.project["id"], not self.project["archived"])
        self.accept()

    def delete(self):
        confirmation = DeleteProjectDialog(self.i18n, self.project["name"], self)
        if confirmation.exec() == RoundedDialog.DialogCode.Accepted:
            self.repository.delete_work_project(self.project["id"])
            self.accept()


class DeleteProjectDialog(RoundedDialog):
    """Nested embedded confirmation; cancellation is the safe default."""

    def __init__(self, i18n, name, parent):
        super().__init__(parent)
        self.setWindowTitle(text(i18n, "Удалить проект", "Delete project"))
        self.resize(460, 240)
        root = QVBoxLayout(self)
        message = QLabel(text(i18n,
            f"Проект «{name}».\n\nВы уверены, что хотите удалить? Отменить это действие будет невозможно."
            "\n\nЗадачи и привычки сохранятся без привязки к этому проекту.",
            f"Project “{name}”.\n\nAre you sure you want to delete it? This action cannot be undone."
            "\n\nTasks and habits will remain, without this project assignment."))
        message.setWordWrap(True)
        root.addWidget(message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        polish_dialog_buttons(buttons)
        remove = buttons.button(QDialogButtonBox.StandardButton.Save)
        remove.setText(text(i18n, "Удалить проект", "Delete project"))
        remove.setAutoDefault(False)
        remove.setDefault(False)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText(i18n.t("cancel"))
        cancel.setDefault(True)
        cancel.setFocus()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class CaptureScheduleDialog(RoundedDialog):
    def __init__(self, repository, i18n, capture, parent):
        super().__init__(parent)
        self.repository, self.capture = repository, capture
        self.setWindowTitle(text(i18n, "Запланировать дело", "Schedule captured task"))
        self.resize(480, 250)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.day = ScrollDateEdit(QDate.currentDate())
        self.project = QComboBox()
        self.project.addItem(text(i18n, "Без проекта", "No project"), None)
        for project in repository.work_projects():
            self.project.addItem(project["name"], project["id"])
        form.addRow(text(i18n, "Дата задачи", "Task date"), self.day)
        form.addRow(text(i18n, "Проект", "Project"), self.project)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        polish_dialog_buttons(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.t("save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.t("cancel"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        self.repository.schedule_capture(self.capture["id"], self.day.date().toPython(),
                                          self.project.currentData())
        self.accept()

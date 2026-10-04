"""Small settings form; values are persisted only when Settings is saved."""

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
)

from .resources import CharacterConfig, epsilon_manifest


class CharacterSettings(QGroupBox):
    def __init__(self, repository, i18n, parent=None):
        ru = i18n.language == "ru"
        super().__init__(
            "Персонаж Live2D — Epsilon" if ru else "Live2D character — Epsilon", parent
        )
        self.repository = repository
        config = CharacterConfig.load(repository)
        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.enabled = QCheckBox("Показывать персонажа" if ru else "Show character")
        self.enabled.setChecked(config.enabled)
        form.addRow(self.enabled)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.5, 2.0)
        self.scale.setSingleStep(0.1)
        self.scale.setValue(config.scale)
        form.addRow("Масштаб" if ru else "Scale", self.scale)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.1, 1.0)
        self.opacity.setSingleStep(0.1)
        self.opacity.setValue(config.opacity)
        form.addRow("Непрозрачность" if ru else "Opacity", self.opacity)
        self.offset_x, self.offset_y = QSpinBox(), QSpinBox()
        for spin, value in ((self.offset_x, config.offset_x), (self.offset_y, config.offset_y)):
            spin.setRange(-1000, 1000)
            spin.setSuffix(" px")
            spin.setValue(value)
        form.addRow("Отступ справа" if ru else "Right offset", self.offset_x)
        form.addRow("Отступ снизу" if ru else "Bottom offset", self.offset_y)
        self.idle = QCheckBox("Анимации ожидания" if ru else "Idle animations")
        self.idle.setChecked(config.idle)
        form.addRow(self.idle)
        self.interaction = QCheckBox(
            "Реакция на курсор и нажатия" if ru else "React to cursor and clicks"
        )
        self.interaction.setChecked(config.interaction)
        self.interaction.setToolTip(
            "Поглаживание: зажми левую кнопку и проведи по голове или щеке."
            if ru else "To stroke: hold the left mouse button and move over the head or cheek."
        )
        form.addRow(self.interaction)
        self.reactions = QCheckBox("Реакции на выполненные задачи" if ru else "Task completion reactions")
        self.reactions.setChecked(config.reactions)
        form.addRow(self.reactions)
        self.captions = QCheckBox("Короткие реплики" if ru else "Short captions")
        self.captions.setChecked(config.captions)
        form.addRow(self.captions)
        self.voice = QCheckBox("Локальный голос (необязательно)" if ru else "Local voice (optional)")
        self.voice.setChecked(config.voice)
        form.addRow(self.voice)
        voice_note = QLabel(
            str(QApplication.instance().property("live2dVoiceError") or "")
            or ("Голос зависит от установленного системного синтезатора. Без облака."
                if ru else "Voice requires an installed system speech engine. No cloud.")
        )
        voice_note.setWordWrap(True)
        form.addRow(voice_note)
        status = str(QApplication.instance().property("live2dError") or "")
        if not epsilon_manifest().is_file():
            status = (
                "Модель не установлена. См. docs/live2d.md."
                if ru
                else "Model not installed. See docs/live2d.md."
            )
        self.status = QLabel(
            status
            or (
                "Работает локально. Epsilon © Live2D Inc."
                if ru
                else "Runs locally. Epsilon © Live2D Inc."
            )
        )
        self.status.setWordWrap(True)
        form.addRow(self.status)

    def save(self):
        CharacterConfig(
            enabled=self.enabled.isChecked(),
            scale=self.scale.value(),
            offset_x=self.offset_x.value(),
            offset_y=self.offset_y.value(),
            opacity=self.opacity.value(),
            idle=self.idle.isChecked(),
            interaction=self.interaction.isChecked(),
            reactions=self.reactions.isChecked(),
            captions=self.captions.isChecked(),
            voice=self.voice.isChecked(),
        ).save(self.repository)

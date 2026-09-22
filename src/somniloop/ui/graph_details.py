"""Human-readable graph inspector with source links and explicit contradictions."""

from __future__ import annotations

import html
from datetime import date
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from somniloop.core.dates import age_on, display_date, display_timestamp
from somniloop.knowledge.people import has_birth_conflict, humanize_details

from .controls import rich_details
from .graph_data import CATEGORY_NAMES
from .graph_items import colors


def section(title, value):
    if not value:
        return ""
    values = value if isinstance(value, list) else [value]
    body = "".join(
        f"<p>{html.escape(humanize_details(item)).replace(chr(10), '<br>')}</p>"
        for item in values
        if item
    )
    return f"<h3>{html.escape(title)}</h3>{body}" if body else ""


def details_html(node, source_limit=40):
    metadata = node.metadata
    person = metadata.get("profile", {})
    result = ""
    updated = metadata.get("graph_updated_at", "")
    if person:
        result += section("О человеке", person.get("biography"))
        result += section(
            "Связь со мной", person.get("relationship") or metadata.get("relationship")
        )
        birth = person.get("birth_date", "")
        if birth:
            result += section("Дата рождения", display_date(birth))
            try:
                as_of = date.fromisoformat(updated[:10]) if updated else date.today()
            except ValueError:
                as_of = date.today()
            age = age_on(birth, as_of)
            if age is not None and not has_birth_conflict(
                {"conflicts": metadata.get("conflicts", [])}
            ):
                result += section("Возраст", f"{age} · на {display_date(as_of)}")
        for key, title in (
            ("occupation", "Сейчас"),
            ("education", "Образование"),
            ("history", "Учёба и работа · история"),
            ("interests", "Интересы"),
            ("facts", "Важные сведения"),
            ("contact", "Контакт"),
        ):
            result += section(title, person.get(key))
    if not result:
        result = rich_details(node.details or "Сведения пока не заполнены.")
    conflicts = metadata.get("conflicts", [])
    if conflicts:
        result += f'<h3 style="color:{colors()["warning"]}">⚠ Противоречивые сведения</h3><p>Обе версии сохранены. Уточните, какая из них верна.</p>'
        for index, conflict in enumerate(conflicts):
            result += f'<p style="color:{colors()["warning"]}"><u>{html.escape(humanize_details(conflict))}</u></p>'
            if metadata.get("person_id"):
                result += f'<p><a href="clarify:{metadata["person_id"]}:{index}">Уточнить сведения</a></p>'
    sources = metadata.get("sources", [])
    if sources:
        result += "<h3>Упоминания и источники</h3>"
        ordered = sorted(
            (source for source in sources if isinstance(source, dict)),
            key=lambda source: str(source.get("date", "")),
            reverse=True,
        )
        for source in ordered[:source_limit]:
            if not isinstance(source, dict):
                continue
            identifier = str(source.get("id", source.get("source_id", "")))
            title = str(source.get("title", source.get("source_title", "Источник")))
            stamp = str(source.get("date", ""))[:10]
            caption = html.escape(title + (f" · {display_date(stamp)}" if stamp else ""))
            if identifier:
                caption = f'<a href="source:{quote(identifier, safe="")}">{caption}</a>'
            result += f"<p>{caption}</p>"
            if source.get("evidence"):
                evidence = str(source["evidence"])
                excerpt = evidence[:600] + ("…" if len(evidence) > 600 else "")
                result += f"<blockquote>{html.escape(excerpt)}</blockquote>"
        if len(ordered) > source_limit:
            result += f'<p><a href="more-sources">Показать ещё источники · осталось {len(ordered) - source_limit}</a></p>'
    last = person.get("updated_at", "")
    connections = metadata.get("inferred_connections", [])
    if connections:
        result += "<h3>Возможные знакомства · гипотезы LLM</h3>"
        for connection in connections[:source_limit]:
            result += section(connection["name"], connection["reason"])
            result += section("Основание в этом досье", connection["evidence"])
            result += section("Основание в досье другого человека", connection["other_evidence"])
        if len(connections) > source_limit:
            result += '<p><a href="more-sources">Показать ещё предполагаемые связи</a></p>'
    if last:
        result += section("Сведения обновлены", display_timestamp(last))
    if updated:
        result += section("Граф обновлён", display_timestamp(updated))
    return result


class GraphDetailsPanel(QFrame):
    close_requested = Signal()
    person_requested = Signal(object)
    source_requested = Signal(str)
    neighborhood_requested = Signal(str)
    pin_requested = Signal(str, bool)
    bio_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumWidth(270)
        self.node = None
        self._source_limit = 40
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        eyebrow = QLabel("КАРТОЧКА УЗЛА")
        eyebrow.setObjectName("muted")
        eyebrow.setStyleSheet("font-size: 10px; letter-spacing: 1px;")
        header = QHBoxLayout()
        header.addWidget(eyebrow, 1)
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(32, 32)
        self.close_button.setToolTip("Закрыть карточку · Esc")
        self.close_button.setAccessibleName("Закрыть карточку узла")
        self.close_button.clicked.connect(self.close_requested)
        header.addWidget(self.close_button)
        root.addLayout(header)
        self.title = QLabel("Выберите узел")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setObjectName("sectionTitle")
        self.title.setWordWrap(True)
        root.addWidget(self.title)
        self.category = QLabel("Люди и привычки — в одном пространстве")
        self.category.setWordWrap(True)
        self.category.setObjectName("muted")
        root.addWidget(self.category)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setStyleSheet("background: transparent; border: none;")
        self.browser.document().setDefaultStyleSheet(
            f"h3 {{ font-size: 13px; margin-top: 18px; margin-bottom: 5px; }} p {{ margin: 5px 0; }} a {{ color: {('#345f94' if colors()['light'] else '#9abbe4')}; }} blockquote {{ margin: 5px 0 14px 12px; }}"
        )
        self.browser.setPlainText(
            "Нажмите на человека, чтобы увидеть его историю, факты и источники.\n\nСтрелки переключают узлы, P закрепляет позицию, 0 показывает весь граф."
        )
        self.browser.anchorClicked.connect(self._link)
        root.addWidget(self.browser, 1)
        self.edit = QPushButton("Открыть карточку человека")
        self.edit.setObjectName("primary")
        self.edit.clicked.connect(self._edit)
        root.addWidget(self.edit)
        row = QHBoxLayout()
        self.nearby = QPushButton("Окружение")
        self.nearby.clicked.connect(
            lambda: self.neighborhood_requested.emit(self.node.id) if self.node else None
        )
        self.pin = QPushButton("Закрепить")
        self.pin.setCheckable(True)
        self.pin.clicked.connect(
            lambda value: self.pin_requested.emit(self.node.id, value) if self.node else None
        )
        row.addWidget(self.nearby)
        row.addWidget(self.pin)
        root.addLayout(row)
        self.edit.hide()
        self.nearby.setEnabled(False)
        self.pin.setEnabled(False)

    def show_node(self, node, degree=0, pinned=False):
        self.node = node
        self._source_limit = 40
        self.title.setText(node.label)
        self.category.setText(
            f"{CATEGORY_NAMES.get(node.category, node.category)} · Связей: {degree}"
        )
        status = node.metadata.get("view_status", "")
        self.status.setText(
            {
                "new": "● Новые сведения",
                "changed": "● Сведения изменились",
                "stale": "◷ Источники изменены · обновите граф",
            }.get(status, "")
        )
        self.status.setStyleSheet(
            f"color:{colors()['warning'] if status in ('changed', 'stale') else colors()['muted']}; font-size:12px;"
        )
        self.browser.setHtml(details_html(node))
        self.edit.setVisible(bool(node.metadata.get("person_id") or node.metadata.get("is_owner")))
        self.edit.setText(
            "Открыть моё био" if node.metadata.get("is_owner") else "Открыть карточку человека"
        )
        self.nearby.setEnabled(node.category != "groups")
        if node.category == "groups":
            self.status.setText("Двойной щелчок или Enter — перейти к людям")
        self.pin.setEnabled(node.category != "groups")
        self.pin.setChecked(pinned)
        self.pin.setText("Открепить" if pinned else "Закрепить")

    def _edit(self):
        if self.node.metadata.get("is_owner"):
            self.bio_requested.emit()
        elif self.node.metadata.get("person_id"):
            self.person_requested.emit((self.node.metadata["person_id"], None))

    def _link(self, url):
        value = url.toString()
        if value == "more-sources" and self.node:
            position = self.browser.verticalScrollBar().value()
            self._source_limit += 40
            self.browser.setHtml(details_html(self.node, self._source_limit))
            self.browser.verticalScrollBar().setValue(position)
        elif value.startswith("source:"):
            self.source_requested.emit(unquote(value[7:]))
        elif value.startswith("clarify:"):
            try:
                _, person_id, index = value.split(":", 2)
                self.person_requested.emit((int(person_id), int(index)))
            except ValueError:
                pass

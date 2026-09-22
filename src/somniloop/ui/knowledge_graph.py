from __future__ import annotations

import json
import time
from collections import deque

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from somniloop.core.dates import display_timestamp
from somniloop.knowledge.pipeline import BuildCancelled, KnowledgeBuilder, source_fingerprint

from .controls import show_saved
from .graph_canvas import GraphView
from .graph_data import CATEGORY_NAMES, GraphIndex, enriched_graph
from .graph_details import GraphDetailsPanel, section
from .graph_items import colors


class GraphBuildThread(QThread):
    graph_ready = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(object)
    cache_ready = Signal(str, object)

    def __init__(self, source: dict, model_path: str, cache: dict, find_connections=False) -> None:
        super().__init__()
        self.source, self.model_path, self.cache = source, model_path, cache
        self.find_connections = find_connections

    def run(self) -> None:
        try:
            builder = KnowledgeBuilder(
                self.model_path,
                self.cache,
                self.progress.emit,
                self.isInterruptionRequested,
                cache_saved=self.cache_ready.emit,
                find_connections=self.find_connections,
            )
            self.graph_ready.emit(builder.build(self.source))
        except BuildCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class GraphProgressDialog(QDialog):
    """Modeless progress window backed by real knowledge-pipeline stages."""

    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Обновление графа знаний")
        self.setMinimumWidth(520)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._started_at = time.monotonic()
        self._last_sample_at = self._started_at
        self._last_processed = 0
        self._unit_times = deque(maxlen=12)
        self._running = True

        root = QVBoxLayout(self)
        self.phase_label = QLabel("Этап 1 из 5 · Подготовка")
        self.phase_label.setObjectName("sectionTitle")
        root.addWidget(self.phase_label)
        self.title_label = QLabel("Собираю исходные данные…")
        self.title_label.setWordWrap(True)
        root.addWidget(self.title_label)
        self.activity_label = QLabel()
        self.activity_label.setObjectName("muted")
        self.activity_label.setWordWrap(True)
        root.addWidget(self.activity_label)
        self.plan_label = QLabel("Определяю объём работы…")
        self.plan_label.setWordWrap(True)
        root.addWidget(self.plan_label)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setFormat("0,0%")
        root.addWidget(self.bar)
        self.stage_label = QLabel()
        self.stage_label.setWordWrap(True)
        self.stage_label.hide()
        root.addWidget(self.stage_label)
        self.stage_bar = QProgressBar()
        self.stage_bar.setTextVisible(False)
        self.stage_bar.setRange(0, 10000)
        self.stage_bar.hide()
        root.addWidget(self.stage_bar)
        self.counts_label = QLabel("Определяю объём работы…")
        self.counts_label.setObjectName("muted")
        self.counts_label.setWordWrap(True)
        root.addWidget(self.counts_label)
        self.time_label = QLabel("Прошло: 0 с · Оценка времени появится после первых результатов")
        self.time_label.setObjectName("muted")
        root.addWidget(self.time_label)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton("Остановить обновление")
        self.cancel_button.clicked.connect(self._cancel)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._update_time)
        self._clock.start()
        self._last_event = {}

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0, round(seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours} ч {minutes:02d} мин"
        if minutes:
            return f"{minutes} мин {seconds:02d} с"
        return f"{seconds} с"

    def _cancel(self) -> None:
        if not self._running:
            return
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Останавливаю…")
        self.activity_label.setText("Отмена запрошена")
        self.cancel_requested.emit()

    def update_progress(self, event: dict) -> None:
        now = time.monotonic()
        if event.get("phase") != self._last_event.get("phase"):
            self._last_sample_at = now
            self._last_processed = 0
            self._unit_times.clear()
        self._last_event = dict(event)
        processed = int(event.get("stage_done", event.get("processed_changes", 0)))
        if processed > self._last_processed:
            elapsed = now - self._last_sample_at
            self._unit_times.append(elapsed / (processed - self._last_processed))
            self._last_sample_at = now
            self._last_processed = processed

        percent = float(event.get("percent", 0))
        if "work_total" in event:
            done, total = int(event["work_done"]), int(event["work_total"])
            percent = 100 * done / max(1, total)
            self.bar.setRange(0, 10000)
            self.bar.setValue(round(percent * 100))
            self.bar.setFormat(f"План: {done}/{total} операций · {percent:.2f}%".replace(".", ","))
            stage_done, stage_total = int(event["stage_done"]), int(event["stage_total"])
            self.stage_bar.show()
            self.stage_bar.setValue(round(10000 * stage_done / max(1, stage_total)))
            unit = "человек" if event["phase"] in {"connections", "merge"} else "операций"
            self.stage_bar.setFormat(
                f"Этап: {stage_done}/{stage_total} {unit} · {100 * stage_done / max(1, stage_total):.2f}%".replace(
                    ".", ","
                )
            )
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(round(percent * 10))
            self.bar.setFormat(f"{percent:.1f}%".replace(".", ","))
        self.plan_label.setText(self.bar.format())
        self.stage_label.setVisible(not self.stage_bar.isHidden())
        self.stage_label.setText(self.stage_bar.format())
        phase_names = {
            "prepare": "Подготовка",
            "analyze": "Анализ изменений",
            "merge": "Сборка досье",
            "links": "Построение связей",
            "connections": "Поиск знакомств · LLM",
            "save": "Сохранение",
            "done": "Готово",
        }
        phase = str(event.get("phase", "prepare"))
        self.phase_label.setText(
            f"Этап {event.get('phase_index', 1)} из {event.get('phase_total', 5)} · "
            f"{phase_names.get(phase, phase)}"
        )
        self.title_label.setText(str(event.get("title", "")))
        if self.cancel_button.isEnabled():
            self.activity_label.setText(
                "\n".join(
                    dict.fromkeys(
                        str(event[key]) for key in ("recovery", "activity") if event.get(key)
                    )
                )
            )
        pending = int(event.get("pending_changes", 0))
        cached = int(event.get("planned_cached", 0))
        cache_hits = int(event.get("cache_hits", 0))
        calls = int(event.get("model_calls", 0))
        documents = int(event.get("changed_documents", 0))
        if phase == "prepare" and not event.get("chunks"):
            self.counts_label.setText("Определяю объём работы…")
        elif phase == "connections":
            self.counts_label.setText(
                f"Полностью обработано людей: {processed}/{event.get('stage_total', event.get('total', 0))} · "
                f"Кэш: {cache_hits} · Вызовов LLM: {calls}. Повторные попытки не увеличивают процент."
            )
        else:
            self.counts_label.setText(
                f"Изменения: {processed}/{pending} · Изменённых источников: {documents} · "
                f"Кэш: {cache_hits} попаданий ({cached} найдено заранее) · Вызовов LLM: {calls}"
            )
        self._update_time()

    def _eta_seconds(self) -> float | None:
        event = self._last_event
        processed = int(event.get("stage_done", event.get("processed_changes", 0)))
        pending = int(event.get("stage_total", event.get("pending_changes", 0)))
        if (
            event.get("phase") in {"analyze", "merge", "connections"}
            and self._unit_times
            and processed < pending
        ):
            mean = sum(self._unit_times) / len(self._unit_times)
            current_elapsed = time.monotonic() - self._last_sample_at
            if current_elapsed > 2 * mean:
                return None  # An unusually long attempt invalidates this estimate.
            return max(1, mean * (pending - processed) - current_elapsed)
        if float(event.get("percent", 0)) >= 100:
            return 0
        return None

    def _update_time(self) -> None:
        elapsed = time.monotonic() - self._started_at
        eta = self._eta_seconds()
        remaining = (
            "Прогноз уточняется"
            if eta is None
            else f"До конца этапа: примерно {self._duration(eta)}"
        )
        self.time_label.setText(f"Прошло: {self._duration(elapsed)} · {remaining}")

    def complete(self, success: bool, message: str) -> None:
        self._running = False
        self._clock.stop()
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Готово" if success else "Закрыть")
        self.activity_label.clear()
        self.title_label.setText(message)
        if success:
            self.bar.setValue(self.bar.maximum())
            self.bar.setFormat("100,0%")
            self.plan_label.setText("План выполнен · 100,00%")
            if not self.stage_bar.isHidden():
                self.stage_bar.setValue(self.stage_bar.maximum())
                self.stage_bar.setFormat("Сохранено · 100,00%")
                self.stage_label.setText(self.stage_bar.format())
            if "work_total" in self._last_event:
                total = self._last_event["work_total"]
                self.counts_label.setText(
                    f"Выполнено {total}/{total} операций плана. Граф сохранён."
                )
            self.phase_label.setText("Этап 5 из 5 · Готово")
            self.time_label.setText(
                f"Выполнено за {self._duration(time.monotonic() - self._started_at)}"
            )
            QTimer.singleShot(900, self.close)
        else:
            self.cancel_button.setEnabled(True)
            self.cancel_button.clicked.disconnect()
            self.cancel_button.clicked.connect(self.close)

    def closeEvent(self, event) -> None:
        if self._running:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)


class KnowledgeGraphPage(QWidget):
    bio_requested = Signal()
    people_requested = Signal(object)
    source_requested = Signal(str)
    graph_updated = Signal()

    def __init__(self, repository, i18n, parent=None):
        super().__init__(parent)
        self.repository, self.i18n = repository, i18n
        self.current_category = "all"
        self.neighborhood = None
        self.all_nodes, self.all_edges = [], []
        self.index = GraphIndex()
        self.worker = self.progress_dialog = None
        self.rebuild_label = i18n.t("rebuild_graph")
        root = QVBoxLayout(self)
        root.setSpacing(12)
        top = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Граф знаний")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        self.summary = QLabel("Люди и привычки · ваши связи и их история")
        self.summary.setObjectName("muted")
        heading.addWidget(self.summary)
        top.addLayout(heading, 1)
        for caption, callback in (
            ("Моё био", self.bio_requested.emit),
            ("Люди", lambda: self.people_requested.emit(None)),
        ):
            button = QPushButton(caption)
            button.clicked.connect(callback)
            top.addWidget(button)
        self.rebuild = QPushButton(self.rebuild_label)
        self.rebuild.setObjectName("primary")
        self.rebuild.clicked.connect(lambda: self._rebuild())
        top.addWidget(self.rebuild)
        root.addLayout(top)
        self.connections_skill = QCheckBox("Навык LLM: искать связи людей")
        self.connections_skill.setChecked(
            repository.get_setting("graph_find_connections", "0") == "1"
        )
        self.connections_skill.setToolTip(
            "При обновлении сопоставлять места учёбы, работодателей, группы и годы. "
            "Предполагаемые знакомства показываются пунктиром и не считаются фактами. "
            "Требуется локальная LLM; неизменившиеся досье берутся из кэша."
        )
        self.connections_skill.toggled.connect(
            lambda checked: repository.set_setting(
                "graph_find_connections", "1" if checked else "0"
            )
        )
        self.connections_skill.toggled.connect(lambda: self.mark_stale())
        root.addWidget(self.connections_skill)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Найти по имени, биографии, фактам или источникам…")
        self.search.setAccessibleName("Поиск по графу")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self._search_changed)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        search_row.addWidget(self.search, 1)
        self.relations = QComboBox()
        self.relations.setMinimumWidth(190)
        self.relations.setAccessibleName("Фильтр по типу связи")
        self.relations.currentIndexChanged.connect(self._apply_filter)
        search_row.addWidget(self.relations)
        root.addLayout(search_row)
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self.search.setFocus)
        filters = QHBoxLayout()
        self.filter_group = QButtonGroup(self)
        self.filter_buttons = {}
        for category, caption in (
            ("all", "Все"),
            ("people", "Люди"),
            ("habits", "Привычки"),
        ):
            button = QPushButton(caption)
            button.setCheckable(True)
            button.setChecked(category == "all")
            button.clicked.connect(lambda checked=False, value=category: self._set_category(value))
            self.filter_group.addButton(button)
            self.filter_buttons[category] = button
            filters.addWidget(button)
        self.back = QPushButton("← Весь граф")
        self.back.clicked.connect(self._all_graph)
        self.back.hide()
        filters.addWidget(self.back)
        filters.addStretch()
        self.graph_view = GraphView(repository=repository)
        self.graph_view.node_clicked.connect(self._show_node)
        self.graph_view.neighborhood_requested.connect(self._neighborhood)
        self.graph_view.pin_changed.connect(self._pin_changed)
        for caption, tooltip, callback in (
            ("−", "Уменьшить масштаб", lambda: self.graph_view.zoom(1 / 1.2)),
            ("+", "Увеличить масштаб", lambda: self.graph_view.zoom(1.2)),
            ("Вписать", "Показать все видимые узлы · 0", self.graph_view.fit_nodes),
        ):
            button = QPushButton(caption)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            filters.addWidget(button)
        root.addLayout(filters)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.graph_view)
        self.inspector = GraphDetailsPanel()
        self.inspector.close_requested.connect(self.graph_view.clear_selection)
        self.graph_view.selection_cleared.connect(self._close_inspector)
        self.close_inspector_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.close_inspector_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.close_inspector_shortcut.activated.connect(self.graph_view.clear_selection)
        self.inspector.person_requested.connect(self.people_requested)
        self.inspector.bio_requested.connect(self.bio_requested)
        self.inspector.source_requested.connect(self._open_source)
        self.inspector.neighborhood_requested.connect(self._neighborhood)
        self.inspector.pin_requested.connect(self.graph_view.set_pinned)
        self.results = QListWidget()
        self.results.setMaximumHeight(175)
        self.results.itemClicked.connect(self._result_selected)
        self.results.itemActivated.connect(self._result_selected)
        self.results.hide()
        self.inspector.layout().insertWidget(1, self.results)
        self.node_title = self.inspector.title
        self.node_category = self.inspector.category
        self.node_details = self.inspector.browser
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([900, 310])
        self._inspector_width = 310
        self.inspector.hide()
        root.addWidget(self.splitter, 1)
        self.build_status = QLabel()
        self.build_status.setObjectName("timestamp")
        self.build_status.setStyleSheet(f"color: {colors()['muted']}; font-size: 11px;")
        root.addWidget(self.build_status)
        self.refresh()

    def refresh(self):
        selected = self.inspector.node.id if self.inspector.node else None
        self.all_nodes, self.all_edges = enriched_graph(self.repository)
        # Preserve old place records in SQLite, but do not expose them on this canvas.
        self.all_nodes = [node for node in self.all_nodes if node.category != "places"]
        visible = {node.id for node in self.all_nodes}
        self.all_edges = [
            edge for edge in self.all_edges if edge.source in visible and edge.target in visible
        ]
        self.index = GraphIndex(self.all_nodes, self.all_edges)
        for node in self.all_nodes:
            node.metadata["view_status"] = self.graph_view.state.status(
                node, self.index.signatures[node.id]
            )
        self.relations.blockSignals(True)
        previous = self.relations.currentData()
        self.relations.clear()
        self.relations.addItem("Все типы связей", "")
        for relation in sorted({edge.relation for edge in self.all_edges}):
            self.relations.addItem(relation, relation)
        self.relations.setCurrentIndex(max(0, self.relations.findData(previous)))
        self.relations.blockSignals(False)
        self._apply_filter()
        if selected in self.index.nodes:
            self._show_node(self.index.nodes[selected])
        elif selected is not None:
            self._close_inspector()
        updated = self.repository.get_setting("graph_updated_at")
        self.build_status.setText(
            "Граф ещё не обновлялся" if not updated else f"Обновлён {display_timestamp(updated)}"
        )
        try:
            report = json.loads(self.repository.get_setting("graph_connections_report", "{}"))
        except (ValueError, TypeError):
            report = {}
        if report.get("failures"):
            self.build_status.setText(
                f"Поиск знакомств не завершён: {report['done']}/{report['total']} человек. Успешная работа сохранена."
            )
            self.rebuild.setText("Продолжить поиск связей")
        if self.repository.get_setting("graph_input_hash") != source_fingerprint(
            self.repository.knowledge_source()
        ):
            self.mark_stale()

    def mark_stale(self):
        self.build_status.setText(self.i18n.t("graph_needs_refresh"))

    def _set_category(self, category):
        self.current_category = category
        self._apply_filter()

    def _apply_filter(self, *_):
        nodes, edges = self.index.subset(
            self.current_category, self.relations.currentData() or "", self.neighborhood
        )
        self.graph_view.set_graph(nodes, edges)
        self.summary.setText(f"Узлов: {len(nodes)} из {len(self.all_nodes)} · Связей: {len(edges)}")
        self.back.setVisible(bool(self.neighborhood))
        self._search_changed()

    def _search_changed(self):
        self.results.clear()
        query = self.search.text().strip()
        self.results.setVisible(bool(query))
        if not query:
            self.graph_view.highlight(None)
            return
        matches = [key for key in self.index.search(query) if key in self.graph_view.nodes]
        self.graph_view.highlight(set(matches))
        for key in matches:
            node = self.index.nodes[key]
            item = QListWidgetItem(
                f"{node.label} · {CATEGORY_NAMES.get(node.category, node.category)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.results.addItem(item)
        if matches:
            self._show_node(self.index.nodes[matches[0]])
        else:
            self._open_inspector()
            self.inspector.node = None
            self.node_title.setText("Ничего не найдено")
            self.node_category.clear()
            self.inspector.status.clear()
            self.inspector.edit.hide()
            self.inspector.pin.setEnabled(False)
            self.inspector.nearby.setEnabled(False)
            self.node_details.setPlainText(
                "Совпадений нет. Попробуйте другой запрос или снимите фильтры."
            )

    def _result_selected(self, item):
        identifier = item.data(Qt.ItemDataRole.UserRole)
        self.graph_view.focus_node(identifier)
        self._show_node(self.index.nodes[identifier])

    def _show_node(self, node):
        self._open_inspector()
        self.inspector.show_node(
            node, len(self.index.adjacency[node.id]), node.id in self.graph_view.state.pinned
        )
        if node.id in self.index.signatures:
            self.graph_view.state.seen[node.id] = self.index.signatures[node.id]
            self.graph_view.schedule_save()

    def _open_inspector(self):
        if self.inspector.isHidden():
            self.inspector.show()
            width = min(self._inspector_width, max(270, self.splitter.width() // 3))
            self.splitter.setSizes([max(1, self.splitter.width() - width), width])

    def _close_inspector(self):
        # Forget the selection so refresh cannot reopen a dismissed card.
        self.search_timer.stop()
        if not self.inspector.isHidden():
            self._inspector_width = self.inspector.width()
        self.inspector.node = None
        self.inspector.hide()
        self.results.clear()
        self.results.hide()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.graph_view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _pin_changed(self, identifier, pinned):
        if self.inspector.node and self.inspector.node.id == identifier:
            self.inspector.pin.setChecked(pinned)
            self.inspector.pin.setText("Открепить" if pinned else "Закрепить")

    def _neighborhood(self, identifier):
        if identifier not in self.index.nodes:
            return
        self.neighborhood = identifier
        self.current_category = "all"
        self.filter_buttons["all"].setChecked(True)
        self._apply_filter()
        self.graph_view.fit_nodes()
        self._show_node(self.index.nodes[identifier])

    def _all_graph(self):
        self.neighborhood = None
        self.current_category = "all"
        self.filter_buttons["all"].setChecked(True)
        self.relations.setCurrentIndex(0)
        self._apply_filter()
        self.graph_view.fit_nodes()

    def _open_node_link(self, url):
        self.inspector._link(url)

    def _open_source(self, identifier):
        if identifier.startswith("note:"):
            self.source_requested.emit(identifier)
            return
        if identifier in ("bio", "profile"):
            self.bio_requested.emit()
            return
        if identifier.startswith("person:"):
            try:
                self.people_requested.emit((int(identifier.split(":")[1]), None))
                return
            except ValueError:
                pass
        sources = [
            source
            for node in self.all_nodes
            for source in node.metadata.get("sources", [])
            if source.get("id") == identifier
        ]
        source = sources[0] if sources else {}
        fragments = list(
            dict.fromkeys(str(item.get("evidence", "")) for item in sources if item.get("evidence"))
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Источник сведений")
        dialog.resize(600, 440)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(
            section(
                source.get("title") or "Источник",
                source.get("content") or fragments or "Исходный текст недоступен в текущей базе.",
            )
        )
        layout.addWidget(browser)
        close = QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _rebuild(self, offline: bool = False) -> None:
        if self.worker and self.worker.isRunning():
            if self.progress_dialog:
                self.progress_dialog.show()
                self.progress_dialog.raise_()
                self.progress_dialog.activateWindow()
            return
        if (
            self.connections_skill.isChecked()
            and not offline
            and not self.repository.get_setting("model_path", "")
        ):
            QMessageBox.information(
                self,
                "Поиск связей",
                "Выберите локальную LLM в настройках, чтобы использовать этот навык.",
            )
            return
        self.connections_skill.setEnabled(False)
        self.rebuild.setText("Показать ход обновления")
        self.build_status.setText(self.i18n.t("graph_building"))
        self.progress_dialog = GraphProgressDialog(self.window())
        self.progress_dialog.cancel_requested.connect(self._cancel)
        self.progress_dialog.show()
        path = "" if offline else self.repository.get_setting("model_path", "")
        self.worker = GraphBuildThread(
            self.repository.knowledge_source(),
            path,
            self.repository.load_knowledge_cache(),
            find_connections=self.connections_skill.isChecked() and not offline,
        )
        self.worker.graph_ready.connect(self._build_done)
        self.worker.failed.connect(self._build_failed)
        self.worker.cancelled.connect(self._build_cancelled)
        self.worker.progress.connect(self._progress)
        self.worker.cache_ready.connect(self.repository.save_knowledge_cache)
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker:
            self.worker.requestInterruption()
            self.build_status.setText(self.i18n.t("cancel_after_chunk"))

    def _progress(self, event: dict) -> None:
        if self.progress_dialog:
            self.progress_dialog.update_progress(event)
        percent = float(event.get("percent", 0))
        self.build_status.setText(f"План обновления: {percent:.2f}% · {event.get('title', '')}")

    def _finish(self) -> None:
        self.rebuild.setText(self.rebuild_label)
        self.connections_skill.setEnabled(True)

    def _build_done(self, result) -> None:
        work = {
            key: result.stats[key] for key in ("work_done", "work_total") if key in result.stats
        }
        if self.progress_dialog:
            self.progress_dialog.update_progress(
                {
                    "phase": "save",
                    "phase_index": 5,
                    "phase_total": 5,
                    "percent": 97,
                    "title": "Сохраняю граф в базе данных",
                    **work,
                    "stage_done": 0,
                    "stage_total": 1,
                    "changed_documents": result.stats.get("changed_documents", 0),
                    "pending_changes": result.stats.get("pending_changes", 0),
                    "processed_changes": result.stats.get("pending_changes", 0),
                    "planned_cached": result.stats.get("chunks", 0)
                    - result.stats.get("pending_changes", 0),
                    "cache_hits": result.stats.get("cache_hits", 0),
                    "model_calls": result.stats.get("model_calls", 0),
                    "chunks": result.stats.get("chunks", 0),
                }
            )
            QApplication.processEvents()
        if self.worker and self.worker.isInterruptionRequested():
            self._build_cancelled()
            return
        if not self.repository.apply_knowledge_result(result):
            self._finish()
            if self.progress_dialog:
                self.progress_dialog.complete(
                    False, "Исходные данные изменились — результат не сохранён"
                )
            self.mark_stale()
            return
        self._finish()
        self.refresh()
        failures = result.stats.get("connection_failures", [])
        if failures:
            message = (
                f"Основной граф сохранён. Поиск знакомств: полностью обработано "
                f"{result.stats['connections_done']}/{result.stats['connections_total']} человек. "
                "Есть необработанные фрагменты; нажмите «Продолжить поиск связей». "
                "Успешные результаты сохранены в кэше.\n"
                + "\n".join(f"{item['name']}: {item['error']}" for item in failures[:5])
            )
            self.rebuild.setText("Продолжить поиск связей")
            self.build_status.setText(message.split("\n")[0])
            if self.progress_dialog:
                if work:
                    self.progress_dialog.update_progress(
                        {
                            "phase": "save",
                            "phase_index": 5,
                            "percent": 100 * (work["work_done"] + 1) / work["work_total"],
                            **work,
                            "work_done": work["work_done"] + 1,
                            "stage_done": 1,
                            "stage_total": 1,
                            "title": "Основной граф сохранён",
                        }
                    )
                self.progress_dialog.complete(False, message)
            self.graph_updated.emit()
            return
        self.build_status.setText(
            self.i18n.t(
                "graph_stats", calls=result.stats["model_calls"], cached=result.stats["cache_hits"]
            )
        )
        if self.progress_dialog:
            self.progress_dialog.complete(True, "Граф знаний обновлён")
        self.graph_updated.emit()
        show_saved(self, self.i18n.t("graph_ready"))

    def _build_cancelled(self) -> None:
        self._finish()
        if self.progress_dialog:
            self.progress_dialog.complete(False, "Обновление остановлено. Прежний граф сохранён")
        self.build_status.setText(self.i18n.t("graph_cancelled"))

    def _build_failed(self, error: str) -> None:
        self._finish()
        if self.progress_dialog:
            self.progress_dialog.complete(False, f"Ошибка: {error}")
        self.build_status.setText(self.i18n.t("graph_preserved"))
        if self.repository.get_setting("model_path"):
            answer = QMessageBox.question(
                self, self.i18n.t("knowledge"), self.i18n.t("graph_fallback_question", error=error)
            )
            if answer == QMessageBox.StandardButton.Yes:
                if self.worker and self.worker.isRunning():
                    self.worker.finished.connect(lambda: self._rebuild(offline=True))
                else:
                    QTimer.singleShot(0, lambda: self._rebuild(offline=True))
        else:
            QMessageBox.warning(self, self.i18n.t("knowledge"), error)

import os
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTextBrowser

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.core.models import KnowledgeEdge, KnowledgeNode
from somniloop.ui.graph_canvas import GraphView
from somniloop.ui.graph_data import GraphIndex, GraphViewState, enriched_graph
from somniloop.ui.graph_details import details_html
from somniloop.ui.graph_layout import Body, ForceLayout
from somniloop.ui.knowledge_graph import KnowledgeGraphPage
from somniloop.ui.theme import stylesheet


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    repository = Repository(tmp_path / "graph.db")
    yield repository
    repository.close()


def sample_graph():
    nodes = [
        KnowledgeNode("me", "Роман", "people", "Моё био", {"is_owner": True}),
        KnowledgeNode(
            "anna",
            "Анна Ковалёва",
            "people",
            "Подруга",
            {
                "relationship": "друг",
                "person_id": 17,
                "profile": {
                    "biography": "Архитектор из Казани",
                    "birth_date": "2000-07-28",
                    "interests": ["Шахматы"],
                    "facts": ["Помогла с переездом"],
                    "occupation": "Архитектор",
                    "history": ["Училась в МГУ"],
                },
                "sources": [
                    {"id": "note:42", "title": "Встреча в парке", "evidence": "Обсудили выставку"}
                ],
            },
        ),
        KnowledgeNode("ira", "Ирина Смирнова", "people", "Коллега", {"relationship": "коллега"}),
        KnowledgeNode("city", "Казань", "places", "Родной город"),
        KnowledgeNode("habit", "Чтение", "habits", "Каждый вечер"),
    ]
    edges = [
        KnowledgeEdge("me", "anna", "дружит"),
        KnowledgeEdge("me", "ira", "работает"),
        KnowledgeEdge("anna", "city", "живёт"),
        KnowledgeEdge("me", "habit", "практикует"),
    ]
    return nodes, edges


@pytest.mark.parametrize(
    "query",
    ["Ковалева", "архитектор казан", "шахматы", "переезд", "мгу", "выставку", "встреча парке"],
)
def test_search_includes_profile_history_facts_and_sources(query):
    assert GraphIndex(*sample_graph()).search(query) == ["anna"]


def test_filters_combine_relationship_category_and_neighborhood():
    index = GraphIndex(*sample_graph())
    nodes, edges = index.subset("places", "живёт", "anna")
    assert {node.id for node in nodes} == {"anna", "city"}
    assert [edge.relation for edge in edges] == ["живёт"]
    nodes, edges = index.subset(focus="anna")
    assert {node.id for node in nodes} == {"anna", "city", "me"}
    assert len(edges) == 2


def test_position_and_pins_survive_refresh_filter_and_reopen(app, repo):
    nodes, edges = sample_graph()
    view = GraphView(repository=repo)
    view.set_graph(nodes, edges)
    view.nodes["anna"].setPos(1234, -567)
    view.set_pinned("anna", True)
    view.set_graph(nodes[:1], [])
    view.set_graph(nodes, edges)
    assert view.nodes["anna"].pos() == QPointF(1234, -567)
    view.save_state()
    restored = GraphView(repository=repo)
    restored.set_graph(nodes, edges)
    assert restored.nodes["anna"].pos() == QPointF(1234, -567)
    assert restored.nodes["anna"].pinned
    # Adding a new node must not move any existing anchor.
    original = {key: item.pos() for key, item in restored.nodes.items()}
    restored.set_graph([*nodes, KnowledgeNode("new", "Новый человек", "people")], edges)
    assert all(restored.nodes[key].pos() == point for key, point in original.items())
    view.close()
    restored.close()


def test_view_state_tolerates_damaged_settings(repo):
    repo.set_setting(
        GraphViewState.KEY, '{"positions":{"bad":[NaN,2],"good":[100,200]},"pinned":["good","bad"]}'
    )
    state = GraphViewState(repo)
    assert state.positions == {"good": (100, 200)}
    assert state.pinned == {"good"}


def test_archive_roundtrip_preserves_layout_and_ignores_delayed_old_page_save(repo, tmp_path):
    state = GraphViewState(repo)
    state.positions = {"anna": (120, 340)}
    state.pinned = {"anna"}
    state.save()
    payload = repo.export_payload()
    state.positions["anna"] = (999, 999)
    state.save()
    repo.restore_payload(payload)
    # Closing/rebuilding the old screen after restoring an archive must not undo it.
    state.positions["anna"] = (888, 777)
    state.save()
    restored = GraphViewState(repo)
    assert restored.positions == {"anna": (120, 340)}
    assert restored.pinned == {"anna"}


def test_relation_labels_follow_zoom_selection_and_hover(app):
    view = GraphView()
    nodes, edges = sample_graph()
    view.resize(1100, 800)
    view.set_graph(nodes, edges)
    view.nodes["me"].setPos(-300, 0)
    view.nodes["anna"].setPos(300, 0)
    view.centerOn(0, 0)
    edge = view.edges[0]
    view.resetTransform()
    view.scale(0.6, 0.6)
    view._update_edges()
    assert not edge.label.isVisible()
    view._clicked(nodes[0])
    assert edge.label.isVisible()
    view.highlight(None)
    edge.hovered = True
    edge.refresh_style()
    assert edge.label.isVisible()
    assert edge.pen().isCosmetic()
    view.close()


def test_new_changed_stale_indicators_cover_profile_edits(repo):
    nodes, edges = sample_graph()
    state = GraphViewState(repo)
    node = nodes[1]
    before = GraphIndex(nodes, edges).signatures[node.id]
    assert state.status(node, before) == "new"
    state.seen[node.id] = before
    assert state.status(node, before) == ""
    modified = replace(
        node, metadata={**node.metadata, "profile": {"biography": "Новая биография"}}
    )
    after = GraphIndex([modified], []).signatures[node.id]
    assert state.status(modified, after) == "changed"
    modified.metadata["stale"] = True
    assert state.status(modified, after) == "stale"


def test_contradictions_keep_both_versions_and_safe_source_links(app, repo):
    node = sample_graph()[0][1]
    node.metadata.update(
        {
            "graph_updated_at": "2026-09-16T12:00:00",
            "conflicts": [
                {"field": "occupation", "values": ["Архитектор", "Программист <script>"]}
            ],
        }
    )
    markup = details_html(node)
    assert "<u>" in markup and "clarify:17:0" in markup
    assert "Архитектор" in markup and "Программист &lt;script&gt;" in markup
    assert "source:note%3A42" in markup
    assert "26 · на 16 сен 2026" in markup
    browser = QTextBrowser()
    browser.setHtml(markup)
    assert "Противоречивые сведения" in browser.toPlainText()
    assert '"field"' not in browser.toPlainText()
    repo.replace_knowledge_graph([node], [])
    resolved, _ = enriched_graph(repo)
    assert resolved[0].metadata["conflicts"] == node.metadata["conflicts"]


def test_uncertain_birth_does_not_show_definitive_age(app):
    node = sample_graph()[0][1]
    node.metadata["conflicts"] = ["Дата рождения: 2000 или 2001 год"]
    assert "<h3>Возраст</h3>" not in details_html(node)


def test_long_source_history_is_loaded_in_small_pages(app):
    node = sample_graph()[0][1]
    node.metadata["sources"] = [
        {"id": f"note:{i}", "evidence": f"Фрагмент-{i}", "date": "2026-09-16"} for i in range(100)
    ]
    first = details_html(node)
    assert "Фрагмент-39" in first and "Фрагмент-40" not in first
    assert 'href="more-sources"' in first
    assert "Фрагмент-99" in details_html(node, 120)


def test_spatial_repulsion_has_bounded_neighbor_work_and_stops():
    bodies = {str(i): Body(*ForceLayout.initial(i)) for i in range(2000)}
    engine = ForceLayout(bodies, [])
    started = time.perf_counter()
    engine.step()
    assert engine.pair_checks < 2000 * 40  # Not the two million pairs of an all-pairs layout.
    assert time.perf_counter() - started < 3
    small = ForceLayout({str(i): Body(*ForceLayout.initial(i)) for i in range(40)}, [])
    for _ in range(360):
        small.step()
    assert small.settled
    values = list(small.bodies.values())
    assert not any(
        abs(a.x - b.x) < (a.width + b.width) / 2 and abs(a.y - b.y) < (a.height + b.height) / 2
        for i, a in enumerate(values)
        for b in values[i + 1 :]
    )


def test_dense_hub_has_no_overlaps_after_settling():
    bodies = {str(i): Body(*ForceLayout.initial(i)) for i in range(120)}
    bodies["0"].fixed = True
    engine = ForceLayout(bodies, [("0", str(i)) for i in range(1, 120)])
    for _ in range(360):
        if not engine.step():
            break
    assert engine.settled
    assert (bodies["0"].x, bodies["0"].y) == (0, 0)
    values = list(bodies.values())
    assert not any(
        abs(a.x - b.x) < (a.width + b.width) / 2 and abs(a.y - b.y) < (a.height + b.height) / 2
        for i, a in enumerate(values)
        for b in values[i + 1 :]
    )


def test_large_graph_search_and_scene_creation(app):
    nodes = [
        KnowledgeNode(str(i), f"Человек {i}", "people", f"Факт маркер{i}") for i in range(1200)
    ]
    edges = [KnowledgeEdge("0", str(i), "знает") for i in range(1, len(nodes))]
    started = time.perf_counter()
    index = GraphIndex(nodes, edges)
    assert index.search("маркер1199") == ["1199"]
    view = GraphView()
    view.resize(1200, 800)
    view.set_graph(nodes, edges)
    assert len(view.nodes) == 1200
    first_scale = view.transform().m11()
    view.fit_nodes()
    assert view.transform().m11() == pytest.approx(first_scale)
    assert view._collapsed
    cluster = next(iter(view.clusters.values()))
    assert cluster.rect.width() * cluster.scale() * first_scale > 100
    assert time.perf_counter() - started < 8
    view.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_themed_canvas_keyboard_neighborhood_and_hidden_timers(app, repo, theme):
    previous = app.property("somniloopTheme")
    old_stylesheet = app.styleSheet()
    app.setProperty("somniloopTheme", theme)
    app.setStyleSheet(stylesheet(theme))
    nodes, edges = sample_graph()
    repo.replace_knowledge_graph(nodes, edges)
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page.resize(1300, 800)
    page.show()
    app.processEvents()
    assert not page.grab().isNull()
    page.graph_view.setFocus()
    QTest.keyClick(page.graph_view, Qt.Key.Key_Right)
    selected = page.graph_view._selected
    assert selected in page.graph_view.nodes
    QTest.keyClick(page.graph_view, Qt.Key.Key_P)
    assert selected in page.graph_view.state.pinned
    page._neighborhood("anna")
    assert set(page.graph_view.nodes) == {"anna", "me"}
    page._all_graph()
    assert len(page.graph_view.nodes) == len([node for node in nodes if node.category != "places"])
    page.hide()
    assert not page.graph_view.timer.isActive()
    assert not page.graph_view._save_timer.isActive()
    page.close()
    app.setStyleSheet(old_stylesheet)
    app.setProperty("somniloopTheme", previous)


@pytest.mark.parametrize("dismiss", ["button", "escape", "canvas"])
def test_inspector_is_optional_dismissible_and_stays_closed_after_refresh(app, repo, dismiss):
    from PySide6.QtCore import QPoint

    nodes, edges = sample_graph()
    repo.replace_knowledge_graph(nodes, edges)
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page.resize(1300, 800)
    page.show()
    app.processEvents()
    assert page.inspector.isHidden()
    full_width = page.graph_view.width()
    page._show_node(page.index.nodes["anna"])
    app.processEvents()
    assert page.inspector.isVisible()
    assert page.graph_view.width() < full_width
    if dismiss == "button":
        QTest.mouseClick(page.inspector.close_button, Qt.MouseButton.LeftButton)
    elif dismiss == "escape":
        page.inspector.browser.setFocus()
        QTest.keyClick(page.inspector.browser, Qt.Key.Key_Escape)
    else:
        # Move far outside graph bounds, then click truly empty canvas space.
        page.graph_view.centerOn(100000, 100000)
        app.processEvents()
        point = QPoint(20, 20)
        assert page.graph_view.itemAt(point) is None
        QTest.mouseClick(page.graph_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    assert page.inspector.isHidden()
    assert page.inspector.node is None
    assert page.graph_view.width() == full_width
    page.refresh()
    assert page.inspector.isHidden()
    page._show_node(page.index.nodes["anna"])
    assert page.inspector.isVisible()
    page.close()


def test_search_panel_can_be_dismissed_without_reopening_on_refresh(app, repo):
    repo.replace_knowledge_graph(*sample_graph())
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page.show()
    page.search.setText("Анна")
    QTest.qWait(250)
    assert page.inspector.isVisible()
    assert page.results.count() > 0
    page.inspector.close_button.click()
    assert not page.search.text()
    page.refresh()
    assert page.inspector.isHidden()
    page.search.setText("совершенно отсутствующая строка")
    QTest.qWait(250)
    assert page.inspector.isVisible()
    assert page.inspector.node is None
    assert not page.inspector.edit.isVisible()
    assert not page.inspector.pin.isEnabled()
    page.close()


def test_places_are_hidden_not_deleted_and_connections_skill_is_persisted(app, repo):
    repo.replace_knowledge_graph(*sample_graph())
    page = KnowledgeGraphPage(repo, I18n("ru"))
    assert "places" not in page.filter_buttons
    assert "city" not in page.index.nodes
    assert any(node.category == "places" for node in repo.load_knowledge_graph()[0])
    assert not page.connections_skill.isChecked()
    page.connections_skill.setChecked(True)
    assert repo.get_setting("graph_find_connections") == "1"
    assert page.worker is None  # Toggling never starts the LLM.
    page.close()
    reopened = KnowledgeGraphPage(repo, I18n("ru"))
    assert reopened.connections_skill.isChecked()
    reopened.close()


def test_inferred_edges_are_dashed(app):
    view = GraphView()
    nodes = [KnowledgeNode("a", "Анна", "people"), KnowledgeNode("b", "Ирина", "people")]
    view.set_graph(nodes, [KnowledgeEdge("a", "b", "Возможно знакомы · NUP")])
    assert view.edges[0].pen().style() == Qt.PenStyle.DashLine
    view.close()


def test_connections_switch_is_passed_to_graph_worker(app, repo, monkeypatch):
    from somniloop.ui.knowledge_graph import GraphBuildThread

    started = []
    monkeypatch.setattr(GraphBuildThread, "start", lambda worker: started.append(worker))
    repo.set_setting("model_path", "test-only.gguf")
    page = KnowledgeGraphPage(repo, I18n("ru"))
    page.connections_skill.setChecked(True)
    page._rebuild()
    assert started == [page.worker]
    assert page.worker.find_connections is True
    assert not page.connections_skill.isEnabled()
    page._build_cancelled()
    assert page.connections_skill.isEnabled()
    page.progress_dialog.close()
    page.close()

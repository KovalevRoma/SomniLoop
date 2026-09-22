from somniloop.knowledge.extractor import (
    HeuristicExtractor,
    extract_person_facts,
    humanize_details,
)


def test_fallback_graph_has_category_nodes_and_valid_edges():
    source = {
        "profile": {"name": "Roman", "bio": "I live in Bremen"},
        "notes": [{"title": "Моя цель", "content": "Хочу изучать математику"}],
        "trackers": [
            {
                "name": "Sport",
                "description": "Training",
                "schedule": "interval",
                "streak": 4,
                "tasks": ["Warm-up"],
            }
        ],
    }
    nodes, edges = HeuristicExtractor().extract(source)
    node_ids = {node.id for node in nodes}
    categories = {node.category for node in nodes}
    assert {"people", "habits"}.issubset(categories)
    assert "goals" not in categories
    assert "interests" not in categories
    assert "events" not in categories
    assert all(edge.source in node_ids and edge.target in node_ids for edge in edges)


def test_people_keep_real_names_and_readable_russian_details():
    source = {
        "profile": {"name": "Роман", "bio": ""},
        "notes": [],
        "trackers": [],
        "people": [
            {
                "name": "Ковалёв Виктор",
                "relationship": "grandfather",
                "biography": "Родился и жил в Омске.",
                "birth_date": "12.03.1948",
                "education": "Омский институт",
                "occupation": "Инженер",
                "facts": ["Любит шахматы"],
                "updated_at": "2026-08-27T12:30:00",
            }
        ],
    }
    nodes, edges = HeuristicExtractor().extract(source)
    victor = next(node for node in nodes if node.label == "Ковалёв Виктор")
    assert "Кем приходится: дедушка" in victor.details
    assert "Дата рождения: 12 мар 1948" in victor.details
    assert "{'" not in victor.details
    assert any(edge.relation == "дедушка" for edge in edges)


def test_raw_dictionary_details_are_human_readable():
    details = humanize_details({"name": "Виктор", "relation": "дедушка"})
    assert details == "Имя: Виктор\nКем приходится: дедушка"


def test_person_fallback_extracts_only_supplied_story():
    result = extract_person_facts(
        "Анна",
        "подруга",
        "Родилась 12.05.1998. Училась в МГУ. Работает дизайнером.",
    )
    assert result["birth_date"] == "1998-05-12"
    assert any("Училась в МГУ" in fact for fact in result["history"])
    assert "Работает дизайнером" in result["occupation"]

import json

import pytest

from somniloop.core.database import Repository
from somniloop.core.dossier_import import DossierImportError, load_dossier_file


def dossier_payload():
    def person(external_id, telegram_id, name):
        return {
            "external_id": external_id,
            "telegram_ids": [telegram_id],
            "name": name,
            "relationship": "друг",
            "group_name": "Друзья",
            "contact": f"Telegram ID: {telegram_id}",
            "birth_date": "",
            "last_message_date": "2026-09-15",
            "biography": f"Подтверждённая биография: {name}.",
            "education": "",
            "occupation": "",
            "interests": "",
            "facts": ["Любит пешие прогулки."],
            "history": [],
            "conflicts": [],
            "clarifications": [],
            "sources": [],
        }

    return {
        "schema_version": "somniloop.dossiers.v1",
        "language": "ru",
        "generated_at": "2026-09-15T20:00:00",
        "source": {"type": "telegram_desktop_json"},
        "people": [
            person("person:tg:user2", "user2", "Ирина Ковалёва"),
            person("person:tg:user3", "user3", "Анна Смирнова"),
        ],
        "connections": [
            {
                "source_external_id": "person:tg:user2",
                "target_external_id": "person:tg:user3",
                "relation": "общий чат",
            }
        ],
        "places": [
            {
                "external_id": "place:berlin",
                "name": "Берлин",
                "details": "Город проживания.",
                "person_external_ids": ["person:tg:user2"],
            }
        ],
        "processing": {"status": "complete"},
    }


def test_ready_dossiers_build_graph_without_telegram_or_llm(tmp_path):
    repository = Repository(tmp_path / "somniloop.db")
    repository.save_profile("Роман", "Моя биография")
    repository.set_setting("telegram_import", json.dumps({"path": "/old/result.json"}))
    repository.save_knowledge_cache("old", {"people": []})
    progress = []

    result = repository.import_dossier_payload(
        dossier_payload(), lambda current, total, title: progress.append((current, total, title))
    )

    assert result == {"created": 2, "updated": 0, "people": 2, "connections": 1, "places": 1}
    assert repository.telegram_manifest() == {}
    assert repository.load_knowledge_cache() == {}
    assert {person.name for person in repository.list_people()} == {
        "Анна Смирнова",
        "Ирина Ковалёва",
    }
    nodes, edges = repository.load_knowledge_graph()
    assert {node.category for node in nodes} == {"people", "places"}
    assert any(edge.relation == "общий чат" for edge in edges)
    assert any(edge.relation == "связан с местом" for edge in edges)
    assert progress[-1][:2] == (100, 100)
    repository.close()


def test_reset_graph_keeps_only_profile_and_detaches_telegram(tmp_path):
    repository = Repository(tmp_path / "somniloop.db")
    repository.save_profile("Роман", "Моя биография")
    repository.set_setting("telegram_import", json.dumps({"path": "/old/result.json"}))
    repository.save_knowledge_cache("old", {"people": []})
    repository.import_dossier_payload(dossier_payload())
    person_id = repository.list_people()[0].id
    repository.set_setting(
        "telegram_import",
        json.dumps(
            {
                "path": "/old/result.json",
                "identity_map": {"user2": {"person_id": person_id, "name": "Ирина"}},
            }
        ),
    )

    repository.reset_knowledge_graph(detach_telegram=True)

    nodes, edges = repository.load_knowledge_graph()
    assert len(nodes) == 1
    assert nodes[0].label == "Роман"
    assert nodes[0].details == "Моя биография"
    assert edges == []
    assert repository.telegram_manifest() == {}
    detached = json.loads(repository.get_setting("detached_telegram_identity_map", "{}"))
    assert detached["user2"]["person_id"] == person_id
    assert repository.load_knowledge_cache() == {}
    repository.close()


def test_dossier_file_rejects_duplicate_telegram_ids(tmp_path):
    payload = dossier_payload()
    payload["people"][1]["telegram_ids"] = ["user2"]
    path = tmp_path / "somniloop_dossiers.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DossierImportError, match="нескольким людям"):
        load_dossier_file(path)

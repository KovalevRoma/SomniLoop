import json

from somniloop.core.database import Repository
from somniloop.core.telegram_import import scan_telegram_export, telegram_documents
from somniloop.knowledge.pipeline import KnowledgeBuilder, node_id


def telegram_payload():
    return {
        "personal_information": {
            "user_id": 1,
            "first_name": "Роман",
            "last_name": "",
        },
        "chats": {
            "list": [
                {
                    "id": 10,
                    "type": "personal_chat",
                    "name": "Анна",
                    "messages": [
                        {
                            "id": 1,
                            "type": "message",
                            "date": "2020-01-01T10:00:00",
                            "from": "Роман",
                            "from_id": "user1",
                            "text": "Привет",
                        },
                        {
                            "id": 2,
                            "type": "message",
                            "date": "2020-01-01T10:01:00",
                            "from": "Анна",
                            "from_id": "user2",
                            "text": ["Я живу в ", {"type": "bold", "text": "Берлине"}],
                        },
                        *[
                            {
                                "id": 10 + index,
                                "type": "message",
                                "date": f"2020-01-01T10:{index + 2:02d}:00",
                                "from": "Анна",
                                "from_id": "user2",
                                "text": "Работаю архитектором.",
                            }
                            for index in range(9)
                        ],
                    ],
                },
                {
                    "id": 20,
                    "type": "private_group",
                    "name": "Общий чат",
                    "messages": [
                        {
                            "id": 3,
                            "type": "message",
                            "date": "2021-02-02T10:00:00",
                            "from": "Анна",
                            "from_id": "user3",
                            "text": "Работаю архитектором.",
                        },
                        {
                            "id": 4,
                            "type": "message",
                            "date": "2021-02-02T10:01:00",
                            "from": "Борис",
                            "from_id": "user4",
                            "text": "Люблю шахматы.",
                        },
                    ],
                },
                {
                    "id": 11,
                    "type": "personal_chat",
                    "name": "Анна",
                    "messages": [
                        {
                            "id": 100 + index,
                            "type": "message",
                            "date": f"2020-02-01T10:{index:02d}:00",
                            "from": "Анна",
                            "from_id": "user3",
                            "text": "Привет из второго диалога.",
                        }
                        for index in range(11)
                    ],
                },
                {
                    "id": 30,
                    "type": "public_channel",
                    "name": "Новости",
                    "messages": [
                        {
                            "id": 5,
                            "type": "message",
                            "date": "2022-03-03T10:00:00",
                            "from": "Новости",
                            "from_id": "channel30",
                            "text": "Текст канала",
                        }
                    ],
                },
            ]
        },
    }


def test_full_telegram_export_is_registered_and_same_names_share_person(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(telegram_payload(), ensure_ascii=False), encoding="utf-8")
    scan_progress = []
    scan = scan_telegram_export(path, lambda percent, title: scan_progress.append((percent, title)))
    assert scan["chats"] == 4
    assert scan["messages"] == 25
    assert scan_progress[0][0] == 5
    assert scan_progress[-1][0] == 100
    assert [percent for percent, _title in scan_progress] == sorted(
        percent for percent, _title in scan_progress
    )

    repository = Repository(tmp_path / "somniloop.db")
    import_progress = []
    result = repository.register_telegram_export(
        scan,
        {"user2": "create"},
        progress=lambda current, total, title: import_progress.append((current, total, title)),
    )
    people = repository.list_people(managed_only=True)
    assert {person.name for person in people} == {"Анна"}
    assert (
        result["identity_map"]["user2"]["person_id"] == result["identity_map"]["user3"]["person_id"]
    )
    assert result["chats"] == 4
    assert import_progress[0][0] == 0
    assert import_progress[-1][0] == import_progress[-1][1]
    repository.close()


def test_telegram_documents_include_every_chat_and_all_time(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(telegram_payload(), ensure_ascii=False), encoding="utf-8")
    scan = scan_telegram_export(path)
    repository = Repository(tmp_path / "somniloop.db")
    repository.save_profile("Я", "")
    repository.register_telegram_export(scan, {"user2": "create"})
    manifest = repository.telegram_manifest()
    documents = telegram_documents(manifest)
    assert {document["chat_type"] for document in documents} == {
        "personal_chat",
        "private_group",
        "public_channel",
    }
    assert any("2020-01-01" in document["text"] for document in documents)
    assert any("2022-03-03" in document["text"] for document in documents)
    assert any("Я живу в Берлине" in document["text"] for document in documents)

    graph = KnowledgeBuilder().build(repository.knowledge_source())
    assert sum(node.label == "Анна" for node in graph.nodes) == 1
    repository.close()


def test_people_in_the_same_telegram_chat_get_connected(tmp_path):
    export_path = tmp_path / "empty.json"
    export_path.write_text(json.dumps({"chats": {"list": []}}), encoding="utf-8")
    source = {
        "profile": {"name": "Роман", "bio": ""},
        "people": [
            {"id": 1, "name": "Анна", "relationship": "подруга"},
            {"id": 2, "name": "Борис", "relationship": "коллега"},
        ],
        "notes": [],
        "trackers": [],
        "telegram": {
            "path": str(export_path),
            "identity_map": {
                "user2": {"person_id": 1, "name": "Анна", "chats": ["shared"]},
                "user3": {"person_id": 2, "name": "Борис", "chats": ["shared"]},
            },
        },
    }
    result = KnowledgeBuilder().build(source)
    assert any(
        edge.relation == "общий чат"
        and {edge.source, edge.target} == {node_id("people", "Анна"), node_id("people", "Борис")}
        for edge in result.edges
    )

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DossierImportError(ValueError):
    pass


def load_dossier_file(path: str | Path, progress=None) -> dict[str, Any]:
    """Read and validate a ready-to-use SomniLoop dossier export."""
    source = Path(path).expanduser().resolve()
    if progress:
        progress(5, 100, "Читаю файл готовых досье")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DossierImportError(f"Не удалось прочитать JSON с досье: {exc}") from exc
    if progress:
        progress(20, 100, "Проверяю структуру файла")
    if not isinstance(payload, dict):
        raise DossierImportError("Корневой элемент файла досье должен быть объектом.")
    if payload.get("schema_version") != "somniloop.dossiers.v1":
        raise DossierImportError(
            "Ожидался формат somniloop.dossiers.v1. Проверь инструкцию для внешней LLM."
        )
    for key in ("source", "people", "connections", "places", "processing"):
        if key not in payload:
            raise DossierImportError(f"В файле отсутствует обязательный раздел: {key}.")
    if not isinstance(payload["people"], list):
        raise DossierImportError("Раздел people должен быть массивом.")
    if not isinstance(payload["connections"], list) or not isinstance(payload["places"], list):
        raise DossierImportError("Разделы connections и places должны быть массивами.")

    external_ids: set[str] = set()
    telegram_ids: set[str] = set()
    for index, person in enumerate(payload["people"], start=1):
        if not isinstance(person, dict) or not str(person.get("name", "")).strip():
            raise DossierImportError(f"У человека #{index} отсутствует имя.")
        external_id = str(person.get("external_id", "")).strip()
        if not external_id or external_id in external_ids:
            raise DossierImportError(f"Некорректный или повторяющийся external_id у #{index}.")
        external_ids.add(external_id)
        for telegram_id in person.get("telegram_ids", []):
            value = str(telegram_id).strip()
            if value and value in telegram_ids:
                raise DossierImportError(f"Telegram ID {value} назначен нескольким людям.")
            if value:
                telegram_ids.add(value)
    for connection in payload["connections"]:
        if not isinstance(connection, dict):
            raise DossierImportError("Каждая связь должна быть объектом.")
        if (
            connection.get("source_external_id") not in external_ids
            or connection.get("target_external_id") not in external_ids
        ):
            raise DossierImportError("Связь ссылается на отсутствующего человека.")
    if progress:
        progress(25, 100, "Файл досье проверен")
    return payload

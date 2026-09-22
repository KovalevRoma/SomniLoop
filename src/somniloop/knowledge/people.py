from __future__ import annotations

import ast
import json
import re
from datetime import date
from typing import Any

from somniloop.core.dates import (
    age_on,
    display_date,
    display_timestamp,
    normalize_birth_date,
    parse_birth_date,
)

FIELD_NAMES = {
    "name": "Имя",
    "relation": "Кем приходится",
    "relationship": "Кем приходится",
    "biography": "Биография",
    "birth_date": "Дата рождения",
    "education": "Образование",
    "occupation": "Чем занимается",
    "interests": "Интересы",
    "facts": "Факты",
    "description": "Описание",
    "updated_at": "Информация обновлена",
}
RELATIONS = {
    "grandfather": "дедушка",
    "grandmother": "бабушка",
    "mother": "мама",
    "father": "папа",
    "sister": "сестра",
    "brother": "брат",
    "friend": "друг",
    "girlfriend": "девушка",
    "boyfriend": "парень",
    "knows": "знает",
    "related": "связано с",
}


def normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold().replace("ё", "е")))


def humanize_details(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(
            f"{FIELD_NAMES.get(str(key), 'Сведения')}: {humanize_details(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    if isinstance(value, list):
        return "\n".join(f"• {humanize_details(item)}" for item in value if item)
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith(("{", "[")) and len(text) < 100_000:
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(text)
                if isinstance(parsed, (dict, list)):
                    return humanize_details(parsed)
            except (ValueError, SyntaxError, TypeError, RecursionError):
                continue
    return RELATIONS.get(text.casefold(), text)


def _fact_value(person: dict, claim: dict) -> str:
    value = str(claim["value"]).strip()
    if claim["field"] in {"biography", "birth_date", "other"}:
        return value
    name = re.escape(person.get("name", ""))
    if name:
        value = re.sub(rf"^{name}\b\s*[,—:]?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"^(?:сейчас|ранее|раньше|теперь|он|она)\b\s*:?\s*", "", value, flags=re.IGNORECASE
    )
    value = re.sub(r"^(?:интересы|образование|занятие)\s*:\s*", "", value, flags=re.IGNORECASE)
    return value[:1].upper() + value[1:]


def merge_person_claims(person: dict, claims: list[dict], as_of: date) -> dict:
    result = {
        **person,
        "facts": list(person.get("facts", [])),
        "history": [],
        "conflicts": [],
        "sources": [],
    }
    by_field: dict[str, list[dict]] = {}
    latest: dict[tuple, dict] = {}
    source_keys: set[tuple] = set()
    for claim in sorted(claims, key=lambda item: (item.get("date", ""), item.get("source_id", ""))):
        source_key = (claim.get("source_id"), claim.get("evidence"))
        if source_key not in source_keys:
            result["sources"].append(
                {
                    "id": claim.get("source_id", ""),
                    "title": claim.get("source_title", ""),
                    "date": claim.get("date", ""),
                    "updated_at": claim.get("updated_at", ""),
                    "evidence": claim.get("evidence", ""),
                }
            )
            source_keys.add(source_key)
        value = _fact_value(person, claim)
        key = (claim["field"], normalized(value), claim.get("temporal", "unknown"))
        latest[key] = {**claim, "value": value}
    for claim in sorted(
        latest.values(), key=lambda item: (item.get("date", ""), item.get("source_id", ""))
    ):
        by_field.setdefault(claim["field"], []).append(claim)

    birth_claims = []
    for claim in by_field.get("birth_date", []):
        birth = normalize_birth_date(claim["value"])
        if birth:
            birth_claims.append((birth, claim))
    if birth_claims:
        # A partial birthday agrees with a complete date sharing its month/day.
        full = [(value, claim) for value, claim in birth_claims if not value.startswith("--")]
        result["birth_date"] = (full or birth_claims)[-1][0]
        chosen = parse_birth_date(result["birth_date"])
        for value, claim in birth_claims:
            other = parse_birth_date(value)
            if other[1:] != chosen[1:] or (other[0] and chosen[0] and other[0] != chosen[0]):
                result["conflicts"].append(
                    f"Дата рождения: {display_date(value)} ({claim.get('source_title', 'рассказ')}) противоречит {display_date(result['birth_date'])}."
                )
    result["birth_date"] = normalize_birth_date(result.get("birth_date", ""))

    for field in ("education", "occupation", "interests", "biography", "other"):
        records = by_field.get(field, [])
        current = [item for item in records if item.get("temporal") != "past"]
        historical = [item for item in records if item.get("temporal") == "past"]
        if field in {"education", "occupation"}:
            if current:
                result[field] = current[-1]["value"]
                historical += current[:-1]
            elif historical:
                result[field] = ""
            for item in historical:
                result["history"].append(f"Ранее: {item['value']}")
        elif field == "interests" and records:
            result[field] = "; ".join(item["value"] for item in current)
            result["history"].extend(f"Ранее: {item['value']}" for item in historical)
        elif field == "biography" and records:
            result[field] = " ".join(item["value"] for item in records)
        elif field == "other":
            result["facts"].extend(item["value"] for item in records)

    if not result.get("biography"):
        pieces = list(dict.fromkeys(result["history"]))
        if result.get("occupation"):
            pieces.append(f"Сейчас: {result['occupation']}")
        result["biography"] = "\n".join(pieces)
    result["history"] = list(dict.fromkeys(result["history"]))
    result["facts"] = list(dict.fromkeys(result["facts"]))
    result["conflicts"] = list(dict.fromkeys(result["conflicts"]))
    result["graph_updated_at"] = as_of.isoformat()
    result["age"] = age_on(result["birth_date"], as_of) if not has_birth_conflict(result) else None
    return result


def has_birth_conflict(person: dict) -> bool:
    return any(
        "рождени" in normalized(str(item)) or "birth" in normalized(str(item))
        for item in person.get("conflicts", [])
    )


def format_person_details(person: dict, as_of: date | None = None) -> str:
    lines = []
    for key in ("relationship", "biography", "birth_date", "education", "occupation", "interests"):
        value = person.get(key, "")
        if value:
            rendered = display_date(value) if key == "birth_date" else humanize_details(value)
            lines.append(f"{FIELD_NAMES[key]}: {rendered}")
    age = age_on(person.get("birth_date", ""), as_of or date.today())
    if age is not None and not has_birth_conflict(person):
        lines.append(f"Возраст на {display_date(as_of or date.today())}: {age}")
    for key, heading in (
        ("history", "История"),
        ("facts", "Факты"),
        ("conflicts", "Нужно уточнить"),
    ):
        if person.get(key):
            lines.append(f"\n{heading}:")
            lines.extend(
                ("⚠ " if key == "conflicts" else "• ") + humanize_details(item)
                for item in person[key]
            )
    if person.get("sources"):
        lines.append("\nИз твоих записей:")
        lines.extend(
            f"• {item.get('title', 'Рассказ')} · {display_date(str(item.get('date', ''))[:10])}: {item.get('evidence', '')}"
            for item in person["sources"]
        )
    last_updated = max(
        [person.get("updated_at", "")]
        + [item.get("updated_at", "") for item in person.get("sources", [])]
    )
    if last_updated:
        lines.append(f"\nИнформация обновлена: {display_timestamp(last_updated)}")
    return "\n".join(lines) or "Информация пока не заполнена."

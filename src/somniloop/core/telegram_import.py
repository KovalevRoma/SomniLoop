from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

MIN_PERSONAL_MESSAGES = 10


class TelegramExportError(ValueError):
    pass


def _telegram_user_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith(("user", "channel")) else f"user{text}"


def _message_author(message: dict) -> tuple[str, str]:
    identifier = _telegram_user_id(message.get("from_id") or message.get("actor_id"))
    name = str(message.get("from") or message.get("actor") or "").strip()
    return identifier, name


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain_text(item) for item in value)
    if isinstance(value, dict):
        return _plain_text(value.get("text", ""))
    return ""


def load_telegram_export(path: str | Path) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        with source.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TelegramExportError(f"Не удалось прочитать Telegram JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("chats", {}).get("list"), list):
        raise TelegramExportError(
            "Это не полный JSON-экспорт Telegram: раздел chats.list не найден."
        )
    return payload


def scan_telegram_export(path: str | Path, progress=None) -> dict:
    source = Path(path).expanduser().resolve()
    if progress:
        progress(5, "Читаю Telegram JSON")
    payload = load_telegram_export(source)
    if progress:
        progress(20, "Разбираю чаты и сообщения")
    profile = payload.get("personal_information", {})
    owner_id = _telegram_user_id(profile.get("user_id"))
    owner_name = " ".join(
        part
        for part in (str(profile.get("first_name", "")), str(profile.get("last_name", "")))
        if part.strip()
    ).strip()
    identities: dict[str, dict] = {}
    personal_by_id: dict[str, dict] = {}
    chat_count = 0
    message_count = 0

    chats = payload["chats"]["list"]
    progress_step = max(1, len(chats) // 80)
    for chat_index, chat in enumerate(chats, start=1):
        if progress and (chat_index == len(chats) or chat_index % progress_step == 0):
            progress(20 + int(chat_index * 75 / max(1, len(chats))), "Разбираю чаты и сообщения")
        if not isinstance(chat, dict):
            continue
        chat_count += 1
        messages = chat.get("messages", [])
        if not isinstance(messages, list):
            continue
        message_count += len(messages)
        participants: dict[str, str] = {}
        for message in messages:
            if not isinstance(message, dict):
                continue
            identifier, name = _message_author(message)
            if not identifier or identifier.startswith("channel") or identifier == owner_id:
                continue
            if name:
                participants[identifier] = name
            identity = identities.setdefault(
                identifier,
                {
                    "telegram_id": identifier,
                    "name": name or "Неизвестный контакт",
                    "messages": 0,
                    "chats": set(),
                    "first_date": "",
                    "last_date": "",
                    "last_message_date": "",
                    "personal": False,
                },
            )
            if name:
                identity["name"] = name
            identity["messages"] += 1
            identity["chats"].add(str(chat.get("id", "")))
            day = str(message.get("date", ""))[:10]
            if day:
                identity["first_date"] = min(identity["first_date"] or day, day)
                identity["last_date"] = max(identity["last_date"], day)
                identity["last_message_date"] = max(identity["last_message_date"], day)

        if chat.get("type") != "personal_chat":
            continue
        chat_name = str(chat.get("name", "")).strip() or "Удалённый аккаунт"
        peer_ids = list(participants)
        peer_id = peer_ids[0] if len(peer_ids) == 1 else f"chat:{chat.get('id', chat_name)}"
        identity = identities.setdefault(
            peer_id,
            {
                "telegram_id": peer_id,
                "name": chat_name,
                "messages": 0,
                "chats": {str(chat.get("id", ""))},
                "first_date": "",
                "last_date": "",
                "last_message_date": "",
                "personal": True,
            },
        )
        identity["name"] = chat_name
        identity["personal"] = True
        chat_last_date = max(
            (
                str(message.get("date", ""))[:10]
                for message in messages
                if isinstance(message, dict)
            ),
            default="",
        )
        identity["last_message_date"] = max(identity.get("last_message_date", ""), chat_last_date)
        personal = personal_by_id.setdefault(
            peer_id,
            {
                "chat_id": str(chat.get("id", "")),
                "chat_ids": [],
                "telegram_id": peer_id,
                "name": chat_name,
                "messages": 0,
                "last_message_date": "",
            },
        )
        personal["chat_ids"].append(str(chat.get("id", "")))
        personal["messages"] += len(messages)
        personal["last_message_date"] = max(personal["last_message_date"], chat_last_date)
        if len(chat_name.split()) > len(personal["name"].split()):
            personal["name"] = chat_name

    serializable = []
    for identity in identities.values():
        serializable.append({**identity, "chats": sorted(identity["chats"])})
    stat = source.stat()
    if progress:
        progress(100, "Список Telegram готов")
    return {
        "path": str(source),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "owner_id": owner_id,
        "owner_name": owner_name,
        "chats": chat_count,
        "messages": message_count,
        "identities": sorted(serializable, key=lambda item: item["name"].casefold()),
        "personal_chats": sorted(personal_by_id.values(), key=lambda item: item["name"].casefold()),
    }


def telegram_documents(manifest: dict) -> list[dict]:
    path = Path(str(manifest.get("path", "")))
    if not path.is_file():
        raise TelegramExportError(
            "Файл Telegram больше недоступен. Выбери его заново в настройках."
        )
    payload = load_telegram_export(path)
    identity_map = manifest.get("identity_map", {})
    owner_id = str(manifest.get("owner_id", ""))
    owner_name = str(manifest.get("owner_name", "")) or "Я"
    skipped = set(manifest.get("skipped_ids", []))
    skipped_chats = set(manifest.get("skipped_chats", []))
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    metadata: dict[tuple[str, str], dict] = {}

    for chat in payload["chats"]["list"]:
        if not isinstance(chat, dict):
            continue
        chat_id = str(chat.get("id", ""))
        if chat_id in skipped_chats:
            continue
        chat_name = str(chat.get("name", "")).strip() or "Чат без названия"
        chat_type = str(chat.get("type", ""))
        for message in chat.get("messages", []):
            if not isinstance(message, dict) or message.get("type") != "message":
                continue
            body = _plain_text(message.get("text", "")).strip()
            if not body:
                continue
            identifier, raw_name = _message_author(message)
            if identifier in skipped:
                continue
            if identifier == owner_id:
                author = owner_name
            else:
                author = str(identity_map.get(identifier, {}).get("name", "")) or raw_name
            author = author.strip() or "Неизвестный автор"
            day = str(message.get("date", ""))[:10]
            month = day[:7] if len(day) >= 7 else "без-даты"
            forwarded = str(message.get("forwarded_from", "")).strip()
            prefix = f"[переслано от {forwarded}] " if forwarded else ""
            line = f"[{day or 'дата неизвестна'}] {author}: {prefix}{body}"
            key = (chat_id, month)
            buckets[key].append(line)
            metadata[key] = {
                "title": f"Telegram · {chat_name} · {month}",
                "date": day,
                "chat_type": chat_type,
            }

    documents = []
    for (chat_id, month), lines in buckets.items():
        info = metadata[(chat_id, month)]
        documents.append(
            {
                "id": f"telegram:{chat_id}:{month}",
                "title": info["title"],
                "date": info["date"],
                "updated_at": info["date"],
                "text": "\n".join(lines),
                "subject": "",
                "telegram": True,
                "chat_type": info["chat_type"],
            }
        )
    return documents

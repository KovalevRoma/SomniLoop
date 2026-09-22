from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ModelOutputError(ValueError):
    pass


class ModelRepetitionError(ModelOutputError):
    pass


class RepetitionGuard:
    """Inspect streamed JSON incrementally, keeping facts scoped to their person."""

    def __init__(self) -> None:
        self.text = ""
        self._objects: list[int] = []
        self._quoted = False
        self._escaped = False
        self._string_tail = ""
        self._counts: Counter = Counter()
        self._whitespace = 0

    def feed(self, fragment: str) -> None:
        offset = len(self.text)
        self.text += fragment
        for position, char in enumerate(fragment, offset):
            if self._quoted:
                if self._escaped:
                    self._escaped = False
                elif char == "\\":
                    self._escaped = True
                elif char == '"':
                    self._quoted = False
                    self._string_tail = ""
                    continue
                self._string_tail = (self._string_tail + char)[-384:]
                # Repeated long passages inside one value are not JSON syntax.
                for size in range(24, min(128, len(self._string_tail) // 3) + 1):
                    if self._string_tail[-size:] * 3 == self._string_tail[-3 * size :]:
                        raise ModelRepetitionError("Модель повторяет текст внутри одного факта.")
                continue
            self._whitespace = self._whitespace + 1 if char.isspace() else 0
            if self._whitespace >= 128:
                raise ModelRepetitionError("Модель генерирует пробелы вместо ответа.")
            if char == '"':
                self._quoted = True
            elif char == "{":
                self._objects.append(position)
            elif char == "}" and self._objects:
                start = self._objects.pop()
                try:
                    value = json.loads(self.text[start : position + 1])
                except ValueError:
                    continue  # The final schema validator reports malformed JSON.
                parent = self._objects[-1] if self._objects else -1
                if {"field", "value", "temporal", "evidence"} <= value.keys():
                    # Different quotes do not make the same fact new; another person does.
                    identity = [value["field"], value["value"], value["temporal"]]
                elif {"name", "claims"} <= value.keys():
                    identity = ["person", value["name"]]
                elif {"source", "target", "relation"} <= value.keys():
                    identity = ["link", value["source"], value["target"], value["relation"]]
                elif {"name", "category", "details"} <= value.keys():
                    identity = ["entity", value["name"], value["category"]]
                elif {"first", "second", "reason"} <= value.keys():
                    identity = ["conflict", value["first"], value["second"]]
                elif {"organization", "kind", "evidence"} <= value.keys():
                    identity = [
                        "affiliation",
                        value["organization"],
                        value["kind"],
                        value.get("cohort"),
                        value.get("start_year"),
                        value.get("end_year"),
                    ]
                else:
                    continue
                key = parent, json.dumps(identity, ensure_ascii=False, sort_keys=True).casefold()
                self._counts[key] += 1
                if self._counts[key] >= 3:
                    raise ModelRepetitionError("Модель повторяет одни и те же факты или людей.")


def validate_payload(value: Any, schema: dict, path: str = "root") -> None:
    kind = schema.get("type")
    expected = {"object": dict, "array": list, "string": str, "integer": int}.get(kind)
    if expected and (
        not isinstance(value, expected) or (kind == "integer" and isinstance(value, bool))
    ):
        raise ModelOutputError(f"Неверный тип данных в ответе модели: {path}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ModelOutputError(f"Неизвестное значение в ответе модели: {path}.")
    if kind == "object":
        if any(key not in value for key in schema.get("required", [])):
            raise ModelOutputError(f"В ответе модели отсутствуют поля: {path}.")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ModelOutputError(f"В ответе модели есть неизвестные поля: {path}.")
        for key, item in value.items():
            if key in properties:
                validate_payload(item, properties[key], f"{path}.{key}")
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", len(value)
        ):
            raise ModelOutputError(f"Неверное число элементов в ответе модели: {path}.")
        for index, item in enumerate(value):
            validate_payload(item, schema["items"], f"{path}[{index}]")


def _remove_trailing_commas(text: str) -> str:
    result = []
    quoted = escaped = False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "," and text[index + 1 :].lstrip().startswith(("}", "]")):
            continue
        result.append(char)
    return "".join(result)


def decode_json(text: str) -> dict[str, Any]:
    """Accept fenced JSON and trailing commas, but never accept a partial object."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    if start < 0:
        raise ModelOutputError("Модель не вернула структурированные данные.")
    candidate = text[start:]
    decoder = json.JSONDecoder()
    for value in (candidate, _remove_trailing_commas(candidate)):
        try:
            payload, end = decoder.raw_decode(value)
            if not isinstance(payload, dict):
                break
            if value[end:].strip().strip("`"):
                raise ModelOutputError("После ответа модели обнаружены лишние данные.")
            return payload
        except json.JSONDecodeError:
            continue
    raise ModelOutputError("Модель вернула незавершённый или некорректный JSON.")


def model_fingerprint(model_path: str) -> str:
    if not model_path.strip():
        return "heuristic"
    path = Path(model_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"GGUF-модель не найдена: {path}")
    stat = path.stat()
    return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"


class LocalLlama:
    _lock = threading.RLock()
    _model = None
    _fingerprint = ""

    def __init__(
        self,
        model_path: str,
        threads: int = 0,
        check_cancel: Callable | None = None,
        activity: Callable[[str], None] | None = None,
    ) -> None:
        self.path = str(Path(model_path).expanduser())
        self.fingerprint = model_fingerprint(model_path)
        self.threads = threads or min(6, max(2, (os.cpu_count() or 4) - 2))
        self.check_cancel = check_cancel or (lambda: None)
        self.activity = activity or (lambda message: None)

    def _load(self):
        if LocalLlama._model is None or LocalLlama._fingerprint != self.fingerprint:
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise RuntimeError(
                    "Не установлен llama-cpp-python. Установи дополнение .[llm] из папки проекта."
                ) from exc
            if LocalLlama._model is not None:
                LocalLlama._model.close()
                LocalLlama._model = None
                LocalLlama._fingerprint = ""
            LocalLlama._model = Llama(
                model_path=self.path,
                n_ctx=4096,
                n_threads=self.threads,
                n_threads_batch=self.threads,
                n_gpu_layers=0,
                use_mmap=True,
                verbose=False,
            )
            LocalLlama._fingerprint = self.fingerprint
        return LocalLlama._model

    def json_completion(
        self, system: str, prompt: str, schema: dict, max_tokens: int = 1800
    ) -> dict:
        # One resident model is shared by graph and person jobs; calls stay serial.
        with self._lock:
            self.check_cancel()
            model = self._load()
            prompt_tokens = len(model.tokenize((system + prompt).encode("utf-8"))) + 160
            available = 4096 - prompt_tokens
            if available < 700:
                raise ModelOutputError("Фрагмент не помещается в контекст модели.")
            for attempt in range(2):
                self.check_cancel()
                self.activity("Проверяю формат повторно" if attempt else "Модель составляет ответ")
                guard = RepetitionGuard()
                stream = model.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object", "schema": schema},
                    temperature=0.0,
                    repeat_penalty=1.08,
                    max_tokens=min(max_tokens, available),
                    stream=True,
                )
                finish_reason = None
                last_notice = time.monotonic()
                try:
                    for chunk in stream:
                        self.check_cancel()
                        for choice in chunk.get("choices", []):
                            guard.feed(choice.get("delta", {}).get("content") or "")
                            finish_reason = choice.get("finish_reason") or finish_reason
                        now = time.monotonic()
                        if now - last_notice >= 1:
                            self.activity(f"Модель составляет ответ · {len(guard.text)} символов")
                            last_notice = now
                finally:
                    stream.close()
                self.check_cancel()
                if finish_reason == "length":
                    raise ModelOutputError("Ответ модели не завершён; нужен меньший фрагмент.")
                try:
                    result = decode_json(guard.text)
                    validate_payload(result, schema)
                    return result
                except ModelOutputError:
                    if attempt:
                        raise
            raise ModelOutputError("Не удалось прочитать ответ модели.")

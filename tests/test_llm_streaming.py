import json

import pytest

from somniloop.knowledge.llm import LocalLlama, ModelRepetitionError, RepetitionGuard
from somniloop.knowledge.pipeline import EXTRACTION_SCHEMA, BuildCancelled


def fact(value="Работает архитектором", evidence="Работает архитектором"):
    return {"field": "occupation", "value": value, "temporal": "current", "evidence": evidence}


def response(people):
    return json.dumps({"people": people, "entities": [], "links": []}, ensure_ascii=False)


def person(name, claims):
    return {"name": name, "relationship": "", "claims": claims}


def test_guard_stops_duplicate_facts_with_different_quotes():
    guard = RepetitionGuard()
    text = response([person("Анна", [fact(evidence=str(i)) for i in range(3)])])
    with pytest.raises(ModelRepetitionError):
        for char in text:
            guard.feed(char)


def test_guard_allows_same_fact_for_different_people_and_shared_evidence():
    claims = [fact(value=f"Факт {i}", evidence='Общая цитата с "кавычками" и \\') for i in range(5)]
    guard = RepetitionGuard()
    text = response([person(name, claims) for name in ("Анна", "Борис", "Вера")])
    for char in text:
        guard.feed(char)
    assert json.loads(guard.text)["people"][2]["claims"] == claims


@pytest.mark.parametrize("text", ['{"value":"' + "Один и тот же длинный фрагмент. " * 5, " " * 128])
def test_guard_stops_repetition_before_a_json_object_is_complete(text):
    with pytest.raises(ModelRepetitionError):
        RepetitionGuard().feed(text)


class StreamingModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = 0

    def tokenize(self, text):
        return list(range(10))

    def create_chat_completion(self, **kwargs):
        self.requests.append(kwargs)
        text = next(self.responses)

        def stream():
            try:
                yield {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}
                for char in text:
                    yield {"choices": [{"delta": {"content": char}, "finish_reason": None}]}
                yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}
            finally:
                self.closed += 1

        return stream()


def local_model(tmp_path, model, **kwargs):
    path = tmp_path / "fake.gguf"
    path.touch()
    local = LocalLlama(str(path), **kwargs)
    local._load = lambda: model
    return local


def test_streamed_answer_is_validated_and_looping_attempt_is_closed(tmp_path):
    valid = response([person("Анна", [fact()])])
    loop = response([person("Анна", [fact()] * 3)])
    model = StreamingModel([valid, loop])
    local = local_model(tmp_path, model)
    assert local.json_completion("system", "input", EXTRACTION_SCHEMA) == json.loads(valid)
    with pytest.raises(ModelRepetitionError):
        local.json_completion("system", "input", EXTRACTION_SCHEMA)
    assert model.closed == 2
    assert len(model.requests) == 2  # No identical hidden retry after repetition.
    assert all(request["stream"] for request in model.requests)


def test_cancel_interrupts_a_stream_before_full_answer(tmp_path):
    model = StreamingModel([response([person("Анна", [fact()])])])
    checks = []

    def check_cancel():
        checks.append(True)
        if len(checks) >= 5:
            raise BuildCancelled()

    local = local_model(tmp_path, model, check_cancel=check_cancel)
    with pytest.raises(BuildCancelled):
        local.json_completion("system", "input", EXTRACTION_SCHEMA)
    assert model.closed == 1


def test_invalid_stream_retries_but_never_returns_partial_json(tmp_path):
    valid = response([])
    model = StreamingModel(['{"people": [', valid])
    local = local_model(tmp_path, model)
    assert local.json_completion("system", "input", EXTRACTION_SCHEMA) == json.loads(valid)
    assert model.closed == 2

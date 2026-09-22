"""Long-run and checkpoint regressions for the optional LLM stage."""

from collections import Counter

import pytest

from somniloop.core.database import Repository
from somniloop.core.models import KnowledgeNode
from somniloop.knowledge.connections import _extract_affiliations, run_skill
from somniloop.knowledge.llm import ModelOutputError, ModelRepetitionError
from somniloop.knowledge.pipeline import BuildCancelled, KnowledgeBuilder
from somniloop.knowledge.progress import WorkPlan


class SmallOutputBackend:
    def __init__(self, limit=500, error=ModelOutputError):
        self.limit, self.error = limit, error
        self.calls = Counter()
        self.cancel = False
        self.stop_after = None

    def json_completion(self, system, prompt, schema, max_tokens):
        self.calls[prompt] += 1
        if self.stop_after and sum(self.calls.values()) >= self.stop_after:
            self.cancel = True
        if len(prompt) > self.limit:
            raise self.error("Ответ модели не завершён; нужен меньший фрагмент.")
        items = (
            [
                {
                    "organization": "NUP",
                    "kind": "education",
                    "cohort": "",
                    "start_year": 0,
                    "end_year": 0,
                    "evidence": prompt,
                }
            ]
            if "NUP" in prompt
            else []
        )
        return {"affiliations": items}


def dossier(index=0):
    return (
        f"Студент {index} учился в NUP. Дополнительные сведения о человеке {index}. " * 12
    ).strip()


@pytest.mark.parametrize("error", [ModelOutputError, ModelRepetitionError])
def test_truncation_and_repetition_recover_all_text_without_replaying_failed_parent(error):
    backend = SmallOutputBackend(error=error)
    builder = KnowledgeBuilder(backend=backend)
    text = dossier()
    payload = _extract_affiliations(builder, text)
    assert payload["affiliations"]
    leaves = [prompt for prompt in backend.calls if len(prompt) <= backend.limit]
    # Every source character is covered, including both sides of a split boundary.
    coverage = set()
    for leaf in leaves:
        start = text.find(leaf)
        assert start >= 0
        # Repeated source paragraphs can produce identical cached leaves at several offsets.
        while start >= 0:
            coverage.update(range(start, start + len(leaf)))
            start = text.find(leaf, start + 1)
    assert len(coverage) == len(text)
    calls = sum(backend.calls.values())
    second = KnowledgeBuilder(backend=backend, cache=builder.new_cache)
    assert _extract_affiliations(second, text) == payload
    assert sum(backend.calls.values()) == calls
    assert backend.calls[text] == 1


def test_all_198_people_finish_and_all_19503_pairs_are_processed():
    nodes = [KnowledgeNode(str(i), f"Человек {i}", "people", dossier(i)) for i in range(198)]
    backend, events = SmallOutputBackend(), []
    builder = KnowledgeBuilder(backend=backend, progress=events.append)
    builder.work = WorkPlan(0, 198, 198)
    builder.work.finish("merge", 198)
    edges = []
    run_skill(builder, nodes, edges)
    assert builder.stats["connections_done"] == 198
    assert builder.stats["connection_failures"] == []
    assert len(edges) == 198 * 197 // 2
    assert all(len(node.metadata["inferred_connections"]) == 197 for node in nodes)
    assert [event["percent"] for event in events] == sorted(event["percent"] for event in events)
    assert events[-1]["stage_done"] == events[-1]["stage_total"] == 198
    assert events[-1]["work_done"] < events[-1]["work_total"]  # Assembly and commit still pending.
    assert all(
        event["percent"] == 100 * event["work_done"] / event["work_total"] for event in events
    )


def test_cancel_and_database_restart_reuse_successful_leaves_and_split_plans(tmp_path):
    repo = Repository(tmp_path / "resume.db")
    backend = SmallOutputBackend(limit=240)
    backend.stop_after = 5
    builder = KnowledgeBuilder(
        backend=backend, cancelled=lambda: backend.cancel, cache_saved=repo.save_knowledge_cache
    )
    text = dossier()
    with pytest.raises(BuildCancelled):
        _extract_affiliations(builder, text)
    successful = {prompt: count for prompt, count in backend.calls.items() if len(prompt) <= 240}
    assert successful
    repo.close()
    repo = Repository(tmp_path / "resume.db")
    backend.cancel, backend.stop_after = False, None
    resumed = KnowledgeBuilder(
        backend=backend, cache=repo.load_knowledge_cache(), cache_saved=repo.save_knowledge_cache
    )
    assert _extract_affiliations(resumed, text)["affiliations"]
    assert backend.calls[text] == 1
    assert all(backend.calls[prompt] == count for prompt, count in successful.items())
    repo.close()


def test_permanently_bad_person_does_not_block_others_or_count_as_complete():
    class Backend(SmallOutputBackend):
        broken = True

        def json_completion(self, system, prompt, schema, max_tokens):
            if self.broken and "POISON" in prompt:
                self.calls[prompt] += 1
                raise ModelOutputError("Постоянная ошибка")
            return super().json_completion(system, prompt, schema, max_tokens)

    backend, events = Backend(), []
    nodes = [
        KnowledgeNode("bad", "Ошибка", "people", "POISON"),
        KnowledgeNode("ok", "Анна", "people", "Училась в NUP."),
    ]
    builder = KnowledgeBuilder(backend=backend, progress=events.append)
    run_skill(builder, nodes, [])
    assert builder.stats["connections_attempted"] == 2
    assert builder.stats["connections_done"] == 1
    assert builder.stats["connection_failures"][0]["id"] == "bad"
    assert backend.calls["POISON"] == 2
    assert events[-1]["percent"] == 50
    calls = backend.calls["Училась в NUP."]
    backend.broken = False
    resumed = KnowledgeBuilder(backend=backend, cache=builder.new_cache)
    run_skill(resumed, nodes, [])
    assert resumed.stats["connections_done"] == 2
    assert backend.calls["Училась в NUP."] == calls

from __future__ import annotations

from .people import format_person_details, humanize_details
from .pipeline import CATEGORIES, KnowledgeBuilder

__all__ = [
    "CATEGORIES",
    "HeuristicExtractor",
    "LlamaCppExtractor",
    "extract_graph",
    "extract_person_facts",
    "format_person_details",
    "humanize_details",
]


class HeuristicExtractor:
    def extract(self, source: dict):
        result = KnowledgeBuilder().build(source)
        return result.nodes, result.edges


class LlamaCppExtractor:
    def __init__(self, model_path: str) -> None:
        self.model_path = model_path

    def extract(self, source: dict):
        result = KnowledgeBuilder(self.model_path).build(source)
        return result.nodes, result.edges


def extract_graph(source: dict, model_path: str = ""):
    result = KnowledgeBuilder(model_path).build(source)
    return result.nodes, result.edges


def extract_person_facts(
    name: str,
    relationship: str,
    raw_notes: str,
    model_path: str = "",
    *,
    person: dict | None = None,
) -> dict:
    details = person or {"name": name, "relationship": relationship, "raw_notes": raw_notes}
    result = KnowledgeBuilder(model_path).build(
        {"profile": {"name": "Я", "bio": ""}, "people": [details], "notes": [], "trackers": []}
    )
    return next((item for item in result.people if item["name"] == name), {})

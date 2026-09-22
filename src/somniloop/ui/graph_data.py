"""Graph read model, indexed search and backward-compatible view persistence."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, replace

from somniloop.knowledge.people import normalized
from somniloop.knowledge.pipeline import digest

CATEGORY_NAMES = {"people": "Люди", "places": "Места", "habits": "Привычки", "groups": "Группы"}


def text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from text_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from text_values(child)


def enriched_graph(repository):
    nodes, edges = repository.load_knowledge_graph()
    people = {person.id: asdict(person) for person in repository.list_people()}
    notes = {f"note:{note.id}": asdict(note) for note in repository.list_notes()}
    updated = repository.get_setting("graph_updated_at")
    result = []
    for node in nodes:
        metadata = dict(node.metadata)
        person = people.get(metadata.get("person_id"), metadata.get("profile", {}))
        metadata["profile"] = person
        metadata["graph_updated_at"] = updated
        sources = person.get("sources", []) or metadata.get("sources", [])
        resolved = []
        for source in sources:
            item = dict(source) if isinstance(source, dict) else {"id": str(source)}
            identifier = str(item.get("id", item.get("source_id", "")))
            note = notes.get(identifier)
            if note:
                item.setdefault("title", note["title"])
                item["content"] = note["content"]
                item["current_updated_at"] = note["updated_at"]
            item["id"] = identifier
            resolved.append(item)
        metadata["sources"] = resolved
        # Keep structured imported contradictions as well as legacy strings.
        metadata["conflicts"] = []
        for conflict in [*node.metadata.get("conflicts", []), *person.get("conflicts", [])]:
            if conflict not in metadata["conflicts"]:
                metadata["conflicts"].append(conflict)
        dates = [person.get("updated_at", "")]
        if metadata.get("is_owner"):
            dates.append(repository.get_setting("profile_updated_at"))
        dates.extend(item.get("current_updated_at", "") for item in resolved)
        metadata["stale"] = bool(updated and any(stamp > updated for stamp in dates))
        result.append(replace(node, metadata=metadata))
    return result, edges


class GraphIndex:
    def __init__(self, nodes=(), edges=()):
        self.nodes = {node.id: node for node in nodes}
        self.edges = list(edges)
        self.adjacency = defaultdict(set)
        self.text = {}
        self.tokens = defaultdict(set)
        self.signatures = {}
        for edge in self.edges:
            self.adjacency[edge.source].add(edge.target)
            self.adjacency[edge.target].add(edge.source)
        for node in nodes:
            value = normalized(
                " ".join(
                    [
                        node.label,
                        node.details,
                        *text_values(node.metadata.get("profile", {})),
                        *text_values(node.metadata.get("sources", [])),
                    ]
                )
            )
            self.text[node.id] = value
            for word in set(value.split()):
                self.tokens[word].add(node.id)
            self.signatures[node.id] = digest(
                [
                    node.label,
                    node.category,
                    node.details,
                    node.metadata.get("conflicts", []),
                    {
                        key: node.metadata.get("profile", {}).get(key)
                        for key in (
                            "biography",
                            "birth_date",
                            "relationship",
                            "occupation",
                            "education",
                            "facts",
                            "history",
                            "interests",
                            "contact",
                        )
                    },
                    node.metadata.get("sources", []),
                ]
            )

    def search(self, query):
        words = normalized(query).split()
        if not words:
            return []
        candidates = set(self.nodes)
        for word in words:
            hits = set()
            for token, identifiers in self.tokens.items():
                if word in token:
                    hits.update(identifiers)
            candidates &= hits
        return sorted(
            candidates,
            key=lambda key: (
                not normalized(self.nodes[key].label).startswith(" ".join(words)),
                self.nodes[key].label.casefold(),
            ),
        )

    def subset(self, category="all", relation="", focus=None):
        edges = [edge for edge in self.edges if not relation or edge.relation == relation]
        valid = set(self.nodes)
        if category != "all":
            primary = {key for key, node in self.nodes.items() if node.category == category}
            valid = primary | {
                endpoint
                for edge in edges
                if edge.source in primary or edge.target in primary
                for endpoint in (edge.source, edge.target)
            }
        if relation:
            valid &= {endpoint for edge in edges for endpoint in (edge.source, edge.target)}
        if focus:
            neighborhood = {focus} | {
                endpoint
                for edge in edges
                if focus in (edge.source, edge.target)
                for endpoint in (edge.source, edge.target)
            }
            valid &= neighborhood
            if focus in self.nodes:
                valid.add(focus)
        return [node for key, node in self.nodes.items() if key in valid], [
            edge for edge in edges if edge.source in valid and edge.target in valid
        ]


class GraphViewState:
    KEY = "knowledge_graph_view_v1"

    def __init__(self, repository=None):
        self.repository = repository
        self.positions = {}
        self.pinned = set()
        self.seen = {}
        self.viewport = {}
        self._saved = ""
        if repository:
            try:
                self._saved = repository.get_setting(self.KEY, "")
                data = json.loads(self._saved or "{}")
                for key, point in data.get("positions", {}).items():
                    if (
                        isinstance(point, list)
                        and len(point) == 2
                        and all(
                            isinstance(v, (float, int)) and math.isfinite(v) and abs(v) < 1e7
                            for v in point
                        )
                    ):
                        self.positions[str(key)] = tuple(point)
                self.pinned = set(data.get("pinned", [])) & self.positions.keys()
                self.seen = data.get("seen", {}) if isinstance(data.get("seen", {}), dict) else {}
                viewport = data.get("viewport", {})
                if isinstance(viewport, dict) and all(
                    isinstance(viewport.get(k), (int, float)) and math.isfinite(viewport[k])
                    for k in ("x", "y", "scale")
                ):
                    self.viewport = viewport
            except (TypeError, ValueError, AttributeError):
                pass

    def status(self, node, signature):
        if node.metadata.get("stale"):
            return "stale"
        if node.id not in self.seen:
            return "new"
        return "changed" if self.seen[node.id] != signature else ""

    def save(self):
        value = json.dumps(
            {
                "positions": self.positions,
                "pinned": sorted(self.pinned),
                "seen": self.seen,
                "viewport": self.viewport,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if self.repository and value != self._saved:
            # A restored archive or another open view must not be overwritten by a
            # delayed save from a page about to be destroyed.
            if self.repository.get_setting(self.KEY, "") != self._saved:
                return
            self.repository.set_setting(self.KEY, value)
            self._saved = value

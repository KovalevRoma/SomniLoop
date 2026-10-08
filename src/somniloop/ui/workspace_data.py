"""Current work projections, ordered by completion and date."""

from dataclasses import dataclass
from datetime import date

from somniloop.core.models import TaskState, TrackerMode


@dataclass(frozen=True)
class WorkEntry:
    kind: str
    identifier: int
    title: str
    due: str
    time: str = ""
    project_id: int | None = None
    priority: int = 0
    planned_on: str = ""
    next_action: str = ""
    habit: bool = False
    done: bool = False

    @property
    def key(self):
        return self.kind, self.identifier


def work_entries(data, metadata):
    entries = []
    for task in data.planner:
        values = metadata.get(("planner", task.id), {})
        entries.append(WorkEntry("planner", task.id, task.title, task.due_date, task.due_time,
                                 **{key: values[key] for key in
                                    ("project_id", "priority", "planned_on", "next_action") if key in values}))
    for record in data.trackers.values():
        values = metadata.get(("tracker", record.tracker.id), {})
        habit = record.tracker.mode == TrackerMode.REGULAR
        pending = any(item.state != TaskState.DONE for _, items in record.occurrences for item in items)
        done = bool(record.occurrences) and not pending
        if record.meta.quota_target and (record.meta.quota_done or 0) >= record.meta.quota_target:
            done = True
        entries.append(WorkEntry(
            "tracker", record.tracker.id, record.tracker.name,
            record.next_date.isoformat() if record.next_date else "", habit=habit, done=done,
            **{key: values[key] for key in ("project_id", "priority", "planned_on", "next_action")
               if key in values},
        ))
    return entries


def order_work(entries, today=None):
    today = (today or date.today()).isoformat()
    return sorted(entries, key=lambda item: (
        item.done, not (item.due and item.due <= today),
        item.due or "9999", item.time or "24:00", item.title.casefold(), item.key,
    ))

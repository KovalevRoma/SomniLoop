from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .dates import normalize_birth_date
from .models import (
    DashboardMeta,
    DayStatus,
    DaySummary,
    DayTask,
    KnowledgeEdge,
    KnowledgeNode,
    Note,
    Person,
    ScheduleType,
    Task,
    TaskState,
    Tracker,
    TrackerMode,
)
from .planning import PlanningRepository
from .scheduling import due_dates_between, is_due, merge_dates, week_bounds

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS trackers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL CHECK(mode IN ('regular', 'manual')),
    schedule_type TEXT NOT NULL,
    schedule_json TEXT NOT NULL DEFAULT '{}',
    created_on TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#8267e8',
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    schedule_type TEXT,
    schedule_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    entry_date TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('done', 'not_done', 'unset')),
    UNIQUE(task_id, entry_date)
);

CREATE TABLE IF NOT EXISTS manual_dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    due_date TEXT NOT NULL,
    UNIQUE(tracker_id, due_date)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    entry_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    display_name TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO profile(id, display_name, bio) VALUES (1, '', '');

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT '',
    raw_notes TEXT NOT NULL DEFAULT '',
    biography TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '',
    occupation TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    analyzed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS knowledge_nodes (
    node_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    category TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES knowledge_nodes(node_id) ON DELETE CASCADE,
    relation TEXT NOT NULL DEFAULT '',
    UNIQUE(source_id, target_id, relation)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    content_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_cache (
    cache_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planner_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    due_date TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    completed INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS planner_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planner_id INTEGER NOT NULL REFERENCES planner_tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS birthday_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    birthday TEXT NOT NULL,
    title TEXT NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0,
    UNIQUE(person_id, birthday)
);
CREATE INDEX IF NOT EXISTS task_entries_by_tracker_date ON task_entries(tracker_id, entry_date);
CREATE INDEX IF NOT EXISTS tasks_by_tracker ON tasks(tracker_id);
CREATE INDEX IF NOT EXISTS planner_by_archive_date ON planner_tasks(archived, due_date);
"""


class Repository(PlanningRepository):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        database_existed = self.path.exists() and self.path.stat().st_size > 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.path.chmod(0o600)
        self.connection.row_factory = sqlite3.Row
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if self.path.stat().st_size and version < 3:
            backup_path = self.path.with_suffix(self.path.suffix + ".pre-v3.bak")
            if not backup_path.exists():
                with sqlite3.connect(backup_path) as backup:
                    self.connection.backup(backup)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.executescript(SCHEMA)
        self._migrate_schema()
        self.connection.execute("PRAGMA user_version=3")
        self.connection.commit()
        self._cache_generation = -1
        self._read_cache: dict[tuple, Any] = {}
        self.backup_error = ""
        if database_existed:
            try:
                self._daily_backup()
            except (OSError, sqlite3.Error) as exc:
                # A backup problem must not lock the user out of the primary database.
                self.backup_error = str(exc)

    def backup(self, *, label: str = "manual") -> Path:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")
        target = backup_dir / f"somniloop-{label}-{stamp}.db"
        with sqlite3.connect(target) as backup:
            self.connection.backup(backup)
        target.chmod(0o600)
        return target

    def _daily_backup(self) -> None:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"somniloop-auto-{date.today().isoformat()}.db"
        if not target.exists():
            with sqlite3.connect(target) as backup:
                self.connection.backup(backup)
            target.chmod(0o600)
        backups = sorted(backup_dir.glob("somniloop-auto-*.db"), reverse=True)
        for old in backups[7:]:
            old.unlink()

    def _migrate_schema(self) -> None:
        """Keep databases created by earlier SomniLoop versions usable."""
        additions = {
            "task_entries": {"partial": "INTEGER NOT NULL DEFAULT 0"},
            "planner_tasks": {"state": "TEXT NOT NULL DEFAULT 'unset'"},
            "planner_items": {"state": "TEXT NOT NULL DEFAULT 'unset'"},
            "tasks": {"occurrence_date": "TEXT"},
            "people": {
                "interests": "TEXT NOT NULL DEFAULT ''",
                "birth_date_input": "TEXT NOT NULL DEFAULT ''",
                "interests_input": "TEXT NOT NULL DEFAULT ''",
                "history_json": "TEXT NOT NULL DEFAULT '[]'",
                "conflicts_json": "TEXT NOT NULL DEFAULT '[]'",
                "sources_json": "TEXT NOT NULL DEFAULT '[]'",
                "managed": "INTEGER NOT NULL DEFAULT 1",
                "contact": "TEXT NOT NULL DEFAULT ''",
                "group_name": "TEXT NOT NULL DEFAULT ''",
                "clarifications_json": "TEXT NOT NULL DEFAULT '[]'",
                "manual_overrides_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "knowledge_nodes": {"metadata_json": "TEXT NOT NULL DEFAULT '{}'"},
        }
        for table, columns in additions.items():
            existing = {
                row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")
            }
            for column, definition in columns.items():
                if column not in existing:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    if table == "people" and column == "birth_date_input":
                        self.connection.execute("UPDATE people SET birth_date_input=birth_date")
        note_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(notes)")}
        if "entry_date" not in note_columns:
            self.connection.execute(
                "ALTER TABLE notes ADD COLUMN entry_date TEXT NOT NULL DEFAULT ''"
            )
        self.connection.execute(
            """UPDATE notes SET entry_date=substr(created_at, 1, 10)
               WHERE entry_date=''"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS notes_by_date ON notes(entry_date DESC, updated_at DESC)"
        )
        graph_schema = self.connection.execute(
            "SELECT value FROM settings WHERE key='knowledge_graph_schema'"
        ).fetchone()
        if graph_schema is None or graph_schema[0] != "3":
            # The graph is derived data. Rebuild it to remove legacy event nodes
            # and categories that are no longer part of the product.
            self.connection.execute("DELETE FROM knowledge_edges")
            self.connection.execute("DELETE FROM knowledge_nodes")
            self.connection.execute(
                """INSERT INTO settings(key, value) VALUES ('knowledge_graph_schema', '3')
                   ON CONFLICT(key) DO UPDATE SET value='3'"""
            )

    def close(self) -> None:
        self.connection.close()

    def _cached(self, key: tuple, loader):
        # SQLite's change counter invalidates every view after any local write.
        if self._cache_generation != self.connection.total_changes:
            self._read_cache.clear()
            self._cache_generation = self.connection.total_changes
        if key not in self._read_cache:
            self._read_cache[key] = loader()
        return self._read_cache[key]

    @staticmethod
    def _tracker(row: sqlite3.Row) -> Tracker:
        return Tracker(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            mode=TrackerMode(row["mode"]),
            schedule_type=ScheduleType(row["schedule_type"]),
            schedule=json.loads(row["schedule_json"] or "{}"),
            created_on=date.fromisoformat(row["created_on"]),
            color=row["color"],
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            tracker_id=row["tracker_id"],
            name=row["name"],
            details=row["details"],
            position=row["position"],
            schedule_type=ScheduleType(row["schedule_type"]) if row["schedule_type"] else None,
            schedule=json.loads(row["schedule_json"] or "{}"),
            occurrence_date=row["occurrence_date"],
        )

    def create_tracker(
        self,
        name: str,
        description: str,
        mode: TrackerMode,
        schedule_type: ScheduleType,
        schedule: dict[str, Any],
        task_names: Iterable[str] = (),
        color: str = "#8267e8",
        created_on: date | None = None,
    ) -> int:
        mode = TrackerMode(mode)
        schedule_type = ScheduleType(schedule_type)
        created = created_on or date.today()
        cursor = self.connection.execute(
            """INSERT INTO trackers
               (name, description, mode, schedule_type, schedule_json, created_on, color)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name.strip(),
                description.strip(),
                mode.value,
                schedule_type.value,
                json.dumps(schedule),
                created.isoformat(),
                color,
            ),
        )
        tracker_id = int(cursor.lastrowid)
        for position, task_name in enumerate(x.strip() for x in task_names if x.strip()):
            self.connection.execute(
                "INSERT INTO tasks(tracker_id, name, position) VALUES (?, ?, ?)",
                (tracker_id, task_name, position),
            )
        self.connection.commit()
        return tracker_id

    def update_tracker(
        self,
        tracker_id: int,
        name: str,
        description: str,
        schedule_type: ScheduleType | None = None,
        schedule: dict[str, Any] | None = None,
    ) -> None:
        # mode is deliberately absent: regular/manual is immutable.
        if schedule_type is None:
            self.connection.execute(
                "UPDATE trackers SET name=?, description=? WHERE id=?",
                (name.strip(), description.strip(), tracker_id),
            )
        else:
            schedule_type = ScheduleType(schedule_type)
            self.connection.execute(
                """UPDATE trackers SET name=?, description=?, schedule_type=?, schedule_json=?
                   WHERE id=?""",
                (
                    name.strip(),
                    description.strip(),
                    schedule_type.value,
                    json.dumps(schedule or {}),
                    tracker_id,
                ),
            )
        self.connection.commit()

    def delete_tracker(self, tracker_id: int) -> None:
        self.connection.execute("DELETE FROM trackers WHERE id=?", (tracker_id,))
        self.connection.commit()

    def archive_tracker(self, tracker_id: int, archived: bool = True) -> None:
        self.connection.execute(
            "UPDATE trackers SET archived=? WHERE id=?", (int(archived), tracker_id)
        )
        self.connection.commit()

    def list_trackers(self, include_archived: bool = False) -> list[Tracker]:
        sql = "SELECT * FROM trackers"
        if not include_archived:
            sql += " WHERE archived=0"
        sql += " ORDER BY mode, id"
        return [self._tracker(row) for row in self.connection.execute(sql)]

    def get_tracker(self, tracker_id: int) -> Tracker:
        row = self.connection.execute("SELECT * FROM trackers WHERE id=?", (tracker_id,)).fetchone()
        if row is None:
            raise KeyError(f"Tracker {tracker_id} does not exist")
        return self._tracker(row)

    def list_tasks(self, tracker_id: int) -> list[Task]:
        return self._cached(
            ("tasks", tracker_id),
            lambda: [
                self._task(row)
                for row in self.connection.execute(
                    "SELECT * FROM tasks WHERE tracker_id=? ORDER BY position, id", (tracker_id,)
                )
            ],
        )

    def add_task(
        self,
        tracker_id: int,
        name: str,
        details: str = "",
        schedule_type: ScheduleType | None = None,
        schedule: dict[str, Any] | None = None,
        occurrence_date: date | None = None,
    ) -> int:
        if schedule_type is not None:
            schedule_type = ScheduleType(schedule_type)
        position = self.connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE tracker_id=?",
            (tracker_id,),
        ).fetchone()[0]
        cursor = self.connection.execute(
            """INSERT INTO tasks
               (tracker_id, name, details, position, schedule_type, schedule_json, occurrence_date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                tracker_id,
                name.strip(),
                details.strip(),
                position,
                schedule_type.value if schedule_type else None,
                json.dumps(schedule or {}),
                occurrence_date.isoformat() if occurrence_date else None,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_task(
        self,
        task_id: int,
        name: str,
        details: str = "",
        schedule_type: ScheduleType | None = None,
        schedule: dict[str, Any] | None = None,
    ) -> None:
        if schedule_type is not None:
            schedule_type = ScheduleType(schedule_type)
        self.connection.execute(
            """UPDATE tasks SET name=?, details=?, schedule_type=?, schedule_json=?
               WHERE id=?""",
            (
                name.strip(),
                details.strip(),
                schedule_type.value if schedule_type else None,
                json.dumps(schedule or {}),
                task_id,
            ),
        )
        self.connection.commit()

    def delete_task(self, task_id: int) -> None:
        self.connection.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.connection.commit()

    def add_manual_date(self, tracker_id: int, day: date) -> bool:
        try:
            self.connection.execute(
                "INSERT INTO manual_dates(tracker_id, due_date) VALUES (?, ?)",
                (tracker_id, day.isoformat()),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def add_manual_occurrence(self, tracker_id: int, day: date, task_names: Iterable[str]) -> bool:
        if self.get_tracker(tracker_id).mode != TrackerMode.MANUAL:
            raise ValueError("Only manual trackers support occurrence-specific tasks")
        if day in self.list_manual_dates(tracker_id):
            return False
        with self.connection:
            self.connection.execute(
                "INSERT INTO manual_dates(tracker_id, due_date) VALUES (?, ?)",
                (tracker_id, day.isoformat()),
            )
            for position, name in enumerate(task_names):
                if name.strip():
                    self.connection.execute(
                        "INSERT INTO tasks(tracker_id, name, position, occurrence_date) VALUES (?, ?, ?, ?)",
                        (tracker_id, name.strip(), position, day.isoformat()),
                    )
        return True

    def remove_manual_date(self, tracker_id: int, day: date) -> None:
        self.connection.execute(
            "DELETE FROM manual_dates WHERE tracker_id=? AND due_date=?",
            (tracker_id, day.isoformat()),
        )
        self.connection.execute(
            "DELETE FROM tasks WHERE tracker_id=? AND occurrence_date=?",
            (tracker_id, day.isoformat()),
        )
        self.connection.commit()

    def list_manual_dates(
        self, tracker_id: int, start: date | None = None, end: date | None = None
    ) -> list[date]:
        dates = self._cached(
            ("manual", tracker_id),
            lambda: [
                date.fromisoformat(row[0])
                for row in self.connection.execute(
                    "SELECT due_date FROM manual_dates WHERE tracker_id=? ORDER BY due_date",
                    (tracker_id,),
                )
            ],
        )
        return [
            day for day in dates if (start is None or day >= start) and (end is None or day <= end)
        ]

    def _task_is_due(self, tracker: Tracker, task: Task, day: date) -> bool:
        if tracker.schedule_type != ScheduleType.ITEM_DATES:
            return True
        if task.schedule_type is None:
            return False
        return is_due(task.schedule_type, task.schedule, day, tracker.created_on)

    def scheduled_tasks(self, tracker: Tracker, day: date) -> list[Task]:
        tasks = self.list_tasks(tracker.id)
        if tracker.mode == TrackerMode.MANUAL:
            return (
                [task for task in tasks if task.occurrence_date in (None, day.isoformat())]
                if day in self.list_manual_dates(tracker.id, day, day)
                else []
            )
        if tracker.schedule_type == ScheduleType.WEEKLY_QUOTA:
            # Flexible quota: any day may be chosen by the user.
            return tasks
        if tracker.schedule_type == ScheduleType.ITEM_DATES:
            return [task for task in tasks if self._task_is_due(tracker, task, day)]
        if is_due(tracker.schedule_type, tracker.schedule, day, tracker.created_on):
            return tasks
        return []

    def _entries_for_day(self, tracker_id: int, day: date) -> dict[int, TaskState]:
        start = day.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)

        def load():
            result: dict[str, dict[int, TaskState]] = {}
            for row in self.connection.execute(
                "SELECT task_id, state, partial, entry_date FROM task_entries WHERE tracker_id=? AND entry_date>=? AND entry_date<?",
                (tracker_id, start.isoformat(), end.isoformat()),
            ):
                result.setdefault(row["entry_date"], {})[row["task_id"]] = (
                    TaskState.PARTIAL if row["partial"] else TaskState(row["state"])
                )
            return result

        return self._cached(("entries", tracker_id, start.isoformat()), load).get(
            day.isoformat(), {}
        )

    def day_summary(
        self, tracker: Tracker | int, day: date, today: date | None = None
    ) -> DaySummary:
        if isinstance(tracker, int):
            tracker = self.get_tracker(tracker)
        current = today or date.today()
        tasks = self.scheduled_tasks(tracker, day)
        entries = self._entries_for_day(tracker.id, day)

        # A flexible weekly quota day is only visible in history if it has entries.
        if tracker.schedule_type == ScheduleType.WEEKLY_QUOTA and not entries:
            return DaySummary(day, DayStatus.UNSCHEDULED, [])
        if not tasks:
            return DaySummary(day, DayStatus.UNSCHEDULED, [])

        day_tasks = [DayTask(task, entries.get(task.id, TaskState.UNSET)) for task in tasks]
        states = [item.state for item in day_tasks]
        if states and all(state == TaskState.DONE for state in states):
            status = DayStatus.DONE
        elif any(state in (TaskState.DONE, TaskState.PARTIAL) for state in states):
            status = DayStatus.PARTIAL
        elif any(state == TaskState.NOT_DONE for state in states):
            status = DayStatus.MISSED
        elif day < current:
            status = DayStatus.MISSED
        else:
            status = DayStatus.UNSET
        return DaySummary(day, status, day_tasks)

    def set_task_state(self, tracker_id: int, task_id: int, day: date, state: TaskState) -> None:
        self._cached(("sync",), lambda: None)
        if state == TaskState.UNSET:
            self.connection.execute(
                "DELETE FROM task_entries WHERE task_id=? AND entry_date=?",
                (task_id, day.isoformat()),
            )
        else:
            self.connection.execute(
                """INSERT INTO task_entries(tracker_id, task_id, entry_date, state, partial)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(task_id, entry_date) DO UPDATE SET state=excluded.state, partial=excluded.partial""",
                (
                    tracker_id,
                    task_id,
                    day.isoformat(),
                    TaskState.NOT_DONE.value if state == TaskState.PARTIAL else state.value,
                    int(state == TaskState.PARTIAL),
                ),
            )
        self.connection.commit()

        # A quick mark changes one month/year only; unrelated and historical blocks
        # remain valid. Other mutation paths retain conservative invalidation.
        self._read_cache.pop(("entries", tracker_id, day.replace(day=1).isoformat()), None)
        self._read_cache.pop(("streak_status", tracker_id, day.year), None)
        self._cache_generation = self.connection.total_changes

    def _scheduled_dates(self, tracker: Tracker, start: date, end: date) -> list[date]:
        if tracker.mode == TrackerMode.MANUAL:
            return self.list_manual_dates(tracker.id, start, end)
        if tracker.schedule_type == ScheduleType.ITEM_DATES:
            tasks = self.list_tasks(tracker.id)
            return merge_dates(
                due_dates_between(task.schedule_type, task.schedule, start, end, tracker.created_on)
                for task in tasks
                if task.schedule_type is not None
            )
        if tracker.schedule_type == ScheduleType.WEEKLY_QUOTA:
            rows = self.connection.execute(
                """SELECT DISTINCT entry_date FROM task_entries
                   WHERE tracker_id=? AND entry_date BETWEEN ? AND ?""",
                (tracker.id, start.isoformat(), end.isoformat()),
            )
            return sorted(date.fromisoformat(row[0]) for row in rows)
        return due_dates_between(
            tracker.schedule_type, tracker.schedule, start, end, tracker.created_on
        )

    def calendar_statuses(self, tracker_id: int, start: date, end: date) -> dict[date, DayStatus]:
        tracker = self.get_tracker(tracker_id)
        result = {
            day: self.day_summary(tracker, day).status
            for day in self._scheduled_dates(tracker, start, end)
        }
        if tracker.schedule_type == ScheduleType.WEEKLY_QUOTA:
            cursor, _ = week_bounds(start)
            while cursor <= end:
                week_end = cursor + timedelta(days=6)
                if week_end < date.today():
                    done, target = self.weekly_progress(tracker, cursor)
                    if done < target and start <= week_end <= end:
                        result[week_end] = DayStatus.MISSED
                cursor += timedelta(days=7)
        return result

    def weekly_progress(self, tracker: Tracker, day: date | None = None) -> tuple[int, int]:
        current = day or date.today()
        start, end = week_bounds(current)
        target = max(1, int(tracker.schedule.get("count", 1)))
        completed = 0
        cursor = start
        while cursor <= end:
            if (
                self.day_summary(tracker, cursor, today=end + timedelta(days=1)).status
                == DayStatus.DONE
            ):
                completed += 1
            cursor += timedelta(days=1)
        return completed, target

    def streak(self, tracker: Tracker, today: date | None = None) -> tuple[int, str]:
        current = today or date.today()
        if tracker.schedule_type == ScheduleType.WEEKLY_QUOTA:
            count = 0
            start, end = week_bounds(current)
            done, target = self.weekly_progress(tracker, current)
            if done >= target:
                count += 1
            start -= timedelta(days=7)
            end -= timedelta(days=7)
            while end >= tracker.created_on:
                done, target = self.weekly_progress(tracker, start)
                if done < target:
                    break
                count += 1
                start -= timedelta(days=7)
                end -= timedelta(days=7)
            return count, "weeks"

        dates = self._scheduled_dates(tracker, tracker.created_on, current)
        if tracker.mode == TrackerMode.REGULAR and tracker.schedule_type != ScheduleType.ITEM_DATES:
            # Aggregate a year into day outcomes instead of loading every historical
            # task mark. Stop reading older blocks as soon as the streak breaks.
            count = 0
            for day in reversed(dates):

                def load_year(year=day.year):
                    return {
                        row["entry_date"]: bool(row["positive"])
                        for row in self.connection.execute(
                            """SELECT e.entry_date, MAX(e.state='done' OR e.partial=1) AS positive
                           FROM task_entries e JOIN tasks t ON t.id=e.task_id
                           WHERE e.tracker_id=? AND e.entry_date>=? AND e.entry_date<?
                             AND (e.state!='unset' OR e.partial=1)
                           GROUP BY e.entry_date""",
                            (tracker.id, f"{year:04d}-01-01", f"{year + 1:04d}-01-01"),
                        )
                    }

                outcomes = self._cached(("streak_status", tracker.id, day.year), load_year)
                value = outcomes.get(day.isoformat())
                if day == current and value is None:
                    continue
                if value:
                    count += 1
                else:
                    break
            return count, "occurrences"
        count = 0
        for day in reversed(dates):
            status = self.day_summary(tracker, day, today=current).status
            if day == current and status == DayStatus.UNSET:
                continue
            if status in (DayStatus.DONE, DayStatus.PARTIAL):
                count += 1
            elif status == DayStatus.MISSED:
                break
        return count, "occurrences"

    def _all_tasks_explicit(self, tracker: Tracker, day: date) -> bool:
        tasks = self.scheduled_tasks(tracker, day)
        if not tasks:
            return False
        entries = self._entries_for_day(tracker.id, day)
        return all(task.id in entries and entries[task.id] != TaskState.PARTIAL for task in tasks)

    def dashboard_meta(self, tracker: Tracker, today: date | None = None) -> DashboardMeta:
        current = today or date.today()
        streak, unit = self.streak(tracker, current)
        quota_done = quota_target = None
        next_date = None

        if tracker.mode == TrackerMode.MANUAL:
            dates = self.list_manual_dates(tracker.id)
            unresolved = [day for day in dates if not self._all_tasks_explicit(tracker, day)]
            needs_attention = any(day <= current for day in unresolved)
            future_or_today = [day for day in unresolved if day >= current]
            next_date = min(future_or_today, default=None)
            label = "manual"
        elif tracker.schedule_type == ScheduleType.WEEKLY_QUOTA:
            quota_done, quota_target = self.weekly_progress(tracker, current)
            _, week_end = week_bounds(current)
            remaining = max(0, quota_target - quota_done)
            days_left = (week_end - current).days + 1
            needs_attention = remaining > 0 and remaining >= days_left
            label = "weekly_quota"
        else:
            summary = self.day_summary(tracker, current)
            needs_attention = bool(summary.tasks) and not self._all_tasks_explicit(tracker, current)
            label = tracker.schedule_type.value

        return DashboardMeta(
            streak=streak,
            streak_unit=unit,
            needs_attention=needs_attention,
            schedule_label=label,
            quota_done=quota_done,
            quota_target=quota_target,
            next_date=next_date,
        )

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            """INSERT INTO settings(key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )
        self.connection.commit()

    def get_profile(self) -> tuple[str, str]:
        row = self.connection.execute("SELECT display_name, bio FROM profile WHERE id=1").fetchone()
        return row[0], row[1]

    def save_profile(self, display_name: str, bio: str) -> None:
        if self.get_profile() == (display_name.strip(), bio.strip()):
            return
        self.connection.execute(
            "UPDATE profile SET display_name=?, bio=? WHERE id=1",
            (display_name.strip(), bio.strip()),
        )
        self.connection.commit()
        self.set_setting("profile_updated_at", datetime.now().isoformat(timespec="microseconds"))

    def list_notes(self, include_content: bool = True) -> list[Note]:
        content_column = "content" if include_content else "'' AS content"
        return [
            Note(**dict(row))
            for row in self.connection.execute(
                f"""SELECT id, title, {content_column}, entry_date, created_at, updated_at
                   FROM notes ORDER BY entry_date DESC, updated_at DESC"""
            )
        ]

    def get_note(self, note_id: int) -> Note:
        row = self.connection.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        if row is None:
            raise KeyError(f"Note {note_id} does not exist")
        return Note(**dict(row))

    def save_note(
        self,
        title: str,
        content: str,
        entry_date: date | str | None = None,
        note_id: int | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        day = entry_date.isoformat() if isinstance(entry_date, date) else entry_date
        day = day or date.today().isoformat()
        date.fromisoformat(day)
        if note_id is not None:
            previous = self.connection.execute(
                "SELECT title, content, entry_date FROM notes WHERE id=?", (note_id,)
            ).fetchone()
            if previous and tuple(previous) == (title.strip(), content.strip(), day):
                return note_id
        if note_id is None:
            cursor = self.connection.execute(
                """INSERT INTO notes
                   (title, content, entry_date, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (title.strip(), content.strip(), day, now, now),
            )
            note_id = int(cursor.lastrowid)
        else:
            self.connection.execute(
                """UPDATE notes SET title=?, content=?, entry_date=?, updated_at=?
                   WHERE id=?""",
                (title.strip(), content.strip(), day, now, note_id),
            )
        self.connection.commit()
        return note_id

    def delete_note(self, note_id: int) -> None:
        self.connection.execute("DELETE FROM notes WHERE id=?", (note_id,))
        self.connection.commit()

    @staticmethod
    def _person(row: sqlite3.Row) -> Person:
        try:
            facts = json.loads(row["facts_json"] or "[]")
        except json.JSONDecodeError:
            facts = []
        return Person(
            id=row["id"],
            name=row["name"],
            relationship=row["relationship"],
            raw_notes=row["raw_notes"],
            biography=row["biography"],
            birth_date=row["birth_date"],
            education=row["education"],
            occupation=row["occupation"],
            facts=[str(item) for item in facts],
            updated_at=row["updated_at"],
            analyzed_at=row["analyzed_at"],
            interests=row["interests"],
            birth_date_input=row["birth_date_input"],
            interests_input=row["interests_input"],
            history=json.loads(row["history_json"]),
            conflicts=json.loads(row["conflicts_json"]),
            sources=json.loads(row["sources_json"]),
            managed=bool(row["managed"]),
            contact=row["contact"],
            group_name=row["group_name"],
            clarifications=json.loads(row["clarifications_json"]),
            manual_overrides=json.loads(row["manual_overrides_json"]),
        )

    def create_person(self, name: str = "Новый человек", *, managed: bool = True) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        cursor = self.connection.execute(
            "INSERT INTO people(name, updated_at, managed) VALUES (?, ?, ?)",
            (name.strip() or "Новый человек", now, int(managed)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_people(self, *, managed_only: bool = False) -> list[Person]:
        where = "WHERE managed=1" if managed_only else ""
        return [
            self._person(row)
            for row in self.connection.execute(
                f"SELECT * FROM people {where} ORDER BY name COLLATE NOCASE"
            )
        ]

    def get_person(self, person_id: int) -> Person:
        row = self.connection.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        if row is None:
            raise KeyError(f"Person {person_id} does not exist")
        return self._person(row)

    def save_person_input(
        self,
        person_id: int,
        name: str,
        relationship: str,
        raw_notes: str,
        birth_date: str | None = None,
        interests: str | None = None,
        contact: str | None = None,
        group_name: str | None = None,
    ) -> bool:
        current = self.get_person(person_id)
        birth = current.birth_date_input if birth_date is None else normalize_birth_date(birth_date)
        interest_text = current.interests_input if interests is None else interests.strip()
        contact_text = current.contact if contact is None else contact.strip()
        group_text = current.group_name if group_name is None else group_name.strip()
        normalized = (
            name.strip(),
            relationship.strip(),
            raw_notes.strip(),
            birth,
            interest_text,
            contact_text,
            group_text,
        )
        previous = (
            current.name,
            current.relationship,
            current.raw_notes,
            current.birth_date_input,
            current.interests_input,
            current.contact,
            current.group_name,
        )
        if normalized == previous:
            return False
        now = datetime.now().isoformat(timespec="microseconds")
        previous_count = self.connection.execute(
            "SELECT COUNT(*) FROM person_revisions WHERE person_id=?", (person_id,)
        ).fetchone()[0]
        if not previous_count and any(previous[2:]):
            self._record_person_revision(person_id, previous, current.updated_at)
        self._record_person_revision(person_id, normalized, now)
        self.connection.execute(
            """UPDATE people SET name=?, relationship=?, raw_notes=?, birth_date_input=?,
               interests_input=?, contact=?, group_name=?, updated_at=?, managed=1
               WHERE id=?""",
            (*normalized, now, person_id),
        )
        if birth_date is not None:
            self.connection.execute("UPDATE people SET birth_date=? WHERE id=?", (birth, person_id))
        if interests is not None:
            self.connection.execute(
                "UPDATE people SET interests=? WHERE id=?", (interest_text, person_id)
            )
        self.connection.commit()
        return True

    def _record_person_revision(self, person_id: int, values: tuple, recorded_at: str) -> None:
        payload = dict(
            zip(
                (
                    "name",
                    "relationship",
                    "raw_notes",
                    "birth_date_input",
                    "interests_input",
                    "contact",
                    "group_name",
                ),
                values,
            )
        )
        self.connection.execute(
            "INSERT INTO person_revisions(person_id, content_json, recorded_at) VALUES (?, ?, ?)",
            (person_id, json.dumps(payload, ensure_ascii=False), recorded_at),
        )

    def save_person_analysis(
        self, person_id: int, analysis: dict[str, Any], *, commit: bool = True
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        current = self.get_person(person_id)
        overrides = current.manual_overrides
        facts_source = overrides.get("facts", analysis.get("facts", []))
        facts = [str(item).strip() for item in facts_source if str(item).strip()]
        conflicts = [
            str(item).strip() for item in analysis.get("conflicts", []) if str(item).strip()
        ]
        previous_answers = {
            str(item.get("question", "")): str(item.get("answer", ""))
            for item in current.clarifications
            if isinstance(item, dict)
        }
        clarifications = [
            {"question": question, "answer": previous_answers.get(question, "")}
            for question in conflicts
        ]
        relationship = current.relationship
        proposed_relationship = str(analysis.get("relationship", "")).strip()
        if proposed_relationship and relationship in {
            "",
            "личный контакт из Telegram",
            "участник общих Telegram-чатов",
        }:
            relationship = proposed_relationship
        self.connection.execute(
            """UPDATE people SET relationship=?, biography=?, birth_date=?, education=?,
               occupation=?, facts_json=?, analyzed_at=?, interests=?, history_json=?,
               conflicts_json=?, sources_json=?, clarifications_json=? WHERE id=?""",
            (
                relationship,
                str(overrides.get("biography", analysis.get("biography", ""))).strip(),
                normalize_birth_date(str(analysis.get("birth_date", ""))),
                str(overrides.get("education", analysis.get("education", ""))).strip(),
                str(overrides.get("occupation", analysis.get("occupation", ""))).strip(),
                json.dumps(facts, ensure_ascii=False),
                now,
                str(analysis.get("interests", "")),
                json.dumps(analysis.get("history", []), ensure_ascii=False),
                json.dumps(conflicts, ensure_ascii=False),
                json.dumps(analysis.get("sources", []), ensure_ascii=False),
                json.dumps(clarifications, ensure_ascii=False),
                person_id,
            ),
        )
        if commit:
            self.connection.commit()

    def save_person_details(
        self,
        person_id: int,
        *,
        biography: str,
        education: str,
        occupation: str,
        facts: list[str],
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        cleaned = list(dict.fromkeys(item.strip() for item in facts if item.strip()))
        overrides = {
            "biography": biography.strip(),
            "education": education.strip(),
            "occupation": occupation.strip(),
            "facts": cleaned,
        }
        self.connection.execute(
            """UPDATE people SET biography=?, education=?, occupation=?, facts_json=?,
               manual_overrides_json=?, updated_at=? WHERE id=?""",
            (
                biography.strip(),
                education.strip(),
                occupation.strip(),
                json.dumps(cleaned, ensure_ascii=False),
                json.dumps(overrides, ensure_ascii=False),
                now,
                person_id,
            ),
        )
        self.connection.commit()

    def save_clarification(self, person_id: int, index: int, answer: str) -> None:
        person = self.get_person(person_id)
        if index < 0 or index >= len(person.clarifications):
            raise IndexError(index)
        person.clarifications[index]["answer"] = answer.strip()
        self.connection.execute(
            "UPDATE people SET clarifications_json=?, updated_at=? WHERE id=?",
            (
                json.dumps(person.clarifications, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
                person_id,
            ),
        )
        self.connection.commit()

    def merge_people(self, primary_id: int, duplicate_id: int) -> int:
        if primary_id == duplicate_id:
            return primary_id
        primary, duplicate = self.get_person(primary_id), self.get_person(duplicate_id)

        def joined(first: str, second: str) -> str:
            values = [value.strip() for value in (first, second) if value.strip()]
            return "\n\n".join(dict.fromkeys(values))

        def combined(first: list, second: list) -> list:
            result = []
            seen = set()
            for value in first + second:
                marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
                if marker not in seen:
                    seen.add(marker)
                    result.append(value)
            return result

        conflicts = combined(primary.conflicts, duplicate.conflicts)
        if (
            primary.birth_date
            and duplicate.birth_date
            and primary.birth_date != duplicate.birth_date
        ):
            conflicts.append(
                f"Указаны разные даты рождения: {primary.birth_date} и {duplicate.birth_date}."
            )
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                "UPDATE person_revisions SET person_id=? WHERE person_id=?",
                (primary_id, duplicate_id),
            )
            self.connection.execute(
                """UPDATE people SET name=?, relationship=?, raw_notes=?, biography=?, birth_date=?,
                   education=?, occupation=?, facts_json=?, updated_at=?, analyzed_at=?, interests=?,
                   birth_date_input=?, interests_input=?, history_json=?, conflicts_json=?,
                   sources_json=?, managed=1, contact=?, group_name=?, clarifications_json=?,
                   manual_overrides_json=? WHERE id=?""",
                (
                    primary.name or duplicate.name,
                    primary.relationship or duplicate.relationship,
                    joined(primary.raw_notes, duplicate.raw_notes),
                    joined(primary.biography, duplicate.biography),
                    primary.birth_date or duplicate.birth_date,
                    joined(primary.education, duplicate.education),
                    joined(primary.occupation, duplicate.occupation),
                    json.dumps(combined(primary.facts, duplicate.facts), ensure_ascii=False),
                    now,
                    max(primary.analyzed_at, duplicate.analyzed_at),
                    joined(primary.interests, duplicate.interests),
                    primary.birth_date_input or duplicate.birth_date_input,
                    joined(primary.interests_input, duplicate.interests_input),
                    json.dumps(combined(primary.history, duplicate.history), ensure_ascii=False),
                    json.dumps(list(dict.fromkeys(conflicts)), ensure_ascii=False),
                    json.dumps(combined(primary.sources, duplicate.sources), ensure_ascii=False),
                    primary.contact or duplicate.contact,
                    primary.group_name or duplicate.group_name,
                    json.dumps(
                        combined(primary.clarifications, duplicate.clarifications),
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {**duplicate.manual_overrides, **primary.manual_overrides},
                        ensure_ascii=False,
                    ),
                    primary_id,
                ),
            )
            self.connection.execute("DELETE FROM people WHERE id=?", (duplicate_id,))
        return primary_id

    def delete_person(self, person_id: int) -> None:
        self.connection.execute("DELETE FROM people WHERE id=?", (person_id,))
        self.connection.commit()

    def telegram_manifest(self) -> dict[str, Any]:
        try:
            value = json.loads(self.get_setting("telegram_import", "{}"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def register_telegram_export(
        self,
        scan: dict,
        decisions: dict[str, Any],
        progress=None,
    ) -> dict:
        """Attach every Telegram author to one local person and remember the source file."""
        from somniloop.core.telegram_import import MIN_PERSONAL_MESSAGES

        def name_key(value: str) -> str:
            words = value.casefold().replace("ё", "е").split()
            return " ".join(sorted(words)) if 2 <= len(words) <= 3 else " ".join(words)

        people = self.list_people(managed_only=True)
        by_name: dict[str, int] = {}
        for person in people:
            by_name.setdefault(name_key(person.name), person.id)
        valid_ids = {person.id for person in people}
        old_map = self.telegram_manifest().get("identity_map", {})
        personal_ids = {
            item["telegram_id"]
            for item in scan.get("personal_chats", [])
            if item.get("telegram_id") and int(item.get("messages", 0)) > MIN_PERSONAL_MESSAGES
        }
        skipped_ids: set[str] = set()
        identity_map: dict[str, dict] = {}
        created = 0

        identities = scan.get("identities", [])
        total_identities = len(identities)
        if progress:
            progress(0, total_identities, "Подготовка импорта Telegram")
        with self.connection:
            for index, identity in enumerate(identities, start=1):
                telegram_id = str(identity.get("telegram_id", ""))
                if progress:
                    progress(index, total_identities, "Сохраняю контакты и связи")
                if not telegram_id:
                    continue
                old_mapping = old_map.get(telegram_id, {})
                if telegram_id not in personal_ids and not old_mapping:
                    continue
                decision = decisions.get(telegram_id)
                selected_group = ""
                if isinstance(decision, dict):
                    selected_group = str(decision.get("group_name", "")).strip()
                    choice = decision.get("action")
                else:
                    choice = decision
                if choice is None:
                    previous = old_map.get(telegram_id, {}).get("person_id")
                    choice = previous if previous in valid_ids else "create"
                if choice == "skip":
                    skipped_ids.add(telegram_id)
                    continue
                person_id = choice if isinstance(choice, int) and choice in valid_ids else None
                display_name = str(identity.get("name", "")).strip() or "Контакт Telegram"
                if person_id is None:
                    person_id = by_name.get(name_key(display_name))
                if person_id is None:
                    now = datetime.now().isoformat(timespec="seconds")
                    cursor = self.connection.execute(
                        """INSERT INTO people
                           (name, relationship, contact, group_name, updated_at, managed)
                           VALUES (?, ?, ?, 'Telegram', ?, 1)""",
                        (
                            display_name,
                            "личный контакт из Telegram"
                            if telegram_id in personal_ids
                            else "участник общих Telegram-чатов",
                            f"Telegram ID: {telegram_id}",
                            now,
                        ),
                    )
                    person_id = int(cursor.lastrowid)
                    valid_ids.add(person_id)
                    by_name[name_key(display_name)] = person_id
                    created += 1
                person = self.get_person(person_id)
                if selected_group and selected_group != person.group_name:
                    self.connection.execute(
                        "UPDATE people SET group_name=? WHERE id=?",
                        (selected_group, person_id),
                    )
                identity_map[telegram_id] = {
                    "person_id": person_id,
                    "name": person.name,
                    "messages": int(identity.get("messages", 0)),
                    "chats": identity.get("chats", []),
                    "first_date": identity.get("first_date", ""),
                    "last_date": identity.get("last_date", ""),
                    "last_message_date": identity.get("last_message_date", ""),
                    "personal": telegram_id in personal_ids,
                }

            skipped_chats = [
                chat_id
                for item in scan.get("personal_chats", [])
                if item.get("telegram_id") in skipped_ids
                for chat_id in item.get("chat_ids", [item.get("chat_id", "")])
            ]
            manifest = {
                "path": scan["path"],
                "size": scan["size"],
                "mtime_ns": scan["mtime_ns"],
                "owner_id": scan.get("owner_id", ""),
                "owner_name": scan.get("owner_name", ""),
                "chats": int(scan.get("chats", 0)),
                "messages": int(scan.get("messages", 0)),
                "min_personal_messages": MIN_PERSONAL_MESSAGES,
                "identity_map": identity_map,
                "skipped_ids": sorted(skipped_ids),
                "skipped_chats": skipped_chats,
                "imported_at": datetime.now().isoformat(timespec="seconds"),
            }
            self.connection.execute(
                """INSERT INTO settings(key, value) VALUES ('telegram_import', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (json.dumps(manifest, ensure_ascii=False),),
            )
        if progress:
            progress(total_identities, total_identities, "Импорт Telegram завершён")
        return {"created": created, "linked": len(identity_map), **manifest}

    def reset_knowledge_graph(self, *, detach_telegram: bool = True) -> None:
        """Discard derived graph state while preserving the user's profile and source data."""
        from somniloop.knowledge.pipeline import node_id

        telegram = self.telegram_manifest()
        name, bio = self.get_profile()
        owner_name = name.strip() or "Я"
        owner = KnowledgeNode(
            node_id("people", owner_name),
            owner_name,
            "people",
            bio.strip() or "Биография пока не заполнена.",
            {"is_owner": True},
        )
        with self.connection:
            self._write_knowledge_graph([owner], [])
            self.connection.execute("DELETE FROM knowledge_cache")
            keys = ["graph_input_hash", "external_dossier_import"]
            if detach_telegram:
                keys.append("telegram_import")
            placeholders = ",".join("?" for _ in keys)
            self.connection.execute(
                f"DELETE FROM settings WHERE key IN ({placeholders})",
                keys,
            )
            if detach_telegram and telegram.get("identity_map"):
                detached_map = {
                    telegram_id: {
                        "person_id": item.get("person_id"),
                        "name": item.get("name", ""),
                    }
                    for telegram_id, item in telegram["identity_map"].items()
                    if isinstance(item, dict) and item.get("person_id")
                }
                self.connection.execute(
                    """INSERT INTO settings(key, value)
                       VALUES ('detached_telegram_identity_map', ?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    (json.dumps(detached_map, ensure_ascii=False),),
                )
            self.connection.execute(
                """INSERT INTO settings(key, value) VALUES ('graph_updated_at', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (datetime.now().isoformat(timespec="seconds"),),
            )

    def import_dossier_payload(self, payload: dict, progress=None) -> dict[str, int]:
        """Import externally prepared dossiers and build their graph without invoking an LLM."""
        from somniloop.knowledge.people import format_person_details
        from somniloop.knowledge.pipeline import node_id, source_fingerprint

        def text(value: Any) -> str:
            if isinstance(value, list):
                return "; ".join(str(item).strip() for item in value if str(item).strip())
            return str(value or "").strip()

        def name_key(value: str) -> str:
            words = value.casefold().replace("ё", "е").split()
            return " ".join(sorted(words)) if 2 <= len(words) <= 3 else " ".join(words)

        people_payload = payload.get("people", [])
        total = max(1, len(people_payload))
        existing = self.list_people(managed_only=True)
        by_name = {name_key(person.name): person.id for person in existing}
        valid_ids = {person.id for person in existing}
        telegram_map = self.telegram_manifest().get("identity_map", {})
        try:
            detached_telegram_map = json.loads(
                self.get_setting("detached_telegram_identity_map", "{}")
            )
        except json.JSONDecodeError:
            detached_telegram_map = {}
        telegram_map = {**detached_telegram_map, **telegram_map}
        try:
            previous_import = json.loads(self.get_setting("external_dossier_import", "{}"))
        except json.JSONDecodeError:
            previous_import = {}
        previous_map = previous_import.get("identity_map", {})
        owner_name, owner_bio = self.get_profile()
        owner_name = owner_name.strip() or "Я"
        owner_id = node_id("people", owner_name)
        nodes = [
            KnowledgeNode(
                owner_id,
                owner_name,
                "people",
                owner_bio.strip() or "Биография пока не заполнена.",
                {"is_owner": True},
            )
        ]
        edges: list[KnowledgeEdge] = []
        external_to_person: dict[str, int] = {}
        external_to_node: dict[str, str] = {}
        created = 0
        updated = 0

        if progress:
            progress(25, 100, "Импортирую готовые досье")
        with self.connection:
            for index, item in enumerate(people_payload, start=1):
                external_id = text(item.get("external_id"))
                telegram_ids = [
                    text(value) for value in item.get("telegram_ids", []) if text(value)
                ]
                imported_name = text(item.get("name")) or "Контакт Telegram"
                person_id = previous_map.get(external_id)
                if person_id not in valid_ids:
                    person_id = next(
                        (
                            telegram_map[value].get("person_id")
                            for value in telegram_ids
                            if value in telegram_map
                            and telegram_map[value].get("person_id") in valid_ids
                        ),
                        None,
                    )
                if person_id not in valid_ids:
                    person_id = by_name.get(name_key(imported_name))
                if person_id is None:
                    cursor = self.connection.execute(
                        "INSERT INTO people(name, updated_at, managed) VALUES (?, ?, 1)",
                        (imported_name, datetime.now().isoformat(timespec="seconds")),
                    )
                    person_id = int(cursor.lastrowid)
                    valid_ids.add(person_id)
                    by_name[name_key(imported_name)] = person_id
                    created += 1
                else:
                    updated += 1
                current = self.get_person(person_id)
                current_name_score = (len(current.name.split()), len(current.name))
                imported_name_score = (len(imported_name.split()), len(imported_name))
                final_name = (
                    imported_name if imported_name_score > current_name_score else current.name
                )
                imported_relationship = text(item.get("relationship"))
                relationship = current.relationship
                if not relationship or relationship in {
                    "личный контакт из Telegram",
                    "участник общих Telegram-чатов",
                    "отношение не установлено",
                }:
                    relationship = imported_relationship or relationship
                imported_contact = text(item.get("contact"))
                contact = current.contact or imported_contact
                imported_group = text(item.get("group_name"))
                group_name = current.group_name
                if not group_name or group_name in {"Telegram", "Контакты"}:
                    group_name = imported_group or group_name or "Контакты"
                now = datetime.now().isoformat(timespec="seconds")
                self.connection.execute(
                    """UPDATE people SET name=?, relationship=?, contact=?, group_name=?,
                       updated_at=?, managed=1 WHERE id=?""",
                    (final_name, relationship, contact, group_name, now, person_id),
                )
                facts = [text(value) for value in item.get("facts", []) if text(value)]
                history = [text(value) for value in item.get("history", []) if text(value)]
                conflicts = [text(value) for value in item.get("conflicts", []) if text(value)]
                sources = [
                    {
                        "id": text(source.get("source_id")),
                        "title": text(source.get("chat_name")) or "Telegram",
                        "date": text(source.get("date")),
                        "updated_at": text(source.get("date")),
                        "evidence": text(source.get("excerpt")),
                    }
                    for source in item.get("sources", [])
                    if isinstance(source, dict)
                ]
                analysis = {
                    "relationship": relationship,
                    "biography": text(item.get("biography")),
                    "birth_date": text(item.get("birth_date")),
                    "education": text(item.get("education")),
                    "occupation": text(item.get("occupation")),
                    "interests": text(item.get("interests")),
                    "facts": facts,
                    "history": history,
                    "conflicts": conflicts,
                    "sources": sources,
                }
                self.save_person_analysis(person_id, analysis, commit=False)
                imported_overrides = {
                    key: analysis[key]
                    for key in ("biography", "education", "occupation", "facts")
                    if analysis[key]
                }
                self.connection.execute(
                    "UPDATE people SET manual_overrides_json=? WHERE id=?",
                    (
                        json.dumps(
                            {**imported_overrides, **current.manual_overrides},
                            ensure_ascii=False,
                        ),
                        person_id,
                    ),
                )
                external_to_person[external_id] = person_id
                identifier = node_id("people", f"{final_name}|{external_id}")
                external_to_node[external_id] = identifier
                last_message = text(item.get("last_message_date"))
                details = format_person_details({**analysis, "name": final_name, "updated_at": now})
                if contact:
                    details += f"\nКонтакт: {contact}"
                if group_name:
                    details += f"\nГруппа: {group_name}"
                if last_message:
                    details += f"\nПоследнее сообщение: {last_message}"
                nodes.append(
                    KnowledgeNode(
                        identifier,
                        final_name,
                        "people",
                        details,
                        {
                            "person_id": person_id,
                            "external_id": external_id,
                            "relationship": relationship,
                            "contact": contact,
                            "group": group_name,
                            "last_message_date": last_message,
                            "is_owner": False,
                        },
                    )
                )
                edges.append(KnowledgeEdge(owner_id, identifier, relationship or "знает"))
                if progress:
                    progress(25 + int(index * 55 / total), 100, f"Импортирую: {final_name}")

            if progress:
                progress(82, 100, "Создаю связи и места")
            for connection in payload.get("connections", []):
                source_id = external_to_node.get(text(connection.get("source_external_id")))
                target_id = external_to_node.get(text(connection.get("target_external_id")))
                if source_id and target_id and source_id != target_id:
                    edges.append(
                        KnowledgeEdge(
                            source_id,
                            target_id,
                            text(connection.get("relation")) or "общий чат",
                        )
                    )
            for place in payload.get("places", []):
                place_name = text(place.get("name"))
                if not place_name:
                    continue
                place_external_id = text(place.get("external_id")) or place_name
                place_id = node_id("places", place_external_id)
                nodes.append(
                    KnowledgeNode(
                        place_id,
                        place_name,
                        "places",
                        text(place.get("details")) or "Географическое место из Telegram-досье.",
                        {"external_id": place_external_id},
                    )
                )
                for external_id in place.get("person_external_ids", []):
                    person_node = external_to_node.get(text(external_id))
                    if person_node:
                        edges.append(KnowledgeEdge(person_node, place_id, "связан с местом"))

            unique_nodes = {node.id: node for node in nodes}
            unique_edges = {(edge.source, edge.target, edge.relation): edge for edge in edges}
            self._write_knowledge_graph(list(unique_nodes.values()), list(unique_edges.values()))
            self.connection.execute("DELETE FROM knowledge_cache")
            self.connection.execute(
                "DELETE FROM settings WHERE key IN ('telegram_import', 'detached_telegram_identity_map')"
            )
            imported_at = datetime.now().isoformat(timespec="seconds")
            import_manifest = {
                "schema_version": payload.get("schema_version"),
                "generated_at": payload.get("generated_at", ""),
                "imported_at": imported_at,
                "source": payload.get("source", {}),
                "identity_map": external_to_person,
                "people": len(external_to_person),
                "connections": len(payload.get("connections", [])),
                "places": len(payload.get("places", [])),
            }
            self.connection.execute(
                """INSERT INTO settings(key, value) VALUES ('external_dossier_import', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (json.dumps(import_manifest, ensure_ascii=False),),
            )
            self.connection.executemany(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                [
                    ("graph_updated_at", imported_at),
                    ("graph_input_hash", source_fingerprint(self.knowledge_source())),
                ],
            )
        self.sync_birthday_notifications()
        if progress:
            progress(100, 100, "Готовые досье импортированы")
        return {
            "created": created,
            "updated": updated,
            "people": len(external_to_person),
            "connections": len(payload.get("connections", [])),
            "places": len(payload.get("places", [])),
        }

    def replace_knowledge_graph(
        self, nodes: list[KnowledgeNode], edges: list[KnowledgeEdge]
    ) -> None:
        with self.connection:
            self._write_knowledge_graph(nodes, edges)

    def _write_knowledge_graph(
        self, nodes: list[KnowledgeNode], edges: list[KnowledgeEdge]
    ) -> None:
        self.connection.execute("DELETE FROM knowledge_edges")
        self.connection.execute("DELETE FROM knowledge_nodes")
        self.connection.executemany(
            "INSERT INTO knowledge_nodes(node_id, label, category, details, metadata_json) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    node.id,
                    node.label,
                    node.category,
                    node.details,
                    json.dumps(node.metadata, ensure_ascii=False),
                )
                for node in nodes
            ],
        )
        valid = {node.id for node in nodes}
        self.connection.executemany(
            "INSERT OR IGNORE INTO knowledge_edges(source_id, target_id, relation) VALUES (?, ?, ?)",
            [
                (edge.source, edge.target, edge.relation)
                for edge in edges
                if edge.source in valid and edge.target in valid
            ],
        )

    def load_knowledge_graph(self) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
        nodes = [
            KnowledgeNode(row[0], row[1], row[2], row[3], json.loads(row[4]))
            for row in self.connection.execute(
                "SELECT node_id, label, category, details, metadata_json FROM knowledge_nodes"
            )
        ]
        edges = [
            KnowledgeEdge(row[0], row[1], row[2])
            for row in self.connection.execute(
                "SELECT source_id, target_id, relation FROM knowledge_edges"
            )
        ]
        return nodes, edges

    def knowledge_source(self) -> dict[str, Any]:
        name, bio = self.get_profile()
        trackers = []
        for tracker in self.list_trackers():
            trackers.append(
                {
                    "name": tracker.name,
                    "description": tracker.description,
                    "mode": tracker.mode.value,
                    "schedule": tracker.schedule_type.value,
                    "tasks": [task.name for task in self.list_tasks(tracker.id)],
                }
            )
        telegram = self.telegram_manifest()
        if telegram:
            try:
                stat = Path(telegram["path"]).stat()
                telegram = {
                    **telegram,
                    "current_size": stat.st_size,
                    "current_mtime_ns": stat.st_mtime_ns,
                }
            except (KeyError, OSError):
                telegram = {**telegram, "unavailable": True}
        return {
            "profile": {
                "name": name,
                "bio": bio,
                "updated_at": self.get_setting("profile_updated_at"),
            },
            "notes": [
                {
                    "id": n.id,
                    "entry_date": n.entry_date,
                    "updated_at": n.updated_at,
                    "title": n.title,
                    "content": n.content,
                }
                for n in self.list_notes()
            ],
            "people": [
                {
                    "id": person.id,
                    "name": person.name,
                    "relationship": person.relationship,
                    "raw_notes": person.raw_notes,
                    "birth_date": person.birth_date_input,
                    "birth_date_input": person.birth_date_input,
                    "interests_input": person.interests_input,
                    "interests": person.interests_input,
                    "contact": person.contact,
                    "group_name": person.group_name,
                    "clarifications": person.clarifications,
                    "manual_overrides": person.manual_overrides,
                    "updated_at": person.updated_at,
                    "managed": person.managed,
                    "revisions": [
                        {**json.loads(row["content_json"]), "recorded_at": row["recorded_at"]}
                        for row in self.connection.execute(
                            "SELECT content_json, recorded_at FROM person_revisions WHERE person_id=? ORDER BY recorded_at, id",
                            (person.id,),
                        )
                    ],
                }
                for person in self.list_people(managed_only=True)
            ],
            "trackers": trackers,
            "telegram": telegram,
        }

    def load_knowledge_cache(self) -> dict[str, dict]:
        return {
            row[0]: json.loads(row[1])
            for row in self.connection.execute(
                "SELECT cache_key, payload_json FROM knowledge_cache"
            )
        }

    def save_knowledge_cache(self, key: str, payload: dict) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO knowledge_cache(cache_key, payload_json) VALUES (?, ?)",
            (key, json.dumps(payload, ensure_ascii=False)),
        )
        self.connection.commit()

    def apply_knowledge_result(self, result) -> bool:
        from somniloop.knowledge.pipeline import source_fingerprint

        if source_fingerprint(self.knowledge_source()) != result.input_hash:
            return False
        by_name = {
            person.name.casefold().replace("ё", "е"): person.id for person in self.list_people()
        }
        with self.connection:
            for summary in result.people:
                key = summary["name"].casefold().replace("ё", "е")
                person_id = summary.get("id") or by_name.get(key)
                if person_id is None:
                    cursor = self.connection.execute(
                        "INSERT INTO people(name, relationship, updated_at, managed) VALUES (?, ?, ?, 0)",
                        (
                            summary["name"],
                            summary.get("relationship", ""),
                            summary.get("updated_at") or result.built_at,
                        ),
                    )
                    person_id = int(cursor.lastrowid)
                    by_name[key] = person_id
                self.save_person_analysis(person_id, summary, commit=False)
                for node in result.nodes:
                    if node.category == "people" and node.label == summary["name"]:
                        node.metadata["person_id"] = person_id
            self._write_knowledge_graph(result.nodes, result.edges)
            self.connection.executemany(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                [
                    ("graph_updated_at", result.built_at),
                    (
                        "graph_connections_report",
                        json.dumps(
                            {
                                "done": result.stats.get("connections_done", 0),
                                "total": result.stats.get("connections_total", 0),
                                "failures": result.stats.get("connection_failures", []),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                    ("graph_input_hash", source_fingerprint(self.knowledge_source())),
                ],
            )
        self.sync_birthday_notifications()
        return True

    def export_payload(self) -> dict[str, Any]:
        tables = (
            "trackers",
            "tasks",
            "task_entries",
            "manual_dates",
            "notes",
            "profile",
            "people",
            "knowledge_nodes",
            "knowledge_edges",
            "settings",
            "person_revisions",
            "planner_tasks",
            "planner_items",
            "birthday_notifications",
        )
        return {
            "format": "SomniLoop export",
            "version": 3,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "tables": {
                table: [dict(row) for row in self.connection.execute(f"SELECT * FROM {table}")]
                for table in tables
            },
        }

    def restore_payload(self, payload: dict[str, Any]) -> Path:
        if payload.get("format") != "SomniLoop export" or payload.get("version") != 3:
            raise ValueError("Файл не является совместимым экспортом SomniLoop 0.3.")
        data = payload.get("tables")
        if not isinstance(data, dict):
            raise ValueError("В экспорте отсутствуют таблицы данных.")

        tables = (
            "trackers",
            "tasks",
            "task_entries",
            "manual_dates",
            "notes",
            "profile",
            "people",
            "knowledge_nodes",
            "knowledge_edges",
            "settings",
            "person_revisions",
            "planner_tasks",
            "planner_items",
            "birthday_notifications",
        )
        if any(table not in data or not isinstance(data[table], list) for table in tables):
            raise ValueError("Экспорт неполный или повреждён.")

        known_columns = {
            table: {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            for table in tables
        }
        for table in tables:
            for row in data[table]:
                if not isinstance(row, dict) or not row.keys() <= known_columns[table]:
                    raise ValueError(f"Некорректные данные таблицы {table}.")

        backup = self.backup(label="before-import")
        delete_order = (
            "birthday_notifications",
            "planner_items",
            "person_revisions",
            "knowledge_edges",
            "task_entries",
            "manual_dates",
            "tasks",
            "planner_tasks",
            "knowledge_nodes",
            "people",
            "trackers",
            "notes",
            "settings",
            "profile",
        )
        with self.connection:
            for table in delete_order:
                self.connection.execute(f"DELETE FROM {table}")
            for table in tables:
                for row in data[table]:
                    columns = list(row)
                    placeholders = ", ".join("?" for _ in columns)
                    self.connection.execute(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                        [row[column] for column in columns],
                    )
            self.connection.execute(
                "INSERT OR IGNORE INTO profile(id, display_name, bio) VALUES (1, '', '')"
            )
        self._read_cache.clear()
        self._cache_generation = self.connection.total_changes
        return backup

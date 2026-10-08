"""Additive project, daily-intention and inbox storage over existing tasks."""

import re
from datetime import date, datetime

from .project_colors import distinct_project_color

WORKSPACE_TABLES = ("work_projects", "work_items", "work_inbox")
SCHEMA = """
CREATE TABLE IF NOT EXISTS work_projects (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS work_items (
    kind TEXT NOT NULL CHECK(kind IN ('planner','tracker')), item_id INTEGER NOT NULL,
    project_id INTEGER REFERENCES work_projects(id) ON DELETE SET NULL,
    priority INTEGER NOT NULL DEFAULT 0 CHECK(priority BETWEEN 0 AND 2),
    planned_on TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(kind, item_id)
);
CREATE TABLE IF NOT EXISTS work_inbox (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS work_by_project ON work_items(project_id);
CREATE TRIGGER IF NOT EXISTS work_planner_deleted AFTER DELETE ON planner_tasks BEGIN
    DELETE FROM work_items WHERE kind='planner' AND item_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS work_tracker_deleted AFTER DELETE ON trackers BEGIN
    DELETE FROM work_items WHERE kind='tracker' AND item_id=OLD.id;
END;
"""


class ProductivityRepository:
    def update_task_fields(self, identifiers, **fields):
        """Apply small edits atomically without rebuilding checklist items."""
        allowed = {"title", "due_date", "due_time", "archived"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Invalid task fields")
        if "title" in fields:
            fields["title"] = fields["title"].strip()
            if not fields["title"]:
                raise ValueError("A task needs a title")
        if fields.get("due_date"):
            date.fromisoformat(fields["due_date"])
        if fields.get("due_time") and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", fields["due_time"]):
            raise ValueError("Invalid time")
        if fields.get("due_date") == "":
            fields["due_time"] = ""
        fields["updated_at"] = datetime.now().isoformat(timespec="microseconds")
        assignments = ",".join(f"{name}=?" for name in fields)
        with self.connection:
            self.connection.executemany(f"UPDATE planner_tasks SET {assignments} WHERE id=?",
                                        [(*fields.values(), identifier) for identifier in identifiers])
        if fields.get("archived"):
            self.activity.emit("archived")

    def assign_tasks(self, identifiers, project_id):
        with self.connection:
            self.connection.executemany(
                "INSERT INTO work_items(kind,item_id,project_id) VALUES ('planner',?,?) "
                "ON CONFLICT(kind,item_id) DO UPDATE SET project_id=excluded.project_id",
                [(identifier, project_id) for identifier in identifiers],
            )

    def completion_snapshot(self, task_id):
        task = self.connection.execute("SELECT * FROM planner_tasks WHERE id=?", (task_id,)).fetchone()
        return (dict(task), [dict(item) for item in self.connection.execute(
            "SELECT * FROM planner_items WHERE planner_id=? ORDER BY id", (task_id,))])

    def restore_completion(self, before, expected):
        """Undo only if no subsequent edit has changed the completed task."""
        task, items = before
        current = self.connection.execute("SELECT * FROM planner_tasks WHERE id=?", (task["id"],)).fetchone()
        if current is None or self.completion_snapshot(task["id"]) != expected:
            return False
        with self.connection:
            self.connection.execute(
                "UPDATE planner_tasks SET completed=?,archived=?,state=?,updated_at=? WHERE id=?",
                (task["completed"], task["archived"], task["state"], task["updated_at"], task["id"]),
            )
            self.connection.executemany("UPDATE planner_items SET done=?,state=? WHERE id=?",
                                        [(item["done"], item["state"], item["id"]) for item in items])
        return True

    def next_project_color(self):
        return distinct_project_color(p["color"] for p in self.work_projects(True))

    def migrate_work_projects(self):
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(work_projects)")}
        for name, definition in (("color", "TEXT NOT NULL DEFAULT '#3778bd'"),
                                 ("sort_order", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE work_projects ADD COLUMN {name} {definition}")

    def work_projects(self, include_archived=False):
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM work_projects WHERE archived=0 OR ? ORDER BY sort_order, name COLLATE NOCASE, id",
            (int(include_archived),),
        )]

    def save_work_project(self, name, outcome="", project_id=None, *, color=None):
        if not name.strip():
            raise ValueError("A project needs a name")
        if color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Invalid project color")
        with self.connection:
            if project_id is None:
                return self.connection.execute(
                    "INSERT INTO work_projects(name,outcome,color,sort_order) VALUES (?,?,?,"
                    "(SELECT COALESCE(MAX(sort_order),-1)+1 FROM work_projects))",
                    (name.strip(), outcome.strip(), color or self.next_project_color())
                ).lastrowid
            self.connection.execute("UPDATE work_projects SET name=?,outcome=? WHERE id=?",
                                    (name.strip(), outcome.strip(), project_id))
            if color is not None:
                self.connection.execute("UPDATE work_projects SET color=? WHERE id=?", (color, project_id))
        return project_id

    def reorder_work_projects(self, identifiers):
        existing = {p["id"] for p in self.work_projects(True)}
        if len(identifiers) != len(existing) or set(identifiers) != existing:
            raise ValueError("Project order must contain every project exactly once")
        with self.connection:
            self.connection.executemany("UPDATE work_projects SET sort_order=? WHERE id=?",
                                        enumerate(identifiers))

    def archive_work_project(self, project_id, archived=True):
        # Project archiving never archives or deletes its tasks.
        with self.connection:
            self.connection.execute("UPDATE work_projects SET archived=? WHERE id=?",
                                    (int(archived), project_id))

    def delete_work_project(self, project_id):
        # Remove only the grouping; tasks, history and other metadata survive.
        with self.connection:
            self.connection.execute("UPDATE work_items SET project_id=NULL WHERE project_id=?", (project_id,))
            self.connection.execute("DELETE FROM work_projects WHERE id=?", (project_id,))

    def work_metadata(self):
        return {(row["kind"], row["item_id"]): dict(row)
                for row in self.connection.execute("SELECT * FROM work_items")}

    def save_work_item(self, kind, item_id, *, project_id=None, priority=0,
                       planned_on="", next_action=""):
        if kind not in ("planner", "tracker") or priority not in (0, 1, 2):
            raise ValueError("Invalid work item")
        if planned_on:
            date.fromisoformat(planned_on)
        table = "planner_tasks" if kind == "planner" else "trackers"
        if not self.connection.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone():
            raise ValueError("Work item no longer exists")
        if project_id is not None and not self.connection.execute(
            "SELECT 1 FROM work_projects WHERE id=?", (project_id,)
        ).fetchone():
            raise ValueError("Project no longer exists")
        with self.connection:
            self.connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?) ON CONFLICT(kind,item_id) DO UPDATE SET "
                "project_id=excluded.project_id,priority=excluded.priority,"
                "planned_on=excluded.planned_on,next_action=excluded.next_action",
                (kind, item_id, project_id, priority, planned_on, next_action.strip()),
            )

    def capture_work(self, title):
        if not title.strip():
            raise ValueError("A task needs a title")
        with self.connection:
            return self.connection.execute(
                "INSERT INTO work_inbox(title,created_at) VALUES (?,?)",
                (title.strip(), datetime.now().isoformat(timespec="seconds")),
            ).lastrowid

    def work_inbox(self):
        return [dict(row) for row in self.connection.execute("SELECT * FROM work_inbox ORDER BY id")]

    def schedule_capture(self, capture_id, day, project_id=None, priority=0):
        date.fromisoformat(day.isoformat())
        if priority not in (0, 1, 2):
            raise ValueError("Invalid priority")
        if project_id is not None and not self.connection.execute(
            "SELECT 1 FROM work_projects WHERE id=?", (project_id,),
        ).fetchone():
            raise ValueError("Project no longer exists")
        with self.connection:
            row = self.connection.execute("SELECT title FROM work_inbox WHERE id=?", (capture_id,)).fetchone()
            if row is None:
                raise ValueError("Capture no longer exists")
            item_id = self.connection.execute(
                "INSERT INTO planner_tasks(title,due_date,updated_at) VALUES (?,?,?)",
                (row[0], day.isoformat(), datetime.now().isoformat(timespec="seconds")),
            ).lastrowid
            self.connection.execute("INSERT INTO work_items(kind,item_id,project_id,priority) VALUES ('planner',?,?,?)",
                                    (item_id, project_id, priority))
            self.connection.execute("DELETE FROM work_inbox WHERE id=?", (capture_id,))
        self.activity.emit("created")
        return item_id

from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import date, datetime

from .dates import age_on, birthday_in_year, display_date, one_month_before
from .models import PlannerTask, TaskState


class PlanningRepository:
    """Planner and reminder queries share the application's SQLite connection."""

    def save_planner_task(
        self,
        title: str,
        due_date: date,
        description: str = "",
        items: list[str] | None = None,
        task_id: int | None = None,
        due_time: str | None = None,
    ) -> int:
        if not title.strip():
            raise ValueError("A task needs a title")
        # None preserves an existing time for older callers; an empty string clears it.
        if due_time is not None and due_time != "" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", due_time):
            raise ValueError("Time must use HH:mm format")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            if task_id is None:
                cursor = self.connection.execute(
                    "INSERT INTO planner_tasks(title, due_date, description, updated_at, due_time) VALUES (?, ?, ?, ?, ?)",
                    (title.strip(), due_date.isoformat(), description.strip(), now, due_time or ""),
                )
                task_id = int(cursor.lastrowid)
            else:
                self.connection.execute(
                    "UPDATE planner_tasks SET title=?, due_date=?, description=?, updated_at=?, due_time=COALESCE(?, due_time) WHERE id=?",
                    (title.strip(), due_date.isoformat(), description.strip(), now, due_time, task_id),
                )
            if items is not None:
                previous = defaultdict(deque)
                for row in self.connection.execute(
                    "SELECT title, done, state FROM planner_items WHERE planner_id=? ORDER BY id",
                    (task_id,),
                ):
                    previous[row["title"]].append((row["done"], row["state"]))
                self.connection.execute("DELETE FROM planner_items WHERE planner_id=?", (task_id,))
                for item_title in items:
                    item_title = item_title.strip()
                    if item_title:
                        done, state = (
                            previous[item_title].popleft() if previous[item_title] else (0, "unset")
                        )
                        self.connection.execute(
                            "INSERT INTO planner_items(planner_id, title, done, state) VALUES (?, ?, ?, ?)",
                            (task_id, item_title, done, state),
                        )
        return task_id

    def list_planner_tasks(
        self, archived: bool = False, completed_on: date | None = None
    ) -> list[PlannerTask]:
        condition = "p.archived=?"
        parameters = [int(archived)]
        if completed_on:
            condition += " AND p.completed=1 AND substr(p.updated_at,1,10)=?"
            parameters.append(completed_on.isoformat())
        grouped = defaultdict(list)
        for row in self.connection.execute(
            f"SELECT i.* FROM planner_items i JOIN planner_tasks p ON p.id=i.planner_id WHERE {condition} ORDER BY i.id",
            parameters,
        ):
            grouped[row["planner_id"]].append(dict(row))
        return [
            PlannerTask(
                id=row["id"],
                title=row["title"],
                due_date=row["due_date"],
                description=row["description"],
                completed=bool(row["completed"]),
                archived=bool(row["archived"]),
                updated_at=row["updated_at"],
                items=grouped[row["id"]],
                state=TaskState.DONE if row["completed"] else TaskState(row["state"]),
                due_time=row["due_time"],
            )
            for row in self.connection.execute(
                f"SELECT p.* FROM planner_tasks p WHERE {condition} ORDER BY due_date, COALESCE(NULLIF(due_time,''),'24:00'), id",
                parameters,
            )
        ]

    def set_planner_item_done(self, item_id: int, done: bool) -> None:
        self.set_planner_item_state(item_id, TaskState.DONE if done else TaskState.UNSET)

    def set_planner_item_state(self, item_id: int, state: TaskState) -> None:
        row = self.connection.execute(
            "SELECT planner_id FROM planner_items WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            return
        task_id = row[0]
        with self.connection:
            self.connection.execute(
                "UPDATE planner_items SET done=?, state=? WHERE id=?",
                (int(state == TaskState.DONE), state.value, item_id),
            )
            remaining = self.connection.execute(
                "SELECT COUNT(*) FROM planner_items WHERE planner_id=? AND done=0", (task_id,)
            ).fetchone()[0]
            self.connection.execute(
                "UPDATE planner_tasks SET completed=?, archived=?, updated_at=?, state=? WHERE id=?",
                (
                    int(not remaining),
                    int(not remaining),
                    datetime.now().isoformat(timespec="seconds"),
                    "done"
                    if not remaining
                    else "partial"
                    if self.connection.execute(
                        "SELECT 1 FROM planner_items WHERE planner_id=? AND (done=1 OR state='partial') LIMIT 1",
                        (task_id,),
                    ).fetchone()
                    else "unset",
                    task_id,
                ),
            )

    def complete_planner_task(self, task_id: int) -> None:
        self.set_planner_task_state(task_id, TaskState.DONE)

    def set_planner_task_state(self, task_id: int, state: TaskState) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE planner_items SET done=?, state=? WHERE planner_id=?",
                (int(state == TaskState.DONE), state.value, task_id),
            )
            self.connection.execute(
                "UPDATE planner_tasks SET completed=?, archived=?, state=?, updated_at=? WHERE id=?",
                (
                    int(state == TaskState.DONE),
                    int(state == TaskState.DONE),
                    state.value,
                    datetime.now().isoformat(timespec="seconds"),
                    task_id,
                ),
            )

    def archive_planner_task(self, task_id: int, archived: bool = True) -> None:
        with self.connection:
            if archived:
                self.connection.execute(
                    "UPDATE planner_tasks SET archived=1 WHERE id=?", (task_id,)
                )
            else:
                self.connection.execute(
                    "UPDATE planner_tasks SET archived=0, completed=0, state='unset' WHERE id=?",
                    (task_id,),
                )
                self.connection.execute(
                    "UPDATE planner_items SET done=0, state='unset' WHERE planner_id=?", (task_id,)
                )

    def sync_birthday_notifications(self, today: date | None = None) -> None:
        from somniloop.knowledge.people import has_birth_conflict

        today = today or date.today()
        with self.connection:
            for person in self.list_people():
                birth_conflict = has_birth_conflict({"conflicts": person.conflicts})
                # A corrected birthday must not leave an obsolete future reminder.
                for reminder in self.connection.execute(
                    "SELECT id, birthday FROM birthday_notifications WHERE person_id=? AND dismissed=0 AND birthday>=?",
                    (person.id, today.isoformat()),
                ).fetchall():
                    due = date.fromisoformat(reminder["birthday"])
                    if birth_conflict or birthday_in_year(person.birth_date, due.year) != due:
                        self.connection.execute(
                            "UPDATE birthday_notifications SET dismissed=1 WHERE id=?",
                            (reminder["id"],),
                        )
                if birth_conflict:
                    continue
                for year in (today.year, today.year + 1):
                    birthday = birthday_in_year(person.birth_date, year)
                    if birthday is None or not one_month_before(birthday) <= today <= birthday:
                        continue
                    age = age_on(person.birth_date, birthday)
                    suffix = f" · исполняется {age}" if age is not None else ""
                    title = f"{person.name} · {display_date(birthday)}{suffix}"
                    self.connection.execute(
                        """INSERT INTO birthday_notifications(person_id, birthday, title) VALUES (?, ?, ?)
                           ON CONFLICT(person_id, birthday) DO UPDATE SET title=excluded.title
                           WHERE title<>excluded.title""",
                        (person.id, birthday.isoformat(), title),
                    )

    def list_notifications(self) -> list[dict]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM birthday_notifications WHERE dismissed=0 ORDER BY birthday, id"
            )
        ]

    def dismiss_notification(self, notification_id: int) -> None:
        self.connection.execute(
            "UPDATE birthday_notifications SET dismissed=1 WHERE id=?", (notification_id,)
        )
        self.connection.commit()

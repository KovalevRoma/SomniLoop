"""Local, rate-limited feedback; no repository writes or LLM calls."""

import logging
import time
from datetime import date

from PySide6.QtCore import QLocale, QObject, QTimer, Signal

from somniloop.core.models import TaskState

logger = logging.getLogger(__name__)


class CompletionMonitor:
    """Observe snapshots, using cached summaries for disappearing overdue plans."""

    def __init__(self):
        self.day = None
        self.previous = {}
        self.celebrated = set()
        self.invalidated = False

    def observe(self, data):
        states, due = {}, set()
        for record in data.trackers.values():
            for day, items in record.occurrences:
                for item in items:
                    key = ("tracker", record.tracker.id, day, item.task.id)
                    states[key] = item.state == TaskState.DONE
                    if day <= data.today:
                        due.add(key)
        for task in [*data.planner, *data.completed]:
            items = [(item["id"], item["done"]) for item in task.items] or [
                (0, task.state == TaskState.DONE)
            ]
            for identifier, done in items:
                key = ("planner", task.id, identifier)
                states[key] = bool(done)
                if task.due_date and date.fromisoformat(task.due_date) <= data.today:
                    due.add(key)
        # Completed overdue plans leave the pending snapshot immediately. Verify
        # their cached day summary instead of treating disappearance as completion.
        if self.day == data.today and hasattr(data, "repository"):
            missing_days = {
                (key[1], key[2]) for key in self.previous
                if key[0] == "tracker" and key not in states
                and key[1] in data.trackers and key[2] < data.today
            }
            for identifier, day in missing_days:
                record = data.trackers[identifier]
                for item in data.repository.day_summary(record.tracker, day).tasks:
                    key = ("tracker", identifier, day, item.task.id)
                    states[key] = item.state == TaskState.DONE
                    due.add(key)
        self.invalidated = self.day != data.today or any(
            done and not states.get(key, False) for key, done in self.previous.items()
        )
        if self.day != data.today:
            self.day, self.previous, self.celebrated = data.today, states, set()
            return None
        newly_done = {
            key for key, done in states.items()
            if done and self.previous.get(key) is False and key not in self.celebrated
        }
        self.previous = states
        self.celebrated.update(newly_done)
        if not newly_done:
            return None
        return bool(newly_done & due) and bool(due) and all(states[key] for key in due)


class ReactionController(QObject):
    requested = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_reaction = float("-inf")
        self.last_all_done = False
        self.all_done = False
        self.pending = QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.setInterval(900)
        self.pending.timeout.connect(self.flush)

    def submit(self, all_done=False):
        # Coalesce a burst and drop cooldown events rather than queueing old praise.
        if time.monotonic() - self.last_reaction < 15 and not (
            all_done and not self.last_all_done
        ):
            return
        self.all_done |= all_done
        if not self.pending.isActive():
            self.pending.start()

    def flush(self):
        self.pending.stop()
        all_done, self.all_done = self.all_done, False
        self.last_reaction = time.monotonic()
        self.last_all_done = all_done
        self.requested.emit(all_done)

    def cancel(self):
        self.pending.stop()
        self.all_done = False


class LocalSpeech(QObject):
    """Load optional Qt speech bindings lazily and use only local system engines."""

    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = None

    def say(self, text, language):
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech

            if self.engine is None:
                available = QTextToSpeech.availableEngines()
                name = next((n for n in ("speechd", "flite", "darwin", "sapi") if n in available), None)
                if name is None:
                    raise RuntimeError("No local speech engine is installed")
                self.engine = QTextToSpeech(name, self)
                self.engine.errorOccurred.connect(self._error)
                self.engine.setVolume(0.55)
                self.engine.setRate(-0.05)
            self.engine.setLocale(QLocale("ru_RU" if language == "ru" else "en_GB"))
            if self.engine.state() == QTextToSpeech.State.Error:
                raise RuntimeError(self.engine.errorString())
            self.engine.say(text)
        except (ImportError, RuntimeError, OSError) as error:
            self._error(None, str(error))

    def _error(self, reason, message):
        logger.warning("Character voice unavailable: %s", message)
        self.failed.emit(message)

    def stop(self):
        if self.engine is not None:
            self.engine.stop()

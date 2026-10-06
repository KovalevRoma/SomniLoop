"""Transient post-commit notifications; independent of Qt and persisted data."""

import logging


class ActivityEvents:
    def __init__(self):
        self.listeners = []

    def subscribe(self, callback):
        self.listeners.append(callback)

        def unsubscribe():
            if callback in self.listeners:
                self.listeners.remove(callback)

        return unsubscribe

    def emit(self, event):
        for callback in tuple(self.listeners):
            try:
                callback(event)
            except Exception:
                # Optional UI feedback must never turn a successful save into an error.
                logging.getLogger(__name__).exception("Activity listener failed")

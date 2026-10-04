"""Deterministic touch rules and geometry-relative hit zones for Epsilon."""

import math


class TouchState:
    quiet_seconds = 60.0

    def __init__(self):
        self.last_touch = None
        self.last_action = None
        self.repetitions = 0
        self.emotion = "Normal"

    def react(self, zone, stroke, now):
        if zone is None:
            return None
        quiet = self.last_touch is None or now - self.last_touch >= self.quiet_seconds
        action = (zone, stroke)
        self.repetitions = (
            self.repetitions + 1 if not quiet and action == self.last_action else 1
        )
        self.last_action, self.last_touch = action, now
        if self.repetitions > 4:
            emotion = "Angry"
        elif zone in ("chest", "hips", "legs"):
            emotion = "Blushing" if self.emotion == "Smile" and zone != "legs" else "Angry"
        elif stroke and zone in ("head", "cheek"):
            emotion = "Smile"
        elif quiet:
            emotion = "Surprised"
        else:
            return None
        self.emotion = emotion
        return emotion


class StrokeGesture:
    """One press/drag/release is one gesture, independent of mouse event frequency."""

    def __init__(self):
        self.cancel()

    def cancel(self):
        self.zone = None
        self.point = None
        self.distance = 0.0

    def begin(self, zone, x, y):
        self.zone, self.point, self.distance = zone, (x, y), 0.0

    def move(self, zone, x, y):
        if self.point is None:
            return
        if zone != self.zone:
            self.cancel()
            return
        self.distance += math.hypot(x - self.point[0], y - self.point[1])
        self.point = (x, y)

    def finish(self, zone, x, y, threshold):
        self.move(zone, x, y)
        result = (self.zone, self.distance >= threshold)
        self.cancel()
        return result


def hit_zone(x, y, parts):
    """Use deformed part bounds in normalized viewport coordinates, not fixed pixels."""
    def inside(bounds, left=0, top=0, right=1, bottom=1):
        if not bounds:
            return False
        x0, y0, x1, y1 = bounds
        return (x0 + (x1 - x0) * left <= x <= x0 + (x1 - x0) * right
                and y0 + (y1 - y0) * top <= y <= y0 + (y1 - y0) * bottom)

    face = parts.get("face")
    cheeks = parts.get("cheeks")
    if inside(cheeks, 0, 0, 0.36, 1) or inside(cheeks, 0.64, 0, 1, 1):
        return "cheek"
    if (inside(parts.get("hair")) or inside(parts.get("hair_back"), 0, 0, 1, 0.20)
            or inside(face, 0, 0, 1, 0.48)):
        return "head"
    if inside(parts.get("body"), 0.15, 0.05, 0.85, 0.35):
        return "chest"
    if inside(parts.get("body"), 0.05, 0.72, 0.95, 1):
        return "hips"
    if inside(parts.get("legs")):
        return "legs"
    return "other"


PART_IDS = {
    "face": "PARTS_01_FACE_001",
    "cheeks": "PARTS_01_HOHO",
    "hair": "PARTS_01_HAIR_FRONT_002",
    "hair_back": "PARTS_01_HAIR_BACK_002",
    "body": "PARTS_01_CLOTHES",
    "legs": "PARTS_01_FOOT",
}

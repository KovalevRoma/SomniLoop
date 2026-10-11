"""Choreography for the bundled 150 BPM track, measured offline."""

import math
import random
from dataclasses import dataclass

BEAT_SECONDS = 0.4
DROP_SECONDS = 3.47
TRAVEL_SECONDS = 9.87
OUTRO_SECONDS = 29.07


def _travel_points():
    rng = random.Random(150)
    points = [(0.0, 0.0)]
    for _ in range(128):
        while True:
            target = (rng.uniform(-.88, .88), rng.uniform(-.88, .88))
            if math.dist(target, points[-1]) > .8:
                points.append(target)
                break
    return tuple(points)


_TRAVEL_POINTS = _travel_points()


def travel_position(seconds):
    if seconds < TRAVEL_SECONDS:
        return 0.0, 0.0
    beat = (seconds - TRAVEL_SECONDS) / BEAT_SECONDS
    index = min(math.floor(beat), len(_TRAVEL_POINTS) - 2)
    phase = beat % 1
    duration = .09 if index % 4 == 0 else .14
    progress = min(1, phase * BEAT_SECONDS / duration)
    ease = 1 - (1 - progress) ** 3
    before, after = _TRAVEL_POINTS[index:index + 2]
    return tuple(a + (b - a) * ease for a, b in zip(before, after))


@dataclass(frozen=True)
class CatPose:
    x: float
    y: float
    angle: float
    scale: float
    opacity: float
    yaw: float = 0.0
    pitch: float = 0.0


def cat_pose(seconds: float) -> CatPose:
    seconds = max(0.0, seconds)
    beat = max(0.0, (seconds - DROP_SECONDS) / BEAT_SECONDS)
    phase = beat % 1
    if seconds < DROP_SECONDS:
        intro_turn = max(0, min(1, (seconds - 1.6) / 1.2))
        yaw = 720 * intro_turn
        return CatPose(0, 0, 15 * math.sin(math.radians(yaw)), 1, 1,
                       yaw, 35 * math.sin(math.radians(yaw)))

    # Keep the reference spin phrases independent of beat-triggered travel.
    phrase = beat % 8
    direction = 1 if int(beat // 8) % 2 == 0 else -1
    if phrase < 2:
        turns = 0.0
    elif phrase < 4:
        turns = phrase - 2
    elif phrase < 5:
        turns = 2.0
    else:
        turns = 2 + (phrase - 5) * 2
    yaw = turns * 360 * direction
    orbit = math.radians(yaw)
    travel = min(1, max(0, (seconds - TRAVEL_SECONDS) / 1.6))
    tx, ty = travel_position(seconds)
    x = tx + .08 * travel * math.sin(orbit / 2)
    kick = math.sin(math.pi * min(1, phase / .55)) ** 2
    y = ty - .06 * abs(math.sin(orbit)) - .035 * kick
    angle = 20 * math.sin(orbit)
    pitch = 55 * math.sin(orbit)
    scale = 1 + 0.07 * kick
    pulse = (1 - math.cos(math.tau * (seconds - DROP_SECONDS) / 0.8)) / 2
    opacity = 1 - 0.20 * pulse
    if seconds >= OUTRO_SECONDS:
        blend = min(1.0, (seconds - OUTRO_SECONDS) / 0.8)
        x *= 1 - 0.55 * blend
        y *= 1 - 0.55 * blend
        # Half-time, low-contrast breathing; never a visibility toggle.
        pulse = (1 - math.cos(math.tau * (seconds - OUTRO_SECONDS) / 0.8)) / 2
        opacity = (1 - blend) * opacity + blend * (1 - 0.28 * pulse)
    return CatPose(x, y, angle, scale, opacity, yaw, pitch)


def projected_scale(pose):
    """Suggest depth without letting a single-photo cutout vanish edge-on."""
    facing = math.cos(math.radians(pose.yaw))
    width = math.copysign(.38 + .62 * abs(facing), facing)
    height = .55 + .45 * math.cos(math.radians(pose.pitch))
    return width, height


def light_motes(seconds):
    """Bounded local glows, with staggered smooth envelopes rather than flashes."""
    for slot in range(56):
        lifetime = 1.8 + (slot % 8) * 0.2
        elapsed = seconds - slot * 0.037
        if elapsed < 0:
            continue
        cycle = math.floor(elapsed / lifetime)
        phase = elapsed / lifetime - cycle
        seed = (slot + 1) * 73856093 ^ (cycle + 1) * 19349663
        x = ((seed * 16807) % 65521) / 65521
        y = ((seed * 48271) % 65519) / 65519
        opacity = 0.48 * math.sin(math.pi * phase) ** 2
        yield x, y, (slot + cycle) % 8, 18 + seed % 35, opacity

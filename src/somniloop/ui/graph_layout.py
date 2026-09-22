"""Deterministic, collision-aware force layout with spatially indexed repulsion."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Body:
    x: float
    y: float
    width: float = 180
    height: float = 78
    fixed: bool = False
    vx: float = 0
    vy: float = 0


class ForceLayout:
    def __init__(self, bodies, edges):
        self.bodies = bodies
        self.edges = [(a, b) for a, b in edges if a in bodies and b in bodies and a != b]
        self.degree = defaultdict(int)
        for a, b in self.edges:
            self.degree[a] += 1
            self.degree[b] += 1
        self.iterations = 0
        self.quiet = 0
        self.pair_checks = 0
        self.settled = not any(not body.fixed for body in bodies.values())

    @staticmethod
    def initial(index):
        radius = 170 * math.sqrt(index)
        angle = index * 2.399963229728653
        return math.cos(angle) * radius, math.sin(angle) * radius

    def step(self):
        if self.settled:
            return False
        cells = defaultdict(list)
        keys = list(self.bodies)
        for index, key in enumerate(keys):
            body = self.bodies[key]
            cells[(math.floor(body.x / 320), math.floor(body.y / 320))].append(index)
        forces = [[0.0, 0.0] for _ in keys]
        self.pair_checks = 0
        overlaps = 0
        for index, key in enumerate(keys):
            a = self.bodies[key]
            cx, cy = math.floor(a.x / 320), math.floor(a.y / 320)
            for sx in (-1, 0, 1):
                for sy in (-1, 0, 1):
                    for other in cells.get((cx + sx, cy + sy), ()):
                        if other <= index:
                            continue
                        b = self.bodies[keys[other]]
                        if a.fixed and b.fixed:
                            continue
                        self.pair_checks += 1
                        dx, dy = a.x - b.x, a.y - b.y
                        if abs(dx) + abs(dy) < 0.01:
                            dx, dy = (1 if index % 2 else -1), 0.5
                        px = (a.width + b.width) / 2 + 20 - abs(dx)
                        py = (a.height + b.height) / 2 + 20 - abs(dy)
                        fx = fy = 0.0
                        if px > 0 and py > 0:
                            overlaps += 1
                            gain = 0.65 if a.fixed or b.fixed else 0.35
                            if px < py:
                                fx = math.copysign(px * gain + 0.5, dx)
                            else:
                                fy = math.copysign(py * gain + 0.5, dy)
                        else:
                            distance = max(30, math.hypot(dx, dy))
                            strength = min(2.5, 6500 / distance**2)
                            fx, fy = dx / distance * strength, dy / distance * strength
                        forces[index][0] += fx
                        forces[index][1] += fy
                        forces[other][0] -= fx
                        forces[other][1] -= fy
        indexes = {key: index for index, key in enumerate(keys)}
        for source, target in self.edges:
            a, b = self.bodies[source], self.bodies[target]
            dx, dy = b.x - a.x, b.y - a.y
            distance = max(1, math.hypot(dx, dy))
            # Dense hubs need room for their neighborhood instead of pulling every leaf
            # onto the same small ring. Collision constraints still set the minimum gap.
            preferred = 250 + 65 * math.sqrt(max(self.degree[source], self.degree[target]))
            strength = (distance - preferred) * 0.004
            fx, fy = dx / distance * strength, dy / distance * strength
            for key, sign in ((source, 1), (target, -1)):
                forces[indexes[key]][0] += fx * sign
                forces[indexes[key]][1] += fy * sign
        movement = 0.0
        cooling = max(0.08, 1 - self.iterations / 320)
        for index, key in enumerate(keys):
            body = self.bodies[key]
            if body.fixed:
                continue
            fx, fy = forces[index]
            body.vx = (body.vx + fx * cooling) * 0.65
            body.vy = (body.vy + fy * cooling) * 0.65
            speed = math.hypot(body.vx, body.vy)
            if speed > 12:
                body.vx *= 12 / speed
                body.vy *= 12 / speed
            body.x += body.vx
            body.y += body.vy
            movement = max(movement, min(speed, 12))
        movement = max(movement, self._separate())
        self.iterations += 1
        self.quiet = self.quiet + 1 if movement < 0.2 and not overlaps else 0
        self.settled = self.quiet >= 8 or self.iterations >= 360
        if self.settled:
            self._finish_without_overlaps()
        return not self.settled

    def _separate(self):
        """Project overlapping rectangles apart; springs must never overpower padding."""
        movement = 0.0
        for _ in range(2):
            cells = defaultdict(list)
            for index, body in enumerate(self.bodies.values()):
                cells[(math.floor(body.x / 320), math.floor(body.y / 320))].append((index, body))
            for index, a in enumerate(self.bodies.values()):
                cx, cy = math.floor(a.x / 320), math.floor(a.y / 320)
                for sx in (-1, 0, 1):
                    for sy in (-1, 0, 1):
                        for other, b in cells.get((cx + sx, cy + sy), ()):
                            if other <= index or (a.fixed and b.fixed):
                                continue
                            dx, dy = a.x - b.x, a.y - b.y
                            px = (a.width + b.width) / 2 + 12 - abs(dx)
                            py = (a.height + b.height) / 2 + 12 - abs(dy)
                            if px <= 0 or py <= 0:
                                continue
                            shift = (min(px, py) + 0.1) / (1 if a.fixed or b.fixed else 2)
                            movement = max(movement, shift)
                            axis = "x" if px < py else "y"
                            delta = math.copysign(shift, dx if axis == "x" else dy)
                            if not a.fixed:
                                setattr(a, axis, getattr(a, axis) + delta)
                            if not b.fixed:
                                setattr(b, axis, getattr(b, axis) - delta)
        return movement

    def _finish_without_overlaps(self):
        """Bounded final packing, respecting all restored and manually pinned anchors."""
        cells = defaultdict(list)
        for body in sorted(self.bodies.values(), key=lambda body: not body.fixed):
            origin_x, origin_y = body.x, body.y
            attempt = 0
            while not body.fixed:
                cx, cy = math.floor(body.x / 320), math.floor(body.y / 320)
                blocked = any(
                    abs(body.x - other.x) < (body.width + other.width) / 2 + 10
                    and abs(body.y - other.y) < (body.height + other.height) / 2 + 10
                    for sx in (-1, 0, 1)
                    for sy in (-1, 0, 1)
                    for other in cells.get((cx + sx, cy + sy), ())
                )
                if not blocked:
                    break
                attempt += 1
                angle = attempt * 2.399963229728653
                radius = 24 * math.sqrt(attempt)
                body.x = origin_x + math.cos(angle) * radius
                body.y = origin_y + math.sin(angle) * radius
            cells[(math.floor(body.x / 320), math.floor(body.y / 320))].append(body)

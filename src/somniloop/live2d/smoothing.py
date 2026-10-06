"""Frame-rate-independent smoothing of the cursor target before Cubism tracking."""

import math


class SmoothGaze:
    def __init__(self):
        self.target = (0.0, 0.0)
        self.position = (0.0, 0.0)

    def aim(self, x, y):
        self.target = (max(-1, min(1, x)), max(-1, min(1, y)))

    def advance(self, dt):
        # Short time constant removes pointer jitter without a sluggish head turn.
        weight = -math.expm1(-max(0, min(.1, dt)) / .085)
        self.position = tuple(current + (target - current) * weight
                              for current, target in zip(self.position, self.target))
        return self.position

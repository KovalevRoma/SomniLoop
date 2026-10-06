"""Cursor filtering must be bounded and independent of rendering frequency."""

import pytest

from somniloop.live2d.smoothing import SmoothGaze


def test_smoothing_is_monotonic_and_does_not_jump_or_overshoot():
    gaze = SmoothGaze()
    gaze.aim(5, -5)
    previous = 0
    for _ in range(60):
        x, y = gaze.advance(1 / 60)
        assert previous < x < 1
        assert y == -x
        previous = x
    assert x > .99
    gaze.aim(-1, 1)
    assert -1 < gaze.advance(1 / 60)[0] < x


def test_smoothing_matches_at_30_and_60_fps():
    results = []
    for fps in (30, 60):
        gaze = SmoothGaze()
        gaze.aim(.8, -.5)
        for _ in range(fps):
            gaze.advance(1 / fps)
        results.append(gaze.position)
    assert results[0] == pytest.approx(results[1])


def test_negative_delta_is_ignored_and_long_pause_is_bounded():
    gaze = SmoothGaze()
    gaze.aim(1, 1)
    assert gaze.advance(-1) == (0, 0)
    assert 0 < gaze.advance(30)[0] < .8

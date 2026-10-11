import math

import pytest

from somniloop.ui.rave_motion import (
    BEAT_SECONDS,
    DROP_SECONDS,
    OUTRO_SECONDS,
    TRAVEL_SECONDS,
    cat_pose,
    light_motes,
    projected_scale,
    travel_position,
)


def test_face_on_holds_alternate_with_depth_spins():
    for beat in (0.5, 1.5, 4.5, 8.5):
        pose = cat_pose(DROP_SECONDS + beat * BEAT_SECONDS)
        assert projected_scale(pose) == pytest.approx((1, 1))
        assert pose.angle == pytest.approx(0, abs=1e-8)
    pose = cat_pose(DROP_SECONDS + 2.25 * BEAT_SECONDS)
    assert abs(projected_scale(pose)[0]) < .4
    assert abs(pose.pitch) > 50


def test_spin_varies_in_direction_and_includes_pauses():
    changes = [round(cat_pose(DROP_SECONDS + beat * BEAT_SECONDS + .3).yaw
                     - cat_pose(DROP_SECONDS + beat * BEAT_SECONDS).yaw)
               for beat in range(32)]
    assert min(changes) < 0 < max(changes)
    assert 0 in changes
    assert len(set(changes)) >= 5


def test_positions_are_continuous_at_beat_boundaries():
    for beat in range(1, 63):
        time = DROP_SECONDS + beat * BEAT_SECONDS
        before, after = cat_pose(time - 1e-7), cat_pose(time + 1e-7)
        assert before.x == pytest.approx(after.x, abs=1e-4)
        assert before.y == pytest.approx(after.y, abs=1e-4)


def test_outro_pulses_without_disappearing():
    values = [cat_pose(OUTRO_SECONDS + 1 + i / 100).opacity for i in range(160)]
    assert min(values) >= .72
    assert max(values) == pytest.approx(1)
    assert max(values) - min(values) > .25
    assert .8 <= cat_pose(15).opacity <= 1


def test_cat_breathes_without_blinking_out_during_main_section():
    values = [cat_pose(DROP_SECONDS + i / 100).opacity for i in range(160)]
    assert min(values) == pytest.approx(.8)
    assert max(values) == pytest.approx(1)
    assert max(abs(a - b) for a, b in zip(values, values[1:])) < .01


def test_poses_are_bounded_and_repeatable():
    for i in range(4385):
        pose = cat_pose(i / 100)
        assert pose == cat_pose(i / 100)
        assert -1 <= pose.x <= 1 and -1 <= pose.y <= 1
        assert .72 <= pose.opacity <= 1
        assert 1 <= pose.scale <= 1.07
        assert math.isfinite(pose.angle)
        width, height = projected_scale(pose)
        assert .38 <= abs(width) <= 1
        assert .55 <= height <= 1


def test_travel_looks_random_but_repeats_and_hits_all_quadrants():
    points = [travel_position(TRAVEL_SECONDS + i * BEAT_SECONDS + .2)
              for i in range(40)]
    assert len(set(points)) == 40
    assert len({(x > 0, y > 0) for x, y in points}) == 4
    assert all(math.dist(a, b) > .8 for a, b in zip(points, points[1:]))
    for i, point in enumerate(points):
        assert point == travel_position(TRAVEL_SECONDS + i * BEAT_SECONDS + .3)
        assert point == travel_position(TRAVEL_SECONDS + i * BEAT_SECONDS + .2)
    assert travel_position(TRAVEL_SECONDS - .01) == (0, 0)


def test_bounce_and_zoom_follow_each_beat_even_during_front_facing_holds():
    for beat in (0, 1, 4, 8):
        start = cat_pose(DROP_SECONDS + beat * BEAT_SECONDS + 1e-8)
        accent = cat_pose(DROP_SECONDS + (beat + .275) * BEAT_SECONDS)
        settled = cat_pose(DROP_SECONDS + (beat + .7) * BEAT_SECONDS)
        assert start.scale == pytest.approx(1)
        assert accent.scale == pytest.approx(1.07)
        assert settled.scale == pytest.approx(1)


def test_glows_are_bounded_repeatable_and_change_location():
    for time in (0, 1, 4, 16, 43):
        lights = list(light_motes(time))
        assert lights == list(light_motes(time))
        assert len(lights) <= 56
        for x, y, color, radius, opacity in lights:
            assert 0 <= x <= 1 and 0 <= y <= 1
            assert 0 <= color < 8 and 18 <= radius <= 52
            assert 0 <= opacity <= .48
    assert len(list(light_motes(4))) == 56
    assert list(light_motes(4))[0][:2] != list(light_motes(8))[0][:2]

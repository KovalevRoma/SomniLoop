"""Pure interaction rules: gesture counting, precedence and geometric hit areas."""

import pytest

from somniloop.live2d.interaction import StrokeGesture, TouchState, hit_zone


def test_quiet_tap_surprises_but_specific_gestures_take_priority():
    state = TouchState()
    assert state.react("other", False, 0) == "Surprised"
    assert state.react("other", False, 59) is None
    assert state.react("other", False, 119) == "Surprised"
    assert state.react("head", True, 200) == "Smile"


@pytest.mark.parametrize("zone", ["chest", "hips", "legs"])
def test_sensitive_touch_is_angry_even_after_long_pause(zone):
    assert TouchState().react(zone, False, 100) == "Angry"


@pytest.mark.parametrize("zone", ["chest", "hips"])
def test_smile_then_sensitive_touch_blushes(zone):
    state = TouchState()
    state.react("cheek", True, 1)
    assert state.react(zone, False, 2) == "Blushing"
    assert state.react(zone, False, 3) == "Angry"


def test_legs_after_smile_still_angry():
    state = TouchState()
    state.react("head", True, 1)
    assert state.react("legs", False, 2) == "Angry"


@pytest.mark.parametrize("zone", ["head", "cheek"])
def test_fifth_same_stroke_is_angry_and_sequence_resets(zone):
    state = TouchState()
    assert [state.react(zone, True, i) for i in range(5)] == ["Smile"] * 4 + ["Angry"]
    assert state.react(zone, True, 5) == "Angry"
    other = "cheek" if zone == "head" else "head"
    assert state.react(other, True, 6) == "Smile"
    assert state.react(zone, True, 7) == "Smile"
    assert state.react(zone, True, 100) == "Smile"


def test_a_stroke_is_one_drag_not_each_mouse_move():
    gesture = StrokeGesture()
    gesture.begin("head", 10, 10)
    for x in range(11, 40):
        gesture.move("head", x, 10)
    assert gesture.finish("head", 40, 10, 12) == ("head", True)
    assert gesture.finish("head", 40, 10, 12) == (None, False)
    gesture.begin("head", 10, 10)
    assert gesture.finish("head", 11, 10, 12) == ("head", False)
    gesture.begin("head", 10, 10)
    gesture.move("chest", 30, 50)
    assert gesture.finish("head", 10, 10, 12) == (None, False)


def test_hit_zones_follow_translated_and_scaled_parts():
    parts = {
        "face": (.35, .10, .65, .35), "cheeks": (.39, .26, .61, .30),
        "hair": (.34, .08, .66, .24), "body": (.28, .38, .70, .88),
        "legs": (.32, .78, .68, .96),
    }
    cases = [(.5, .15, "head"), (.4, .28, "cheek"), (.5, .48, "chest"),
             (.5, .82, "hips"), (.5, .93, "legs"), (.1, .5, "other")]
    for x, y, zone in cases:
        assert hit_zone(x, y, parts) == zone
        transformed = {key: tuple(value * .7 + .1 for value in rect)
                       for key, rect in parts.items()}
        assert hit_zone(x * .7 + .1, y * .7 + .1, transformed) == zone

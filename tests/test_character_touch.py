"""Pure interaction rules: gesture counting, precedence and geometric hit areas."""

import pytest

from somniloop.live2d.interaction import TapGesture, TouchState, hit_zone


def test_quiet_tap_surprises_but_specific_gestures_take_priority():
    state = TouchState()
    assert state.react("other", 0) == "Surprised"
    assert state.react("other", 59) is None
    assert state.react("other", 119) == "Surprised"
    assert state.react("head", 200) == "Smile"


@pytest.mark.parametrize("zone", ["chest", "hips", "legs"])
def test_sensitive_touch_is_angry_even_after_long_pause(zone):
    assert TouchState().react(zone, 100) == "Angry"


@pytest.mark.parametrize("zone", ["chest", "hips"])
def test_smile_then_sensitive_touch_blushes(zone):
    state = TouchState()
    state.react("cheek", 1)
    assert state.react(zone, 2) == "Blushing"
    assert state.react(zone, 3) == "Angry"


def test_legs_after_smile_still_angry():
    state = TouchState()
    state.react("head", 1)
    assert state.react("legs", 2) == "Angry"


@pytest.mark.parametrize("zone", ["head", "cheek"])
def test_affection_never_triggers_anger(zone):
    state = TouchState()
    assert [state.react(zone, i) for i in range(20)] == ["Smile"] * 20
    assert state.motion is None
    other = "cheek" if zone == "head" else "head"
    assert state.react(other, 20) == "Smile"
    assert state.react(zone, 21) == "Smile"
    assert state.react(zone, 100) == "Smile"


def test_dragging_is_not_a_tap():
    gesture = TapGesture()
    gesture.begin("head", 10, 10)
    for x in range(11, 40):
        gesture.move("head", x, 10)
    assert gesture.finish("head", 40, 10) is None
    assert gesture.finish("head", 40, 10) is None
    gesture.begin("head", 10, 10)
    assert gesture.finish("head", 11, 10) == "head"
    gesture.begin("head", 10, 10)
    gesture.move("chest", 30, 50)
    assert gesture.finish("head", 10, 10) is None


def test_lower_body_fifth_tap_has_priority_over_general_excessive_touch():
    state = TouchState()
    for i, zone in enumerate(["legs", "hips", "legs", "hips", "legs"]):
        state.react(zone, i)
        assert state.motion == ("Tap", 2 if i < 4 else 3)
    assert state.emotion == "Disgust"


def test_mixed_rapid_taps_trigger_shake():
    state = TouchState()
    for i, zone in enumerate(["chest", "legs", "hips", "legs", "chest"]):
        state.react(zone, i)
    assert state.motion == ("Shake", 1)
    assert state.emotion == "Disgust"


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

"""Offline unit checks plus opt-in tests using the real Cubism Native SDK."""

import json
import os

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.live2d.resources import CharacterConfig, ModelResources, epsilon_manifest
from somniloop.live2d.settings import CharacterSettings


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def repo(tmp_path):
    value = Repository(tmp_path / "test.db")
    yield value
    value.close()


@pytest.mark.parametrize("language, expected", [
    ("ru", ("Смущена", "Отвращение")),
    ("en", ("Blushing", "Disgusted")),
])
def test_status_badge_blushing_and_disgust_labels(app, language, expected):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from somniloop.live2d.status import EmotionBadge

    host = QWidget()
    host.i18n = I18n(language)
    badge = EmotionBadge(host)
    try:
        for emotion, label in zip(("Blushing", "Disgust"), expected):
            badge.set_emotion(emotion)
            assert badge.label() == label
            assert badge.accessibleName() == label
        assert not badge.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    finally:
        host.close()


def test_activity_motion_mapping_and_priority(app, monkeypatch):
    import time

    from PySide6.QtWidgets import QWidget

    from somniloop.live2d.overlay import Live2DOverlay

    host = QWidget()
    character = Live2DOverlay(host, CharacterConfig(enabled=True))
    calls = []
    monkeypatch.setattr(character, "_event_motion", lambda *args: calls.append(args) or True)
    try:
        for event, motion in [("created", ("FlickUp", 0)),
                              ("settings_saved", ("FlickUp", 0)),
                              ("archived", ("FlickUp", 1))]:
            character.applicationEvent(event)
            character._process_activity(time.monotonic())
            assert calls[-1] == (*motion, 3)
            assert character.status.emotion == ("Normal" if event == "archived" else "Smile")
        for motion in [("Tap", 1), ("FlickDown", 0), ("FlickDown", 1)]:
            monkeypatch.setattr("somniloop.live2d.overlay.random.choice", lambda choices: motion)
            character.applicationEvent("not_done")
            character._process_activity(time.monotonic())
            assert calls[-1] == (*motion, 3)
            assert character.status.emotion == "Sad"
        character.preview_remaining = 5
        before = len(calls)
        character.applicationEvent("created")
        character._process_activity(time.monotonic())
        assert len(calls) == before
        character.preview_remaining = 0
        character._process_activity(time.monotonic() + 31)
        assert character.pending_activity is None and len(calls) == before
        character.config.reactions = False
        character.applicationEvent("created")
        assert character.pending_activity is None
        character.reaction_started = time.monotonic()
        character.effect_duration = 6
        # Ambient/hover motions must not erase a just-shown completion smile.
        assert not Live2DOverlay._event_motion(character, "Flick3", 0, 1)
        assert not Live2DOverlay._event_motion(character, "FlickUp", 0, 2)
        character.reaction_started = 0
        character.reactions.submit(True)
        assert not Live2DOverlay._event_motion(character, "Flick3", 0, 1)
        assert character.reactions.pending.isActive()
    finally:
        character.dispose()
        host.close()


def test_hover_triggers_on_entry_not_every_frame(app, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QWidget

    from somniloop.live2d.overlay import Live2DOverlay

    host = QWidget()
    character = Live2DOverlay(host, CharacterConfig(enabled=False, interaction=True))
    calls = []
    cursor = [QPoint(10, 10)]
    zone = ["chest"]
    monkeypatch.setattr("somniloop.live2d.overlay.QCursor.pos", lambda: cursor[0])
    monkeypatch.setattr(character, "_zone_at", lambda point: zone[0])
    monkeypatch.setattr(character, "_event_motion", lambda *args: calls.append(args) or True)
    try:
        character._hover(100)
        assert calls == [("Flick", 0, 2)]
        character._hover(103)
        cursor[0] = QPoint(11, 10)
        character._hover(104)
        assert len(calls) == 1
        cursor[0] = QPoint(12, 10)
        zone[0] = "legs"
        character._hover(106)
        assert calls[-1] == ("Shake", 0, 2)
        cursor[0] = QPoint(13, 10)
        zone[0] = "head"
        character._hover(109)
        assert calls[-1] == ("FlickUp", 0, 2)
        assert character.status.emotion == "Smile"
        character.config.interaction = False
        cursor[0] = QPoint(14, 10)
        zone[0] = "chest"
        character._hover(110)
        assert len(calls) == 3
    finally:
        character.dispose()
        host.close()


def test_character_settings_roundtrip_and_draft_does_not_save(app, repo):
    draft = CharacterSettings(repo, I18n("en"))
    draft.enabled.setChecked(False)
    draft.scale.setValue(1.4)
    draft.captions.setChecked(True)
    draft.voice.setChecked(True)
    draft.reactions.setChecked(False)
    assert CharacterConfig.load(repo).enabled
    draft.save()
    saved = CharacterConfig.load(repo)
    assert not saved.enabled and saved.scale == 1.4
    assert saved.captions and saved.voice and not saved.reactions
    draft.close()


def test_rate_limit_coalesces_and_cancel_stops_pending(app):
    from somniloop.live2d.reactions import ReactionController

    controller = ReactionController(app)
    received = []
    controller.requested.connect(received.append)
    controller.submit(False)
    controller.submit(True)
    controller.flush()
    assert received == [True]
    controller.submit()
    assert not controller.pending.isActive()
    controller.last_reaction = float("-inf")
    controller.submit()
    controller.cancel()
    assert not controller.pending.isActive()
    controller.last_all_done = False
    controller.submit(True)
    assert controller.pending.isActive()
    controller.flush()
    assert received == [True, True]
    controller.deleteLater()


def test_missing_optional_voice_keeps_visual_feedback_available(app, monkeypatch):
    import sys

    from somniloop.live2d.reactions import LocalSpeech

    monkeypatch.setitem(sys.modules, "PySide6.QtTextToSpeech", None)
    speech = LocalSpeech(app)
    failures = []
    speech.failed.connect(failures.append)
    speech.say("Nice work", "en")
    assert failures and speech.engine is None
    speech.stop()
    speech.deleteLater()


@pytest.mark.parametrize("raw", ["not json", "[]", '{"scale":"oops"}', '{"enabled":"false"}'])
def test_invalid_config_is_safe(repo, raw):
    repo.set_setting("live2d_config", raw)
    assert CharacterConfig.load(repo) == CharacterConfig()


def test_disabled_overlay_never_loads_native_library(app, monkeypatch):
    from PySide6.QtWidgets import QMainWindow

    from somniloop.live2d import overlay

    def forbidden(*args):
        raise AssertionError("Disabled characters must not load native code")

    monkeypatch.setattr(overlay, "NativeRenderer", forbidden)
    host = QMainWindow()
    character = overlay.Live2DOverlay(host, CharacterConfig(enabled=False))
    host.show()
    app.processEvents()
    character._sync()
    assert character.renderer is None and not character.timer.isActive()
    character.dispose()
    character.dispose()
    host.close()


def test_missing_model_fails_without_breaking_host(app, monkeypatch):
    from PySide6.QtWidgets import QMainWindow

    from somniloop.live2d.overlay import Live2DOverlay

    host = QMainWindow()
    character = Live2DOverlay(host, CharacterConfig())

    def fail():
        raise FileNotFoundError("Missing test model")

    monkeypatch.setattr(character, "_initialize", fail)
    host.show()
    character._sync()
    assert "Missing test model" in character.error
    assert host.isEnabled() and not character.timer.isActive()
    character.dispose()
    host.close()


def test_resource_path_validation():
    if not epsilon_manifest().is_file():
        pytest.skip("Optional official model not installed")
    resources = ModelResources(epsilon_manifest())
    assert len(resources.textures) == 3
    assert resources.expression_named("Smile") == "Smile.exp3.json"
    assert "Tap" in resources.motions
    with pytest.raises((ValueError, FileNotFoundError)):
        resources.resolve("../Readme.txt")
    with pytest.raises(ValueError):
        resources.resolve(str(resources.manifest))
    with pytest.raises(FileNotFoundError):
        resources.resolve("missing.png")


@pytest.mark.skipif(
    os.environ.get("SOMNILOOP_TEST_LIVE2D") != "1",
    reason="Requires installed Cubism and real OpenGL",
)
def test_real_sdk_blink_breath_physics_expressions_and_return_to_idle(app):
    from somniloop.live2d.renderer import NativeRenderer

    resources = ModelResources(epsilon_manifest())
    renderer = NativeRenderer(resources)
    eyes, breath, hair = [], [], []
    try:
        from somniloop.live2d.interaction import PART_IDS

        renderer.frame(QSize(120, 160), 1 / 30, 1)
        full = renderer.frame(QSize(120, 160), 0, .7)
        reduced = renderer.frame(QSize(120, 160), 0, .7, output_size=QSize(60, 80))
        if renderer.readback_fbo is not None:
            from PySide6.QtCore import Qt

            assert reduced.size() == QSize(60, 80)
            expected = full.scaled(QSize(60, 80), Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            differences = []
            for x in range(0, 60, 3):
                for y in range(0, 80, 3):
                    actual_pixel = reduced.pixelColor(x, y)
                    expected_pixel = expected.pixelColor(x, y)
                    differences.append(abs(actual_pixel.alpha() - expected_pixel.alpha()))
            assert sum(differences) / len(differences) < 3
            assert reduced.pixelColor(0, 0).alpha() == 0
            buffer = renderer.readback_fbo
            renderer.frame(QSize(120, 160), 0, 1, output_size=QSize(60, 80))
            assert renderer.readback_fbo is buffer
            assert renderer.frame(QSize(160, 200), 0, 1,
                                  output_size=QSize(80, 100)).size() == QSize(80, 100)
            renderer.frame(QSize(120, 160), 0, 1)
        for part in PART_IDS.values():
            bounds = renderer.part_bounds(part, 120, 160)
            assert bounds is not None
            assert bounds[0] < bounds[2] and bounds[1] < bounds[3]
        before = renderer.part_bounds(PART_IDS["face"], 120, 160)
        renderer.check(renderer.lib.sl_parameter(renderer.handle, b"PARAM_ANGLE_X", 30))
        renderer.frame(QSize(120, 160), 1 / 30, 1)
        after = renderer.part_bounds(PART_IDS["face"], 120, 160)
        assert abs(before[0] - after[0]) > .001
        renderer.check(renderer.lib.sl_parameter(renderer.handle, b"PARAM_ANGLE_X", 0))
        assert renderer.part_bounds("missing_part", 120, 160) is None
        # Stop idle clips so blink and physics are measured independently of animation curves.
        renderer.lib.sl_idle(renderer.handle, 0)
        for index in range(360):
            renderer.lib.sl_look(renderer.handle, 0.8 if index % 120 < 60 else -0.8, 0.2)
            renderer.frame(QSize(120, 160), 1 / 30, 1)
            eyes.append(renderer.parameter("PARAM_EYE_L_OPEN"))
            breath.append(renderer.parameter("PARAM_BREATH"))
            hair.append(renderer.parameter("PARAM_HAIR_SIDE_L"))
        assert min(eyes) < 0.3 and max(eyes) > 0.9
        assert max(breath) - min(breath) > 0.5
        assert max(hair) - min(hair) > 0.01
        for name, parameter in (("Smile", "PARAM_EYE_L_SMILE"), ("Blushing", "PARAM_TERE")):
            renderer.check(
                renderer.lib.sl_expression(
                    renderer.handle, resources.expression_named(name).encode()
                )
            )
            for _ in range(45):
                renderer.frame(QSize(120, 160), 1 / 30, 1)
            assert renderer.parameter(parameter) > 0.8
        renderer.check(renderer.lib.sl_expression(renderer.handle, b""))
        # Reset must fade, not erase blushing in a single 60 FPS frame.
        before_reset = renderer.parameter("PARAM_TERE")
        renderer.frame(QSize(120, 160), 1 / 60, 1)
        assert renderer.parameter("PARAM_TERE") > before_reset * .5
        for _ in range(120):
            renderer.frame(QSize(120, 160), 1 / 60, 1)
        assert renderer.parameter("PARAM_TERE") < .1
        renderer.check(renderer.lib.sl_motion(renderer.handle, b"Tap", 0))
        renderer.lib.sl_idle(renderer.handle, 1)
        clip = json.loads(resources.resolve(resources.motions["Tap"][0]["File"]).read_text())
        for _ in range(int((clip["Meta"]["Duration"] + 2) * 30)):
            renderer.frame(QSize(120, 160), 1 / 30, 1)
        assert renderer.lib.sl_motion_group(renderer.handle) == b"Idle"
    finally:
        renderer.close()
    # Framework/GL resources must be reusable after disposal.
    second = NativeRenderer(resources)
    second.frame(QSize(80, 100), 1 / 30, 1)
    second.close()

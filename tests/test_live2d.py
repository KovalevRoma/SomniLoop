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

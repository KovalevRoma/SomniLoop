from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from somniloop.live2d.overlay import Live2DOverlay
from somniloop.live2d.resources import CharacterConfig


def test_dance_loops_blocks_reactions_and_restores_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    character = Live2DOverlay(host, CharacterConfig(enabled=True, interaction=True, idle=False))
    calls = []
    character.resources = SimpleNamespace(
        motions={"Shake": [{}], "Idle": [{}]}, expression_named=lambda name: None)
    character.renderer = SimpleNamespace(
        handle=1, lib=SimpleNamespace(sl_idle=lambda *args: calls.append(("idle", args[-1]))),
        close=lambda: None)
    monkeypatch.setattr(character, "_sync", lambda: None)
    monkeypatch.setattr(character, "resetExpression", lambda: character.status.set_emotion("Normal"))
    monkeypatch.setattr(character, "playMotion", lambda *args: calls.append(args))
    monkeypatch.setattr(character, "_duration", lambda *args: 3.233)
    try:
        character.setRaveActive(True)
        assert character.rave_active and character.timer.interval() == 33
        assert calls[-1] == ("Shake", 0)
        assert character.status.emotion == "Dancing"
        assert character.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        before = list(calls)
        character._touch_reaction("chest")
        character.applicationEvent("archived")
        character.taskCompleted(True)
        character._react(True)
        assert not character._event_motion("Tap", 0, 3)
        character._advance_dance()
        assert calls == before and character.pending_activity is None
        assert not character.reactions.pending.isActive()
        character.motion_remaining = 0
        character._advance_dance()
        assert calls[-1] == ("Shake", 0) and len(calls) == len(before) + 1
        character.setRaveActive(True)
        character.setRaveActive(False)
        assert not character.rave_active and character.timer.interval() == 16
        assert not character.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert calls[-2:] == [("Idle", 0), ("idle", 0)]
        assert character.config.idle is False
        assert character.status.emotion == "Normal"
        before = list(calls)
        character.setRaveActive(False)
        assert calls == before
    finally:
        character.dispose()
        host.close()
        app.processEvents()


def test_disabled_character_does_not_load_for_dance(monkeypatch):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    character = Live2DOverlay(host, CharacterConfig(enabled=False))
    monkeypatch.setattr(character, "_initialize", lambda: (_ for _ in ()).throw(AssertionError()))
    try:
        character.setRaveActive(True)
        assert not character.rave_active and character.renderer is None
    finally:
        character.dispose()
        host.close()
        app.processEvents()

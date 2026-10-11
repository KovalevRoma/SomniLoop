import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from somniloop.core.database import Repository
from somniloop.core.i18n import I18n
from somniloop.ui.activity_scrollbar import ActivityScrollBar
from somniloop.ui.image_block import ImageBlock
from somniloop.ui.planner import NotificationDrawer, PlannerDialog
from somniloop.ui.rich_text import RichTextEditor, RichTextView


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    value = RichTextEditor("BeforeAfter")
    value.resize(550, 450)
    value.show()
    app.processEvents()
    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#456789"))
    app.clipboard().setImage(image)
    yield value
    value.close()
    app.clipboard().clear()


def test_ctrl_v_inserts_at_cursor_and_resize_roundtrips(editor):
    cursor = editor.textCursor()
    cursor.setPosition(6)
    editor.setTextCursor(cursor)
    editor.active.setFocus()
    QTest.keyClick(editor.active, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    block = next(b for b in editor.blocks if isinstance(b, ImageBlock))
    assert editor.toPlainText().splitlines() == ["Before", "[Image]", "After"]
    start = block.handle_rect.center().toPoint()
    QTest.mousePress(block, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(block, start - type(start)(80, 40))
    QTest.mouseRelease(block, Qt.MouseButton.LeftButton, pos=start - type(start)(80, 40))
    assert block.preferred_width < 320
    width = block.preferred_width
    source = editor.source()
    editor.set_source(source)
    restored = next(b for b in editor.blocks if isinstance(b, ImageBlock))
    assert restored.preferred_width == width
    assert not restored.pixmap.isNull()
    view = RichTextView(source)
    image = next(b for b in view.blocks if isinstance(b, ImageBlock))
    assert image.read_only and image.remove_button.isHidden()
    image.remove()
    assert image in view.blocks
    view.close()


def test_legacy_attachments_migrate_only_on_save(editor, tmp_path):
    editor.active.paste()
    image = next(b for b in editor.blocks if isinstance(b, ImageBlock))
    repo = Repository(tmp_path / "images.db")
    try:
        identifier = repo.save_planner_task("Old task", None, "Original text")
        repo.save_task_images(identifier, [("old.png", image.data)])
        task = repo.list_planner_tasks()[0]
        dialog = PlannerDialog(repo, I18n("en"), task)
        assert any(isinstance(b, ImageBlock) for b in dialog.description_edit.blocks)
        dialog.reject()
        assert len(repo.task_images(identifier)) == 1
        dialog = PlannerDialog(repo, I18n("en"), task)
        dialog._save()
        assert not repo.task_images(identifier)
        assert "<somniloop-image" in repo.list_planner_tasks()[0].description
    finally:
        repo.close()


def test_birthdays_stay_inside_host_and_close_without_native_windows(editor, tmp_path):
    repo = Repository(tmp_path / "birthdays.db")
    host = QWidget()
    host.resize(700, 500)
    host.show()
    from PySide6.QtWidgets import QPushButton

    anchor = QPushButton("Birthdays", host)
    anchor.move(500, 10)
    anchor.show()
    popup = NotificationDrawer(repo, I18n("en"), host)
    try:
        for _ in range(5):
            popup.toggle_at(anchor)
            QApplication.processEvents()
            assert popup.isVisible() and not popup.isWindow()
            assert popup.windowHandle() is None
            assert isinstance(popup.list.verticalScrollBar(), ActivityScrollBar)
            QTest.keyClick(host, Qt.Key.Key_Escape)
            assert not popup.isVisible()
    finally:
        popup.close()
        host.close()
        repo.close()

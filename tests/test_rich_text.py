"""Rich documents retain text, formatting, nested toggles, and legacy content."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from somniloop.ui.rich_text import RichTextEditor, RichTextView, ToggleBlock, safe_link


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    value = RichTextEditor("Начало\n\nКонец")
    value.resize(500, 350)
    value.show()
    app.processEvents()
    yield value
    value.close()


def test_untouched_legacy_text_is_preserved_exactly(editor):
    value = "  Plain text\n\nhttps://example.com\n"
    editor.set_source(value)
    assert editor.source() == value


def test_custom_context_menu_preserves_native_edit_actions(editor):
    editor.active.selectAll()
    menu = editor.active.createStandardContextMenu()
    try:
        actions = {action.objectName(): action for action in menu.actions() if not action.isSeparator()}
        assert set(actions) == {"edit-undo", "edit-redo", "edit-cut", "edit-copy",
                                "edit-paste", "edit-delete", "select-all"}
        assert all(not action.icon().isNull() for action in actions.values())
        assert actions["edit-copy"].isEnabled()
        actions["edit-copy"].trigger()
        assert "Начало" in QApplication.clipboard().text()
        actions["edit-delete"].trigger()
        assert not editor.active.toPlainText()
        editor.active.undo()
        assert "Начало" in editor.active.toPlainText()
    finally:
        menu.deleteLater()


def test_bold_formatting_survives_save_and_reload(editor):
    cursor = editor.textCursor()
    cursor.select(QTextCursor.SelectionType.WordUnderCursor)
    editor.setTextCursor(cursor)
    editor.format_text("bold")
    source = editor.source()
    assert "**Начало**" in source
    editor.set_source(source)
    assert editor.toPlainText() == "Начало\nКонец"


def test_markdown_typing_converts_inline_styles_and_headings(editor):
    editor.clear()
    editor.active.setFocus()
    QTest.keyClicks(editor.active, "**hello**")
    assert editor.toPlainText() == "hello"
    assert "**hello**" in editor.source()
    editor.clear()
    QTest.keyClicks(editor.active, "# Heading")
    assert editor.active.textCursor().blockFormat().headingLevel() == 1
    assert editor.source().startswith("# Heading")


def test_toggle_splits_at_cursor_and_roundtrips_nested_content(editor):
    cursor = editor.textCursor()
    cursor.setPosition(len("Начало"))
    editor.setTextCursor(cursor)
    editor.format_text("toggle")
    toggle = next(b for b in editor.blocks if isinstance(b, ToggleBlock))
    toggle.title.setText("Детали <важно>")
    toggle.content.set_source("**Скрытый текст**\n\n<details>\n<summary>Вложенный</summary>\n\n[Ссылка](https://example.com)\n\n</details>")
    source = editor.source()
    assert source.index("Начало") < source.index("<details>") < source.index("Конец")
    assert "&lt;важно&gt;" in source
    editor.set_source(source)
    assert "Скрытый текст" in editor.toPlainText()
    assert "Ссылка" in editor.toPlainText()
    toggle = next(b for b in editor.blocks if isinstance(b, ToggleBlock))
    assert not toggle.toggle.isChecked()
    QTest.qWait(20)
    QTest.mouseClick(toggle.toggle, Qt.MouseButton.LeftButton)
    assert toggle.content.isVisible()
    assert editor.source() == source


def test_readonly_toggles_work_without_exposing_edit_actions(editor):
    view = RichTextView("<details>\n<summary>Title</summary>\n\n**Body**\n\n</details>")
    view.show()
    toggle = next(b for b in view.blocks if isinstance(b, ToggleBlock))
    assert view.toolbar.isHidden() and toggle.title.isReadOnly()
    assert toggle.remove_button.isHidden()
    toggle.toggle.click()
    assert toggle.content.isVisible()
    assert toggle.content.active.isReadOnly()
    view.close()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,x", "../secret"])
def test_unsafe_links_are_not_opened(url):
    assert safe_link(url) is None


def test_malformed_toggle_is_not_lost(editor):
    source = "before\n<details>\n<summary>not closed</summary>\nafter"
    editor.set_source(source)
    assert editor.source() == source


def test_collapsed_toggle_has_no_editor_sized_gaps_or_unnecessary_scroll(editor):
    from somniloop.ui.rich_text import TextBlock

    editor.clear()
    editor.resize(520, 220)
    editor.format_text("toggle")
    toggle = next(b for b in editor.blocks if isinstance(b, ToggleBlock))
    toggle.title.setText("Experiment")
    toggle.toggle.setChecked(False)
    QTest.qWait(30)
    assert all(b.height() < 50 for b in editor.blocks if isinstance(b, TextBlock))
    assert toggle.height() <= toggle.title.height() + 12
    assert editor.scroll.verticalScrollBar().maximum() == 0
    toggle.content.set_source("Line\n\n" * 30)
    toggle.toggle.setChecked(True)
    QTest.qWait(30)
    assert editor.scroll.verticalScrollBar().maximum() > 0
    toggle.toggle.setChecked(False)
    QTest.qWait(30)
    assert editor.scroll.verticalScrollBar().maximum() == 0


def test_block_menu_uses_english_labels(editor):
    from PySide6.QtCore import QTimer

    labels = []
    def inspect_menu():
        menu = QApplication.activePopupWidget()
        labels.extend(a.text() for a in menu.actions())
        menu.close()

    QTimer.singleShot(20, inspect_menu)
    editor.block_menu()
    assert "Toggle list" in labels and "Heading 1" in labels
    assert all(label.isascii() for label in labels)


def test_task_and_bio_forms_store_formatted_source_without_flattening(editor, tmp_path):
    from somniloop.core.database import Repository
    from somniloop.core.i18n import I18n
    from somniloop.ui.personal_dialogs import BioDialog
    from somniloop.ui.planner import PlannerDialog

    source = "# Heading\n\n<details>\n<summary>Title</summary>\n\n**Body**\n\n</details>"
    repo = Repository(tmp_path / "rich.db")
    try:
        dialog = PlannerDialog(repo, I18n("en"))
        dialog.title_edit.setText("Task")
        dialog.description_edit.set_source(source)
        dialog._save()
        assert repo.list_planner_tasks()[0].description == source
        reopened = PlannerDialog(repo, I18n("en"), repo.list_planner_tasks()[0])
        assert reopened.description_edit.source() == source
        assert "Body" in reopened.description_edit.toPlainText()
        reopened.reject()
        bio = BioDialog(repo, I18n("en"))
        bio.bio_edit.set_source(source)
        bio._persist()
        assert repo.get_profile()[1] == source
        bio.reject()
    finally:
        repo.close()

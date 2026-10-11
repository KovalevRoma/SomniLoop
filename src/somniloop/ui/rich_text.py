"""Offline Markdown editing with native text formatting and nested toggle blocks."""

import base64
import html
import math
import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QImage,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .activity_scrollbar import ActivityScrollBar
from .controls import RoundedDialog, polish_dialog_buttons
from .icons import interface_icon
from .image_block import ImageBlock


def safe_link(value):
    url = QUrl(value.strip())
    return url if url.scheme().lower() in {"https", "http", "mailto"} else None


class LocalDocument(QTextDocument):
    def loadResource(self, kind, url):
        # Pasted/imported documents must not read local files or fetch remote images.
        if kind == QTextDocument.ResourceType.ImageResource:
            return QImage()
        return None


class TextBlock(QTextEdit):
    def __init__(self, owner, source=""):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("richTextBlock")
        self.setDocument(LocalDocument(self))
        self.setAcceptRichText(True)
        self.setMarkdown(source)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self.resize_content)
        self.textChanged.connect(owner.changed)
        self.document().documentLayout().documentSizeChanged.connect(self.resize_content)
        self.resize_content()

    def resize_content(self, *_):
        # Empty paragraphs still need a caret line, not a full editor-sized gap.
        self.setFixedHeight(math.ceil(self.document().size().height()) + 2 * self.frameWidth() + 2)

    def createStandardContextMenu(self, *args):
        menu = super().createStandardContextMenu(*args)
        icons = {"edit-undo": "undo", "edit-redo": "redo", "edit-cut": "cut",
                 "edit-copy": "copy", "edit-paste": "paste", "edit-delete": "delete",
                 "select-all": "select_all"}
        for action in menu.actions():
            if icon := icons.get(action.objectName()):
                action.setIcon(interface_icon(icon))
        return menu

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu(event.pos())
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

    def focusInEvent(self, event):
        self.owner.root_editor().active = self
        super().focusInEvent(event)

    def canInsertFromMimeData(self, source):
        return source.hasImage() or bool(self.clipboard_image_path(source)) or super().canInsertFromMimeData(source)

    @staticmethod
    def clipboard_image_path(source):
        urls = source.urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                return path
        return None

    def insertFromMimeData(self, source):
        path = self.clipboard_image_path(source)
        if not source.hasImage() and path is None:
            return super().insertFromMimeData(source)
        if self.isReadOnly():
            return
        if not source.hasImage():
            try:
                with path.open("rb") as stream:
                    data = stream.read(10 * 1024 * 1024 + 1)
                self.owner.insert_image(data, editor=self)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Image", str(error))
            return
        raw = source.imageData()
        image = raw.toImage() if isinstance(raw, QPixmap) else QImage(raw)
        if image.isNull() or image.width() * image.height() > 40_000_000:
            QMessageBox.warning(self, "Image", "Image is invalid or larger than 40 megapixels")
            return
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        try:
            self.owner.insert_image(bytes(data), editor=self)
        except ValueError as error:
            QMessageBox.warning(self, "Image", str(error))

    def mouseReleaseEvent(self, event):
        if self.isReadOnly() or event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            url = safe_link(self.anchorAt(event.position().toPoint()))
            if url:
                QDesktopServices.openUrl(url)
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.isReadOnly():
            return super().keyPressEvent(event)
        root = self.owner.root_editor()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            action = {Qt.Key.Key_B: "bold", Qt.Key.Key_I: "italic",
                      Qt.Key.Key_K: "link"}.get(event.key())
            if action:
                root.format_text(action)
                return
        if event.text() == "/" and not self.textCursor().block().text().strip():
            root.block_menu(self.mapToGlobal(self.cursorRect().bottomLeft()))
            return
        if event.key() == Qt.Key.Key_Space:
            cursor = self.textCursor()
            prefix = cursor.block().text()
            actions = {"#": "h1", "##": "h2", "###": "h3", "-": "bullet",
                       "*": "bullet", "1.": "number", "[]": "check", "[ ]": "check",
                       ">": "toggle"}
            if prefix in actions and cursor.atBlockEnd():
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                self.setTextCursor(cursor)
                root.format_text(actions[prefix])
                return
        super().keyPressEvent(event)
        if event.text() in ("*", "~", "`", ")"):
            self.parse_inline()

    def parse_inline(self):
        cursor = self.textCursor()
        before = cursor.block().text()[:cursor.positionInBlock()]
        patterns = ((r"(?<!\*)\*\*([^*\n]+)\*\*$", "bold"),
                    (r"(?<!\*)\*([^*\n]+)\*$", "italic"),
                    (r"~~([^~\n]+)~~$", "strike"),
                    (r"`([^`\n]+)`$", "code"),
                    (r"\[([^\]\n]+)\]\(([^\s)]+)\)$", "link"))
        for pattern, kind in patterns:
            match = re.search(pattern, before)
            if match is None or (kind == "link" and safe_link(match[2]) is None):
                continue
            original = cursor.charFormat()
            fmt = QTextCharFormat(original)
            if kind == "bold":
                fmt.setFontWeight(QFont.Weight.Bold)
            elif kind == "italic":
                fmt.setFontItalic(True)
            elif kind == "strike":
                fmt.setFontStrikeOut(True)
            elif kind == "code":
                fmt.setFontFamilies(["monospace"])
                fmt.setFontFixedPitch(True)
            else:
                fmt.setAnchor(True)
                fmt.setAnchorHref(match[2])
                fmt.setFontUnderline(True)
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor,
                                len(match[0]))
            cursor.insertText(match[1], fmt)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            self.setCurrentCharFormat(original)
            break


class ToggleBlock(QWidget):
    def __init__(self, owner, title, source):
        super().__init__(owner)
        self.owner = owner
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setAccessibleName("Развернуть / Expand")
        row.addWidget(self.toggle)
        self.title = QLineEdit(title)
        self.title.setPlaceholderText("Заголовок / Title")
        self.title.textChanged.connect(owner.changed)
        row.addWidget(self.title, 1)
        remove = QToolButton()
        remove.setText("×")
        remove.setToolTip("Удалить блок / Delete block")
        remove.clicked.connect(self.remove_block)
        row.addWidget(remove)
        self.remove_button = remove
        layout.addLayout(row)
        self.content = RichTextEditor(source, self, nested=True)
        self.content.outer = owner
        self.content.textChanged.connect(owner.changed)
        layout.addWidget(self.content)
        self.content.hide()
        self.toggle.toggled.connect(self.expand)

    def expand(self, visible):
        self.content.setVisible(visible)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)
        self.toggle.setAccessibleName("Свернуть / Collapse" if visible else "Развернуть / Expand")

    def source(self):
        return "<details>\n<summary>" + html.escape(self.title.text()) + "</summary>\n\n" + self.content.source() + "\n\n</details>"

    def remove_block(self):
        dialog = RoundedDialog(self)
        dialog.setWindowTitle("Удалить блок / Delete block")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Удалить блок вместе с текстом? / Delete this block and its text?"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        layout.addWidget(buttons)
        if dialog.exec():
            owner = self.owner
            owner.blocks.remove(self)
            owner.column.removeWidget(self)
            owner.root_editor().active = next(b for b in owner.blocks if isinstance(b, TextBlock))
            self.hide()
            self.deleteLater()
            owner.changed()


def split_blocks(source):
    """Recognize balanced, line-based details blocks without dropping malformed input."""
    lines = source.splitlines(keepends=True)
    result, buffer = [], []
    index = 0
    while index < len(lines):
        image = re.fullmatch(r'<somniloop-image width="(\d{1,4})" data="([A-Za-z0-9+/=]+)" />', lines[index].strip())
        if image and len(image[2]) <= 14 * 1024 * 1024:
            if buffer:
                result.append(("text", "".join(buffer).strip(), ""))
                buffer = []
            result.append(("image", image[2], image[1]))
            index += 1
            continue
        if lines[index].strip() == "<details>" and index + 1 < len(lines):
            summary = re.fullmatch(r"<summary>(.*?)</summary>", lines[index + 1].strip())
            if summary:
                depth, end = 1, index + 2
                while end < len(lines):
                    if lines[end].strip() == "<details>":
                        depth += 1
                    elif lines[end].strip() == "</details>":
                        depth -= 1
                    if depth == 0:
                        break
                    end += 1
                if depth == 0:
                    if buffer:
                        result.append(("text", "".join(buffer).strip(), ""))
                        buffer = []
                    result.append(("toggle", html.unescape(summary[1]), "".join(lines[index + 2:end]).strip()))
                    index = end + 1
                    continue
        buffer.append(lines[index])
        index += 1
    if buffer or not result:
        result.append(("text", "".join(buffer).strip(), ""))
    return result


class RichTextEditor(QWidget):
    textChanged = Signal()

    def __init__(self, source="", parent=None, *, nested=False):
        super().__init__(parent)
        self.outer = None
        self.nested = nested
        self.blocks = []
        self.active = None
        self.loading = False
        self.read_only = False
        dark = QApplication.instance().property("somniloopTheme") == "dark"
        bg, fg, border, hover = (("#202936", "#e5edf9", "#46566c", "#34445c") if dark
                                else ("#ffffff", "#243247", "#d3dce8", "#eaf0fa"))
        self.setStyleSheet(f"""
            QWidget#richTextBody {{ background: {bg}; }}
            QTextEdit#richTextBlock {{ background: transparent; color: {fg}; border: none; border-radius: 0; padding: 4px; }}
            QToolButton {{ background: transparent; color: {fg}; border: 1px solid {border};
                border-radius: 5px; min-width: 24px; min-height: 24px; padding: 2px; }}
            QToolButton:hover {{ background: {hover}; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self.toolbar = QWidget(self)
        self.toolbar.setObjectName("richTextToolbar")
        bar = QHBoxLayout(self.toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        for icon, action, tip in (("bold", "bold", "Bold · Ctrl+B"),
                                  ("italic", "italic", "Italic · Ctrl+I"),
                                  ("strike", "strike", "Strikethrough"),
                                  ("link", "link", "Link · Ctrl+K"),
                                  ("add", "menu", "Insert block · /")):
            button = QToolButton()
            button.setIcon(interface_icon(icon))
            button.setIconSize(QSize(20, 20))
            button.setFixedSize(34, 34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _, value=action: self.format_text(value))
            bar.addWidget(button)
        bar.addStretch()
        root.addWidget(self.toolbar)
        self.body = QWidget()
        self.body.setObjectName("richTextBody")
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.body.installEventFilter(self)
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(8 if nested else 0, 0, 0, 0)
        self.column.setSpacing(4)
        self.column.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll = None
        if nested:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            root.addWidget(self.body)
            self.toolbar.hide()
        else:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setVerticalScrollBar(ActivityScrollBar(self.scroll))
            self.scroll.setWidget(self.body)
            root.addWidget(self.scroll, 1)
            self.setMinimumHeight(180)
        self.set_source(source)

    def root_editor(self):
        return self.outer.root_editor() if self.outer else self

    def eventFilter(self, watched, event):
        if watched is self.body and event.type() == QEvent.Type.MouseButtonPress and not self.read_only:
            editor = next((b for b in reversed(self.blocks) if isinstance(b, TextBlock)), None)
            if editor:
                editor.moveCursor(QTextCursor.MoveOperation.End)
                editor.setFocus()
                return True
        return super().eventFilter(watched, event)

    def changed(self):
        if not self.loading:
            self.dirty = True
            self.textChanged.emit()

    def set_source(self, source):
        self.loading = True
        self.original = source
        for block in self.blocks:
            self.column.removeWidget(block)
            block.hide()
            block.deleteLater()
        self.blocks = []
        depth, ancestor = 0, self.parentWidget()
        while ancestor:
            depth += isinstance(ancestor, ToggleBlock)
            ancestor = ancestor.parentWidget()
        parts = split_blocks(source) if depth < 20 else [("text", source, "")]
        for kind, value, content in parts:
            if kind == "image":
                try:
                    block = ImageBlock(self, base64.b64decode(value, validate=True), int(content))
                except ValueError:
                    block = TextBlock(self, f'<somniloop-image width="{content}" data="{value}" />')
            else:
                block = ToggleBlock(self, value, content) if kind == "toggle" else TextBlock(self, value)
            self.append_block(block)
        if not self.blocks or not isinstance(self.blocks[-1], TextBlock):
            self.append_block(TextBlock(self))
        self.active = next((b for b in self.blocks if isinstance(b, TextBlock)), None)
        self.setFocusProxy(self.active)
        self.dirty = False
        self.loading = False
        self.setReadOnly(self.read_only)
        self.textChanged.emit()

    def append_block(self, block):
        self.blocks.append(block)
        self.column.addWidget(block)

    def source(self):
        if not self.dirty:
            return self.original
        return "\n\n".join(value for b in self.blocks if (value := (
            b.source() if isinstance(b, (ToggleBlock, ImageBlock)) else b.toMarkdown().strip())))

    def insert_image(self, data, editor=None):
        if self.read_only:
            return
        editor = editor or self.active
        owner = editor.owner
        block = ImageBlock(owner, data)
        block.preferred_width = max(40, min(320, round(180 * block.pixmap.width() / block.pixmap.height())))
        block._layout_image()
        cursor = editor.textCursor()
        cursor.removeSelectedText()
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        tail = cursor.selection().toHtml()
        cursor.removeSelectedText()
        trailing = TextBlock(owner)
        trailing.setHtml(tail)
        index = owner.blocks.index(editor) + 1
        for offset, widget in enumerate((block, trailing)):
            owner.blocks.insert(index + offset, widget)
            owner.column.insertWidget(index + offset, widget)
        trailing.setFocus()
        self.root_editor().active = trailing
        owner.active = trailing
        owner.changed()
        return block

    def toPlainText(self):
        return "\n".join(b.title.text() + "\n" + b.content.toPlainText()
                         if isinstance(b, ToggleBlock) else b.toPlainText() for b in self.blocks).strip()

    def setPlainText(self, value):
        self.set_source(value)

    def clear(self):
        self.set_source("")

    def setPlaceholderText(self, value):
        if self.active:
            self.active.setPlaceholderText(value)

    def textCursor(self):
        return self.active.textCursor()

    def setTextCursor(self, cursor):
        self.active.setTextCursor(cursor)

    def setReadOnly(self, value):
        self.read_only = value
        self.toolbar.setVisible(not value and not self.nested)
        for block in self.blocks:
            if isinstance(block, ToggleBlock):
                block.title.setReadOnly(value)
                block.remove_button.setVisible(not value)
                block.content.setReadOnly(value)
            else:
                block.setReadOnly(value)

    def block_menu(self, position=None):
        menu = QMenu(self)
        for title, action in (("Text", "text"), ("Heading 1", "h1"),
                              ("Heading 2", "h2"), ("Heading 3", "h3"),
                              ("Bulleted list", "bullet"), ("Numbered list", "number"),
                              ("Checklist", "check"), ("Check / uncheck item", "checked"),
                              ("Toggle list", "toggle")):
            menu.addAction(title, lambda value=action: self.format_text(value))
        menu.exec(position or self.toolbar.mapToGlobal(self.toolbar.rect().bottomLeft()))

    def format_text(self, action):
        root = self.root_editor()
        editor = root.active
        if editor is None or self.read_only:
            return
        cursor = editor.textCursor()
        if action == "menu":
            return self.block_menu()
        if action == "toggle":
            owner = editor.owner
            toggle = ToggleBlock(owner, cursor.selectedText(), "")
            cursor.removeSelectedText()
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            tail = cursor.selection().toHtml()
            cursor.removeSelectedText()
            index = owner.blocks.index(editor) + 1
            owner.blocks.insert(index, toggle)
            owner.column.insertWidget(index, toggle)
            trailing = TextBlock(owner)
            trailing.setHtml(tail)
            owner.blocks.insert(index + 1, trailing)
            owner.column.insertWidget(index + 1, trailing)
            toggle.toggle.setChecked(True)
            toggle.title.setFocus()
            owner.changed()
            return
        if action in {"h1", "h2", "h3", "text"}:
            fmt = cursor.blockFormat()
            level = int(action[1]) if action.startswith("h") else 0
            fmt.setHeadingLevel(level)
            cursor.setBlockFormat(fmt)
            char = QTextCharFormat()
            char.setFontWeight(QFont.Weight.Bold if level else QFont.Weight.Normal)
            char.setFontPointSize({1: 20, 2: 17, 3: 14}.get(level, 11))
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.mergeCharFormat(char)
        elif action in {"bullet", "number", "check"}:
            fmt = QTextListFormat()
            fmt.setStyle(QTextListFormat.Style.ListDecimal if action == "number" else QTextListFormat.Style.ListDisc)
            cursor.createList(fmt)
            if action == "check":
                block = cursor.blockFormat()
                block.setMarker(QTextBlockFormat.MarkerType.Unchecked)
                cursor.setBlockFormat(block)
        elif action == "checked":
            fmt = cursor.blockFormat()
            fmt.setMarker(QTextBlockFormat.MarkerType.Unchecked if fmt.marker() == QTextBlockFormat.MarkerType.Checked
                          else QTextBlockFormat.MarkerType.Checked)
            cursor.setBlockFormat(fmt)
        elif action == "link":
            dialog = RoundedDialog(self)
            dialog.setWindowTitle("Ссылка / Link")
            layout = QVBoxLayout(dialog)
            field = QLineEdit(cursor.charFormat().anchorHref())
            field.setPlaceholderText("https://…")
            layout.addWidget(field)
            error = QLabel("Используй https://, http:// или mailto: / Enter a web or email link")
            error.setWordWrap(True)
            error.hide()
            layout.addWidget(error)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            polish_dialog_buttons(buttons)
            buttons.accepted.connect(lambda: dialog.accept() if safe_link(field.text()) else error.show())
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if not dialog.exec():
                return
            value = field.text()
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(value.strip())
            fmt.setFontUnderline(True)
            if cursor.hasSelection():
                cursor.mergeCharFormat(fmt)
            else:
                cursor.insertText(value.strip(), fmt)
        else:
            fmt = QTextCharFormat()
            current = cursor.charFormat()
            if action == "bold":
                fmt.setFontWeight(QFont.Weight.Normal if current.fontWeight() >= QFont.Weight.Bold else QFont.Weight.Bold)
            elif action == "italic":
                fmt.setFontItalic(not current.fontItalic())
            elif action == "strike":
                fmt.setFontStrikeOut(not current.fontStrikeOut())
            cursor.mergeCharFormat(fmt)
            editor.mergeCurrentCharFormat(fmt)
        editor.setTextCursor(cursor)
        editor.setFocus()


class RichTextView(RichTextEditor):
    """The same document renderer with interactive toggles but no editing controls."""

    def __init__(self, source="", parent=None):
        super().__init__(source, parent, nested=True)
        self.setStyleSheet(self.styleSheet() + "QWidget#richTextBody {background: transparent;}")
        self.setReadOnly(True)

    def setText(self, source):
        if source == self.original and not self.dirty:
            return
        self.set_source(source)
        self.setReadOnly(True)

    def setWordWrap(self, enabled):
        pass

    def text(self):
        return self.source()

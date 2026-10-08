# Rich text fields

Task and habit descriptions, task-item details, bio, diary notes, people biographies,
people notes and clarification answers share the native `RichTextEditor`.
Names and line-separated task/fact inputs remain plain text.

Use the toolbar or Ctrl+B / Ctrl+I / Ctrl+K for emphasis and links. The + menu
and `/` on an empty line offer headings, lists, checklists and toggle blocks.
Typing `# `, `## `, `### `, `- `, `1. `, `[ ] ` or `> ` starts the corresponding
block (`>` creates a toggle). Inline `**bold**`, `*italic*`, `~~strike~~`,
backticks and `[label](https://example.com)` convert during typing.

Toggles can contain formatted text and nested toggles. Their arrow only controls
visibility; collapsing never removes content. Deleting a toggle asks for confirmation.
Text editing has Qt undo/redo; structural toggle insert/delete is not part of that
text undo history. Ctrl+click follows links while editing; plain click follows them
in read-only views. Only http, https and mailto links are opened. Images are not
fetched from pasted documents or local file paths.

Storage remains text: Markdown, with balanced `<details>` / `<summary>` blocks.
No schema migration, external editor service or Notion account is required.
Unedited existing content is saved byte-for-byte. Changing formatted content
serializes it to Markdown. This is a focused local block editor, not a complete
Notion implementation (no databases, collaboration or embedded media).

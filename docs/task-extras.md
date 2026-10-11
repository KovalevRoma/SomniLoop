# Task calendars and attachments

The task date popup outlines today in blue independently of the selected day.
Both calendar implementations refresh the today indicator across midnight.
Project task dates carry a dot and a tooltip listing task names and their
assigned `due_time`; an empty time is shown explicitly. These are appointment
times, not durations. Completed tasks remain visible in project date context;
manually archived unfinished tasks are excluded.

The project's task view includes an Add task button with the project preselected.
The editor and row date popup query the same project-calendar resource.

Paste clipboard images with Ctrl+V directly into the rich-text editor. Drag the
bottom-right handle to resize, preserving aspect ratio. Images and their widths
are serialized as self-contained `somniloop-image` blocks, so they survive task
reopening, database backup and JSON export without depending on an external file.
Each image is limited to ten MB and forty megapixels. Cancel discards edits.
Read-only views display the same blocks without resize/delete controls.

Legacy `task_images` attachments are brought into the document when editing a
task. They leave the legacy table only after Save; Cancel preserves them. The
legacy table remains readable for existing backups and exports.

The birthday button opens a child dropdown, never a native popup or an additional
Wayland surface. Outside clicks and Escape close it. Its virtualized list uses
the shared activity scrollbar. It lists each
person's next birthday in chronological order and omits conflicting birth dates.
The button count represents birthdays within thirty days, including today.
Desktop reminders and their dismissal state are independent of this list.

Checks: `tests/test_task_extras.py`; Linux preview: `tools/smoke_task_extras.py`.

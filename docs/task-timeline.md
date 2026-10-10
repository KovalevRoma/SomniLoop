# Task timeline

The workspace displays a continuous due-date chart only in the Chart tab,
immediately after To sort. There is no miniature or separate expanded chart.
The horizontal scrollbar and trackpad/wheel move the viewport; month labels,
gaps and dividers separate months. Adjacent daily bars have a one-pixel gap.
Opening the tab starts at the earliest unfinished overdue date, or today when
there are no overdue tasks. The Today button places today at the left edge.
The range includes every dated task and at least one year back/two years ahead.

- Each column counts tasks, not checklist items, habits or estimated hours.
- Project colors identify segments. Unassigned tasks use a neutral color.
- Unfinished overdue tasks are bright red on their original dates. A task
  without a time becomes overdue the following day; timed tasks use local time.
- Completed tasks, including automatically archived completion history, retain
  their due date and project color, with hatching. Their visibility is toggleable.
- Manually archived unfinished tasks are excluded.
- No-date tasks have a separate button and list, outside the date axis.
- Hover shows counts and project/title details; click opens the day's task list.
  A list item opens the existing task editor. Keyboard arrows select a day and
  Enter opens it.

`ui/task_timeline.py` contains the read-only projection and Qt widgets. No schema
changes or dependencies are required. Only visible days are painted, on demand;
there are no animation timers or per-day widgets. The projection is cached by
database change count and date. Resize and refresh preserve the visible date.
The vertical scale is shared across the loaded date range to avoid jumping bars.

The count axis starts at zero, with integer ticks and subtle gridlines. Totals
appear above nonempty bars when space permits. Weekend shading is limited to
date labels, and today's date is filled rather than outlined like a selection.
Below the chart, a borderless Project / Remaining table counts only unfinished
dated tasks in the visible date range (including partially visible days).
It updates with scrolling, resize and data edits, independently of the completed
visibility toggle. Colored project dots also serve as the project legend.
Projects are grouped by ID; unassigned tasks have their own row. No completion
counts, progress bars or additional charts are included in the table.

The two-column Project / Remaining table occupies 5/7 of the lower section.
Only internal cell separators are drawn. Weekdays appear below dates on the
chart, not in the table. The remaining 2/7 shows all
unfinished overdue tasks (independent of the chart viewport), followed by quick
captures under “На разбор” / “To sort”, the new UI label for Inbox. Links open
the existing task editor or capture scheduling form; storage is unchanged.

Small vector crowns beneath chart dates mark birthdays from People. Hovering
or clicking a crown shows all names for that day. The sidebar's Birthdays section
lists birthdays in the visible date range. Dates without years are supported;
February 29 follows the application's February 28 convention in non-leap years.
Unresolved conflicting birth dates are omitted. Birthday projections are cached
per year and invalidated when repository data changes; scrolling makes no queries.

Verification: `tests/test_task_timeline.py` and
`QT_QPA_PLATFORM=wayland .venv/bin/python tools/smoke_task_timeline.py`.

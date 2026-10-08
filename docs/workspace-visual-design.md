# Workspace visual design

The workspace uses compact, aligned task rows instead of large cards. Titles and
dates remain visible. Clicking the row opens the full task editor; titles are plain
text and there is no separate Open button. Project and date cells open small editors.
The localized date popup supports direct date entry, a calendar, optional time and
Clear, following the date-property pattern documented by
[Notion](https://www.notion.com/en-gb/help/database-properties). Task timers
and the Start action have been removed.
The main viewport retains one vertical scrollbar. Dates use Today, Tomorrow and
Overdue labels, with the exact timestamp available as a tooltip.

Projects are areas of life, with a name and a user-selected color (Edit → Project color).
They have no required goal, outcome or deadline. Saturated color fills identify linked tasks,
with readable foregrounds in both themes and stronger project accents. Project
names remain visible, so color is not the only identifier. Overdue badges
remain distinct from project identity. Priority is no longer exposed or used
for sorting. Existing metadata is retained for backward-compatible exports.

Projects use a compact adaptive grid, with a neutral circular add button below
the last row rather than in the toolbar. Drag the empty
tile surface (buttons and inputs remain interactive): a full
tile image follows the pointer, while a dashed placeholder previews the new slot.
Dropping commits the order; cancelling restores the original order. Arrow buttons
are removed. Tasks open by default, with All, Today, Overdue and Next 7 days filters;
there is no My Day tab. New tasks have an optional, initially hidden checklist.
Order and color persist in SQLite and JSON exports. Older databases and exports
receive defaults without changing task schedules or completion history.

The companion can be moved by dragging its emotion badge. The badge fits all
regular Russian and English labels at the existing 10-point bold font and sits
four logical pixels below the measured visible model. Position persists on release.

## Design references

- [NN/g: Data Tables — Four Major User Tasks](https://www.nngroup.com/articles/data-tables/):
  compact presentation, adjacent data, scanning and discoverable row actions.
- [Atlassian: Accent colors](https://atlassian.design/foundations/color/accents):
  categorical accents and accessible use of color.

These inform the design; this particular implementation has not undergone a
controlled usability study and does not claim a measured productivity increase.

# Productivity workspace

## Current interface (October 2026)

The sections are Tasks, Habits, Projects and Inbox. My Day and priority controls
have been removed. Projects are areas of life with only a name and color, not
goals or deadlines. Tasks sort by date and can be filtered by Today, Overdue or
Next 7 days. Edit combines task fields and project assignment. Checklists are
optional and hidden by default for new tasks; existing checklists are preserved.

Projects use a compact adaptive grid and contrasting project colors.
The neutral circular add button follows the last tile row in the scrollable content.
There is no detailed-tile mode; legacy size settings are ignored.
Drag by the empty tile surface: a full tile image follows the cursor and a dashed
slot previews insertion. The viewport scrolls near its edges. Dropping commits
the order; cancelling leaves storage unchanged. Color and order survive restart.
The compact header displays date, weekday and time on one line.
Task timers, focus sessions and the Start action have been removed.

Click + Task inside a project to open the full task form over a dimmed backdrop,
with the project preselected and no required date or checklist. Clicking a task
row opens the same editor; titles are not editable inline. Project/date cells remain
independent controls. Dates use a compact calendar with optional time and Clear.
Task rows support one-click
completion. A completed row stays in place briefly, with Undo restoring its exact
previous checklist state. Undo refuses to overwrite subsequent edits.
Select mode supports bulk project assignment, date changes and archiving.
Changing only the bulk date preserves each task's existing time.

The following notes document the original design rationale; references to My Day,
priorities and project outcomes below describe the superseded iteration. Their
stored metadata is retained for compatibility, but is no longer part of the UI.

The desktop window now opens a daily workspace rather than three competing lists.
It is designed for a user who struggles with prioritizing, distractions and forgotten
work, and mixes teaching, professional projects, home responsibilities and habits.

## Research and design decisions

These are evidence-informed design choices, not a promise to maximize productivity.
The exact layout, three-action suggestion and timer lengths are product decisions,
not scientifically established optimal numbers.

- [Nielsen Norman Group: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
  recommends making primary actions prominent while keeping secondary functionality
  accessible. SomniLoop separates daily work, the complete task list, habits,
  projects and capture instead of displaying every feature at once.
- [NN/g: Complex Application Design](https://www.nngroup.com/articles/complex-application-design/)
  discusses reducing clutter without removing capability and retaining context
  after interruptions. Project outcomes and task-level next actions support this.
- [APA: Multitasking and Switching Costs](https://www.apa.org/topics/research/multitasking)
  describes costs of task switching. Our application-level inference is to offer
  one-task focus sessions and suppress unsolicited companion motions during them.
- [Gollwitzer & Sheeran, 2006](https://www.sciencedirect.com/science/article/pii/S0065260106380021)
  reviews implementation intentions. A concrete next action and chosen work day
  make intentions more explicit; this UI is not a full implementation-intention intervention.
- [Harkin et al., 2016](https://pubmed.ncbi.nlm.nih.gov/26479070/)
  reviews experimental progress-monitoring interventions. We expose actual completed
  tasks rather than inventing a productivity score.
- [Todoist project documentation](https://www.todoist.com/help/todoist/features/introduction-to-projects-TLTjNftLM)
  and [glossary](https://www.todoist.com/help/todoist/get-started/todoist-glossary-cA60laWMH)
  provide product examples of project grouping, capture and separating intended
  work dates from deadlines. These are workflow precedents, not research proof.

## Daily workflow

1. Capture a thought with **Ctrl+K**, type its title, press Enter. It stays in Inbox
   without a fabricated deadline. Schedule it deliberately when reviewing Inbox.
2. Create a project such as Teaching, Work, Home or Vacation and describe its outcome.
   Add a task directly from the project, or use **Organize** on existing work to link it.
   Habits also expose **Project and priority** in their action menu.
3. Set a priority (Normal / Important / Critical), optional work day and next action.
   The work day is separate metadata: moving it never changes existing task dates,
   checklist history or habit schedules.
4. **My day** shows explicitly chosen unfinished actions, then fills available slots
   with up to three due suggestions. Suggestions are labeled, not silently selected.
   More than three user-selected actions are allowed and never hidden.
5. **Start** opens a one-task focus session, with 15/25/50-minute options and pause/resume.
   Time uses a monotonic clock. Expiry never completes a task. **Mark completion**
   opens the existing checklist controls so the user decides what was actually done.
6. Review overdue work, the next seven days and past daily intentions in **Tasks & plans**.
   The header shows a dated task when it is within 15 minutes or already due today.
   This is an in-app cue, updated while the app runs, not an OS alarm service.

Sorting is transparent: unfinished, priority, due/overdue, date/time, title, stable ID.
No LLM guesses which responsibilities matter most. Set priorities yourself.

## Projects and progress

Projects are arbitrary user-created groupings. They can contain existing one-off
tasks, manually dated plans and habits. Archiving a project does not archive its
members; the project can be restored. The project view shows the next open action,
completed one-off tasks / all linked one-off tasks, and the number of linked
plans/habits. The progress bar measures **one-off task completion**, not overall
project effort or perpetual habit completion. Completed tasks remain available
through the existing archive.

## Persistence and compatibility

Three additive SQLite tables store projects, work metadata and captured ideas.
The original task/tracker/calendar tables and history remain authoritative.
Foreign keys validate projects and delete triggers remove orphan task metadata.
Inbox conversion is a single transaction, including project assignment.
The existing JSON export includes these tables; older v3 exports restore with an
empty workspace extension. Restore still makes a backup first. Do not round-trip
new exports through an older binary that does not understand the extension.

Existing planner, calendar, archive, graph, languages, light/dark themes and
companion reactions remain available. The legacy dashboard components are retained
for habit controls and focused regression coverage; MainWindow enables the new workspace.

The daily list reuses keyed row widgets; project statistics use SQL aggregation,
not all historical habit marks. No cloud account or new package is needed.

## Verification

`tests/test_productivity.py` covers metadata, date separation, persistence, project
archiving, atomic capture conversion, deletion cleanup and JSON compatibility.
`tests/test_productivity_ui.py` covers resizing, both themes, empty states,
sorting, capture and cancel behavior. `tools/smoke_productivity.py` opens the
real MainWindow on a temporary database and saves screenshots of all views.

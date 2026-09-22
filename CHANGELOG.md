# Next

- Added bounded adaptive recovery and persistent split checkpoints for truncated/repetitive connection responses; optional failures no longer abort processing everyone else or silently count as success.
- Replaced fixed stage percentages with logical-work counts and a separate exact people-stage counter; partial connection results remain visibly incomplete and resumable after restart.
- Removed the 10,000 inferred-edge abort; regression tests cover 198 dossiers, 19,503 pairs, cancellation, and persisted recovery.
- Hid place nodes from the graph without deleting stored data; added an opt-in local-LLM people-connections skill with grounded citations, temporal checks, caching, cancellation, and visibly hypothetical edges.
- Made the graph inspector optional: hidden initially, dismissible by its close button, Escape, or empty-canvas click; refresh preserves dismissal.
- Switched input dialogs to native opaque windows without custom input masks; added window-routed modal Add/Save/Cancel regression tests, also checked on Wayland.
- Added inline required-name feedback to planner and tracker creation, without a second blocking dialog.
- Replaced the three-column home screen with a unified Today queue, one scroll surface, and a responsive 2:1 library/agenda layout.
- Added keyed card reuse, search/filter/sort controls, compact action menus, partial marks, localized dates, and the unified Add menu.
- Preserved old SQLite data with additive partial-state columns, bounded month reads, and cached annual streak aggregates.
- Made Bio Cancel discard drafts, added missing cancel buttons, cooperative settings-worker cancellation, and non-blocking feedback for save/cancel clicks.
- Added home-screen regressions for responsive geometry, overflow, empty states, sorting, quick marks, archives, and actual dialog button clicks.
- Rebuilt the knowledge graph workspace with indexed search, relationship filters, a resizable human-readable inspector, source navigation, and neighborhood focus.
- Added persisted coordinates, pinning, overview clusters, a clickable minimap, keyboard navigation, and theme-aware low-detail rendering.
- Split graph data, rendering, spatial force layout, and details into independent modules; added collision, performance, persistence, and contradiction regressions.
- Recover missing explicitly named people with focused LLM extraction, detect repeated model output, and keep progress estimates tied to completed analysis work.
- Focused the main navigation on habits, planning, and the people graph.
- Added one-click habit updates to dashboard cards and clearer dated-plan validation.
- Kept graph context when filtering categories and rendered relationship labels on edges.
- Connected extracted entities to the person whose notes mention them when possible.
- Added atomic private JSON exports, JSON restore with a safety backup, and seven daily backups.
- Added daily desktop birthday reminders through a user systemd timer.
- Switched visible dates to Russian month names and web links to the default browser.
- Fixed the people editor layout at its minimum supported window size.
- Made people edits instantaneous; LLM extraction now runs only from Refresh graph.

# 0.3.0

## Interface

- Separate planner column, task and habit archive, and a birthday notification drawer.
- Rounded calendar cells, week numbers, an outlined current day and scroll-based date controls.
- Per-date manual subtasks with safe HTTP(S) links opening in Firefox.
- Diary autosave, modification timestamps and brief save feedback.
- Rounded window surfaces with native window decorations retained.
- Full graph search, zoom controls, stable initial framing and category-specific node shapes.

## Knowledge processing

- Full diary and biography input, person story revisions and source-linked facts.
- Schema-constrained JSON, response validation, smaller-chunk retries and atomic graph updates.
- CPU-only shared model loading, incremental extraction cache and cancellation between requests.
- Person birth dates, optional birth years, interests, age snapshots and historical facts.
- Highlighted contradictions; uncertain birth dates do not generate reminders.
- Removed event and diary-entry node categories.

## Storage and maintenance

- Additive SQLite schema migration with a pre-upgrade backup.
- One-off task completion archives the task; restoration clears its completion marks.
- Bulk cached tracker history reads and lightweight diary list queries.
- English code comments, Ruff formatting and expanded regression tests.

Native GNOME decorations, installed Firefox and a real GGUF inference run still need
desktop verification. Automated graph tests use controlled responses and the local
rule-based extractor; they do not establish a model's factual accuracy.

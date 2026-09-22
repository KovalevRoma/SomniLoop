# SomniLoop

**Habits, daily plans, and the people in your life — in one local-first desktop app.**

SomniLoop combines a habit tracker, a lightweight planner, and a personal knowledge
graph. Keep track of what needs doing today, write down what you know about people,
and explore connections without sending your notes to a hosted AI service.

Built with **Python, PySide6, and SQLite**. Developed primarily on **Ubuntu 24.04**.

> **Status: hobby project under active development.** The planner and graph UI are
> usable, but local-LLM extraction and relationship discovery are experimental.
> Keep backups of important data. Other operating systems are not yet verified.

## Features

### Habits and planning

- A unified **Today** view for habits, dated plans, and due or overdue one-off tasks.
- Quick completion buttons, checklists, streaks, and editable calendar history.
- Daily, interval, weekday, weekly-quota, monthly, and yearly schedules.
- Manually scheduled plans with different checklist items for each date.
- Search, sorting, collapsible details, and an archive with restoration.
- A compact, responsive dashboard with light and dark themes.

Checklist items are either complete or incomplete. A whole day or task can still
be partially complete when only some items are done. Partially completed scheduled
days currently preserve a streak. Completed one-off tasks move to the archive.

### People and the knowledge graph

- Editable people profiles, birthdays, contact details, and free-form notes.
- Source-linked facts, history, and visible conflicting information.
- An interactive graph with search, filters, neighborhood focus, zoom, and a minimap.
- Saved node positions, pinning, and grouped views when zoomed out.
- Optional local-LLM extraction and suggested connections based on education or work.
- Birthday notifications, including optional Linux desktop reminders.

Suggested connections are **hypotheses, not proof that two people know each other**.
Sharing an employer or university does not automatically mean being friends,
coworkers on the same team, or classmates.

### Data and imports

- Local SQLite storage, JSON export/restore, and automatic backups.
- Telegram Desktop JSON import with a contact-review step in Settings.
- Import of prepared dossiers using the app-specific `somniloop.dossiers.v1` format.
- Russian and English UI support; some graph and import messages are still Russian.

Telegram import is optional, not a requirement for using the planner or graph.
A prepared dossier file is not the same format as a full application backup.

## Getting started

### Requirements

- Python **3.11 or newer** and a desktop environment capable of running Qt.
- Git and Python's `venv` support for the source installation below.
- Optional: `llama-cpp-python` and a compatible GGUF model for local AI features.

### Run from source

```bash
git clone https://github.com/KovalevRoma/SomniLoop.git
cd SomniLoop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m somniloop
```

This installs the app without the optional LLM dependency. The planner does not
require a model; a limited rule-based graph extractor is also available.
Cloning a private repository requires GitHub access to it.

### Ubuntu desktop integration

From the project directory:

```bash
sudo apt update
sudo apt install python3-venv build-essential cmake
./install.sh
```

The installer creates `.venv`, installs the app in editable mode, attempts to install
local LLM support, and adds an application-menu launcher. If LLM installation fails,
it falls back to the base app. It also installs a user-level systemd reminder timer
when systemd is available; desktop notifications use `notify-send` when available.

Keep the project folder in place: the launcher runs its source files. To launch
directly afterward, use `./run-dev.sh`.

## Using the local AI

Install the optional backend inside the virtual environment:

```bash
python -m pip install -e '.[llm]'
```

In **Settings**, download the offered Qwen2.5-1.5B-Instruct Q4_K_M model or select a
compatible local GGUF file. A dedicated GPU is not required. Installing the backend
may require native build tools; speed depends on hardware, model, and input size.

**Saving a person does not run the LLM.** Analysis starts when you explicitly choose
**Refresh graph**. The update roughly follows this pipeline:

1. Collect profile information, people notes, and other stored sources.
2. Extract structured facts from text fragments, reusing cached results where possible.
3. Assemble dossiers and check conflicting claims.
4. Build relationships; optionally run the additional people-connection discovery pass.
5. Save the result and refresh the graph view.

The optional connection pass currently asks the LLM to extract affiliations from
people's dossiers, then compares those affiliations in ordinary code. It does not
make one LLM request for every possible pair of people.

Malformed, truncated, or unsupported answers can trigger smaller-fragment retries.
Successful fragments are cached. If optional connection discovery remains incomplete,
the app can save the main graph and offer **Continue finding connections**. A completed
pass through the queue does not necessarily mean every person's analysis succeeded.

## Known limitations

- **Connection discovery can be very slow.** Repeated extraction and validation
  failures can turn a large update into hours of work. A small local model can still
  produce incorrect or incomplete answers despite JSON validation.
- **Progress is work-based, not time-based.** The current person's queue position,
  successfully completed people, and cache hits are different counters. The ETA can
  be misleading when many attempts fail; it is not a completion-time guarantee.
- **Names are not reliable identities.** Current name-based merging can conflate
  different people with identical names. Review imported contacts and inferred facts.
- **English localization is incomplete**, especially around graph processing and imports.
- **Desktop behavior varies.** Native file dialogs, notifications, window decorations,
  and some modeless windows depend on the desktop environment. Not every window is
  an embedded modal overlay.
- **Data is not encrypted by the app.** Local-first does not mean protected from other
  users or programs with access to your files.

## Privacy and backups

Inference runs locally. Dependency installation and model downloads need internet
access; ordinary local analysis does not require a cloud AI account.

Default Ubuntu data location:

```text
~/.local/share/SomniLoop/
├── somniloop.db     # Personal data, settings, graph, and extraction cache
├── backups/        # Automatic and pre-restore backups
└── models/         # Downloaded models
```

Use **Settings → Export JSON** before major changes or imports. Exports, backups, and
the extraction cache may contain sensitive personal information. Protect them just
like the main database; disk encryption is separate from the app.

The repository excludes Telegram exports in `TG/`, databases, model files, environment
files, and common local artifacts. **Git is a source-code backup, not a backup of your
personal SomniLoop data.** Review files before committing or sharing them.

To try the app with a separate data directory on Linux:

```bash
SOMNILOOP_DATA_DIR=/tmp/somniloop-demo ./run-dev.sh
```

Use a new empty directory for a fresh demo; `/tmp` is temporary, not durable storage.

## Updating

Finish or cancel any active graph update, export a backup, and close the app before
updating its source. Preserve any local code changes before pulling.

```bash
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
python -m somniloop
```

Use `-e '.[llm]'` instead if you also need to install or update the optional backend.
The personal database lives outside the checkout. Editable installs pick up source
changes on restart; the running process does not hot-reload Python code.

## TODO / near-term roadmap

These are planned improvements, **not features already implemented**.

### Reliability and graph performance

- [ ] Extract reusable structured affiliations during dossier creation, avoiding a
      second full LLM reading pass just to discover connections.
- [ ] Recompute only relationships affected by changed people or facts.
- [ ] Make retry budgets and failure reasons clearer; reduce repeated requests that
      cannot improve a result, while preserving successful work.
- [ ] Separate attempted, successful, failed, and cached work in the progress UI;
      correct ETA behavior when processing continues past failures.
- [ ] Benchmark real models with anonymized datasets, including roughly 200 people;
      measure runtime, extraction quality, cancellation, and resume behavior.
- [ ] Improve identity matching with stable IDs and explicit confirmation for
      ambiguous same-name contacts.

### Everyday usability

- [ ] Finish English localization of graph, import, and error messages.
- [ ] Expand real-desktop checks for resizing, keyboard focus, and Save/Cancel behavior.
- [ ] Polish dense graph layouts and make uncertain relationships easier to review.
- [ ] Document the dossier JSON schema with a small, synthetic import example.

### Project maintenance and possible next steps

- [ ] Add GitHub Actions for tests and linting.
- [ ] Add current screenshots using synthetic data and a short first-run walkthrough.
- [ ] Choose a license and document supported platforms and release packaging.
- [ ] Evaluate embeddings for semantic search and candidate relationship discovery;
      keep factual evidence separate from similarity scores.
- [ ] Plan optional encryption and safer handling of sensitive exports.

## Development

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen python -m pytest -q
ruff check src tests tools
```

Tests cover scheduling, persistence, imports, graph processing, and offscreen UI
behavior. LLM tests use controlled responses: passing tests do **not** establish the
accuracy or speed of a real GGUF model. Desktop integration also needs manual testing.

Generate UI previews with disposable sample data:

```bash
QT_QPA_PLATFORM=offscreen python tools/preview_ui.py /tmp/somniloop-previews
```

### Project layout

```text
src/somniloop/
├── core/          # Storage, scheduling, imports, models, and translations
├── knowledge/     # Extraction, validation, connections, and LLM integration
├── ui/            # PySide6 screens, graph canvas, and reusable controls
├── assets/        # Application icon
├── app.py         # Application setup
└── reminders.py   # Birthday notification runner
tests/             # Core and UI regression tests
tools/             # Development helpers
assets/            # Linux launcher and reminder service templates
```

For bug reports, include reproduction steps, platform, and relevant error messages.
For LLM issues, include the model name and failing stage. Use synthetic or redacted
examples — do not attach private chat exports or your personal database.

See [CHANGELOG.md](CHANGELOG.md) for development history.

## License

No license has been selected yet. Public availability, if enabled later, should not
be interpreted as an open-source license grant.

# Epsilon Live2D character

SomniLoop uses **Live2D Cubism SDK for Native 5 R4_1**, its official C++
Framework/OpenGL renderer, and proprietary Cubism Core. Epsilon's full official
`epsilon_pro/runtime/Epsilon.model3.json` is the entry point. No browser, cloud
API, API key, GIF, video, spritesheet or pre-rendered animation is involved.

## Install on Ubuntu/Linux

Prerequisites: CMake, a C++17 compiler, desktop OpenGL and GLEW development files
(`cmake`, `g++`, `libgl1-mesa-dev`, `libglew-dev` on Ubuntu). PySide6 Essentials
already provides the Qt OpenGL bindings used here.

Read the license links below, then explicitly accept them when running:

```bash
.venv/bin/python tools/setup_live2d.py --accept-licenses
.venv/bin/python -m somniloop
```

The setup tool downloads archives only from Live2D's official distribution host,
checks pinned SHA-256 digests, validates extraction paths and builds locally with
two compiler jobs. A changed upstream archive fails the checksum check rather
than silently installing new content. No downloads occur when the app starts.

Local, Git-ignored paths:

- `.live2d/epsilon/epsilon_pro/runtime/`: unmodified model, three texture atlases,
  motions, expressions, physics and display-info files; relative paths preserved.
- `.live2d/epsilon/epsilon_pro/Readme.txt`: original model attribution/license note.
- `.live2d/sdk/CubismSdkForNative-5-r.4.1/`: official SDK, shaders and license files.
- `.live2d/build/libsomniloop_live2d.so`: locally compiled bridge and linked Core.

For an installed wheel or another location, set `SOMNILOOP_LIVE2D_DIR` to the
absolute installation directory and pass the same path as `--root` to setup.
The current tested build is Linux x86-64. The build recipe includes a macOS
OpenGL branch, but macOS has **not** been verified. Linux ARM needs a compatible
official Core binary and an adjusted CMake Core path; it is not supported by the
bundled setup. No Windows-only APIs are used.

## Architecture and lifecycle

`MainWindow` owns `window.character`, a `Live2DOverlay` (`Live2DCharacter` alias).
It is recreated on settings/theme changes and disposed before the window closes.
`resources.py` validates the manifest and referenced files. `renderer.py` owns
an isolated Qt OpenGL context, offscreen surface and framebuffer. `bridge.cpp`
uses the official Cubism Framework for MOC3 loading, texture rendering, motions,
expressions, eye blinking, breathing, gaze and physics.

The model is evaluated and rendered live at up to 30 FPS. Qt composites that
frame with alpha over the existing widgets. A small GPU-to-CPU frame readback
is intentional: it avoids native child-window stacking problems with the app's
embedded dialogs. This is a live render target, not a stored animation.

The character is bounded to the lower-right of the main window. The render
projection preserves model proportions. Rendering pauses when hidden, minimized
or a modal overlay is open. A lightweight 200 ms visibility check remains active.
Textures, motions, framebuffer, context, SDK state, timers and event filters are
released on teardown. Only one character renderer is supported per process.

Failure to load the model, library, shaders, textures or OpenGL disables the
character without disabling the planner. The reason is logged and shown in the
character settings. Headless Qt `offscreen`/`minimal` platforms do not render it;
use X11/Xvfb or Wayland for graphics checks. Native graphics-driver crashes cannot
be caught by Python; the smoke test runs in a separate process for this reason.

## Settings

Settings → **Live2D character — Epsilon** (Russian labels are also provided):

- Enabled: show or disable the character.
- Scale: 0.5–2.0, further constrained by window size.
- Right/bottom offsets: logical pixels, clamped to keep the character inside.
- Opacity: 0.1–1.0.
- Idle animations: replay the shipped idle clip; stop after disabling.
- Interaction: cursor-following gaze and zone-specific touch/stroke expressions.

Interaction is off by default: every click passes through. When enabled, an
alpha-derived silhouette mask limits interception to the character, not its
transparent bounding rectangle. The padded, full-resolution mask refreshes every
three frames without trimming antialiased edges.
Save persists preferences in the existing settings table; Cancel discards drafts.
No new tables or changes to task/graph storage are required.

## Emotion badge and touch zones

A translucent, elongated hexagon below Epsilon shows the current expression in
Russian or English. It does not take mouse input. Space is reserved below the
character, including after resize; the badge hides with the character and modal
dialogs. Expressions return to `Normal` after five seconds (task milestones may
last longer). This is an animation status, not a claim of actual feelings.

Enable **React to cursor and clicks** in character settings to use touch zones.
They are computed from the current deformed Cubism part vertices, projected with
the same matrix as the renderer, then divided into anatomical regions. Invisible
pixels do not register. Epsilon's `HitAreas` manifest remains unchanged. The model
faces forward: the requested backside zone is represented by the hips/shorts
region, not a separate rear-facing mesh.

Rules, in priority order:

1. The fifth consecutive repetition of the same zone/gesture produces `Angry`.
2. Chest, hips/shorts and legs normally produce `Angry`. Chest or hips immediately
   following an active `Smile` produce `Blushing` instead; legs still produce `Angry`.
3. Stroking the head or cheek produces `Smile`.
4. An ordinary tap after at least 60 seconds without contact (including the first
   contact) produces `Surprised`. Recent ordinary taps otherwise keep the emotion.

To stroke, hold the left button, move at least 12 logical pixels (scaled for a
larger character), then release within the same zone. One drag is one stroke,
regardless of how many mouse-move events it generates. Leaving the zone cancels
the gesture. Changing zone/gesture or waiting 60 seconds resets the repetition
count. Touch feedback temporarily takes priority over task-completion feedback.
All state is local and ephemeral; no touch history is saved.

The native bridge adds `sl_part_bounds`; rebuild it with
`cmake --build .live2d/build -j2` after updating sources. Restart an already-running
app to load the rebuilt library.

## Animation controller

```python
character = window.character
character.show()                 # Also supports hide(), setVisible(bool)
character.startIdle()            # stopIdle() stops idle clips, not breathing
print(character.motions)         # Actual manifest groups and clip references
print(character.expressions)     # Actual manifest expression names
character.playMotion("Tap", 0)
character.playRandomMotion("FlickUp")
character.setExpression("Smile.exp3.json")
character.setExpression("Blushing.exp3.json")
character.resetExpression()
character.lookAt(0.5, 0.2)        # Normalized [-1, 1]; positive Y is upward
character.setParameter("PARAM_ANGLE_Z", 5.0)
```

Call on the GUI thread after `loaded` is emitted. Unknown motion/expression/
parameter names are rejected. Parameter overrides persist until teardown and
are applied after physics; avoid overriding physics outputs unintentionally.
Inspect `character.resources.display_info` for Epsilon's parameter metadata.

Actual groups: `Idle` (1), `Tap` (4), `Flick3` (2), `FlickUp` (2),
`FlickDown` (2), `Flick` (2), `Shake` (2).
Actual expressions: `Angry.exp3.json`, `Blushing.exp3.json`, `f01.exp3.json`,
`f02.exp3.json`, `Normal.exp3.json`, `Sad.exp3.json`, `Smile.exp3.json`,
`Surprised.exp3.json`. Names are discovered from the manifest, not fabricated.

There is no `Greeting` clip in Epsilon: the startup greeting uses existing
`Tap/0` with `Smile.exp3.json`. Non-looping motions return to the shipped idle
motion when idle is enabled. A random idle clip is requested every 20–40 seconds
(Epsilon supplies only one idle clip). Expressions return to neutral after five
seconds, or earlier via `resetExpression()`. Eyes blink automatically and the
SDK simulates breathing and the model's four hair-physics outputs. Audio is not
included in Epsilon's manifest. Optional spoken feedback uses the local system
speech engine, not an audio asset from the model.

## Quality and task feedback

The character renders at twice the physical pixel resolution and is smoothly
downsampled by Qt. The longest render-buffer edge is capped at 1536 pixels to
bound GPU memory and readback work. Original model textures remain unchanged;
supersampling smooths edges but cannot invent missing texture detail.

Task completion triggers the real `Smile` expression and a subtle head movement.
Completing all currently due checklist items extends the smile. The controller
compares existing dashboard snapshots (and cached day summaries for completed
overdue plans that leave the pending list): refreshes, newly created items, deletions,
undo and date rollover do not produce praise. A completion is celebrated at most
once per item/day within the current dashboard session. A 900 ms aggregation
window combines quick clicks, followed by
a 15-second cooldown; the all-done milestone can upgrade an ordinary reaction
during cooldown. Old reactions are never queued. Hidden/modal states cancel
pending feedback. No task or scheduling data is changed by this feature.

Settings provide independent **task reactions**, **short captions** and **local
voice** switches. Reactions default on; captions and voice default off and are
used only with reactions enabled. Captions are click-through and disappear after
5.5 seconds. Russian/English phrases follow the application language, contain no
personal task text and do not use an LLM.

Voice loads optional `PySide6.QtTextToSpeech` lazily and uses a local engine
(`speechd` on Ubuntu). If bindings, a system speech service or a suitable voice
are missing, visual feedback still works and the error appears in character
settings. Voice quality/languages depend on installed system voices; this is not
an Epsilon-specific anime voice. No phoneme/lip synchronization is implemented.
Speech stops on hiding, modal dialogs and disposal.

## Verification

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
xvfb-run -a env QT_QPA_PLATFORM=xcb SOMNILOOP_TEST_LIVE2D=1 \
  .venv/bin/python -m pytest -q tests/test_live2d.py
xvfb-run -a env QT_QPA_PLATFORM=xcb .venv/bin/python tools/smoke_live2d.py
QT_QPA_PLATFORM=wayland .venv/bin/python tools/smoke_live2d.py
```

The smoke test opens the actual SomniLoop window with a temporary database and
closes it automatically. It checks live frames, transparency, click-through,
motions, expressions, resizing, modal behavior, hiding and teardown; screenshots
are written to a temporary directory. Native tests also measure blink, breath,
hair physics, expression parameters and return to idle.

## Attribution and licenses

**Epsilon artwork and modeling © Live2D Inc.** Cubism SDK/Core © Live2D Inc.
These third-party assets are **not** covered by SomniLoop's source-code license.
The downloaded archives and native binaries are intentionally excluded from Git;
do not commit them or assume they can be freely relicensed.

- [Official Epsilon sample](https://www.live2d.com/en/learn/sample/epsilon/)
- [Free Material License Agreement](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)
- [Sample Data Terms of Use](https://www.live2d.com/learn/sample/model-terms/)
- [Cubism Native SDK](https://www.live2d.com/en/sdk/download/native/)
- [Proprietary Software License Agreement — Core](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)
- [Open Software License Agreement — Framework](https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html)
- [SDK release licensing](https://www.live2d.com/en/sdk/license/)

Review the applicable agreements and SDK `RedistributableFiles.txt` before
publishing binaries or redistributing sample data. Local integration tests are
not a determination of your eligibility for a publication-license exemption.

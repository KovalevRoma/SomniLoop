# Cat celebration

The overlay uses Qt Multimedia (PySide6-Addons) and a transparent PNG, not a
3D rig. It does not replace Epsilon. One player and one frame timer are active
only during celebrations; mouse input passes through the visual layer.

- Completing the last active task due today plays the entire supplied track
  (Qt reports approximately 43.85 seconds). Other dates and habits do not block it.
- Fully completing a regular habit today plays `min(streak_days / 30, 1)`
  of the track. Here streak means consecutive calendar days fully completed,
  including today; a gap or partial day breaks it. Weekly quotas do not count
  weeks as days. Historical edits alone never start a celebration.
- Unchecking and completing again may restart the effect. Repeated writes of
  an already-completed state do not. Archiving or deleting does not trigger it.
- New celebrations restart the single player. Esc mutes this celebration only;
  the on-screen End celebration button stops both sound and visuals.
- Beams and colors move continuously, without intentional flashing/strobing.
  This is not a medical guarantee of suitability for photosensitive users.
- A visible, enabled Epsilon loops its built-in `Shake/0` sway with `Smile`
  and the localized Dancing badge. The installed model has no dedicated Dance
  clip; the sway was selected after inspecting all 15 motion clips. Touch,
  hover, ambient motions and task reactions are suppressed until celebration
  ends. Esc only mutes sound, so dancing continues. Stop, audio end/error and
  disposal restore normal behavior. Disabled characters remain disabled.
  The existing character timer runs at 30 FPS while dancing, with hit-mask
  calculations disabled, then returns to its previous interval.

Resources: `src/somniloop/assets/rave/cat.png` and `track.mp3`.
`tools/analyze_rave.py` decodes the track with Qt and measures bass transients
using NumPy (offline only). The strongest grid is 150 BPM, 400 ms per beat;
the first strong onset is at 3.45 s (3.47 s with FFT-window centre correction).
The bass-heavy section ends around 29 s. `ui/rave_motion.py` uses this fixed
grid: face-on holds alternating with short axial-spin bursts,
beat-triggered travel between seeded screen positions, and half-time opacity
breathing in the outro, bounded to 72–100%. This is stylized choreography,
not a frame-by-frame recreation of the meme. The supplied cat remains a 2D cutout.
The locally supplied W&W reference is 134.73 seconds, unlike the bundled
43.85-second remix. Sampled frames show central front-facing pauses followed
by axial tumbles. Width compression, mirroring, shear and tilt approximate
that motion using the user's photograph; they do not reconstruct unseen sides.
The reference video is not loaded at runtime, and its background flashes are
not copied. Existing lighting and audio remain unchanged.
Rendering follows media position with at most 60 ms interpolation, not a free-running
animation clock. No decoding or FFT work runs during celebrations.
The lighting uses 16 moving beams, 180 particles and up to 56 small local glows.
From 9.87 s, travel targets change on the 400 ms grid, settling in 90–140 ms.
The route is precomputed once, stays inside the window, and repeats on restart.
The original axial-spin phrases remain layered on top, with a small bounce
and scale accent on every beat, including front-facing holds.
Beams have narrow near-white cores; larger cached glows have white centres
and saturated halos. Screen blending makes overlaps luminous instead of muddy.
The cat gently pulses between 80–100% opacity during the main section and
72–100% in the outro, without visibility toggles.
Glows have staggered 1.8–3.2 s smooth envelopes and cached gradient sprites;
there are no full-screen brightness flashes or extra animation timers.

Rendering is capped at approximately 30 FPS. The lighting layer is cached at
20 FPS in a buffer no larger than 768×432, independently of display pixel
density. It is smoothly upscaled; the cat is still drawn at output resolution.
Resize and restart invalidate the cache, stop releases it, and minimized
windows skip paint requests while audio completion is still checked.
`tools/benchmark_rave.py` measures 120 raster frames at 1920×1080, without
audio or Live2D. With identical 16 ms sample steps, the local before/after
measurements were 60.3 → 8.6 ms wall time and 83.8 → 16.8 ms CPU time per frame.
These are render-only measurements, not a whole-application power benchmark.
The tool defaults to the new 33 ms cadence; use `--step-ms 16` to reproduce
the comparison cadence.
The audio was supplied by the user for their personal installation; no rights
to redistribute that track are asserted. Review rights before distributing it.
The original root MP3 has been preserved.

The cat cutout was prepared with the built-in imagegen tool from the user's
photo, then saved in the project. Prompt:

> Use case: background-extraction. Input image: edit target. Create a clean
> photographic cutout of this exact pet cat for a desktop celebration animation.
> Remove only the car seat and all background, leaving actual transparent alpha.
> Preserve the cat's crouched pose, face, green eyes, tabby markings, white chest
> and white paws, proportions and natural fur. Whole cat visible, close fitting
> canvas with small transparent padding. No added objects, no text, no restyling,
> no painted checkerboard or shadow.

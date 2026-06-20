# Persistent Change Prototype

A standalone classical computer-vision prototype that detects **persistent
pollution-change candidates** in a fixed-view CCTV test video by comparing each
processed frame against an **already-generated fixed reference background
image**.

This module is **independent** from the main project and from the
`normal-background-prototype`. It does **not** identify object classes (it does
not decide whether a region is litter, trash, a person, etc.) and it does
**not** use YOLO, OCR, pollution scoring, advanced tracking, or real-time camera
capture. It only generates better **small, spatially-stable, persistent** change
candidates for a later YOLO fusion stage.

---

## Corrected detection objective

The targets are **small** pollution-related changes — cigarette butts, small
litter, cups, bottles, cans, plastic fragments, small accumulated waste. These
are generally **much smaller** than people, vehicles, large shadows, major
illumination changes, or camera obstruction.

> **Important:** bigger ≠ more likely pollution. The detector does **not**
> improve by simply raising the minimum area. The intended hierarchy is:
>
> - **extremely tiny + unstable** → likely pixel/compression noise
> - **small/medium, stable, persistent** → useful pollution candidate
> - **large + moving/unstable** → likely person, vehicle, shadow, dynamic object
> - **globally large** → likely illumination, weather, camera movement/obstruction
>
> The module prioritizes **spatial stability and persistence over raw area**.

A region is a persistent pollution-change candidate when it is **small enough to
plausibly be litter**, **spatially stationary**, **reasonably stable in size**,
and **persists (while stationary) for a configurable duration**.

---

## Moving-object suppression (two-mask design)

A single moving person fragments into many contours (face / torso / legs /
shadow). Tracking those fragment centers is meaningless, and any of them could
wrongly accumulate persistence. So the detector uses **two clearly separate
masks**:

- **A. Motion mask** — current frame vs. the *previous processed frame*. It
  finds dynamic areas (people, vehicles, moving shadows). It is intentionally
  **more inclusive** than the reference-diff mask: nearby motion fragments are
  **merged and padded** into broad dynamic regions. The goal is to cover the
  *whole area* of a mover, not segment it.
- **B. Reference-difference mask** — current frame vs. the *fixed reference
  background*. It finds what changed versus the normal scene.

The candidate mask is then:

```
stationary_candidate_mask = reference_difference_mask AND NOT dynamic_exclusion_mask
```

No persistent candidate is created from pixels inside the dynamic exclusion, so
fragmented person contours are suppressed **as a group**. The detector never
tries to classify a person — it just removes the moving region and evaluates
only what remains.

### Motion cooldown (residual suppression)

When a mover leaves it can leave residue (shadows, exposure adaptation,
compression artifacts). So an area recently covered by motion stays excluded for
`--motion-cooldown-seconds` via a simple per-pixel decaying timer
(`cooldown_map`). The intended sequence:

```
person enters → motion fragments → merged into broad dynamic exclusion →
all person pixels suppressed → person leaves → cooldown →
remaining small stationary object becomes a candidate →
stationary duration accumulates → persistent region created
```

If a tracked candidate becomes covered by motion/cooldown, its stationary
accumulation is **paused** (and it is not promoted, and not expired) until
stability resumes after cooldown.

### Broad-motion guard (separate from the global scene-change guard)

Two independent whole-frame protections, both kept:

- **Global scene change** — the *reference-difference* changed ratio ≥
  `--global-change-ratio` (sudden lighting, rain, exposure, camera move).
- **Broad motion** — the *motion* pixel ratio ≥ `--global-motion-ratio` (a crowd
  or camera-wide movement). 

In either case, candidate creation is suppressed for that frame and the frame is
counted in metadata.

---

## Temporal consistency filter (keep tiny litter, drop flickering noise)

Small litter (a cigarette butt may be only **15–40 px** at this resolution) can
be *smaller* than noise you want to reject. Lowering `--min-area` lets small
litter through but also lets random pixel noise through. **Object size and noise
are filtered separately** — do not solve noise by raising `--min-area` or
`--threshold`.

A temporal filter is applied to the **stationary candidate mask**, *before*
contour extraction and area filtering:

```
small region + repeatedly visible at the same location  → keep
small region + appears only briefly / inconsistently     → reject
```

How it works each non-suppressed frame:

1. The current stationary candidate mask (ref-diff, minus motion + cooldown) is
   pushed into a rolling history of the last `--temporal-window-frames` masks.
2. Per pixel, count how many masks in the window contain it. Keep the pixel only
   if the count ≥ a required number of hits:
   `temporal_vote = sum(recent_stationary_masks) >= required_hits`.
3. Intersect the vote with the **current** stationary mask so the final region is
   never enlarged beyond what is currently detected:
   `temporal_filtered = temporal_vote AND current_stationary_mask`.

`--temporal-min-hits` (default 6 of 9) sets the steady-state requirement. A pixel
present in only 1–5 of 9 frames is removed as temporal noise; a static object
present in ≥6 is kept.

**Startup (buffer not yet full).** To avoid a blind period, the requirement
scales with how many frames we have so far:

```
required_hits = max(1, min(temporal_min_hits,
                           ceil(history_length * temporal_min_hits / temporal_window_frames)))
```

**Spatial tolerance.** CCTV pixels can shift 1–2 px between frames. If
`--temporal-tolerance-kernel > 1` (odd; 1 = disabled), each mask is slightly
dilated **for voting only** before accumulation; the final region is still
bounded by the un-dilated current mask via the intersection above.

**Suppressed frames.** On a global-scene-change or broad-motion frame the history
is **not** updated (the frame is skipped), so one bad frame cannot erase prior
temporal evidence.

**The temporal filter only governs detection** (which pixels become contours). It
does **not** touch the raw motion mask, annotated boxes, or existing tracks, and
it never resets `stationary_duration`. Existing tracks keep all occlusion /
cooldown / recovery / missing-grace behavior.

### The four independent filters

| Filter | Rejects |
| --- | --- |
| `--threshold` | weak pixel differences (low-contrast change vs. reference) |
| `--min-area` / `--max-area` | **object size** only (too small / too large) |
| temporal consistency | **short-lived / inconsistent** pixels (flicker) |
| `--persistence-seconds` | regions not stationary long enough over time |

---

## Occlusion survival (a person may temporarily cover litter)

The dynamic exclusion must **not** destroy an already-detected candidate when a
person walks over it. New-candidate creation and existing-track management are
handled **separately**:

- **New candidates** are never created from pixels inside the motion/cooldown
  exclusion (they come from the stationary mask).
- **Existing tracks** are managed from **track memory**, independent of the
  current mask. A track is **never deleted just because motion overlaps it**.

When motion (or its cooldown) covers a track's **protected area** — its last
bbox grown by `--track-protection-padding` — by at least
`--motion-occlusion-overlap-ratio`, the track is marked **occluded**:

- stationary-duration accumulation **pauses** (it is **not reset**);
- the track ID and full history are **preserved**;
- a snapshot is stored (`last_bbox_before_occlusion`,
  `stationary_duration_before_occlusion`), and `occlusion_count` /
  `total_occluded_duration` are recorded;
- it is **not promoted** while occluded;
- it is **not expired** while motion/cooldown is over it.

When motion clears, **recovery matching** runs *before* normal matching: a
reappearing stationary region near the pre-occlusion location (within
`--occlusion-recovery-distance`, with size similarity and overlap) is bound back
to the **same track ID** (`resumed`), and stationary time **continues from where
it paused**.

### Occlusion grace and stronger persistent protection

A track is only expired if it stays absent **after** motion/cooldown clears,
beyond the applicable grace, with no compatible region reappearing nearby:

- never-occluded track → `--missing-grace-seconds` (default 2);
- occluded non-persistent track → `--motion-occlusion-grace-seconds` (default 5);
- occluded **persistent** track → `--persistent-occlusion-grace-seconds`
  (default 10) — persistent candidates are protected more strongly and resume as
  persistent when visible again.

Lifecycle states: `active`, `occluded_by_motion`, `persistent_occluded`,
`cooldown_wait`, `resumed`, `missing`, `expired` (plus the candidate states
`candidate_unstable` / `candidate_stationary` / `persistent`).

> **Verified sequence** (synthetic test): a small static object becomes
> persistent → a person walks over it → it goes `persistent_occluded` with
> stationary time **frozen** → the person leaves → the **same ID** resumes →
> stationary time continues and persistent status is retained.

---

## Required existing reference background

This module requires a reference background produced by the
`normal-background-prototype`. The default path (resolved relative to this
folder) is:

```
../normal-background-prototype/output/reference_background.jpg
```

The reference image is treated as **read-only** and is never modified. Override
it with `--reference`.

## Where to place the test video

Put one test video inside `persistent-change-prototype/input/`.

---

## Folder structure

```
persistent-change-prototype/
├─ persistent_change_detector.py   # main script
├─ requirements.txt
├─ README.md
├─ input/                          # place your test video here
│  └─ .gitkeep
└─ output/                         # annotated video + JSON written here
   └─ .gitkeep
```

---

## Installation

```bash
pip install -r requirements.txt
```

## Recommended example run (small-litter tuning + temporal filter)

PowerShell (note: `--min-area` is an **object-size** filter, not the noise
filter — the temporal filter handles short-lived noise):

```powershell
python persistent_change_detector.py `
  --input "../normal-background-prototype/input/E05_003.mp4" `
  --reference "../normal-background-prototype/output/reference_background.jpg" `
  --output output `
  --processing-fps 3 `
  --width 960 `
  --threshold 58 `
  --min-area 15 `
  --max-area 5000 `
  --persistence-seconds 12 `
  --motion-threshold 36 `
  --motion-open-kernel 3 `
  --motion-close-kernel 3 `
  --motion-dilate-kernel 5 `
  --motion-dilate-iterations 1 `
  --motion-min-area 450 `
  --motion-merge-distance 10 `
  --motion-box-padding 2 `
  --motion-cooldown-seconds 2 `
  --global-motion-ratio 0.35 `
  --motion-occlusion-overlap-ratio 0.3 `
  --motion-occlusion-grace-seconds 5 `
  --persistent-occlusion-grace-seconds 10 `
  --occlusion-recovery-distance 30 `
  --track-protection-padding 5 `
  --temporal-window-frames 9 `
  --temporal-min-hits 6 `
  --temporal-tolerance-kernel 3 `
  --save-mask-video `
  --save-motion-mask-video `
  --save-stationary-mask-video `
  --save-temporal-mask-video `
  --show-motion-regions `
  --show-ignored-large-regions
```

---

## Per-frame pipeline order

1. Read current frame → 2. resize/preprocess → 3. reference-difference mask →
4. motion mask → 5. dynamic exclusion + cooldown mask → 6. remove motion/cooldown
from the reference-difference mask (= stationary candidate mask) →
7. **push stationary mask into temporal history** → 8. compute temporal vote mask
→ 9. **intersect vote with the current stationary mask** → 10. (existing
morphology already applied to the reference-difference mask) → 11. extract
contours → 12. min/max area + ratio filters → 13. track candidates →
14. persistence + occlusion logic. Temporal filtering applies **only** to the
binary stationary-candidate pixels at steps 7–9.

---

## CLI options

| Option                        | Default | Description                                                                 |
| ----------------------------- | ------- | --------------------------------------------------------------------------- |
| `--input`                     | (req.)  | Test video path.                                                            |
| `--reference`                 | default path above | Reference background image path.                                  |
| `--output`                    | `output`| Output directory.                                                          |
| `--processing-fps`            | `3`     | Video frames processed per second.                                         |
| `--width` / `--height`        | source  | Optional processing resolution (aspect preserved if only one given).       |
| `--threshold`                 | `30`    | Pixel difference threshold (0–255).                                        |
| `--min-area`                  | `30`    | Minimum changed area in px — reject tiny noise. *Resolution-dependent.*    |
| `--max-area`                  | `5000`  | Maximum changed area in px — reject large objects. *Resolution-dependent.* |
| `--min-area-ratio`            | `0.00001`| Minimum `contour_area / frame_area`.                                       |
| `--max-area-ratio`            | `0.02`  | Maximum `contour_area / frame_area`.                                        |
| `--disable-area-ratio-filter` | off     | Use only `--min-area`/`--max-area` (ignore ratios).                         |
| `--max-center-movement`       | `12`    | Max center movement (px/frame) for a stable match.                         |
| `--max-center-movement-ratio` | `0.015` | Max center movement as fraction of processing diagonal.                    |
| `--max-size-change-ratio`     | `0.35`  | Max relative area change for a stable match.                               |
| `--stability-window`          | `8`     | Recent matched observations used for the stable-match ratio.               |
| `--minimum-stationary-ratio`  | `0.8`   | Min fraction of recent matches that must be stable to accumulate time.     |
| `--persistence-seconds`       | `5`     | Required **stationary** duration before a region becomes persistent.       |
| `--missing-grace-seconds`     | `2`     | How long a never-occluded region may disappear before removal.             |
| `--motion-occlusion-overlap-ratio` | `0.3` | Motion overlap of the protected bbox that marks a track occluded (paused). |
| `--motion-occlusion-grace-seconds` | `5.0` | Grace for an occluded non-persistent track after motion clears.          |
| `--persistent-occlusion-grace-seconds` | `10.0` | Longer grace for an occluded **persistent** track.                  |
| `--occlusion-recovery-distance` | `30` | Max distance (px) from the pre-occlusion bbox to re-acquire (reuse ID).    |
| `--track-protection-padding`  | `5`     | Padding (px) around a track's bbox; motion inside pauses (never deletes).  |
| `--temporal-window-frames`    | `9`     | Number of recent stationary masks considered for the temporal vote.        |
| `--temporal-min-hits`         | `6`     | Min hits within the window to keep a pixel (1..window).                     |
| `--temporal-tolerance-kernel` | `3`     | Voting-only dilation for 1–2px shift tolerance (1 = disabled, odd).        |
| `--save-temporal-mask-video`  | off     | Save `output/temporal_filtered_mask.mp4` (mask used for contours).         |
| `--iou-threshold`             | `0.25`  | IoU contribution used in matching.                                         |
| `--matching-center-distance`  | `40`    | Max center distance (px) to allow a match.                                 |
| `--open-kernel`               | `3`     | Morphological **opening** kernel (small — preserves tiny candidates).      |
| `--close-kernel`              | `5`     | Morphological **closing** kernel (connect fragments).                      |
| `--morph-kernel`              | (none)  | **Deprecated.** If set, drives both open & close unless those are given.   |
| `--merge-distance`            | `10`    | Max gap (px) to merge nearby small candidates (within area limits only).   |
| `--global-change-ratio`       | `0.45`  | Reference-diff changed ratio above which a whole frame is a global scene change. |
| `--motion-threshold`          | `25`    | Current-vs-previous-frame difference threshold (0–255).                    |
| `--motion-open-kernel`        | `3`     | Motion opening kernel (remove speckle).                                    |
| `--motion-close-kernel`       | `9`     | Motion closing kernel (fill gaps in a mover).                             |
| `--motion-dilate-kernel`      | `15`    | Motion dilation kernel (grow to cover the whole mover).                    |
| `--motion-dilate-iterations`  | `2`     | Motion dilation iterations.                                                |
| `--motion-min-area`           | `300`   | Minimum motion contour area (px).                                          |
| `--motion-merge-distance`     | `40`    | Max gap (px) to merge motion fragments into one dynamic region.           |
| `--motion-box-padding`        | `20`    | Padding (px) added around each merged motion box (clipped to frame).      |
| `--motion-cooldown-seconds`   | `2.0`   | Keep an area excluded this long after motion leaves.                       |
| `--global-motion-ratio`       | `0.35`  | Motion pixel ratio above which the frame is broad motion (suppressed).     |
| `--show-ignored-large-regions`| off     | Draw ignored large local changes (gray) on the video.                      |
| `--show-motion-regions`       | off     | Draw merged motion regions (blue, "Motion excluded") and cooldown (cyan). |
| `--save-mask-video`           | off     | Save the reference-difference change-mask video.                           |
| `--save-motion-mask-video`    | off     | Save the motion-mask video (`output/motion_mask.mp4`).                     |
| `--save-stationary-mask-video`| off     | Save the stationary-candidate-mask video.                                  |
| `--verbose`                   | off     | One log line per processed frame.                                          |

> The default `--min-area`/`--max-area` pixel values are **starting points and
> resolution-dependent**. Frame-relative **ratio** thresholds transfer more
> cleanly between different resolutions, which is why ratio filtering is on by
> default; a candidate must satisfy **both** the pixel range **and** the ratio
> range (unless ratio filtering is disabled).

---

## Area filtering

A contour's area is classified as:

- `area < min-area` (or ratio `< min-area-ratio`) → **ignored as tiny noise**.
- `min-area ≤ area ≤ max-area` **and** ratio within `[min-area-ratio,
  max-area-ratio]` → **accepted candidate** local change.
- `area > max-area` (or ratio `> max-area-ratio`) → **rejected as a large
  dynamic object / broad change** (see *Large region handling*).

`min-area` must be positive and `max-area` must be greater than `min-area`.

## Noise & morphology

Because the targets are small, morphology must **not** erase small regions.
Opening and closing use **separate** kernels:

- **opening** (`--open-kernel`, default 3) is kept small to remove isolated
  speckle noise without deleting cigarette-butt-sized blobs;
- **closing** (`--close-kernel`, default 5) connects small fragments of one
  object.

> Aggressive morphology (a large opening kernel) can destroy the small
> candidates this module is designed to find. Increase the opening kernel only
> if noise is severe.

The legacy single `--morph-kernel` is still accepted for backward compatibility:
if provided, it sets both kernels, but explicit `--open-kernel`/`--close-kernel`
take precedence.

## Controlled region merge

Nearby small contours may be fragments of one object, but over-eager merging can
fuse a person/shadow into one large blob. Two candidate boxes are merged **only
when** their gap is below `--merge-distance` **and** the merged region stays
within both `--max-area` and `--max-area-ratio`. This prevents uncontrolled
large-region formation.

---

## Matching (combined, prototype-level)

Tracking stays simple — **no DeepSORT, ByteTrack, optical flow, or neural
tracking**. Candidates are matched to existing tracks with a **combined score**:

1. Reject impossible matches whose center distance exceeds
   `--matching-center-distance`.
2. Reject matches whose area differs too much from the track.
3. Among valid matches, prefer **higher IoU**, **lower center distance**, and
   **more similar area** (greedy, best pairs first).

A candidate is therefore **not** matched merely because its box overlaps.

## Spatial stability

The old IoU-only logic was insufficient: a moving person or shadow can overlap
its previous box and wrongly accumulate persistence. Each tracked region now
records its center, previous center, recent center/area history, accumulated
movement, max/min area, stable-match ratio, and more.

A match is **stable** when:

- center movement ≤ the effective movement threshold — the **larger** of
  `--max-center-movement` (px) and `--max-center-movement-ratio × processing
  diagonal`, so it adapts to resolution; **and**
- relative area change ≤ `--max-size-change-ratio`.

A region only accumulates stationary time when the current match is stable
**and** at least `--minimum-stationary-ratio` of the recent
`--stability-window` matches were stable (e.g. 0.8 = 80%).

## Visible duration vs. stationary duration

This is the key correction. The module tracks **both**:

- `visible_duration` — total time the region has been matched (moving or not);
- `stationary_duration` — time accumulated **only while the region is stable and
  stationary**.

A region becomes **persistent** only when it is within the area range, passes
the stability checks, and its **stationary duration** (not visible duration)
exceeds `--persistence-seconds`. A continuously moving region can have a long
visible duration but its stationary duration stays low, so it never becomes
persistent. If a region becomes unstable, it is **not** deleted immediately:
stationary accumulation stops, the track survives the missing grace period, and
stability must be re-established before stationary time grows again.

## Large region handling vs. global scene-change guard

These are **two different** protections, both kept:

- **Large local change** — one region exceeds `--max-area` / `--max-area-ratio`
  (e.g. a person standing still, a parked vehicle, a large shadow). It does
  **not** become a persistent candidate; it is counted separately and, with
  `--show-ignored-large-regions`, drawn in **gray** as "Large change ignored".
  The rest of the frame may still be normal.
- **Global scene change** — a large *proportion of the whole frame* changed
  (`changed_pixel_ratio ≥ --global-change-ratio`), e.g. sudden lighting, rain,
  exposure shift, camera movement, day/night mismatch. The frame is flagged, a
  warning is drawn, local detection is suppressed for that frame, and it is
  counted in metadata. This is a basic safeguard, **not** weather/illumination
  classification.

---

## Region states & annotation colors

States: `noise_rejected`, `candidate_unstable`, `candidate_stationary`,
`persistent`, `large_change_ignored`, `missing`, `expired`.

Internal extra state: `paused_by_motion` (covered by dynamic exclusion — frozen,
not drawn).

Annotated-video colors:

- **gray** — ignored large local change
- **orange** — candidate, unstable or not stationary long enough
- **yellow** — stable stationary candidate, persistence time accumulating
- **red** — persistent changed region
- **purple** — occluded by motion (non-persistent)
- **magenta** — persistent but occluded
- **cyan** — resumed after occlusion (re-acquired track)
- **blue** — merged dynamic motion region ("Motion excluded"), with `--show-motion-regions`
- **light blue tint** — motion cooldown area, with `--show-motion-regions`

Each drawn region shows ID, state, stationary duration, occluded duration, and
occlusion count; the header shows the timestamp and persistent count (and a
warning on global-scene-change or broad-motion frames). While occluded, the box
is drawn at the pre-occlusion location so ID continuity is visible.

---

## Output files

- `output/persistent_change_result.mp4` — annotated video.
- `output/persistent_change_events.json` — configuration (incl. all motion and
  occlusion parameters), video metadata, summary counts (incl. motion regions
  detected / merged, broad-motion frames, frames suppressed by motion, candidate
  pixels removed by exclusion, `tracks_paused_by_motion`,
  `tracks_resumed_after_motion`, `persistent_tracks_occluded`,
  `tracks_expired_after_occlusion`, and the temporal-filter counts
  `total_stationary_pixels_before_temporal`,
  `total_stationary_pixels_after_temporal`,
  `total_pixels_removed_by_temporal_filter`, `temporal_pixel_removal_ratio`,
  `temporal_history_skipped_frames`, `temporal_candidates_created`), and the
  persistent-event list. Each event includes `became_stationary_seconds`,
  `became_persistent_seconds`, `stationary_duration`, `state`, `occlusion_count`,
  `total_occluded_duration_seconds`, `last_occlusion_start_seconds`,
  `resumed_after_occlusion_count`, `stationary_duration_before_occlusion_seconds`,
  `expired_reason`, min/max area, area ratio, average/maximum center movement,
  stable-match ratio, and the last bbox.
- `output/change_mask.mp4` — with `--save-mask-video` (reference-difference mask).
- `output/motion_mask.mp4` — with `--save-motion-mask-video` (white = current motion).
- `output/stationary_candidate_mask.mp4` — with `--save-stationary-mask-video`
  (white = reference difference remaining after motion + cooldown suppression).
  **This is the mask BEFORE temporal voting.**
- `output/temporal_filtered_mask.mp4` — with `--save-temporal-mask-video`
  (white = pixels that passed temporal consistency; **the mask AFTER temporal
  voting, used for contour extraction**).

These debug masks are the primary way to tune the motion + temporal stages and
visually verify that moving people are suppressed and flicker noise is removed.

---

## Recommended tuning order

1. **Processing resolution** (`--width`/`--height`) — scales everything else.
2. **Difference threshold** (`--threshold`).
3. **Minimum area** (`--min-area`, `--min-area-ratio`).
4. **Morphological kernel** (`--open-kernel`/`--close-kernel`).
5. **Persistence duration** (`--persistence-seconds`).
6. **IoU threshold** (`--iou-threshold`).

Also relevant for this objective: `--max-area` / `--max-area-ratio` (reject
large objects), `--max-center-movement` and `--max-size-change-ratio` (stability
strictness), and `--minimum-stationary-ratio`. **For the motion stage**, tune
(using the debug masks) `--motion-threshold`, then the motion morphology /
`--motion-dilate-*` and `--motion-box-padding` to fully cover movers, then
`--motion-cooldown-seconds`, then `--global-motion-ratio`.

---

## First-frame / previous-frame handling

The first processed frame has no previous frame, so the motion mask is empty for
that frame (no false motion is created from initialization); `prev_gray` is then
set and real motion detection begins on the second processed frame.

> If the gap between processed frames is large (low `--processing-fps`), the
> motion mask uses two widely-spaced frames, so frame-difference motion becomes
> **less precise** — a mover can shift far between samples. The script prints a
> note when this gap exceeds 1 s. Raise `--motion-box-padding` /
> `--motion-cooldown-seconds`, or `--processing-fps`, to compensate.

---

## Current limitations

- **No object classification.** It does not know *what* a region is — only that
  it is a small, stable, persistent change. **YOLO is intentionally not used.**
- Motion suppression is frame-difference based: a mover that **stops moving** for
  a while stops generating motion and (after cooldown) can leak into the
  stationary mask; a very slow mover may not trigger enough motion. The dilation
  + padding + cooldown mitigate but do not eliminate this.
- Aggressive motion dilation/padding can also swallow a real small litter item
  that sits right next to a person's path until the person leaves (it is paused,
  not lost, and resumes after the person passes).
- Occlusion recovery is location-based: if the object is actually **removed**
  while hidden by the person, the track survives only until its occlusion grace
  expires, then expires with `expired_reason`. If a *different* small object
  appears within `--occlusion-recovery-distance` of the old one during recovery,
  it could be bound to the old ID (prototype-level matching).
- Sensitive to reference quality: ghosting baked into the reference affects
  differencing.
- Assumes a genuinely **fixed** camera; no stabilization. Camera shake registers
  as broad motion (often caught by the broad-motion guard).
- Prototype-level combined matching; fast/overlapping regions may still swap IDs.
- The global scene-change and broad-motion guards are single ratio thresholds,
  not classifiers.
- When source FPS is unavailable, 30.0 is assumed for sampling.
- The temporal filter assumes a roughly **stationary** target: an object must
  occupy (nearly) the same pixels across the window. A real object that drifts
  more than `--temporal-tolerance-kernel` per frame, or appears for fewer than
  `--temporal-min-hits` frames within the window, is removed. It rejects
  *short-lived* noise but not *persistent structured* noise (e.g. a constantly
  rendered timestamp or a flickering light that is on most frames).
- Temporal filtering only affects new detection; an already-tracked region that
  the temporal mask briefly drops is preserved by missing/occlusion grace.

---

## Pipeline context

```
normal-state video
→ reference background generation        (normal-background-prototype)
→ current-frame comparison + persistent SMALL-change tracking   ← (this prototype)
→ YOLO result fusion
→ pollution score calculation
```

Only the persistent small-change detection stage is implemented here.

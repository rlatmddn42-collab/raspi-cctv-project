# Candidate Dataset Builder

A standalone module that consumes the output of **persistent-change-prototype**
(`persistent_change_events.json`) and packages each persistent candidate into
**human-reviewable evidence** for later labeling and model training.

> **This module does not determine whether a candidate is litter.** It only
> packages detector output into evidence suitable for human labeling. No YOLO, no
> neural inference, no classification, no person detection, no OCR, no server, no
> database. It never modifies the detector results, the original video, or the
> reference image.
>
> **This module creates labeled candidate-classification samples. It does NOT
> train a classifier, and it does NOT prove cross-camera generalization.**

---

## The anomaly-candidate classification concept (schema 2.0)

The future learning problem is **not** "full CCTV image → detect cigarette
butts directly". It is:

```
normal reference appearance A   (reference_background.jpg crop)
+ current persistent-change appearance B   (source video crop at persistent time)
+ difference(A, B)
+ local context
→ classify the MEANING of change B
```

So besides the human-review evidence, this module now exports, per candidate, a
**clean machine-learning input set** under `candidate_XXXX/model_input/` plus a
**training manifest**. A future model will learn whether a region the
persistent-change detector flagged is litter or a false positive.

### Human-review files vs. clean model inputs

| Human-review (existing) | Clean model input (`model_input/`) |
| --- | --- |
| `comparison_panel.jpg`, `*_context.jpg`, crops, clip | `reference.png`, `current.png`, `difference.png`, `mask.png`, `context.png`, `*_context.png`, `paired_horizontal.png`, `paired_grid.png`, `sample.json`, `sample.npz` |
| may contain text, IDs, timestamps, boxes, panels | **no text, no IDs, no timestamps, no boxes, no UI** — clean tensors |

> ⚠️ **Do NOT use `comparison_panel.jpg` (or any `*_context.jpg` with overlays)
> as a training image.** The model must learn only from files under
> `model_input/` (or the paths in `training_manifest.json`). The human-review
> files contain drawn text/boxes and would teach the model the wrong thing.

### Model-input alignment

All paired images share **one** square source-space crop so the candidate never
shifts between `reference`/`current`/`difference`/`mask`:

1. start from the candidate bbox (scaled to source coordinates);
2. expand by `--model-context-padding` (default 24 source px);
3. enforce at least `--model-minimum-region-size` (default 48);
4. square to the larger side, keep the candidate centered, clip to the frame and
   **pad** outside-image areas (never distort geometry);
5. resize all four to `--model-input-size` × `--model-input-size` (default 128).

Interpolation policy: reference/current/context use `INTER_AREA` when shrinking
and `INTER_CUBIC` when enlarging; difference is built from the aligned
reference/current; **mask uses `INTER_NEAREST` only**. A wider context scale
(`reference_context.png` / `current_context.png` / `difference_context.png`) is
also exported at `--context-model-input-size` (default 256).

`paired_horizontal.png` = clean `[reference | current | difference]` (equal
sizes, no separator). `paired_grid.png` = clean 2×2 `reference|current /
difference|mask`. With `--save-model-array`, `sample.npz` holds the uint8 arrays
(`reference`, `current`, `difference`, `mask`, `context`).

### Difference modes (`--difference-mode`)

- `abs_rgb` (default): per-channel `|current − reference|`, 3 channels.
- `abs_gray`: grayscale absolute difference replicated to 3 channels.
- `signed_centered`: `(current − reference) + 128`, clamped — keeps whether
  pixels got brighter/darker.

Per-sample min/max normalization is **off by default** (it would destroy
cross-sample intensity comparability); enable with `--normalize-difference`
(recorded in `sample.json`).

### Candidate mask source (priority + honesty)

The current event JSON contains **no** per-candidate mask/contour. The mask is
chosen by priority and the choice is recorded as `mask_source`:

1. `event_mask` / `event_contour` — *not available in the current schema*.
2. `detector_mask_crop` — from `--temporal-mask-video`
   (`persistent-change-prototype/output/temporal_filtered_mask.mp4`): the mask
   frame nearest the persistent timestamp is upsized to source resolution,
   cropped to the same square, thresholded to binary, and the component
   overlapping the bbox is isolated. Requested/actual mask times are recorded.
3. `reconstructed_contour` — *not available* (no per-candidate geometry).
4. `bbox_fallback` — **filled bounding box**, used only when no mask is
   available. This is **not** a real segmentation mask; it is flagged with a
   warning in `sample.json`.

### Semantic labels (the meaning of the change)

`cigarette_butt`, `other_litter`, `natural_object`, `surface_change`,
`lighting_or_shadow`, `person_or_vehicle_residue`, `compression_or_noise`,
`unknown`, `unreviewed` (plus the auto-generated `background_negative`).

### Sample quality (separate from the class)

`good`, `bbox_too_large`, `bbox_too_small`, `bbox_wrong_location`,
`object_not_visible`, `heavy_occlusion`, `reference_misaligned`, `unusable`,
`unreviewed`. The object class can be **correct** while the detector crop is
poor — e.g. `semantic_label = cigarette_butt` with `sample_quality =
bbox_too_large`. `--exclude-poor-quality-from-training` marks poor-quality
samples unusable **in the training manifest only** (it never deletes evidence).

Optional reviewer `confidence`: `high` / `medium` / `low` / `unset`.

### Legacy label migration (`label_schema_version = "2.0"`)

Old review results still import: `litter → other_litter`, `uncertain →
unknown`; `not_litter` is preserved as `raw_review_label` and flagged for
migration to a specific negative class (it maps to `unknown` until then). Each
sample stores `raw_review_label`, `normalized_semantic_label`, and
`label_schema_version`.

### Training manifest & dataset-leakage metadata

`training_manifest.json` / `.csv` (UTF-8 BOM) list one row per sample with the
model-input paths, labels, `mask_source`, scene/camera grouping, and
`usable_for_training` + `exclusion_reason`. A sample is **usable** only when its
semantic label is reviewed (not `unreviewed`/`unknown` unless allowed), its
quality is acceptable, and alignment passed — so **unreviewed/unknown samples
are never silently treated as training data**.

> **Dataset leakage:** frames from the same video or same persistent event must
> **not** be randomly split across train/validation. Each sample records
> `camera_id`, `scene_id`, `source_video_id`, `candidate_time_group`,
> `duplicate_group_id`, and a `group_key = camera_id + "/" + source_video_id`.
> Split by `group_key` (or `camera_id`). `--camera-id` / `--scene-id` /
> `--capture-condition` set these explicitly; otherwise `camera_id` is inferred
> cautiously from a leading `letters+digits` filename token (e.g. `E05_024.mp4`
> → `E05`) and the source is recorded as `inferred` vs `explicit`. This module
> records grouping metadata but does **not** perform the split.

### Background-only negatives (optional)

`--background-negative-count N` (with `--random-seed`, default 42) samples N
random non-candidate regions (not overlapping any candidate bbox + margin),
exports aligned reference/current/difference and an **empty** mask, labels them
`background_negative`, and marks `generated_negative = true`. Off by default.

### Duplicate handling

Existing duplicate grouping is preserved; manifests expose `duplicate_group_id`
and `is_duplicate_primary`. The builder creates **one** package per persistent
event (it does not emit extra near-identical temporal frames as independent
samples).

## Why this comes before YOLO training

The pipeline already produces persistent-change *events*, but a persistent
candidate could be litter, a cigarette butt, a leaf, a shadow, a stain, or a
compression/lighting artifact. Before a YOLO model can be trained, a human must
**see** each candidate and label it. This tool turns each event into organized
visual evidence + a local review page, so labels can be collected and merged
back. It is the data-preparation step *before* any model training.

---

## Required inputs

| Flag | Meaning |
| --- | --- |
| `--video` | The original CCTV video the detector ran on. |
| `--events` | `persistent_change_events.json` from persistent-change-prototype. |
| `--reference` | `reference_background.jpg` from normal-background-prototype. |
| `--output` | Output directory (default `output`). |

`--events` is always required. `--video` and `--reference` are required for
extraction (not for `--update-labels-only` review import).

## Expected persistent-change JSON

The builder **inspects the actual JSON** rather than assuming field names. It was
verified against the current schema:

- top level: `processing_resolution {width,height}` (event coordinate space),
  `video_metadata {source_fps, source_width, source_height, ...}`,
  `source_video_path`, `reference_background_path`, and the event list
  `persistent_events`.
- each event: `region_id`, `first_seen_seconds`, `became_persistent_seconds`,
  `last_seen_seconds`, `stationary_duration_seconds`, `state`, `occlusion_count`,
  `total_occluded_duration_seconds`, `resumed_after_occlusion_count`,
  `last_bbox {x,y,width,height}`.

### Field normalization rules (adapter)

Each event is normalized to an internal record. The adapter tolerates variations:

- **id**: `candidate_id` → `region_id` → `track_id` → `id` (else a sequential id, with a warning).
- **bbox**: dict `{x,y,width,height}` or `{x,y,w,h}` or `{x1,y1,x2,y2}`, or a 4-list `[x,y,w,h]`.
- **times**: `first_seen_seconds`/`start_time`/`timestamp_seconds`;
  `became_persistent_seconds`/`persistent_time_seconds`;
  `last_seen_seconds`/`end_time`; `stationary_duration_seconds`/`stationary_duration`.

Missing fields get **safe fallbacks**, a recorded **warning**, and the original
raw event is preserved in metadata. Precise values are never silently invented:
when `became_persistent` is missing it falls back to `first_seen + stationary`
(or `first_seen`), and the fallback used is recorded.

## Resolution and bbox scaling

Event coordinates are usually at the **processing resolution** (e.g. 960×540)
while the video is full resolution (e.g. 1920×1080). The builder reads the event
resolution from `processing_resolution` (or `configuration.*_width/height`, or
`--event-width`/`--event-height` overrides) and scales every bbox to source
space before cropping:

```
source_x = event_x * source_width / event_width
source_y = event_y * source_height / event_height
```

Both event-space and source-space bboxes, the resolution of each, and the scale
factors are recorded in metadata. The reference image is resized to source
resolution **for comparison output only** — the source reference file is never
overwritten.

---

## Output folder structure

```
output/
├─ candidates/
│  ├─ candidate_0001/
│  │  ├─ reference_context.jpg      # HUMAN REVIEW (has overlays) — do not train on these
│  │  ├─ before_context.jpg
│  │  ├─ first_seen_context.jpg
│  │  ├─ persistent_context.jpg
│  │  ├─ last_seen_context.jpg
│  │  ├─ persistent_crop.jpg
│  │  ├─ persistent_crop_nearest.png # nearest-neighbor upscale (real pixels)
│  │  ├─ persistent_crop_smooth.png  # Lanczos upscale (viewing only)
│  │  ├─ difference_context.jpg
│  │  ├─ comparison_panel.jpg        # 3x2 labeled summary (NEVER a training image)
│  │  ├─ candidate_clip.mp4
│  │  ├─ metadata.json
│  │  └─ model_input/                # CLEAN ML INPUTS (no text/boxes/labels)
│  │     ├─ reference.png            # 128x128 (default)
│  │     ├─ current.png
│  │     ├─ difference.png
│  │     ├─ mask.png                 # binary anomaly mask (0/255)
│  │     ├─ context.png              # wider current context (256x256 default)
│  │     ├─ reference_context.png    # wider, clean
│  │     ├─ current_context.png
│  │     ├─ difference_context.png
│  │     ├─ paired_horizontal.png    # [reference | current | difference]
│  │     ├─ paired_grid.png          # reference|current / difference|mask
│  │     ├─ sample.json
│  │     └─ sample.npz               # only with --save-model-array
│  ├─ candidate_neg_0001/ ...        # only with --background-negative-count > 0
│  └─ candidate_0002/ ...
├─ manifest.json
├─ manifest.csv                     # UTF-8 with BOM (Korean Windows Excel)
├─ training_manifest.json           # one row per model sample (+ usable_for_training)
├─ training_manifest.csv            # UTF-8 with BOM
├─ extraction_summary.json
└─ review.html
```

> Recommended layout for multiple videos (keep events tied to their video):
> `output/E05_024/`, `output/E05_003/`, … — never reuse one video's events with a
> different video.

### Exact crop vs. context crop

- **Context crop** (`*_context.jpg`): a larger region around the candidate
  (bbox expanded by `--context-padding`, at least `--minimum-context-size`, frame
  aspect preserved, clipped to the frame). The **same** context rectangle is used
  for reference/before/first-seen/persistent/last-seen/difference so they line up
  pixel-for-pixel for direct comparison. A tiny bbox alone would be unreadable.
- **Object crop** (`persistent_crop.jpg`): the bbox + `--crop-padding`, focused on
  the object at source resolution.

### Pixelated vs. smooth upscaling

- `persistent_crop_nearest.png` — nearest-neighbor upscale (`--crop-upscale`).
  Shows the **actual source pixels**; use it to judge real detail.
- `persistent_crop_smooth.png` — Lanczos upscale. Easier to look at but it is an
  **interpolated visualization only**. It does **not** reveal any detail that is
  absent from the source pixels.

### Comparison panel

A 3×2 labeled image:

```
[ reference ]   [ before ]            [ persistent ]
[ difference ]  [ crop nearest x12 ]  [ crop smooth (interp only) ]
```

Context tiles overlay candidate ID, timestamp, source-space bbox, state,
stationary duration, and occlusion count. The bbox is a 1–2 px outline (thin so a
cigarette-butt-sized object is not hidden).

### Candidate clips

A short MP4 around the persistent time
(`persistent_time − clip_before … persistent_time + clip_after`, clipped to the
video). It uses the original source frames, preserves source FPS, draws the
candidate ID, the elapsed source time, and whether the moment is **PRE-persistent**
or **post-persistent**. No new detection is run. Because the event JSON has no
per-frame bbox history, the bbox is drawn **fixed at the event bbox** (documented
behavior). `--clip-width 0` keeps the context resolution; a nonzero value resizes
while preserving aspect.

### Difference view

`difference_context.jpg` is a grayscale-blur absolute difference between the
persistent context and the reference context, normalized and JET color-mapped,
with the bbox overlaid. It is a **visualization only** — this module never
re-detects or modifies events.

---

## Accurate video seeking

OpenCV may not land exactly on a requested frame. The seeker converts time →
target frame via source FPS, seeks near it, reads forward to the nearest
available frame, and records the **requested** time, the **actual** time, and the
**frame index**. If FPS metadata is invalid it falls back to 30 FPS, warns, and
records the fallback. Frame extraction is never claimed to be exact when it isn't.

---

## Candidate selection

By default, events that became persistent are extracted, sorted by (persistent
time, first-seen time, candidate id). Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--include-non-persistent` | off | Also include events that never became persistent. |
| `--state-filter` | (none) | Comma-separated states, e.g. `persistent,persistent_occluded,resumed`. |
| `--min-stationary-seconds` | 0 | Drop candidates below this stationary duration. |
| `--candidate-ids` | (none) | Comma-separated ids to keep. |
| `--max-candidates` | 0 | 0 = no limit. |

### Context / crop / time options

| Flag | Default | | Flag | Default |
| --- | --- | --- | --- | --- |
| `--context-padding` | 80 | | `--crop-padding` | 12 |
| `--context-scale` | 4.0 | | `--crop-upscale` | 12 |
| `--minimum-context-size` | 160 | | `--before-seconds` | 2.0 |
| `--clip-before-seconds` | 3.0 | | `--clip-after-seconds` | 5.0 |
| `--clip-width` | 0 | | `--event-width`/`--event-height` | auto |

### Model-input / labeling options (schema 2.0)

| Flag | Default | Meaning |
| --- | --- | --- |
| `--temporal-mask-video` | (none) | `temporal_filtered_mask.mp4` → real anomaly mask (`detector_mask_crop`). |
| `--model-input-size` | 128 | Square local model-input size. |
| `--model-context-padding` | 24 | Source-px padding before squaring. |
| `--model-minimum-region-size` | 48 | Minimum source-px square side. |
| `--context-model-input-size` | 256 | Square wider-context size. |
| `--difference-mode` | abs_rgb | `abs_rgb` / `abs_gray` / `signed_centered`. |
| `--normalize-difference` | off | Per-sample min/max normalize the difference. |
| `--save-model-array` | off | Also write `model_input/sample.npz`. |
| `--exclude-poor-quality-from-training` | off | Poor quality → unusable in training manifest only. |
| `--camera-id` / `--scene-id` / `--capture-condition` | inferred/unknown | Scene grouping metadata. |
| `--background-negative-count` | 0 | Generate N background-only negatives. |
| `--random-seed` | 42 | Seed for background-negative selection. |

### Duplicate groups

The detector can emit several nearby candidates for one physical object. With
`--group-nearby-candidates`, candidates with centers within
`--duplicate-center-distance` (event space) and overlapping lifetimes (within
`--duplicate-time-overlap-seconds`) get a shared `duplicate_group_id`; the
longest-stationary member is marked primary. **All candidates and their evidence
are retained** — this is review assistance only and never rewrites detector
events.

---

## Review workflow

1. Run the builder → open `output/review.html` **directly in a browser** (no web
   server, no internet).
2. Each candidate is a card: the human-review `comparison_panel.jpg`, plus the
   clean `paired_horizontal.png` and `mask.png` previews, metadata summary, and
   links to the clip and `metadata.json`. Separate control groups:
   **semantic label**, **sample quality**, **confidence** (`high`/`medium`/
   `low`/`unset`), and a notes field. Filter by semantic/quality/state, search by
   ID, navigate prev/next.
3. Click **Download review results** → saves `review_results.json`
   (`candidate_id`, `semantic_label`, `sample_quality`, `confidence`, `notes`,
   `label_schema_version`).

### Static HTML limitation (honest)

A static local HTML page **cannot** safely write to local JSON files. This page
**does not auto-save labels to disk** — it keeps them in page state and you must
use **Download review results**. To persist labels, re-run the builder with
`--review-results`.

### Merging review results back

```powershell
python candidate_dataset_builder.py `
  --events "..\persistent-change-prototype\output\persistent_change_events.json" `
  --output "output\E05_024" `
  --review-results "output\E05_024\review_results.json" `
  --update-labels-only
```

With `--update-labels-only`, the **labels only** are updated — `metadata.json`,
each `model_input/sample.json`, `manifest.json`/`.csv`, and
`training_manifest.json`/`.csv` — and **no images or clips are regenerated**.
Both the **old** review format and the **schema 2.0** format are accepted; legacy
labels are migrated (warnings reported), invalid enum values are reported and
defaulted, and unknown/duplicate ids are reported. (Without
`--update-labels-only`, a normal extraction also merges the labels at the end.)

---

## Example commands (PowerShell)

```powershell
cd "C:\Users\A\Documents\raspi-cctv-project\test modul\candidate-dataset-builder"

python candidate_dataset_builder.py `
  --video "..\normal-background-prototype\input\E05_024.mp4" `
  --events "..\persistent-change-prototype\output\persistent_change_events.json" `
  --reference "..\normal-background-prototype\output\reference_background.jpg" `
  --temporal-mask-video "..\persistent-change-prototype\output\temporal_filtered_mask.mp4" `
  --output "output\E05_024" `
  --camera-id "E05" --scene-id "E05_view" `
  --model-input-size 128 --model-context-padding 24 `
  --model-minimum-region-size 48 --context-model-input-size 256 `
  --difference-mode abs_rgb --crop-upscale 12 `
  --save-model-array `
  --verbose
```

> **The events JSON and the temporal mask video must come from the same source
> video run.** The bundled `persistent_change_events.json` currently has
> `source_video_path = E05_024.mp4`, so the matching video is `E05_024.mp4`.
> **Do not** treat `E05_003` and `E05_024` outputs as interchangeable — run the
> detector per video and pass the matching trio (video, events, temporal mask).

Import review results (updates semantic labels, quality, confidence, notes,
metadata, regular + training manifests, and `sample.json` — without regenerating
images):

```powershell
python candidate_dataset_builder.py `
  --events "..\persistent-change-prototype\output\persistent_change_events.json" `
  --output "output\E05_024" `
  --review-results "output\E05_024\review_results.json" `
  --update-labels-only
```

---

## Installation

```bash
pip install -r requirements.txt
```

`sample_config.json` documents every option and its default (it is a reference;
the builder takes its settings from CLI flags, not from that file).

## Tests

```bash
python -m unittest discover -s tests
```

Covers event normalization, bbox format conversion, event→source scaling, context
clipping, minimum context size, crop padding, time→frame conversion, invalid-bbox
handling, manifest creation, duplicate-group detection, empty-event-list handling,
and the schema-2.0 additions: shared/square crop alignment, boundary padding,
nearest-neighbor mask resize, difference modes, mask-source fallback, legacy-label
migration, semantic/quality validation, schema-2.0 review import,
usable-for-training calculation, alignment failure handling, camera/source
grouping, background-negative non-overlap, and deterministic seeding
(**36 tests**).

---

## Failure cases (handled)

Fatal init errors (nonzero exit): missing/malformed event JSON, missing video,
missing reference, no event list, output-write failure, video that cannot be
opened. Per-candidate problems (invalid/out-of-frame bbox, frame read failure,
clip writer failure) are recorded and **skipped** so one bad candidate does not
abort the rest; reasons are collected in `extraction_summary.json`.

## Current limitations

- It **creates labeled candidate-classification samples; it does not train a
  classifier and does not prove cross-camera generalization.**
- No classification happens here — labeling is a human task.
- Enlarged crops never reveal detail beyond the source pixels (smooth = interp).
- The current event JSON has **no per-candidate mask**, so without
  `--temporal-mask-video` the mask is a `bbox_fallback` filled box (flagged); the
  detector mask itself is a difference/temporal mask, not a precise object
  segmentation.
- Clips use a fixed event bbox (no per-frame bbox history in the event JSON).
- Event/source resolution scaling assumes shared aspect ratio (true here).
- The review page cannot persist labels by itself (static HTML) — use Download +
  `--review-results`.
- Train/validation splitting is **not** performed — only the grouping metadata is
  recorded; split by `group_key`/`camera_id` downstream to avoid leakage.

## Next planned module

A **dataset exporter** that consumes `training_manifest.json`: emit a leakage-safe
train/val split grouped by `group_key`, with image-level classification labels,
optional **manual bbox correction**, negative-example export, and duplicate/source
grouping. (Whether a few-pixel object suits YOLO vs. an image-level classifier
should be decided after reviewing real labels.) The exact next module should be
chosen **after** inspecting human-review results. Model training/deployment is out
of scope here.

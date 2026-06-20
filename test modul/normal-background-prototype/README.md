# Normal Background Prototype

A standalone classical computer-vision prototype that generates a **normal
reference background image** from a fixed-view CCTV video using **per-pixel
temporal median calculation**.

This is **not** a deep-learning model. It is a self-contained experiment that
will be tested independently and integrated into the main project later. It does
not depend on, modify, or read anything from the rest of the repository.

---

## What it does

For a camera with a **fixed viewpoint**, each pixel mostly shows the static
scene over time. By sampling frames across the whole video and taking the
**median value of every pixel independently along the time axis**, we recover a
clean image of the static scene.

### Why temporary moving objects tend to disappear

A person or vehicle occupies any given pixel for only a small fraction of the
sampled frames. Since the **median** picks the middle value of each pixel over
time, transient objects that appear in only a minority of frames are outvoted by
the static background and "disappear".

### Why persistent objects may remain

If an object stays in roughly the **same place for most of the video**, it
occupies the majority of sampled frames at those pixels. The median then treats
it as part of the static scene, so it **remains** in the final reference
background. This is an inherent limitation of the temporal-median approach.

---

## Folder structure

```
normal-background-prototype/
├─ background_builder.py     # main script
├─ requirements.txt          # third-party dependencies
├─ README.md                 # this file
├─ input/                    # place your normal-state CCTV video here
│  └─ .gitkeep
└─ output/                   # generated results are written here
   └─ .gitkeep
```

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Expected input

Place **one** normal-state CCTV video (e.g. `normal_video.mp4`) inside the
`input/` folder. The camera is assumed to have a fixed viewpoint.

## Run command

```bash
python3 background_builder.py --input input/normal_video.mp4 --output output --interval 2 --max-frames 300
```

## Expected outputs

- `output/reference_background.jpg` — the generated reference background image.
- `output/reference_metadata.json` — generation metadata (resolution, sampling
  settings, sampled frame count, estimated memory, timestamp, etc.).

---

## CLI options

| Option                    | Default | Description                                                        |
| ------------------------- | ------- | ------------------------------------------------------------------ |
| `--input`                 | (req.)  | Required input video path.                                         |
| `--output`                | `output`| Output directory.                                                  |
| `--interval`              | `2.0`   | Sampling interval in seconds.                                      |
| `--max-frames`            | `300`   | Maximum sampled frame count (hard cap).                            |
| `--width`                 | (orig.) | Optional processing width. Omit to keep original width.            |
| `--height`                | (orig.) | Optional processing height. Omit to keep original height.          |
| `--blur`                  | off     | Enable Gaussian blur before median calculation.                    |
| `--blur-kernel`           | `5`     | Gaussian blur kernel size. Positive odd integer.                   |
| `--normalize-brightness`  | off     | Enable simple brightness normalization.                            |
| `--jpeg-quality`          | `95`    | JPEG output quality (1–100).                                       |

### Brightness normalization method

When `--normalize-brightness` is enabled, the final image is converted
`BGR → LAB`, **histogram equalization** is applied to the **L (luminance)
channel only**, and the image is converted back to `BGR`. This evens out overall
luminance without altering color balance and without any learned model.

---

## Memory considerations

The future target environment is a **Raspberry Pi 4B (4 GB RAM)**, though this
prototype may be tested on a development PC. Stacking many full-resolution frames
can exhaust memory, so before computing the median the script estimates:

```
sampled_frame_count × width × height × channels × bytes_per_value
```

The estimate is printed. If it exceeds the documented safety threshold
(`MEMORY_SAFETY_THRESHOLD_MB = 1500 MB`, defined in `background_builder.py`),
the program **stops with a clear error** instead of crashing and recommends:

- reducing `--max-frames`
- reducing `--width` and `--height`
- increasing `--interval`

---

## Current limitations

- Persistent or slow-moving objects may survive into the background (see above).
- Assumes a genuinely **fixed** camera; it does **not** perform camera
  stabilization, so a shaking or panning camera will blur the result.
- Produces a **single** reference background — no day/night handling, no
  multiple references.
- Timestamp-based seeking accuracy depends on the video container/codec and the
  OpenCV backend. When FPS/duration metadata is missing, the script falls back
  to frame-step sampling.
- No detection, tracking, OCR, YOLO, background subtraction, anomaly detection,
  or real-time inference is performed — by design.

---

## Next future step

The next stage is **current-frame comparison** against this reference
background. The broader intended pipeline (not implemented here) is:

```
normal-state video
→ reference background generation   ← (this prototype)
→ current-frame comparison
→ persistent change tracking
→ YOLO result fusion
→ pollution score calculation
```

Only the reference-background generation stage is implemented in this prototype.

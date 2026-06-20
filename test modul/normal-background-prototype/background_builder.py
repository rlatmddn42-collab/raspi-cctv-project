#!/usr/bin/env python3
"""
background_builder.py

Generate a normal reference background image from a fixed-view CCTV video
using per-pixel temporal median calculation.

This is a standalone classical computer-vision prototype. It is NOT a
deep-learning model and is independent from the main project. The idea:
for a camera with a fixed viewpoint, the most common (median) value of each
pixel over time approximates the static scene. Temporary moving objects
(people, vehicles) appear in only a minority of sampled frames, so the median
"sees through" them. Objects that remain visible during most of the video may
still survive into the final background -- see README limitations.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment dependent
    sys.stderr.write(
        "ERROR: required third-party package missing: {}\n"
        "Install dependencies with: pip install -r requirements.txt\n".format(exc)
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Memory safety
# ---------------------------------------------------------------------------
# The target deployment is a Raspberry Pi 4B with 4 GB RAM. Stacking many
# full-resolution frames into a single NumPy array can easily exhaust memory.
# We refuse to start the median computation if the estimated stack size exceeds
# this threshold. The value is intentionally conservative so the prototype is
# safe both on the Pi and on a development PC.
MEMORY_SAFETY_THRESHOLD_MB = 1500.0  # documented hard limit for the frame stack

CHANNELS = 3            # BGR
BYTES_PER_VALUE = 1     # uint8


def log(message):
    """Print a progress/status message immediately."""
    print(message, flush=True)


def fail(message, code=1):
    """Print a clear error message and exit with a non-zero exit code."""
    sys.stderr.write("ERROR: {}\n".format(message))
    sys.exit(code)


# ---------------------------------------------------------------------------
# Argument parsing / validation
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a normal reference background from a fixed-view "
                    "CCTV video using temporal median calculation."
    )
    parser.add_argument("--input", required=True,
                        help="Required input video path.")
    parser.add_argument("--output", default="output",
                        help="Output directory. Default: output")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="Sampling interval in seconds. Default: 2.0")
    parser.add_argument("--max-frames", type=int, default=300,
                        help="Maximum sampled frame count. Default: 300")
    parser.add_argument("--width", type=int, default=None,
                        help="Optional processing width. "
                             "If omitted, preserve original width.")
    parser.add_argument("--height", type=int, default=None,
                        help="Optional processing height. "
                             "If omitted, preserve original height.")
    parser.add_argument("--blur", action="store_true",
                        help="Enable Gaussian blur before median calculation. "
                             "Disabled by default.")
    parser.add_argument("--blur-kernel", type=int, default=5,
                        help="Gaussian blur kernel size. Default: 5. "
                             "Must be a positive odd integer.")
    parser.add_argument("--normalize-brightness", action="store_true",
                        help="Enable simple brightness normalization.")
    parser.add_argument("--jpeg-quality", type=int, default=95,
                        help="JPEG output quality. Default: 95")
    return parser.parse_args(argv)


def validate_args(args):
    """Validate user-supplied options before touching the video."""
    if not os.path.exists(args.input):
        fail("input file does not exist: {}".format(args.input))
    if not os.path.isfile(args.input):
        fail("input path is not a file: {}".format(args.input))

    if not (args.interval > 0):
        fail("invalid interval: must be > 0 (got {})".format(args.interval))

    if args.max_frames < 1:
        fail("invalid max-frames: must be >= 1 (got {})".format(args.max_frames))

    if args.width is not None and args.width < 1:
        fail("invalid width: must be >= 1 (got {})".format(args.width))
    if args.height is not None and args.height < 1:
        fail("invalid height: must be >= 1 (got {})".format(args.height))

    if args.blur:
        if args.blur_kernel < 1 or args.blur_kernel % 2 == 0:
            fail("invalid blur-kernel: must be a positive odd integer "
                 "(got {})".format(args.blur_kernel))

    if not (1 <= args.jpeg_quality <= 100):
        fail("invalid jpeg-quality: must be between 1 and 100 "
             "(got {})".format(args.jpeg_quality))


# ---------------------------------------------------------------------------
# Video metadata
# ---------------------------------------------------------------------------
def read_metadata(cap):
    """Read and report basic video metadata. Missing values are handled safely."""
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    # FPS / frame count may be reported as 0 or NaN by some backends/containers.
    if fps is None or fps != fps or fps <= 0:  # NaN check via fps != fps
        log("WARNING: FPS metadata unavailable; will sample by frame count instead.")
        fps = None
    if frame_count is None or frame_count != frame_count or frame_count <= 0:
        log("WARNING: total frame count unavailable; duration is unknown.")
        frame_count = None

    duration = None
    if fps and frame_count:
        duration = frame_count / fps

    return {
        "fps": fps,
        "frame_count": int(frame_count) if frame_count else None,
        "width": width,
        "height": height,
        "duration": duration,
    }


def print_metadata(meta, interval):
    log("Video opened successfully")
    log("Resolution: {}x{}".format(meta["width"], meta["height"]))
    log("FPS: {}".format(meta["fps"] if meta["fps"] else "unknown"))
    if meta["duration"] is not None:
        log("Duration: {:.1f} seconds".format(meta["duration"]))
    else:
        log("Duration: unknown")
    log("Sampling interval: {} seconds".format(interval))


# ---------------------------------------------------------------------------
# Frame sampling
# ---------------------------------------------------------------------------
def preprocess_frame(frame, args):
    """Optionally resize and blur a single frame."""
    if args.width is not None or args.height is not None:
        h, w = frame.shape[:2]
        target_w = args.width if args.width is not None else w
        target_h = args.height if args.height is not None else h
        frame = cv2.resize(frame, (target_w, target_h),
                           interpolation=cv2.INTER_AREA)

    if args.blur:
        frame = cv2.GaussianBlur(frame, (args.blur_kernel, args.blur_kernel), 0)

    return frame


def sample_frames(cap, meta, args):
    """
    Sample frames at the configured time interval rather than reading every
    frame. We prefer seeking by timestamp (CAP_PROP_POS_MSEC); if FPS is known
    we can also derive a frame-step fallback. Never exceed --max-frames.

    Returns a list of preprocessed frames (BGR uint8 arrays).
    """
    frames = []
    skipped = 0

    fps = meta["fps"]
    duration = meta["duration"]
    interval_ms = args.interval * 1000.0

    if fps and duration:
        # Known timeline: compute deterministic sample timestamps.
        num_possible = int(duration // args.interval) + 1
        num_samples = min(num_possible, args.max_frames)
        for i in range(num_samples):
            target_ms = i * interval_ms
            cap.set(cv2.CAP_PROP_POS_MSEC, target_ms)
            ok, frame = cap.read()
            if not ok or frame is None:
                skipped += 1
                log("WARNING: could not read frame at {:.1f}s; skipping."
                    .format(target_ms / 1000.0))
                continue
            frames.append(preprocess_frame(frame, args))
            log("Collected {} / {} frames".format(len(frames), num_samples))
    else:
        # Unknown timeline: step sequentially. If FPS is known, convert the time
        # interval into a frame step; otherwise fall back to every Nth frame.
        frame_step = int(round(fps * args.interval)) if fps else 30
        if frame_step < 1:
            frame_step = 1
        idx = 0
        while len(frames) < args.max_frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                break  # end of stream
            if idx % frame_step == 0:
                frames.append(preprocess_frame(frame, args))
                log("Collected {} / {} frames".format(len(frames), args.max_frames))
            idx += 1

    if skipped:
        log("Skipped {} unreadable frame(s).".format(skipped))

    if not frames:
        fail("no valid frames sampled from the input video.")

    return frames


# ---------------------------------------------------------------------------
# Memory estimation
# ---------------------------------------------------------------------------
def estimate_memory_mb(frame_count, width, height):
    """Estimate the memory needed to stack the sampled frames, in megabytes."""
    total_bytes = frame_count * width * height * CHANNELS * BYTES_PER_VALUE
    return total_bytes / (1024.0 * 1024.0)


def check_memory(frame_count, width, height):
    est_mb = estimate_memory_mb(frame_count, width, height)
    log("Estimated memory usage for frame stack: {:.1f} MB".format(est_mb))
    if est_mb > MEMORY_SAFETY_THRESHOLD_MB:
        fail(
            "estimated memory usage {:.1f} MB exceeds the safety threshold "
            "of {:.1f} MB.\n"
            "  Recommendations:\n"
            "    - reduce --max-frames\n"
            "    - reduce --width and --height\n"
            "    - increase --interval".format(est_mb, MEMORY_SAFETY_THRESHOLD_MB)
        )
    return est_mb


# ---------------------------------------------------------------------------
# Brightness normalization
# ---------------------------------------------------------------------------
def normalize_brightness(image):
    """
    Simple, lightweight brightness normalization.

    Method: convert BGR -> LAB, apply histogram equalization to the L
    (luminance) channel only, then convert back to BGR. This evens out overall
    luminance without altering color balance and without any learned model.
    """
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    l_channel = cv2.equalizeHist(l_channel)
    lab = cv2.merge((l_channel, a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


# ---------------------------------------------------------------------------
# Temporal median
# ---------------------------------------------------------------------------
def compute_median(frames):
    """Stack frames along a new time axis and take the per-pixel median."""
    stack = np.stack(frames, axis=0)            # shape: (N, H, W, C)
    median = np.median(stack, axis=0)           # per-pixel median over time
    return median.astype(np.uint8)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def save_outputs(image, metadata, output_dir, jpeg_quality):
    image_name = "reference_background.jpg"
    metadata_name = "reference_metadata.json"
    image_path = os.path.join(output_dir, image_name)
    metadata_path = os.path.join(output_dir, metadata_name)

    ok = cv2.imwrite(image_path, image,
                     [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        fail("image save failure: could not write {}".format(image_path))
    log("Reference background saved")

    try:
        with open(metadata_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)
    except OSError as exc:
        fail("metadata save failure: {}".format(exc))
    log("Metadata saved")

    return image_path, metadata_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)
    validate_args(args)

    # Prepare output directory.
    try:
        os.makedirs(args.output, exist_ok=True)
    except OSError as exc:
        fail("output directory creation failure: {}".format(exc))

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        fail("video cannot be opened: {}".format(args.input))

    try:
        meta = read_metadata(cap)
        print_metadata(meta, args.interval)

        frames = sample_frames(cap, meta, args)
    finally:
        cap.release()

    # Determine final processing resolution from the actual sampled frames.
    proc_h, proc_w = frames[0].shape[:2]

    # Memory safety check happens before stacking.
    est_mb = check_memory(len(frames), proc_w, proc_h)

    log("Starting temporal median calculation")
    background = compute_median(frames)

    if args.normalize_brightness:
        background = normalize_brightness(background)

    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "source_video": os.path.basename(args.input),
        "source_video_path": args.input,
        "source_fps": meta["fps"],
        "source_frame_count": meta["frame_count"],
        "source_width": meta["width"],
        "source_height": meta["height"],
        "source_duration_seconds": meta["duration"],
        "sampling_interval_seconds": args.interval,
        "maximum_sampled_frames": args.max_frames,
        "sampled_frame_count": len(frames),
        "processing_width": proc_w,
        "processing_height": proc_h,
        "gaussian_blur_enabled": bool(args.blur),
        "gaussian_blur_kernel": args.blur_kernel,
        "brightness_normalization_enabled": bool(args.normalize_brightness),
        "jpeg_quality": args.jpeg_quality,
        "estimated_memory_megabytes": round(est_mb, 1),
        "output_image": "reference_background.jpg",
        "generated_at": generated_at,
    }

    save_outputs(background, metadata, args.output, args.jpeg_quality)

    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

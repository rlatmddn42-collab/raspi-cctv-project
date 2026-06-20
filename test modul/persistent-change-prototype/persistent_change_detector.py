#!/usr/bin/env python3
"""
persistent_change_detector.py

Detect *persistent pollution-change candidates* in a fixed-view CCTV test video
by comparing each processed frame against an already-generated fixed reference
background image, while SUPPRESSING moving objects (people, vehicles, shadows)
as whole regions.

Standalone classical computer-vision prototype, independent from the main
project. NO YOLO / OCR / person detection / pose / optical flow / DeepSORT /
ByteTrack / neural segmentation. It only generates better small, spatially
stable, persistent change candidates for a later YOLO fusion stage.

Key correction in this version
------------------------------
A single moving person fragments into many contours (face / torso / legs /
shadow). Center tracking of those fragments is meaningless. So we now use TWO
clearly separate masks:

  A. MOTION mask  -- current-vs-previous-frame difference; finds dynamic areas.
                     Fragments are MERGED and PADDED into broad dynamic regions.
  B. REFERENCE-DIFFERENCE mask -- current-vs-fixed-reference; finds scene change.

  stationary_candidate_mask = reference_difference_mask AND NOT dynamic_exclusion

The dynamic exclusion = merged+padded motion regions, kept alive for a short
COOLDOWN after motion leaves (shadows / exposure adaptation / compression leave
residue). Only what survives motion + cooldown enters persistent tracking.

Sequence we want:
  person enters -> motion fragments -> merged into broad exclusion ->
  all person pixels suppressed -> person leaves -> cooldown ->
  remaining small stationary object becomes candidate -> stationary duration
  accumulates -> persistent region created.
"""

import argparse
import json
import math
import os
import sys
from collections import deque
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


DEFAULT_REFERENCE = "../normal-background-prototype/output/reference_background.jpg"

# Generous gate used only to reject impossible *matches* (not stability).
MATCH_AREA_REJECT_RATIO = 0.7
# Fraction of a region's bbox that must fall inside the exclusion mask for the
# region to be considered "covered by motion / cooldown".
COVERED_FRACTION = 0.3

# Region states (also used as metadata labels).
STATE_NOISE = "noise_rejected"
STATE_UNSTABLE = "candidate_unstable"      # active candidate, not stationary long enough
STATE_STATIONARY = "candidate_stationary"  # active stable stationary candidate
STATE_PERSISTENT = "persistent"
STATE_LARGE = "large_change_ignored"
STATE_MISSING = "missing"
STATE_EXPIRED = "expired"
# Occlusion lifecycle states.
STATE_ACTIVE = "active"
STATE_OCCLUDED = "occluded_by_motion"          # non-persistent, motion over it now
STATE_PERSISTENT_OCCLUDED = "persistent_occluded"
STATE_COOLDOWN_WAIT = "cooldown_wait"          # motion cleared, waiting to reappear
STATE_RESUMED = "resumed"                      # just re-acquired after occlusion

# Annotated-video colors (BGR).
COLOR_LARGE = (150, 150, 150)        # gray: ignored large local change
COLOR_UNSTABLE = (0, 165, 255)       # orange: candidate
COLOR_STATIONARY = (0, 255, 255)     # yellow: stationary candidate accumulating
COLOR_PERSISTENT = (0, 0, 255)       # red: persistent
COLOR_OCCLUDED = (128, 0, 128)       # purple: occluded by motion
COLOR_PERSISTENT_OCCLUDED = (255, 0, 255)  # magenta: persistent but occluded
COLOR_RESUMED = (255, 255, 0)        # cyan: resumed after occlusion
COLOR_MOTION = (255, 0, 0)           # blue: merged dynamic motion region
COLOR_COOLDOWN = (255, 200, 130)     # light blue: motion cooldown area tint
COLOR_TEXT = (255, 255, 255)
COLOR_WARNING = (0, 0, 255)


def log(message):
    print(message, flush=True)


def fail(message, code=1):
    sys.stderr.write("ERROR: {}\n".format(message))
    sys.exit(code)


# ---------------------------------------------------------------------------
# Argument parsing / validation
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Detect persistent SMALL, spatially-stable pollution-change "
                    "candidates while suppressing moving objects as whole "
                    "dynamic regions.")
    p.add_argument("--input", required=True, help="Required test video path.")
    p.add_argument("--reference", default=DEFAULT_REFERENCE,
                   help="Reference background image path. Default: {}".format(DEFAULT_REFERENCE))
    p.add_argument("--output", default="output", help="Output directory. Default: output")
    p.add_argument("--processing-fps", type=float, default=3.0,
                   help="Video frames processed per second. Default: 3")
    p.add_argument("--width", type=int, default=None, help="Optional processing width.")
    p.add_argument("--height", type=int, default=None, help="Optional processing height.")
    p.add_argument("--threshold", type=int, default=30,
                   help="Reference-difference pixel threshold (0..255). Default: 30")

    # Reference-difference area filtering.
    p.add_argument("--min-area", type=int, default=30,
                   help="Minimum changed area in px (reject tiny noise). "
                        "Default: 30 (resolution-dependent).")
    p.add_argument("--max-area", type=int, default=5000,
                   help="Maximum changed area in px (reject large objects). "
                        "Default: 5000 (resolution-dependent).")
    p.add_argument("--min-area-ratio", type=float, default=0.00001,
                   help="Minimum contour_area/frame_area. Default: 0.00001")
    p.add_argument("--max-area-ratio", type=float, default=0.02,
                   help="Maximum contour_area/frame_area. Default: 0.02")
    p.add_argument("--disable-area-ratio-filter", action="store_true",
                   help="Disable ratio filtering; use only --min-area/--max-area.")

    # Spatial stability tracking.
    p.add_argument("--max-center-movement", type=float, default=12.0,
                   help="Max center movement (px) per frame for a stable match. Default: 12")
    p.add_argument("--max-center-movement-ratio", type=float, default=0.015,
                   help="Max center movement as fraction of processing diagonal. Default: 0.015")
    p.add_argument("--max-size-change-ratio", type=float, default=0.35,
                   help="Max relative area change for a stable match. Default: 0.35")
    p.add_argument("--stability-window", type=int, default=8,
                   help="Recent matched observations for the stable ratio. Default: 8")
    p.add_argument("--minimum-stationary-ratio", type=float, default=0.8,
                   help="Min fraction of recent matches that must be stable. Default: 0.8")

    # Persistence / lifecycle.
    p.add_argument("--persistence-seconds", type=float, default=5.0,
                   help="Required STATIONARY duration before persistent. Default: 5")
    p.add_argument("--missing-grace-seconds", type=float, default=2.0,
                   help="Time a (never-occluded) region may disappear before removal. Default: 2")

    # Motion-occlusion survival (keep candidates alive under a passing person).
    p.add_argument("--motion-occlusion-overlap-ratio", type=float, default=0.3,
                   help="Motion overlap (of the protected bbox) above which a "
                        "track is marked occluded and paused (not deleted). Default: 0.3")
    p.add_argument("--motion-occlusion-grace-seconds", type=float, default=5.0,
                   help="After motion/cooldown clears, how long an occluded "
                        "non-persistent track stays alive awaiting reappearance. Default: 5.0")
    p.add_argument("--persistent-occlusion-grace-seconds", type=float, default=10.0,
                   help="Separate, longer grace for an occluded PERSISTENT track. Default: 10.0")
    p.add_argument("--occlusion-recovery-distance", type=float, default=30.0,
                   help="Max center distance (px) from the pre-occlusion bbox to "
                        "re-acquire an occluded track (reuse its ID). Default: 30")
    p.add_argument("--track-protection-padding", type=int, default=5,
                   help="Padding (px) around a track's last bbox; motion inside "
                        "this protected area pauses (never deletes) the track. Default: 5")

    # Matching.
    p.add_argument("--iou-threshold", type=float, default=0.25,
                   help="IoU contribution used in matching. Default: 0.25")
    p.add_argument("--matching-center-distance", type=float, default=40.0,
                   help="Max center distance (px) to allow a match. Default: 40")

    # Reference-difference morphology (separate kernels) + deprecated alias.
    p.add_argument("--open-kernel", type=int, default=None,
                   help="Reference-diff OPENING kernel (remove noise). Default: 3")
    p.add_argument("--close-kernel", type=int, default=None,
                   help="Reference-diff CLOSING kernel (connect fragments). Default: 5")
    p.add_argument("--morph-kernel", type=int, default=None,
                   help="DEPRECATED single kernel; sets both unless open/close given.")
    p.add_argument("--merge-distance", type=float, default=10.0,
                   help="Max gap (px) to merge nearby small candidates. Default: 10")

    # Global scene-change guard (reference-difference based).
    p.add_argument("--global-change-ratio", type=float, default=0.45,
                   help="Reference-diff changed ratio = global scene change. Default: 0.45")

    # ---- Motion stage ----
    p.add_argument("--motion-threshold", type=int, default=25,
                   help="Current-vs-previous frame difference threshold. Default: 25")
    p.add_argument("--motion-open-kernel", type=int, default=3,
                   help="Motion OPENING kernel. Default: 3")
    p.add_argument("--motion-close-kernel", type=int, default=9,
                   help="Motion CLOSING kernel. Default: 9")
    p.add_argument("--motion-dilate-kernel", type=int, default=15,
                   help="Motion DILATION kernel. Default: 15")
    p.add_argument("--motion-dilate-iterations", type=int, default=2,
                   help="Motion dilation iterations. Default: 2")
    p.add_argument("--motion-min-area", type=int, default=300,
                   help="Minimum motion contour area in px. Default: 300")
    p.add_argument("--motion-merge-distance", type=float, default=40.0,
                   help="Max gap (px) to merge motion fragments. Default: 40")
    p.add_argument("--motion-box-padding", type=int, default=20,
                   help="Padding (px) added around each merged motion box. Default: 20")
    p.add_argument("--motion-cooldown-seconds", type=float, default=2.0,
                   help="Keep an area excluded this long after motion leaves. Default: 2.0")
    p.add_argument("--global-motion-ratio", type=float, default=0.35,
                   help="Motion pixel ratio above which the frame is broad motion "
                        "and all candidate updates are suppressed. Default: 0.35")

    # ---- Temporal consistency filter (small-object noise rejection) ----
    p.add_argument("--temporal-window-frames", type=int, default=9,
                   help="Number of recent stationary masks considered for the "
                        "temporal vote. Default: 9")
    p.add_argument("--temporal-min-hits", type=int, default=6,
                   help="A pixel is kept only if it appears in at least this many "
                        "masks within the window. Must be 1..window. Default: 6")
    p.add_argument("--temporal-tolerance-kernel", type=int, default=3,
                   help="Dilation kernel applied (for voting ONLY) to absorb 1-2px "
                        "shifts. 1 = disabled; odd positive only. Default: 3")

    # Output / display.
    p.add_argument("--show-ignored-large-regions", action="store_true",
                   help="Draw ignored large local changes (gray).")
    p.add_argument("--show-motion-regions", action="store_true",
                   help="Draw merged motion regions (blue) and cooldown (cyan).")
    p.add_argument("--save-mask-video", action="store_true",
                   help="Save the reference-difference change-mask video.")
    p.add_argument("--save-motion-mask-video", action="store_true",
                   help="Save the motion-mask video.")
    p.add_argument("--save-stationary-mask-video", action="store_true",
                   help="Save the stationary-candidate-mask video (before temporal voting).")
    p.add_argument("--save-temporal-mask-video", action="store_true",
                   help="Save the temporal-filtered-mask video (used for contours).")
    p.add_argument("--verbose", action="store_true",
                   help="Print one line per processed frame.")
    return p.parse_args(argv)


def resolve_kernels(args):
    open_k = args.open_kernel
    close_k = args.close_kernel
    if open_k is None:
        open_k = args.morph_kernel if args.morph_kernel is not None else 3
    if close_k is None:
        close_k = args.morph_kernel if args.morph_kernel is not None else 5
    return open_k, close_k


def _check_odd_positive(name, value):
    if value < 1 or value % 2 == 0:
        fail("invalid {}: must be a positive odd integer (got {})".format(name, value))


def validate_args(args, open_k, close_k):
    if not os.path.exists(args.input):
        fail("input video does not exist: {}".format(args.input))
    if not os.path.isfile(args.input):
        fail("input path is not a file: {}".format(args.input))
    if not os.path.exists(args.reference):
        fail("reference image does not exist: {}".format(args.reference))
    if not os.path.isfile(args.reference):
        fail("reference path is not a file: {}".format(args.reference))

    if not (args.processing_fps > 0):
        fail("invalid processing-fps: must be > 0 (got {})".format(args.processing_fps))
    if not (0 <= args.threshold <= 255):
        fail("invalid threshold: must be 0..255 (got {})".format(args.threshold))
    if not (0 <= args.motion_threshold <= 255):
        fail("invalid motion-threshold: must be 0..255 (got {})".format(args.motion_threshold))

    if args.min_area < 1:
        fail("invalid min-area: must be positive (got {})".format(args.min_area))
    if args.max_area <= args.min_area:
        fail("invalid max-area: must be greater than min-area ({} <= {})".format(args.max_area, args.min_area))
    if not (0 < args.min_area_ratio < args.max_area_ratio <= 1.0):
        fail("invalid area ratios: require 0 < min < max <= 1 (got {} and {})".format(
            args.min_area_ratio, args.max_area_ratio))
    if args.motion_min_area < 1:
        fail("invalid motion-min-area: must be positive (got {})".format(args.motion_min_area))

    if not (args.persistence_seconds > 0):
        fail("invalid persistence-seconds: must be > 0 (got {})".format(args.persistence_seconds))
    if args.missing_grace_seconds < 0:
        fail("invalid missing-grace-seconds: must be >= 0 (got {})".format(args.missing_grace_seconds))
    if not (0.0 < args.motion_occlusion_overlap_ratio <= 1.0):
        fail("invalid motion-occlusion-overlap-ratio: must be in (0,1] (got {})".format(args.motion_occlusion_overlap_ratio))
    if args.motion_occlusion_grace_seconds < 0:
        fail("invalid motion-occlusion-grace-seconds: must be >= 0 (got {})".format(args.motion_occlusion_grace_seconds))
    if args.persistent_occlusion_grace_seconds < 0:
        fail("invalid persistent-occlusion-grace-seconds: must be >= 0 (got {})".format(args.persistent_occlusion_grace_seconds))
    if args.occlusion_recovery_distance <= 0:
        fail("invalid occlusion-recovery-distance: must be > 0 (got {})".format(args.occlusion_recovery_distance))
    if args.track_protection_padding < 0:
        fail("invalid track-protection-padding: must be >= 0 (got {})".format(args.track_protection_padding))
    if args.motion_cooldown_seconds < 0:
        fail("invalid motion-cooldown-seconds: must be >= 0 (got {})".format(args.motion_cooldown_seconds))
    if not (0.0 <= args.iou_threshold <= 1.0):
        fail("invalid iou-threshold: must be 0..1 (got {})".format(args.iou_threshold))
    if args.matching_center_distance <= 0:
        fail("invalid matching-center-distance: must be > 0 (got {})".format(args.matching_center_distance))
    if args.max_center_movement < 0:
        fail("invalid max-center-movement: must be >= 0 (got {})".format(args.max_center_movement))
    if not (0 <= args.max_center_movement_ratio <= 1.0):
        fail("invalid max-center-movement-ratio: must be 0..1 (got {})".format(args.max_center_movement_ratio))
    if not (0 < args.max_size_change_ratio <= 1.0):
        fail("invalid max-size-change-ratio: must be in (0,1] (got {})".format(args.max_size_change_ratio))
    if args.stability_window < 1:
        fail("invalid stability-window: must be >= 1 (got {})".format(args.stability_window))
    if not (0 < args.minimum_stationary_ratio <= 1.0):
        fail("invalid minimum-stationary-ratio: must be in (0,1] (got {})".format(args.minimum_stationary_ratio))
    if args.merge_distance < 0:
        fail("invalid merge-distance: must be >= 0 (got {})".format(args.merge_distance))
    if args.motion_merge_distance < 0:
        fail("invalid motion-merge-distance: must be >= 0 (got {})".format(args.motion_merge_distance))
    if args.motion_box_padding < 0:
        fail("invalid motion-box-padding: must be >= 0 (got {})".format(args.motion_box_padding))
    if args.motion_dilate_iterations < 0:
        fail("invalid motion-dilate-iterations: must be >= 0 (got {})".format(args.motion_dilate_iterations))

    _check_odd_positive("open-kernel", open_k)
    _check_odd_positive("close-kernel", close_k)
    _check_odd_positive("motion-open-kernel", args.motion_open_kernel)
    _check_odd_positive("motion-close-kernel", args.motion_close_kernel)
    _check_odd_positive("motion-dilate-kernel", args.motion_dilate_kernel)

    if not (0.0 < args.global_change_ratio <= 1.0):
        fail("invalid global-change-ratio: must be in (0,1] (got {})".format(args.global_change_ratio))
    if not (0.0 < args.global_motion_ratio <= 1.0):
        fail("invalid global-motion-ratio: must be in (0,1] (got {})".format(args.global_motion_ratio))
    if args.temporal_window_frames < 1:
        fail("invalid temporal-window-frames: must be >= 1 (got {})".format(args.temporal_window_frames))
    if not (1 <= args.temporal_min_hits <= args.temporal_window_frames):
        fail("invalid temporal-min-hits: must be between 1 and "
             "--temporal-window-frames ({}) (got {})".format(
                 args.temporal_window_frames, args.temporal_min_hits))
    _check_odd_positive("temporal-tolerance-kernel", args.temporal_tolerance_kernel)
    if args.width is not None and args.width < 1:
        fail("invalid width: must be >= 1 (got {})".format(args.width))
    if args.height is not None and args.height < 1:
        fail("invalid height: must be >= 1 (got {})".format(args.height))


# ---------------------------------------------------------------------------
# Resolution / preprocessing / geometry
# ---------------------------------------------------------------------------
def resolve_processing_size(args, src_w, src_h):
    if args.width and args.height:
        return args.width, args.height, "explicit width and height"
    if args.width and not args.height:
        scale = args.width / float(src_w)
        return args.width, max(1, int(round(src_h * scale))), \
            "width given; height derived to preserve aspect ratio"
    if args.height and not args.width:
        scale = args.height / float(src_h)
        return max(1, int(round(src_w * scale))), args.height, \
            "height given; width derived to preserve aspect ratio"
    return src_w, src_h, "source video resolution"


def preprocess(image_bgr, size, blur_kernel=5):
    resized = cv2.resize(image_bgr, size, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
    return gray


def bbox_center(box):
    x, y, w, h = box
    return (x + w / 2.0, y + h / 2.0)


def center_distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def iou(box_a, box_b):
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, x2 - x1), max(0, y2 - y1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / float(union) if union > 0 else 0.0


def box_gap(box_a, box_b):
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    dx = max(0, max(ax - (bx + bw), bx - (ax + aw)))
    dy = max(0, max(ay - (by + bh), by - (ay + ah)))
    return math.hypot(dx, dy)


def union_box(box_a, box_b):
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    x1, y1 = min(ax, bx), min(ay, by)
    x2 = max(ax + aw, bx + bw)
    y2 = max(ay + ah, by + bh)
    return (x1, y1, x2 - x1, y2 - y1)


def merge_boxes(boxes, merge_distance, max_area=None, max_area_ratio=None,
                total_pixels=None):
    """Distance-based rectangle-union merge. If max_area/ratio are given, only
    merge when the union stays within those limits (used for candidates)."""
    items = list(boxes)
    merged = True
    while merged:
        merged = False
        n = len(items)
        for i in range(n):
            for j in range(i + 1, n):
                if box_gap(items[i], items[j]) > merge_distance:
                    continue
                ub = union_box(items[i], items[j])
                ub_area = ub[2] * ub[3]
                if max_area is not None and ub_area > max_area:
                    continue
                if (max_area_ratio is not None and total_pixels and
                        (ub_area / total_pixels) > max_area_ratio):
                    continue
                items[i] = ub
                del items[j]
                merged = True
                break
            if merged:
                break
    return items


def pad_clip(box, pad, frame_w, frame_h):
    x, y, w, h = box
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(frame_w, x + w + pad)
    y2 = min(frame_h, y + h + pad)
    return (x1, y1, x2 - x1, y2 - y1)


def bbox_covered(mask, box, frac=COVERED_FRACTION):
    """True if at least `frac` of the box area is set in mask (uint8 0/255)."""
    x, y, w, h = box
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(mask.shape[1], x + w), min(mask.shape[0], y + h)
    if x2 <= x1 or y2 <= y1:
        return False
    roi = mask[y1:y2, x1:x2]
    if roi.size == 0:
        return False
    return cv2.countNonZero(roi) >= frac * roi.size


# ---------------------------------------------------------------------------
# Motion mask
# ---------------------------------------------------------------------------
def build_motion(prev_gray, cur_gray, args, motion_open, motion_close,
                 motion_dilate, frame_w, frame_h):
    """
    Return (motion_binary, merged_padded_boxes, n_raw_regions, n_merged_regions).

    motion_binary: dilated binary motion mask (white = current motion).
    merged_padded_boxes: broad dynamic regions to exclude.
    The motion mask is intentionally more inclusive than the reference-diff mask:
    the goal is to cover the WHOLE area of a moving person/vehicle, not segment it.
    """
    diff = cv2.absdiff(prev_gray, cur_gray)
    _, m = cv2.threshold(diff, args.motion_threshold, 255, cv2.THRESH_BINARY)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, motion_open)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, motion_close)
    if args.motion_dilate_iterations > 0:
        m = cv2.dilate(m, motion_dilate, iterations=args.motion_dilate_iterations)

    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    raw_boxes = [cv2.boundingRect(c) for c in contours
                 if cv2.contourArea(c) >= args.motion_min_area]
    merged = merge_boxes(raw_boxes, args.motion_merge_distance)
    padded = [pad_clip(b, args.motion_box_padding, frame_w, frame_h) for b in merged]
    return m, padded, len(raw_boxes), len(merged)


def boxes_to_mask(boxes, frame_w, frame_h):
    mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
    for (x, y, w, h) in boxes:
        cv2.rectangle(mask, (x, y), (x + w, y + h), 255, thickness=-1)
    return mask


# ---------------------------------------------------------------------------
# Tracked region
# ---------------------------------------------------------------------------
class TrackedRegion:
    def __init__(self, region_id, bbox, area, now, stability_window):
        self.region_id = region_id
        self.bbox = bbox
        self.area = area
        self.center = bbox_center(bbox)
        self.prev_center = None
        self.first_seen = now
        self.last_seen = now
        self.visible_duration = 0.0
        self.stationary_duration = 0.0
        self.matched_count = 1
        self.missing_duration = 0.0
        self.max_area = area
        self.min_area = area
        self.center_history = deque([self.center], maxlen=stability_window)
        self.area_history = deque([area], maxlen=stability_window)
        self.stable_history = deque(maxlen=stability_window)
        self.accumulated_movement = 0.0
        self.movement_sum = 0.0
        self.movement_max = 0.0
        self.movement_count = 0
        self.last_movement = 0.0
        self.stable_total = 0
        self.persistent = False
        self.became_stationary_seconds = None
        self.became_persistent_seconds = None
        self.state = STATE_UNSTABLE
        # Occlusion lifecycle. Track memory is independent of the current mask:
        # motion overlap PAUSES a track, it never deletes it or resets history.
        self.occluded = False                       # motion currently over it
        self.occlusion_count = 0
        self.total_occluded_duration = 0.0
        self.occlusion_start_time = None            # current occlusion start
        self.last_occlusion_start_seconds = None    # most recent occlusion start
        self.last_bbox_before_occlusion = None
        self.stationary_duration_before_occlusion = None
        self.resumed_after_occlusion_count = 0
        self.unobserved_since_clear = 0.0           # time absent AFTER motion cleared
        self.expired_reason = None

    # -- helpers ------------------------------------------------------------
    def _enter_occlusion(self, now, dt):
        if not self.occluded:
            # transition into occlusion: snapshot what we must preserve
            self.occluded = True
            self.occlusion_count += 1
            self.occlusion_start_time = now
            self.last_occlusion_start_seconds = now
            self.last_bbox_before_occlusion = self.bbox
            self.stationary_duration_before_occlusion = self.stationary_duration
        self.total_occluded_duration += dt
        self.unobserved_since_clear = 0.0  # frozen while motion is over it
        self.state = STATE_PERSISTENT_OCCLUDED if self.persistent else STATE_OCCLUDED

    def _clear_occlusion_flag(self):
        self.occluded = False

    # -- per-frame updates --------------------------------------------------
    def observe(self, bbox, area, now, dt, move_thresh, max_size_change_ratio,
                minimum_stationary_ratio, min_area, max_area, resumed=False):
        """A compatible stationary region was matched this frame (it is, by
        construction, outside the exclusion mask). Accumulate normally."""
        new_center = bbox_center(bbox)
        movement = center_distance(new_center, self.center)
        last_area = self.area
        area_change = abs(area - last_area) / float(max(area, last_area, 1))

        was_occluded = self.occluded
        self._clear_occlusion_flag()
        self.prev_center = self.center
        self.center = new_center
        self.bbox = bbox
        self.area = area
        self.last_seen = now
        self.visible_duration += dt
        self.matched_count += 1
        self.missing_duration = 0.0
        self.unobserved_since_clear = 0.0
        self.max_area = max(self.max_area, area)
        self.min_area = min(self.min_area, area)

        self.center_history.append(new_center)
        self.area_history.append(area)
        self.accumulated_movement += movement
        self.movement_sum += movement
        self.movement_max = max(self.movement_max, movement)
        self.movement_count += 1
        self.last_movement = movement

        stable = (movement <= move_thresh) and (area_change <= max_size_change_ratio)
        self.stable_history.append(stable)
        if stable:
            self.stable_total += 1
        stable_ratio = sum(1 for s in self.stable_history if s) / float(len(self.stable_history))

        if resumed or was_occluded:
            self.resumed_after_occlusion_count += 1

        in_range = (min_area <= area <= max_area)
        eligible = stable and in_range and (stable_ratio >= minimum_stationary_ratio)
        if eligible:
            if self.became_stationary_seconds is None:
                self.became_stationary_seconds = now
            self.stationary_duration += dt  # PRESERVED across occlusion, resumes here
            self.state = STATE_RESUMED if (resumed or was_occluded) else STATE_STATIONARY
        else:
            self.state = STATE_RESUMED if (resumed or was_occluded) else STATE_UNSTABLE

    def maybe_promote(self, persistence_seconds, now, min_area, max_area):
        if self.persistent:
            if not self.occluded:
                self.state = STATE_PERSISTENT
            return
        if self.occluded:
            return  # never promote while occluded
        if (min_area <= self.area <= max_area and
                self.stationary_duration >= persistence_seconds):
            self.persistent = True
            self.became_persistent_seconds = now
            self.state = STATE_PERSISTENT

    def occlude(self, now, dt):
        """Motion overlaps the protected area: pause, preserve, do not delete."""
        self._enter_occlusion(now, dt)

    def go_unobserved(self, dt):
        """Not matched and not occluded. If it was occluded, this is the
        post-motion cooldown_wait window; otherwise it is plain missing."""
        if self.last_bbox_before_occlusion is not None and self.became_stationary_seconds is not None:
            self.unobserved_since_clear += dt
            self._clear_occlusion_flag()
            self.state = STATE_COOLDOWN_WAIT
        else:
            self.missing_duration += dt
            self._clear_occlusion_flag()
            if not self.persistent:
                self.state = STATE_MISSING

    @property
    def ever_occluded(self):
        return self.occlusion_count > 0

    @property
    def stable_match_ratio(self):
        return self.stable_total / float(self.matched_count) if self.matched_count else 0.0

    @property
    def average_movement(self):
        return self.movement_sum / self.movement_count if self.movement_count else 0.0


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------
class RegionTracker:
    def __init__(self, args, move_thresh):
        self.iou_threshold = args.iou_threshold
        self.matching_center_distance = args.matching_center_distance
        self.persistence_seconds = args.persistence_seconds
        self.missing_grace_seconds = args.missing_grace_seconds
        self.max_size_change_ratio = args.max_size_change_ratio
        self.minimum_stationary_ratio = args.minimum_stationary_ratio
        self.stability_window = args.stability_window
        self.min_area = args.min_area
        self.max_area = args.max_area
        self.move_thresh = move_thresh
        # Occlusion-related thresholds.
        self.occlusion_overlap_ratio = args.motion_occlusion_overlap_ratio
        self.occlusion_grace = args.motion_occlusion_grace_seconds
        self.persistent_occlusion_grace = args.persistent_occlusion_grace_seconds
        self.recovery_distance = args.occlusion_recovery_distance
        self.protection_padding = args.track_protection_padding

        self.regions = []
        self.removed = []
        self._next_id = 1
        self.total_tracks_created = 0
        self._stationary_ids = set()
        self._persistent_ids = set()
        self._occluded_ids = set()
        self._persistent_occluded_ids = set()
        self._resumed_ids = set()
        self.tracks_expired_after_occlusion = 0

    def _match_score(self, region, cand):
        dist = center_distance(region.center, bbox_center(cand["bbox"]))
        if dist > self.matching_center_distance:
            return None
        a_area, b_area = region.area, cand["area"]
        area_change = abs(a_area - b_area) / float(max(a_area, b_area, 1))
        if area_change > MATCH_AREA_REJECT_RATIO:
            return None
        overlap = iou(region.bbox, cand["bbox"])
        norm_dist = dist / self.matching_center_distance
        return overlap * 1.0 + (1.0 - norm_dist) * 0.5 + (1.0 - area_change) * 0.5

    def _recovery_score(self, region, cand):
        """Re-acquire an occluded track from a reappearing region near its
        pre-occlusion location. Uses center distance + size similarity + overlap
        against the LAST bbox before occlusion (not the stale current bbox)."""
        ref_bbox = region.last_bbox_before_occlusion or region.bbox
        ref_center = bbox_center(ref_bbox)
        dist = center_distance(ref_center, bbox_center(cand["bbox"]))
        if dist > self.recovery_distance:
            return None
        ref_area = ref_bbox[2] * ref_bbox[3]
        area_change = abs(ref_area - cand["area"]) / float(max(ref_area, cand["area"], 1))
        if area_change > MATCH_AREA_REJECT_RATIO:
            return None
        overlap = iou(ref_bbox, cand["bbox"])
        return overlap * 1.0 + (1.0 - dist / self.recovery_distance) * 0.5 + (1.0 - area_change) * 0.5

    def _is_occluded(self, region, exclusion_mask):
        """Motion/cooldown overlaps the track's protected area (last bbox grown
        by the protection padding)."""
        if exclusion_mask is None:
            return False
        h, w = exclusion_mask.shape[:2]
        protected = pad_clip(region.bbox, self.protection_padding, w, h)
        return bbox_covered(exclusion_mask, protected, frac=self.occlusion_overlap_ratio)

    def update(self, candidates, now, dt, exclusion_mask):
        unmatched = set(range(len(self.regions)))
        used = set()

        # (1) Recovery matching FIRST: occluded / cooldown-waiting tracks get
        #     priority to re-acquire a reappearing region and keep their ID.
        recovery_pairs = []
        for ri, region in enumerate(self.regions):
            if not (region.occluded or region.state == STATE_COOLDOWN_WAIT or
                    region.last_bbox_before_occlusion is not None):
                continue
            for ci, cand in enumerate(candidates):
                score = self._recovery_score(region, cand)
                if score is not None:
                    recovery_pairs.append((score, ri, ci))
        recovery_pairs.sort(reverse=True)
        for score, ri, ci in recovery_pairs:
            if ri not in unmatched or ci in used:
                continue
            self.regions[ri].observe(
                candidates[ci]["bbox"], candidates[ci]["area"], now, dt,
                self.move_thresh, self.max_size_change_ratio,
                self.minimum_stationary_ratio, self.min_area, self.max_area,
                resumed=True)
            self.regions[ri].maybe_promote(self.persistence_seconds, now,
                                           self.min_area, self.max_area)
            unmatched.discard(ri)
            used.add(ci)

        # (2) Normal matching for the remaining tracks/candidates.
        pairs = []
        for ri, region in enumerate(self.regions):
            if ri not in unmatched:
                continue
            for ci, cand in enumerate(candidates):
                if ci in used:
                    continue
                score = self._match_score(region, cand)
                if score is not None:
                    pairs.append((score, ri, ci))
        pairs.sort(reverse=True)
        for score, ri, ci in pairs:
            if ri not in unmatched or ci in used:
                continue
            self.regions[ri].observe(
                candidates[ci]["bbox"], candidates[ci]["area"], now, dt,
                self.move_thresh, self.max_size_change_ratio,
                self.minimum_stationary_ratio, self.min_area, self.max_area)
            self.regions[ri].maybe_promote(self.persistence_seconds, now,
                                           self.min_area, self.max_area)
            unmatched.discard(ri)
            used.add(ci)

        # (3) New tracks for leftover candidates. Candidates come from the
        #     stationary mask, so they are already outside the exclusion mask.
        for ci, cand in enumerate(candidates):
            if ci in used:
                continue
            region = TrackedRegion(self._next_id, cand["bbox"], cand["area"],
                                   now, self.stability_window)
            self._next_id += 1
            self.total_tracks_created += 1
            self.regions.append(region)

        # (4) Unmatched existing tracks: occluded (motion over protected area) ->
        #     pause+preserve; otherwise unobserved (cooldown_wait or missing).
        for ri in unmatched:
            region = self.regions[ri]
            if self._is_occluded(region, exclusion_mask):
                region.occlude(now, dt)
            else:
                region.go_unobserved(dt)

        # Bookkeeping.
        for region in self.regions:
            if region.became_stationary_seconds is not None:
                self._stationary_ids.add(region.region_id)
            if region.persistent:
                self._persistent_ids.add(region.region_id)
            if region.ever_occluded:
                self._occluded_ids.add(region.region_id)
                if region.persistent:
                    self._persistent_occluded_ids.add(region.region_id)
            if region.resumed_after_occlusion_count > 0:
                self._resumed_ids.add(region.region_id)

        # (5) Expiry with occlusion-aware grace periods. A track is NEVER expired
        #     merely because motion overlaps it; only when it stays absent AFTER
        #     motion/cooldown clears, beyond the applicable grace.
        survivors = []
        for region in self.regions:
            expired = False
            if region.persistent:
                if region.unobserved_since_clear > self.persistent_occlusion_grace:
                    expired, reason = True, "persistent_occlusion_grace_exceeded"
            elif region.ever_occluded:
                if region.unobserved_since_clear > self.occlusion_grace:
                    expired, reason = True, "occlusion_grace_exceeded"
            else:
                if region.missing_duration > self.missing_grace_seconds:
                    expired, reason = True, "missing_grace_exceeded"
            if expired:
                region.state = STATE_EXPIRED
                region.expired_reason = reason
                if region.ever_occluded:
                    self.tracks_expired_after_occlusion += 1
                self.removed.append(region)
            else:
                survivors.append(region)
        self.regions = survivors

    @property
    def active_persistent_count(self):
        return sum(1 for r in self.regions if r.persistent)

    @property
    def total_persistent_count(self):
        return len(self._persistent_ids)

    @property
    def total_stationary_tracks(self):
        return len(self._stationary_ids)

    def all_tracks(self):
        return self.removed + self.regions

    def total_unstable_tracks(self):
        return sum(1 for r in self.all_tracks() if r.became_stationary_seconds is None)

    @property
    def total_paused_tracks(self):
        return len(self._occluded_ids)

    @property
    def total_resumed_tracks(self):
        return len(self._resumed_ids)

    @property
    def total_persistent_occluded(self):
        return len(self._persistent_occluded_ids)

    def persistent_regions(self):
        seen = {}
        for region in self.all_tracks():
            if region.persistent:
                seen[region.region_id] = region
        return [seen[k] for k in sorted(seen)]


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------
def annotate(frame_bgr, tracker, large_boxes, motion_boxes, cooldown_mask,
             now, global_change, broad_motion, total_pixels,
             show_large, show_motion):
    out = frame_bgr.copy()

    if show_motion and cooldown_mask is not None:
        # Tint cooldown areas cyan (areas still excluded after motion left).
        overlay = out.copy()
        overlay[cooldown_mask > 0] = COLOR_COOLDOWN
        cv2.addWeighted(overlay, 0.25, out, 0.75, 0, out)

    if show_large:
        for (x, y, w, h) in large_boxes:
            cv2.rectangle(out, (x, y), (x + w, y + h), COLOR_LARGE, 2)
            cv2.putText(out, "Large change ignored", (x, max(12, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_LARGE, 1, cv2.LINE_AA)

    if show_motion:
        for (x, y, w, h) in motion_boxes:
            cv2.rectangle(out, (x, y), (x + w, y + h), COLOR_MOTION, 2)
            cv2.putText(out, "Motion excluded", (x, max(12, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_MOTION, 1, cv2.LINE_AA)

    for r in tracker.regions:
        # Draw occluded tracks (purple/magenta) so ID continuity is visible;
        # skip only plain missing tracks awaiting reappearance with no history.
        if r.state == STATE_MISSING:
            continue
        if r.state == STATE_PERSISTENT_OCCLUDED:
            color = COLOR_PERSISTENT_OCCLUDED
        elif r.state in (STATE_OCCLUDED, STATE_COOLDOWN_WAIT):
            color = COLOR_PERSISTENT_OCCLUDED if r.persistent else COLOR_OCCLUDED
        elif r.state == STATE_RESUMED:
            color = COLOR_RESUMED
        elif r.persistent:
            color = COLOR_PERSISTENT
        elif r.state == STATE_STATIONARY:
            color = COLOR_STATIONARY
        else:
            color = COLOR_UNSTABLE
        # While occluded the live bbox is stale; show the pre-occlusion bbox.
        box = r.bbox
        if r.state in (STATE_OCCLUDED, STATE_PERSISTENT_OCCLUDED, STATE_COOLDOWN_WAIT) \
                and r.last_bbox_before_occlusion is not None:
            box = r.last_bbox_before_occlusion
        x, y, w, h = box
        ratio = r.area / float(total_pixels)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
        cv2.putText(out, "ID{} {}".format(r.region_id, r.state),
                    (x, max(12, y - 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
        cv2.putText(out, "s{:.1f}s occ{:.1f}s x{}".format(
            r.stationary_duration, r.total_occluded_duration, r.occlusion_count),
            (x, max(24, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, color, 1, cv2.LINE_AA)

    header = "t={:.2f}s  persistent={}  active={}".format(
        now, tracker.active_persistent_count, len(tracker.regions))
    cv2.putText(out, header, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1, cv2.LINE_AA)
    if global_change:
        cv2.putText(out, "GLOBAL SCENE CHANGE - detection suppressed", (8, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_WARNING, 2, cv2.LINE_AA)
    elif broad_motion:
        cv2.putText(out, "BROAD MOTION - detection suppressed", (8, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_MOTION, 2, cv2.LINE_AA)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)
    open_k, close_k = resolve_kernels(args)
    validate_args(args, open_k, close_k)

    try:
        os.makedirs(args.output, exist_ok=True)
    except OSError as exc:
        fail("output directory cannot be created: {}".format(exc))

    reference_bgr = cv2.imread(args.reference, cv2.IMREAD_COLOR)
    if reference_bgr is None:
        fail("reference image cannot be opened: {}".format(args.reference))
    log("Reference image loaded: {}".format(args.reference))

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        fail("test video cannot be opened: {}".format(args.input))
    log("Test video opened: {}".format(args.input))

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    src_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if src_fps is None or src_fps != src_fps or src_fps <= 0:
        log("WARNING: source FPS unavailable; assuming 30.0 for sampling.")
        src_fps = 30.0
    src_count = int(src_count) if (src_count and src_count == src_count and src_count > 0) else None
    src_duration = (src_count / src_fps) if src_count else None

    if src_w <= 0 or src_h <= 0:
        ok, probe = cap.read()
        if not ok or probe is None:
            cap.release()
            fail("no frames can be processed from the input video.")
        src_h, src_w = probe.shape[:2]
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    proc_w, proc_h, resize_note = resolve_processing_size(args, src_w, src_h)
    size = (proc_w, proc_h)
    total_pixels = proc_w * proc_h
    diagonal = math.hypot(proc_w, proc_h)
    move_thresh = max(args.max_center_movement, args.max_center_movement_ratio * diagonal)
    ratio_enabled = not args.disable_area_ratio_filter

    log("Video metadata: {}x{}, src_fps={:.2f}, frames={}, duration={}".format(
        src_w, src_h, src_fps, src_count if src_count is not None else "unknown",
        "{:.1f}s".format(src_duration) if src_duration else "unknown"))
    log("Processing resolution: {}x{} ({})".format(proc_w, proc_h, resize_note))
    log("Processing FPS: {}".format(args.processing_fps))
    log("Reference-diff: threshold={} area {}..{}px ratio {}: {}..{} open={} close={}".format(
        args.threshold, args.min_area, args.max_area, "ON" if ratio_enabled else "OFF",
        args.min_area_ratio, args.max_area_ratio, open_k, close_k))
    log("Motion: threshold={} open={} close={} dilate={}x{} min-area={} merge={} pad={} cooldown={}s".format(
        args.motion_threshold, args.motion_open_kernel, args.motion_close_kernel,
        args.motion_dilate_kernel, args.motion_dilate_iterations, args.motion_min_area,
        args.motion_merge_distance, args.motion_box_padding, args.motion_cooldown_seconds))
    log("Stability: move<= {:.1f}px size-change<= {} window={} min-stationary-ratio={}".format(
        move_thresh, args.max_size_change_ratio, args.stability_window, args.minimum_stationary_ratio))

    frame_step = max(1, int(round(src_fps / args.processing_fps)))
    dt = frame_step / src_fps
    log("Frame sampling interval: every {} source frame(s) (~{:.3f}s)".format(frame_step, dt))
    if dt > 1.0:
        log("NOTE: large gap between processed frames ({:.2f}s); frame-difference "
            "motion detection becomes less precise.".format(dt))

    ref_gray = preprocess(reference_bgr, size)

    # Morphology structuring elements.
    open_se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    close_se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    m_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.motion_open_kernel, args.motion_open_kernel))
    m_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.motion_close_kernel, args.motion_close_kernel))
    m_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.motion_dilate_kernel, args.motion_dilate_kernel))

    # Output writers.
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_path = os.path.join(args.output, "persistent_change_result.mp4")
    writer = cv2.VideoWriter(out_path, fourcc, args.processing_fps, size)
    if not writer.isOpened():
        cap.release()
        fail("output video writer cannot be initialized: {}".format(out_path))

    def open_mask_writer(name):
        path = os.path.join(args.output, name)
        w = cv2.VideoWriter(path, fourcc, args.processing_fps, size, isColor=False)
        if not w.isOpened():
            cap.release()
            writer.release()
            fail("mask video writer cannot be initialized: {}".format(path))
        return w, path

    mask_writer = mask_path = None
    motion_writer = motion_path = None
    stat_writer = stat_path = None
    temporal_writer = temporal_path = None
    if args.save_mask_video:
        mask_writer, mask_path = open_mask_writer("change_mask.mp4")
    if args.save_motion_mask_video:
        motion_writer, motion_path = open_mask_writer("motion_mask.mp4")
    if args.save_stationary_mask_video:
        stat_writer, stat_path = open_mask_writer("stationary_candidate_mask.mp4")
    if args.save_temporal_mask_video:
        temporal_writer, temporal_path = open_mask_writer("temporal_filtered_mask.mp4")

    tracker = RegionTracker(args, move_thresh)
    cooldown_map = np.zeros((proc_h, proc_w), dtype=np.float32)  # seconds remaining
    prev_gray = None

    # Temporal consistency filter state. History holds recent binary stationary
    # masks ({0,1} uint8, optionally tolerance-dilated for voting only).
    temporal_history = deque(maxlen=args.temporal_window_frames)
    temporal_se = (cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (args.temporal_tolerance_kernel, args.temporal_tolerance_kernel))
        if args.temporal_tolerance_kernel > 1 else None)

    processed = 0
    global_change_frames = 0
    broad_motion_frames = 0
    frames_suppressed_by_motion = 0
    noise_rejected_total = 0
    valid_candidate_detections = 0
    large_ignored_total = 0
    total_motion_regions = 0
    total_merged_motion_regions = 0
    total_excluded_pixels = 0
    stationary_pixels_before_temporal = 0
    stationary_pixels_after_temporal = 0
    temporal_history_skipped_frames = 0
    temporal_candidates_created = 0
    src_index = 0

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if src_index % frame_step != 0:
            src_index += 1
            continue
        src_index += 1

        now = processed * dt
        cur_gray = preprocess(frame, size)

        # (B) Reference-difference mask.
        ref_diff = cv2.absdiff(ref_gray, cur_gray)
        _, ref_mask = cv2.threshold(ref_diff, args.threshold, 255, cv2.THRESH_BINARY)
        ref_mask = cv2.morphologyEx(ref_mask, cv2.MORPH_OPEN, open_se)
        ref_mask = cv2.morphologyEx(ref_mask, cv2.MORPH_CLOSE, close_se)
        global_change = (float(np.count_nonzero(ref_mask)) / total_pixels) >= args.global_change_ratio

        # (A) Motion mask (first processed frame has no previous frame).
        if prev_gray is None:
            motion_binary = np.zeros((proc_h, proc_w), dtype=np.uint8)
            motion_boxes, n_raw, n_merged = [], 0, 0
        else:
            motion_binary, motion_boxes, n_raw, n_merged = build_motion(
                prev_gray, cur_gray, args, m_open, m_close, m_dilate, proc_w, proc_h)
        total_motion_regions += n_raw
        total_merged_motion_regions += n_merged
        motion_ratio = float(np.count_nonzero(motion_binary)) / total_pixels
        broad_motion = motion_ratio >= args.global_motion_ratio

        # Cooldown: decay, then refresh where motion is currently excluded.
        if args.motion_cooldown_seconds > 0:
            cooldown_map -= dt
            np.clip(cooldown_map, 0.0, None, out=cooldown_map)
        exclusion_now = boxes_to_mask(motion_boxes, proc_w, proc_h)
        if args.motion_cooldown_seconds > 0:
            cooldown_map[exclusion_now > 0] = args.motion_cooldown_seconds
            dynamic_exclusion = np.where(cooldown_map > 0, 255, 0).astype(np.uint8)
        else:
            dynamic_exclusion = exclusion_now
        cooldown_only = cv2.subtract(dynamic_exclusion, exclusion_now)

        # stationary_candidate_mask = ref_diff AND NOT dynamic_exclusion
        stationary_mask = cv2.bitwise_and(ref_mask, cv2.bitwise_not(dynamic_exclusion))
        total_excluded_pixels += int(np.count_nonzero(cv2.bitwise_and(ref_mask, dynamic_exclusion)))

        large_boxes = []
        suppress = global_change or broad_motion
        if global_change:
            global_change_frames += 1
        if broad_motion:
            broad_motion_frames += 1
            frames_suppressed_by_motion += 1

        # ---- Temporal consistency filter (before contour/area filtering) ----
        # Suppressed frames: skip the history update so one broad-motion / global
        # frame cannot erase prior temporal evidence. The buffer is preserved.
        temporal_filtered = np.zeros((proc_h, proc_w), dtype=np.uint8)
        if suppress:
            temporal_history_skipped_frames += 1
        else:
            # Mask used for VOTING only may be slightly dilated for 1-2px shift
            # tolerance; the original stationary_mask bounds the final region.
            vote_input = stationary_mask
            if temporal_se is not None:
                vote_input = cv2.dilate(stationary_mask, temporal_se)
            temporal_history.append((vote_input > 0).astype(np.uint8))
            counts = np.sum(temporal_history, axis=0)  # per-pixel hit count
            # Startup rule: don't require a full window before producing output.
            required_hits = max(1, min(
                args.temporal_min_hits,
                math.ceil(len(temporal_history) * args.temporal_min_hits
                          / float(args.temporal_window_frames))))
            temporal_vote = np.where(counts >= required_hits, 255, 0).astype(np.uint8)
            # Intersect with the CURRENT stationary mask: tolerance without
            # enlarging the final object beyond the currently detected region.
            temporal_filtered = cv2.bitwise_and(temporal_vote, stationary_mask)
            stationary_pixels_before_temporal += int(np.count_nonzero(stationary_mask))
            stationary_pixels_after_temporal += int(np.count_nonzero(temporal_filtered))

        if suppress:
            # Still update tracks (pause/missing) but create no new candidates.
            tracker.update([], now, dt, dynamic_exclusion)
        else:
            contours, _ = cv2.findContours(temporal_filtered, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for c in contours:
                area = cv2.contourArea(c)
                ratio = area / float(total_pixels)
                too_small = area < args.min_area or (ratio_enabled and ratio < args.min_area_ratio)
                too_large = area > args.max_area or (ratio_enabled and ratio > args.max_area_ratio)
                if too_small:
                    noise_rejected_total += 1
                    continue
                if too_large:
                    large_ignored_total += 1
                    large_boxes.append(cv2.boundingRect(c))
                    continue
                candidates.append({"bbox": cv2.boundingRect(c), "area": area})
            candidates = [{"bbox": b, "area": b[2] * b[3]} for b in
                          merge_boxes([c["bbox"] for c in candidates], args.merge_distance,
                                      args.max_area, args.max_area_ratio, total_pixels)] \
                if candidates else []
            valid_candidate_detections += len(candidates)
            temporal_candidates_created += len(candidates)
            tracker.update(candidates, now, dt, dynamic_exclusion)

        annotated = annotate(cv2.resize(frame, size, interpolation=cv2.INTER_AREA),
                             tracker, large_boxes, motion_boxes, cooldown_only, now,
                             global_change, broad_motion, total_pixels,
                             args.show_ignored_large_regions, args.show_motion_regions)
        writer.write(annotated)
        if mask_writer is not None:
            mask_writer.write(ref_mask)
        if motion_writer is not None:
            motion_writer.write(motion_binary)
        if stat_writer is not None:
            stat_writer.write(stationary_mask)
        if temporal_writer is not None:
            temporal_writer.write(temporal_filtered)

        prev_gray = cur_gray
        processed += 1
        if args.verbose:
            log("frame {} t={:.2f}s active={} persistent={} motion_boxes={} "
                "motion_ratio={:.3f} {}".format(
                    processed, now, len(tracker.regions), tracker.active_persistent_count,
                    len(motion_boxes), motion_ratio,
                    "[GLOBAL]" if global_change else ("[BROAD-MOTION]" if broad_motion else "")))

    cap.release()
    writer.release()
    for w in (mask_writer, motion_writer, stat_writer, temporal_writer):
        if w is not None:
            w.release()

    if processed == 0:
        fail("no frames can be processed from the input video.")

    total_pixels_removed_by_temporal = (
        stationary_pixels_before_temporal - stationary_pixels_after_temporal)
    temporal_pixel_removal_ratio = (
        total_pixels_removed_by_temporal / float(stationary_pixels_before_temporal)
        if stationary_pixels_before_temporal else 0.0)

    log("Processed frame count: {}".format(processed))
    log("Tiny-noise regions rejected: {}".format(noise_rejected_total))
    log("Valid small-change candidate detections: {}".format(valid_candidate_detections))
    log("Large local changes ignored: {}".format(large_ignored_total))
    log("Motion regions detected: {} (merged: {})".format(total_motion_regions, total_merged_motion_regions))
    log("Global scene-change frames: {}".format(global_change_frames))
    log("Broad-motion frames: {}".format(broad_motion_frames))
    log("Candidate pixels removed by dynamic exclusion: {}".format(total_excluded_pixels))
    _tpr = (total_pixels_removed_by_temporal / float(stationary_pixels_before_temporal)
            if stationary_pixels_before_temporal else 0.0)
    log("Temporal filter: {} -> {} stationary px (removed {}, ratio {:.3f}); "
        "history-skipped frames {}".format(
            stationary_pixels_before_temporal, stationary_pixels_after_temporal,
            total_pixels_removed_by_temporal, _tpr, temporal_history_skipped_frames))
    log("Tracks paused (occluded) by motion: {}".format(tracker.total_paused_tracks))
    log("Tracks resumed after motion: {}".format(tracker.total_resumed_tracks))
    log("Persistent tracks occluded: {}".format(tracker.total_persistent_occluded))
    log("Tracks expired after occlusion: {}".format(tracker.tracks_expired_after_occlusion))
    log("Stationary candidate tracks: {}".format(tracker.total_stationary_tracks))
    log("Unstable candidate tracks: {}".format(tracker.total_unstable_tracks()))
    log("Persistent regions detected: {}".format(tracker.total_persistent_count))
    log("Output video saved: {}".format(out_path))
    for path in (mask_path, motion_path, stat_path):
        if path:
            log("Mask video saved: {}".format(path))

    events = []
    for r in tracker.persistent_regions():
        x, y, w, h = r.bbox
        events.append({
            "region_id": r.region_id,
            "first_seen_seconds": round(r.first_seen, 2),
            "became_stationary_seconds": round(r.became_stationary_seconds, 2)
                if r.became_stationary_seconds is not None else None,
            "became_persistent_seconds": round(r.became_persistent_seconds, 2)
                if r.became_persistent_seconds is not None else None,
            "last_seen_seconds": round(r.last_seen, 2),
            "visible_duration_seconds": round(r.visible_duration, 2),
            "stationary_duration_seconds": round(r.stationary_duration, 2),
            "state": r.state,
            "occlusion_count": r.occlusion_count,
            "total_occluded_duration_seconds": round(r.total_occluded_duration, 2),
            "last_occlusion_start_seconds": round(r.last_occlusion_start_seconds, 2)
                if r.last_occlusion_start_seconds is not None else None,
            "resumed_after_occlusion_count": r.resumed_after_occlusion_count,
            "stationary_duration_before_occlusion_seconds":
                round(r.stationary_duration_before_occlusion, 2)
                if r.stationary_duration_before_occlusion is not None else None,
            "expired_reason": r.expired_reason,
            "maximum_area_pixels": int(r.max_area),
            "minimum_area_pixels": int(r.min_area),
            "maximum_area_ratio": round(r.max_area / float(total_pixels), 6),
            "average_center_movement_pixels": round(r.average_movement, 2),
            "maximum_center_movement_pixels": round(r.movement_max, 2),
            "stable_match_ratio": round(r.stable_match_ratio, 2),
            "last_bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
        })

    summary = {
        "source_video_path": args.input,
        "reference_background_path": args.reference,
        "video_metadata": {
            "source_fps": src_fps, "source_frame_count": src_count,
            "source_width": src_w, "source_height": src_h,
            "source_duration_seconds": src_duration,
        },
        "processing_fps": args.processing_fps,
        "processing_resolution": {"width": proc_w, "height": proc_h, "note": resize_note},
        "difference_threshold": args.threshold,
        "configuration": {
            "min_area": args.min_area, "max_area": args.max_area,
            "min_area_ratio": args.min_area_ratio, "max_area_ratio": args.max_area_ratio,
            "area_ratio_filter_enabled": ratio_enabled,
            "max_center_movement": args.max_center_movement,
            "max_center_movement_ratio": args.max_center_movement_ratio,
            "effective_center_movement_pixels": round(move_thresh, 2),
            "max_size_change_ratio": args.max_size_change_ratio,
            "stability_window": args.stability_window,
            "minimum_stationary_ratio": args.minimum_stationary_ratio,
            "matching_center_distance": args.matching_center_distance,
            "iou_threshold": args.iou_threshold,
            "persistence_seconds": args.persistence_seconds,
            "missing_grace_seconds": args.missing_grace_seconds,
            "open_kernel": open_k, "close_kernel": close_k,
            "merge_distance": args.merge_distance,
            "global_change_ratio": args.global_change_ratio,
            "motion_threshold": args.motion_threshold,
            "motion_open_kernel": args.motion_open_kernel,
            "motion_close_kernel": args.motion_close_kernel,
            "motion_dilate_kernel": args.motion_dilate_kernel,
            "motion_dilate_iterations": args.motion_dilate_iterations,
            "motion_min_area": args.motion_min_area,
            "motion_merge_distance": args.motion_merge_distance,
            "motion_box_padding": args.motion_box_padding,
            "motion_cooldown_seconds": args.motion_cooldown_seconds,
            "global_motion_ratio": args.global_motion_ratio,
            "motion_occlusion_overlap_ratio": args.motion_occlusion_overlap_ratio,
            "motion_occlusion_grace_seconds": args.motion_occlusion_grace_seconds,
            "persistent_occlusion_grace_seconds": args.persistent_occlusion_grace_seconds,
            "occlusion_recovery_distance": args.occlusion_recovery_distance,
            "track_protection_padding": args.track_protection_padding,
            "temporal_window_frames": args.temporal_window_frames,
            "temporal_min_hits": args.temporal_min_hits,
            "temporal_tolerance_kernel": args.temporal_tolerance_kernel,
        },
        "summary_counts": {
            "tiny_noise_regions_rejected": noise_rejected_total,
            "valid_small_change_candidate_detections": valid_candidate_detections,
            "large_local_changes_ignored": large_ignored_total,
            "total_motion_regions_detected": total_motion_regions,
            "total_merged_motion_regions": total_merged_motion_regions,
            "total_broad_motion_frames": broad_motion_frames,
            "total_frames_suppressed_by_motion": frames_suppressed_by_motion,
            "total_candidate_pixels_removed_by_exclusion": total_excluded_pixels,
            "total_stationary_pixels_before_temporal": stationary_pixels_before_temporal,
            "total_stationary_pixels_after_temporal": stationary_pixels_after_temporal,
            "total_pixels_removed_by_temporal_filter": total_pixels_removed_by_temporal,
            "temporal_pixel_removal_ratio": round(temporal_pixel_removal_ratio, 4),
            "temporal_history_skipped_frames": temporal_history_skipped_frames,
            "temporal_candidates_created": temporal_candidates_created,
            "tracks_paused_by_motion": tracker.total_paused_tracks,
            "tracks_resumed_after_motion": tracker.total_resumed_tracks,
            "persistent_tracks_occluded": tracker.total_persistent_occluded,
            "tracks_expired_after_occlusion": tracker.tracks_expired_after_occlusion,
            "global_scene_change_frames": global_change_frames,
            "unstable_candidate_tracks": tracker.total_unstable_tracks(),
            "stationary_candidate_tracks": tracker.total_stationary_tracks,
            "total_tracks_created": tracker.total_tracks_created,
            "persistent_regions": tracker.total_persistent_count,
        },
        "total_processed_frames": processed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "persistent_events": events,
    }

    events_path = os.path.join(args.output, "persistent_change_events.json")
    try:
        with open(events_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
    except OSError as exc:
        fail("JSON save failed: {}".format(exc))
    log("Event metadata saved: {}".format(events_path))
    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

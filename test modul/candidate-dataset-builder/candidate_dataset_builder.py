#!/usr/bin/env python3
"""
candidate_dataset_builder.py

Consume the output of persistent-change-prototype (persistent_change_events.json)
and package each persistent candidate into human-reviewable evidence for later
labeling and model training.

This module DOES NOT decide whether a candidate is litter. It only extracts and
organizes detector output (context frames, crops, a difference view, a comparison
panel, a short clip, metadata) plus a static local review page. No YOLO, no
inference, no classification, no server/database. It never modifies the detector
results, the original video, or the reference image.

Importable pure helpers (used by tests):
  parse_bbox, scale_bbox, bbox_area, clip_rect, build_context_rect,
  build_crop_rect, time_to_frame, normalize_event, select_candidates,
  group_duplicates, merge_review_results.
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: required third-party package missing: {}\n"
        "Install dependencies with: pip install -r requirements.txt\n".format(exc))
    sys.exit(1)


# Legacy (schema 1.x) review labels — still accepted on import and migrated.
REVIEW_LABELS = ["litter", "cigarette_butt", "other_litter", "not_litter",
                 "uncertain", "unreviewed"]

# --- Label schema 2.0 -------------------------------------------------------
LABEL_SCHEMA_VERSION = "2.0"

# Semantic label = the MEANING of the persistent change.
SEMANTIC_LABELS = ["cigarette_butt", "other_litter", "natural_object",
                   "surface_change", "lighting_or_shadow",
                   "person_or_vehicle_residue", "compression_or_noise",
                   "unknown", "unreviewed"]
# Internal/auto-generated class (not a normal human review option).
SEMANTIC_LABEL_BACKGROUND = "background_negative"
SEMANTIC_LABELS_ALL = SEMANTIC_LABELS + [SEMANTIC_LABEL_BACKGROUND]

# Sample quality = is the detector CROP good, independent of the class.
QUALITY_LABELS = ["good", "bbox_too_large", "bbox_too_small",
                  "bbox_wrong_location", "object_not_visible",
                  "heavy_occlusion", "reference_misaligned", "unusable",
                  "unreviewed"]
CONFIDENCE_LEVELS = ["high", "medium", "low", "unset"]

# Legacy -> schema 2.0 semantic mapping. `not_litter` is intentionally NOT
# auto-mapped to a positive negative class; it is preserved as a raw label and
# flagged for migration to a specific negative class.
LEGACY_SEMANTIC_MAP = {
    "litter": "other_litter",
    "cigarette_butt": "cigarette_butt",
    "other_litter": "other_litter",
    "uncertain": "unknown",
    "unreviewed": "unreviewed",
    "": "unreviewed",
}


def normalize_semantic_label(raw_label):
    """
    Map a (possibly legacy) raw review label to a schema-2.0 semantic label.
    Returns (normalized_label, migration_warning_or_None). Never discards the
    raw value silently — the caller keeps raw_review_label separately.
    """
    if raw_label is None:
        return "unreviewed", None
    if raw_label in SEMANTIC_LABELS_ALL:
        return raw_label, None
    if raw_label == "not_litter":
        return ("unknown",
                "legacy 'not_litter' preserved as raw label; please migrate to a "
                "specific negative class (lighting_or_shadow / surface_change / "
                "person_or_vehicle_residue / compression_or_noise).")
    if raw_label in LEGACY_SEMANTIC_MAP:
        mapped = LEGACY_SEMANTIC_MAP[raw_label]
        return mapped, "legacy '{}' migrated to '{}'.".format(raw_label, mapped)
    return "unknown", "unrecognized label '{}' migrated to 'unknown'.".format(raw_label)


def validate_quality(value):
    return value if value in QUALITY_LABELS else None


def validate_confidence(value):
    return value if value in CONFIDENCE_LEVELS else None


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def fail(message, code=1):
    sys.stderr.write("ERROR: {}\n".format(message))
    sys.exit(code)


class Logger:
    def __init__(self, verbose=False):
        self.verbose = verbose

    def info(self, msg):
        print(msg, flush=True)

    def debug(self, msg):
        if self.verbose:
            print("  [v] " + msg, flush=True)

    def warn(self, msg):
        print("WARNING: " + msg, flush=True)


# ---------------------------------------------------------------------------
# Bounding-box / geometry helpers (pure -> unit tested)
# ---------------------------------------------------------------------------
def parse_bbox(raw):
    """
    Normalize many bbox encodings to (x, y, w, h) ints.

    Supports:
      * dict {x, y, width, height} or {x, y, w, h}
      * dict {x1, y1, x2, y2}
      * list/tuple [x, y, width, height]
      * list/tuple [x1, y1, x2, y2]   (heuristic: treated as corners when the
        last two values are >= the first two AND look like coordinates)
    Returns (x, y, w, h) or raises ValueError.
    """
    if isinstance(raw, dict):
        keys = set(raw.keys())
        if {"x", "y", "width", "height"} <= keys:
            x, y, w, h = raw["x"], raw["y"], raw["width"], raw["height"]
        elif {"x", "y", "w", "h"} <= keys:
            x, y, w, h = raw["x"], raw["y"], raw["w"], raw["h"]
        elif {"x1", "y1", "x2", "y2"} <= keys:
            x, y = raw["x1"], raw["y1"]
            w, h = raw["x2"] - raw["x1"], raw["y2"] - raw["y1"]
        else:
            raise ValueError("unrecognized bbox dict keys: {}".format(sorted(keys)))
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        a, b, c, d = raw
        # Heuristic: if c,d look like the far corner (>= a,b) and are not tiny,
        # we still default to width/height form unless clearly corners. The
        # persistent detector emits [x,y,w,h]; corner form is rare here.
        x, y, w, h = a, b, c, d
    else:
        raise ValueError("unsupported bbox format: {!r}".format(raw))

    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    if w <= 0 or h <= 0:
        raise ValueError("non-positive bbox size: {}".format((x, y, w, h)))
    return (x, y, w, h)


def scale_bbox(bbox, scale_x, scale_y):
    x, y, w, h = bbox
    return (int(round(x * scale_x)), int(round(y * scale_y)),
            max(1, int(round(w * scale_x))), max(1, int(round(h * scale_y))))


def bbox_area(bbox):
    return int(bbox[2] * bbox[3])


def clip_rect(rect, frame_w, frame_h):
    """Clip (x, y, w, h) to the frame; returns possibly-empty (w/h may be 0)."""
    x, y, w, h = rect
    x1 = max(0, min(int(x), frame_w))
    y1 = max(0, min(int(y), frame_h))
    x2 = max(0, min(int(x + w), frame_w))
    y2 = max(0, min(int(y + h), frame_h))
    return (x1, y1, max(0, x2 - x1), max(0, y2 - y1))


def build_context_rect(bbox, padding, min_size, frame_w, frame_h):
    """
    Context rectangle centered on the candidate: expand the bbox by `padding`,
    enforce at least `min_size` per side, match the frame aspect ratio so panels
    line up, then shift/clip to stay inside the frame.
    """
    x, y, w, h = bbox
    cx, cy = x + w / 2.0, y + h / 2.0
    cw = max(min_size, w + 2 * padding)
    ch = max(min_size, h + 2 * padding)

    aspect = frame_w / float(frame_h) if frame_h else 1.0
    if ch <= 0:
        ch = 1
    if cw / float(ch) < aspect:
        cw = ch * aspect
    else:
        ch = cw / aspect

    cw = min(cw, frame_w)
    ch = min(ch, frame_h)
    x1 = cx - cw / 2.0
    y1 = cy - ch / 2.0
    # keep fully inside the frame where possible
    x1 = min(max(0.0, x1), max(0.0, frame_w - cw))
    y1 = min(max(0.0, y1), max(0.0, frame_h - ch))
    return (int(round(x1)), int(round(y1)), int(round(cw)), int(round(ch)))


def build_crop_rect(bbox, crop_padding, frame_w, frame_h):
    x, y, w, h = bbox
    rect = (x - crop_padding, y - crop_padding,
            w + 2 * crop_padding, h + 2 * crop_padding)
    return clip_rect(rect, frame_w, frame_h)


def time_to_frame(t_seconds, fps):
    if fps is None or fps <= 0:
        fps = 30.0
    return max(0, int(round(t_seconds * fps)))


# ---------------------------------------------------------------------------
# Event JSON normalization (adapter)
# ---------------------------------------------------------------------------
ID_KEYS = ["candidate_id", "region_id", "track_id", "id"]
BBOX_KEYS = ["last_bbox", "bbox", "bbox_source", "box", "rect"]
FIRST_SEEN_KEYS = ["first_seen_seconds", "start_time", "timestamp_seconds"]
PERSIST_KEYS = ["became_persistent_seconds", "persistent_time_seconds"]
LAST_SEEN_KEYS = ["last_seen_seconds", "end_time"]
STATIONARY_KEYS = ["stationary_duration_seconds", "stationary_duration"]


def _first_present(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k], k
    return None, None


def find_event_list(doc):
    """Return the list of candidate/persistent event records from the document."""
    if isinstance(doc, list):
        return doc
    for key in ("persistent_events", "events", "candidates", "candidate_events"):
        val = doc.get(key)
        if isinstance(val, list):
            return val
    raise ValueError("no event list found (looked for persistent_events / events "
                     "/ candidates)")


def normalize_event(raw, source_video, index):
    """
    Normalize one raw event to the internal representation. Missing fields get
    safe fallbacks and a warning; the raw event is always preserved. Returns a
    dict (never raises for missing scalar fields; bbox errors are recorded).
    """
    warnings = []

    cid, _ = _first_present(raw, ID_KEYS)
    if cid is None:
        cid = index + 1
        warnings.append("missing id; assigned sequential id {}".format(cid))

    first_seen, _ = _first_present(raw, FIRST_SEEN_KEYS)
    if first_seen is None:
        first_seen = 0.0
        warnings.append("missing first_seen; defaulted to 0.0")

    stationary, _ = _first_present(raw, STATIONARY_KEYS)
    if stationary is None:
        stationary = 0.0
        warnings.append("missing stationary_duration; defaulted to 0.0")

    persistent_time, pkey = _first_present(raw, PERSIST_KEYS)
    persistent_fallback = None
    if persistent_time is None:
        if stationary:
            persistent_time = float(first_seen) + float(stationary)
            persistent_fallback = "first_seen + stationary_duration"
        else:
            persistent_time = float(first_seen)
            persistent_fallback = "first_seen"
        warnings.append("missing became_persistent; using fallback ({})".format(
            persistent_fallback))

    last_seen, _ = _first_present(raw, LAST_SEEN_KEYS)
    last_seen_fallback = None
    if last_seen is None:
        last_seen = persistent_time
        last_seen_fallback = "persistent_time"
        warnings.append("missing last_seen; using fallback (persistent_time)")

    bbox_raw, _ = _first_present(raw, BBOX_KEYS)
    bbox = None
    bbox_error = None
    if bbox_raw is None:
        bbox_error = "missing bbox"
        warnings.append("missing bbox")
    else:
        try:
            bbox = parse_bbox(bbox_raw)
        except ValueError as exc:
            bbox_error = str(exc)
            warnings.append("invalid bbox: {}".format(exc))

    return {
        "candidate_id": cid,
        "source_video": source_video,
        "first_seen_seconds": float(first_seen),
        "persistent_time_seconds": float(persistent_time),
        "persistent_time_fallback": persistent_fallback,
        "last_seen_seconds": float(last_seen),
        "last_seen_fallback": last_seen_fallback,
        "bbox": bbox,
        "bbox_error": bbox_error,
        "state": raw.get("state", "persistent"),
        "stationary_duration": float(stationary),
        "occlusion_count": int(raw.get("occlusion_count", 0) or 0),
        "total_occluded_duration": float(raw.get("total_occluded_duration_seconds",
                                                  raw.get("total_occluded_duration", 0)) or 0),
        "resumed_after_occlusion_count": int(raw.get("resumed_after_occlusion_count", 0) or 0),
        "warnings": warnings,
        "raw_event": raw,
    }


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def select_candidates(events, include_non_persistent=False, state_filter=None,
                      min_stationary_seconds=0.0, candidate_ids=None,
                      max_candidates=0):
    """Filter + sort normalized events. Returns (selected, skipped) lists where
    skipped items are (event, reason)."""
    selected, skipped = [], []
    id_set = set(str(c) for c in candidate_ids) if candidate_ids else None
    state_set = set(s.strip() for s in state_filter) if state_filter else None

    for ev in events:
        if ev["bbox"] is None:
            skipped.append((ev, "invalid_or_missing_bbox"))
            continue
        if id_set is not None and str(ev["candidate_id"]) not in id_set:
            skipped.append((ev, "not_in_candidate_ids"))
            continue
        if state_set is not None:
            if ev["state"] not in state_set:
                skipped.append((ev, "state_not_in_filter"))
                continue
        elif not include_non_persistent:
            # default: only events that became persistent
            if ev["persistent_time_fallback"] == "first_seen" and \
                    ev["stationary_duration"] <= 0:
                skipped.append((ev, "not_persistent"))
                continue
        if ev["stationary_duration"] < min_stationary_seconds:
            skipped.append((ev, "below_min_stationary"))
            continue
        selected.append(ev)

    selected.sort(key=lambda e: (-e["persistent_time_seconds"],
                                 e["first_seen_seconds"], str(e["candidate_id"])))
    if max_candidates and max_candidates > 0:
        for ev in selected[max_candidates:]:
            skipped.append((ev, "over_max_candidates"))
        selected = selected[:max_candidates]
    return selected, skipped


# ---------------------------------------------------------------------------
# Duplicate grouping
# ---------------------------------------------------------------------------
def group_duplicates(events, center_distance, time_overlap_seconds):
    """
    Assign duplicate_group_id to events whose centers are near and lifetimes
    overlap. Marks the longest-stationary member as primary. Operates in event
    coordinate space. Returns the same list with fields added (non-destructive).
    """
    def center(ev):
        x, y, w, h = ev["bbox"]
        return (x + w / 2.0, y + h / 2.0)

    def lifetime(ev):
        return (ev["first_seen_seconds"], ev["last_seen_seconds"])

    n = len(events)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    for i in range(n):
        for j in range(i + 1, n):
            ci, cj = center(events[i]), center(events[j])
            if math.hypot(ci[0] - cj[0], ci[1] - cj[1]) > center_distance:
                continue
            (a0, a1), (b0, b1) = lifetime(events[i]), lifetime(events[j])
            overlap = min(a1, b1) - max(a0, b0)
            if overlap >= -time_overlap_seconds:  # overlap or near in time
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    gid = 0
    for _, idxs in sorted(groups.items()):
        gid += 1
        primary = max(idxs, key=lambda k: events[k]["stationary_duration"])
        for k in idxs:
            events[k]["duplicate_group_id"] = gid
            events[k]["duplicate_is_primary"] = (k == primary)
            events[k]["duplicate_group_size"] = len(idxs)
    return events


# ---------------------------------------------------------------------------
# Video seeking
# ---------------------------------------------------------------------------
class VideoSeeker:
    def __init__(self, path, logger, fps_override=None):
        self.path = path
        self.logger = logger
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise IOError("video cannot be opened: {}".format(path))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps_fallback = False
        if fps_override and fps_override > 0:
            fps = fps_override
        if fps is None or fps != fps or fps <= 0:
            fps = 30.0
            self.fps_fallback = True
            logger.warn("invalid FPS metadata for {}; falling back to 30.0".format(path))
        self.fps = fps
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.duration = (self.frame_count / self.fps) if self.frame_count else None

    def read_at(self, t_seconds):
        """Seek near t, read forward to the nearest available frame. Returns
        (frame, actual_index, actual_time) or (None, None, None)."""
        target = time_to_frame(t_seconds, self.fps)
        if self.frame_count:
            target = min(target, max(0, self.frame_count - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None, None, None
        idx = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if idx < 0:
            idx = target
        return frame, idx, idx / self.fps

    def iter_range(self, t_start, t_end):
        """Yield (frame, index, time) for frames in [t_start, t_end]."""
        start_idx = time_to_frame(t_start, self.fps)
        end_idx = time_to_frame(t_end, self.fps)
        if self.frame_count:
            end_idx = min(end_idx, self.frame_count - 1)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, start_idx))
        idx = max(0, start_idx)
        while idx <= end_idx:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                break
            yield frame, idx, idx / self.fps
            idx += 1

    def release(self):
        self.cap.release()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
FONT = cv2.FONT_HERSHEY_SIMPLEX
BOX_COLOR = (0, 0, 255)
LABEL_BG = (0, 0, 0)
LABEL_FG = (255, 255, 255)


def draw_bbox(img, bbox_in_img, scale_hint=1.0):
    """Thin outline so a tiny object is not hidden. 1px for small images."""
    x, y, w, h = bbox_in_img
    thick = 1 if max(img.shape[:2]) < 500 else 2
    cv2.rectangle(img, (x, y), (x + w, y + h), BOX_COLOR, thick)


def put_labels(img, lines, origin=(4, 4)):
    """Draw a small readable label box (multi-line) at top-left."""
    x, y = origin
    fs = 0.4
    pad = 3
    th = int(14)
    for i, line in enumerate(lines):
        (tw, _), _ = cv2.getTextSize(line, FONT, fs, 1)
        y0 = y + i * th
        cv2.rectangle(img, (x, y0), (x + tw + 2 * pad, y0 + th), LABEL_BG, -1)
        cv2.putText(img, line, (x + pad, y0 + th - 4), FONT, fs, LABEL_FG, 1, cv2.LINE_AA)


def crop_region(img, rect):
    x, y, w, h = rect
    return img[y:y + h, x:x + w].copy()


def bbox_relative_to_rect(bbox, rect):
    """Express a source-space bbox in coordinates relative to a context rect."""
    bx, by, bw, bh = bbox
    rx, ry, _, _ = rect
    return (bx - rx, by - ry, bw, bh)


# ---------------------------------------------------------------------------
# Review-results merge (pure -> unit tested)
# ---------------------------------------------------------------------------
def merge_review_results(review_doc, valid_ids):
    """
    Normalize a downloaded review_results.json into {id_str: {label, notes}},
    validating ids. Returns (merged, unknown_ids, duplicate_ids).
    Accepts {"results": [...]}, a bare list, or {id: {...}} mapping.
    """
    if isinstance(review_doc, dict) and "results" in review_doc:
        items = review_doc["results"]
    elif isinstance(review_doc, list):
        items = review_doc
    elif isinstance(review_doc, dict):
        items = [{"candidate_id": k, **(v if isinstance(v, dict) else {"label": v})}
                 for k, v in review_doc.items()]
    else:
        raise ValueError("unrecognized review_results structure")

    valid = set(str(v) for v in valid_ids)
    merged, unknown, duplicates = {}, [], []
    migration_warnings, invalid_enums = [], []
    for it in items:
        cid, _ = _first_present(it, ["candidate_id"] + ID_KEYS)
        if cid is None:
            continue
        cid = str(cid)
        if cid not in valid:
            unknown.append(cid)
            continue
        if cid in merged:
            duplicates.append(cid)

        notes = it.get("notes", it.get("reviewer_notes", ""))
        # Schema 2.0 entry vs. legacy entry.
        if "semantic_label" in it:
            sem = it.get("semantic_label", "unreviewed")
            raw = it.get("raw_review_label", sem)
            if sem not in SEMANTIC_LABELS_ALL:
                invalid_enums.append("id {}: semantic_label '{}'".format(cid, sem))
                normalized, w = normalize_semantic_label(sem)
                if w:
                    migration_warnings.append("id {}: {}".format(cid, w))
                sem = normalized
            quality = validate_quality(it.get("sample_quality", "unreviewed"))
            if quality is None:
                invalid_enums.append("id {}: sample_quality '{}'".format(cid, it.get("sample_quality")))
                quality = "unreviewed"
            conf = validate_confidence(it.get("confidence", it.get("reviewer_confidence", "unset")))
            if conf is None:
                invalid_enums.append("id {}: confidence '{}'".format(cid, it.get("confidence")))
                conf = "unset"
            normalized = it.get("normalized_semantic_label", sem)
        else:
            # Legacy: map the single 'label' into raw + normalized semantic.
            raw = it.get("label", "unreviewed")
            normalized, w = normalize_semantic_label(raw)
            sem = normalized
            quality = "unreviewed"
            conf = "unset"
            if w:
                migration_warnings.append("id {}: {}".format(cid, w))

        merged[cid] = {
            "semantic_label": sem,
            "raw_review_label": raw,
            "normalized_semantic_label": normalized,
            "sample_quality": quality,
            "reviewer_confidence": conf,
            "notes": notes,
            # legacy single field kept in sync for backward compatibility
            "label": raw,
        }
    return merged, unknown, duplicates, migration_warnings, invalid_enums


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Package persistent-change detector events into "
                    "human-reviewable candidate evidence (no classification).")
    p.add_argument("--video", help="Original CCTV video used by the detector.")
    p.add_argument("--events", required=True, help="persistent_change_events.json path.")
    p.add_argument("--reference", help="reference_background.jpg path.")
    p.add_argument("--output", default="output", help="Output directory. Default: output")

    # Selection.
    p.add_argument("--include-non-persistent", action="store_true",
                   help="Also include events that never became persistent.")
    p.add_argument("--state-filter", default=None,
                   help="Comma-separated states to keep (e.g. persistent,persistent_occluded).")
    p.add_argument("--min-stationary-seconds", type=float, default=0.0)
    p.add_argument("--candidate-ids", default=None, help="Comma-separated ids to keep.")
    p.add_argument("--max-candidates", type=int, default=0, help="0 = no limit.")

    # Context / crop.
    p.add_argument("--context-padding", type=int, default=80)
    p.add_argument("--context-scale", type=float, default=4.0,
                   help="Upscale factor for saved context images (viewing aid).")
    p.add_argument("--minimum-context-size", type=int, default=160)
    p.add_argument("--crop-padding", type=int, default=12)
    p.add_argument("--crop-upscale", type=int, default=12)

    # Times.
    p.add_argument("--before-seconds", type=float, default=2.0)
    p.add_argument("--clip-before-seconds", type=float, default=3.0)
    p.add_argument("--clip-after-seconds", type=float, default=5.0)
    p.add_argument("--clip-width", type=int, default=0, help="0 = keep context width.")

    # Resolution overrides.
    p.add_argument("--event-width", type=int, default=None)
    p.add_argument("--event-height", type=int, default=None)

    # Duplicates.
    p.add_argument("--group-nearby-candidates", action="store_true")
    p.add_argument("--duplicate-center-distance", type=float, default=20.0)
    p.add_argument("--duplicate-time-overlap-seconds", type=float, default=5.0)

    # Review import.
    p.add_argument("--review-results", default=None,
                   help="review_results.json to merge labels/notes from.")
    p.add_argument("--update-labels-only", action="store_true",
                   help="With --review-results: only update metadata/manifests/sample.json.")

    # --- Model-input export (schema 2.0 additions) ----
    p.add_argument("--temporal-mask-video", default=None,
                   help="Optional persistent-change temporal_filtered_mask.mp4 to "
                        "derive a real anomaly mask (else bbox fallback).")
    p.add_argument("--model-input-size", type=int, default=128,
                   help="Square model-input size (px). Default: 128")
    p.add_argument("--model-context-padding", type=int, default=24,
                   help="Source-pixel padding around the candidate bbox before "
                        "squaring (local crop). Default: 24")
    p.add_argument("--model-minimum-region-size", type=int, default=48,
                   help="Minimum source-pixel side of the local square. Default: 48")
    p.add_argument("--context-model-input-size", type=int, default=256,
                   help="Square wider-context model-input size (px). Default: 256")
    p.add_argument("--difference-mode", default="abs_rgb",
                   choices=["abs_rgb", "abs_gray", "signed_centered"],
                   help="Difference image mode. Default: abs_rgb")
    p.add_argument("--normalize-difference", action="store_true",
                   help="Per-sample min/max normalize the difference (off by default).")
    p.add_argument("--save-model-array", action="store_true",
                   help="Also write model_input/sample.npz (NumPy, uint8).")
    p.add_argument("--exclude-poor-quality-from-training", action="store_true",
                   help="Mark poor sample_quality as unusable in training manifests only.")

    # Scene / camera grouping.
    p.add_argument("--camera-id", default=None, help="Explicit camera id (e.g. E05).")
    p.add_argument("--scene-id", default=None, help="Explicit scene id.")
    p.add_argument("--capture-condition", default=None,
                   help="Free-text capture condition (e.g. cloudy_day).")

    # Background negatives.
    p.add_argument("--background-negative-count", type=int, default=0,
                   help="Number of background-only negative samples to generate. Default: 0")
    p.add_argument("--random-seed", type=int, default=42,
                   help="Random seed for background-negative selection. Default: 42")

    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Resolution resolution
# ---------------------------------------------------------------------------
def resolve_event_resolution(doc, args, src_w, src_h, logger):
    """Figure out the resolution the event coordinates are expressed in."""
    if args.event_width and args.event_height:
        logger.debug("event resolution from CLI override: {}x{}".format(
            args.event_width, args.event_height))
        return args.event_width, args.event_height, "cli_override"
    pr = doc.get("processing_resolution") if isinstance(doc, dict) else None
    if isinstance(pr, dict) and pr.get("width") and pr.get("height"):
        return int(pr["width"]), int(pr["height"]), "processing_resolution"
    cfg = doc.get("configuration", {}) if isinstance(doc, dict) else {}
    for wk, hk in (("output_width", "output_height"),
                   ("resized_width", "resized_height"),
                   ("processing_width", "processing_height")):
        if cfg.get(wk) and cfg.get(hk):
            return int(cfg[wk]), int(cfg[hk]), wk
    logger.warn("event coordinate resolution not found; assuming it equals the "
                "source resolution {}x{}".format(src_w, src_h))
    return src_w, src_h, "assumed_source"


# ---------------------------------------------------------------------------
# Per-candidate extraction
# ---------------------------------------------------------------------------
def tile_with_label(img, label, tile_w):
    """Resize keeping aspect to width tile_w and add a label bar on top."""
    if img is None or img.size == 0:
        img = np.zeros((10, 10, 3), np.uint8)
    h, w = img.shape[:2]
    scale = tile_w / float(w)
    resized = cv2.resize(img, (tile_w, max(1, int(round(h * scale)))),
                         interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST)
    bar = np.zeros((18, tile_w, 3), np.uint8)
    cv2.putText(bar, label, (4, 13), FONT, 0.42, LABEL_FG, 1, cv2.LINE_AA)
    return np.vstack([bar, resized])


def make_comparison_panel(tiles, tile_w):
    """tiles: list of (label, image) in row-major 3x2 order."""
    built = [tile_with_label(im, lab, tile_w) for lab, im in tiles]
    maxh = max(t.shape[0] for t in built)
    padded = []
    for t in built:
        if t.shape[0] < maxh:
            pad = np.zeros((maxh - t.shape[0], tile_w, 3), np.uint8)
            t = np.vstack([t, pad])
        padded.append(t)
    row1 = np.hstack(padded[0:3])
    row2 = np.hstack(padded[3:6])
    return np.vstack([row1, row2])


# ---------------------------------------------------------------------------
# Model-input (clean ML) helpers — NO text/boxes/labels drawn on these images.
# ---------------------------------------------------------------------------
INTERP_POLICY = ("reference/current/context: INTER_AREA when shrinking, "
                 "INTER_CUBIC when enlarging; difference: built from the aligned "
                 "reference/current; mask: INTER_NEAREST only")


def infer_camera_id(filename):
    """Cautious camera id from filename: leading letters+digits token
    (e.g. 'E05_024.mp4' -> 'E05'). Returns (camera_id, source) where source is
    'inferred' or 'none'."""
    if not filename:
        return "unknown", "none"
    base = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r"^([A-Za-z]+\d+)", base)
    if m:
        return m.group(1), "inferred"
    return "unknown", "none"


def build_model_square(bbox_src, padding, min_region, frame_w, frame_h):
    """
    Square source-space crop centered on the candidate bbox: expand by padding,
    enforce min_region, square to the larger side, clip to frame and record the
    outside padding so paired images stay geometrically aligned.
    """
    x, y, w, h = bbox_src
    cx, cy = x + w / 2.0, y + h / 2.0
    side = int(max(w + 2 * padding, h + 2 * padding, min_region, 1))
    fx1 = int(round(cx - side / 2.0))
    fy1 = int(round(cy - side / 2.0))
    fx2, fy2 = fx1 + side, fy1 + side
    cx1, cy1 = max(0, fx1), max(0, fy1)
    cx2, cy2 = min(frame_w, fx2), min(frame_h, fy2)
    return {"full_square": (fx1, fy1, side, side),
            "clip": (cx1, cy1, max(0, cx2 - cx1), max(0, cy2 - cy1)),
            "pads": (cx1 - fx1, cy1 - fy1, fx2 - cx2, fy2 - cy2)}


def scale_square(sq, factor, frame_w, frame_h):
    """Concentric larger/smaller square (for the wider context crop)."""
    fx1, fy1, side, _ = sq["full_square"]
    cx, cy = fx1 + side / 2.0, fy1 + side / 2.0
    nside = max(1, int(round(side * factor)))
    nfx1 = int(round(cx - nside / 2.0))
    nfy1 = int(round(cy - nside / 2.0))
    cx1, cy1 = max(0, nfx1), max(0, nfy1)
    cx2, cy2 = min(frame_w, nfx1 + nside), min(frame_h, nfy1 + nside)
    return {"full_square": (nfx1, nfy1, nside, nside),
            "clip": (cx1, cy1, max(0, cx2 - cx1), max(0, cy2 - cy1)),
            "pads": (cx1 - nfx1, cy1 - nfy1, nfx1 + nside - cx2, nfy1 + nside - cy2)}


def extract_square_image(frame, sq, size, interp, channels=3):
    """Extract the square (padding outside-image areas) and resize to size×size."""
    fx1, fy1, side, _ = sq["full_square"]
    pl, pt, pr, pb = sq["pads"]
    cx, cy, cw, ch = sq["clip"]
    canvas = np.zeros((side, side) if channels == 1 else (side, side, 3), np.uint8)
    if frame is not None and cw > 0 and ch > 0:
        sub = frame[cy:cy + ch, cx:cx + cw]
        if channels == 1 and sub.ndim == 3:
            sub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
        canvas[pt:pt + ch, pl:pl + cw] = sub
    if side != size:
        canvas = cv2.resize(canvas, (size, size), interpolation=interp)
    return canvas


def interp_for(side, target):
    return cv2.INTER_AREA if side > target else cv2.INTER_CUBIC


def make_difference(ref_img, cur_img, mode="abs_rgb", normalize=False):
    """
    Difference image from ALREADY-ALIGNED reference/current crops.
      abs_rgb        : per-channel |current - reference|, 3 channels.
      abs_gray       : grayscale absolute difference replicated to 3 channels.
      signed_centered: (current - reference) + 128, clamped [0,255], 3 channels
                       (retains whether pixels got brighter/darker).
    Per-sample min/max normalization is OFF by default (it would destroy
    cross-sample intensity comparability); enabled via normalize=True.
    """
    info = {"difference_mode": mode, "normalized": False}
    if mode == "abs_gray":
        a = cv2.cvtColor(cur_img, cv2.COLOR_BGR2GRAY)
        b = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
        d = cv2.absdiff(a, b)
        out = cv2.merge([d, d, d])
    elif mode == "signed_centered":
        d = cur_img.astype(np.int16) - ref_img.astype(np.int16)
        out = np.clip(d + 128, 0, 255).astype(np.uint8)
    else:  # abs_rgb
        out = cv2.absdiff(cur_img, ref_img)
    if normalize:
        out = cv2.normalize(out, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        info["normalized"] = True
    return out, info


def bbox_in_square_coords(bbox_src, sq, size):
    """Express a source bbox in model-crop pixel coordinates (after resize)."""
    fx1, fy1, side, _ = sq["full_square"]
    x, y, w, h = bbox_src
    s = size / float(side)
    return (int(round((x - fx1) * s)), int(round((y - fy1) * s)),
            max(1, int(round(w * s))), max(1, int(round(h * s))))


def _filled_bbox_mask(bbox_src, sq, size):
    m = np.zeros((size, size), np.uint8)
    bx, by, bw, bh = bbox_in_square_coords(bbox_src, sq, size)
    cv2.rectangle(m, (bx, by), (bx + bw, by + bh), 255, -1)
    return m


def candidate_mask_square(mask_src_full, bbox_src, sq, size, isolate=True):
    """
    Build a binary (0/255) anomaly mask aligned to the model crop.
    Priority: detector mask (temporal video, already upsized to source) ->
    filled bbox fallback. Returns (mask, mask_source, warnings).
    """
    warns = []
    if mask_src_full is not None:
        m = extract_square_image(mask_src_full, sq, size, cv2.INTER_NEAREST, channels=1)
        _, m = cv2.threshold(m, 127, 255, cv2.THRESH_BINARY)
        if isolate and np.count_nonzero(m) > 0:
            bx, by, bw, bh = bbox_in_square_coords(bbox_src, sq, size)
            num, lbl = cv2.connectedComponents(m)
            sub = lbl[max(0, by):by + bh, max(0, bx):bx + bw]
            keep = set(int(v) for v in np.unique(sub) if v != 0)
            if keep:
                m = np.where(np.isin(lbl, list(keep)), 255, 0).astype(np.uint8)
            else:
                warns.append("temporal mask present but no component overlaps the "
                             "bbox; kept full cropped mask")
        if np.count_nonzero(m) == 0:
            warns.append("temporal mask empty at candidate; using filled-bbox fallback")
            return _filled_bbox_mask(bbox_src, sq, size), "bbox_fallback", warns
        return m, "detector_mask_crop", warns
    warns.append("no temporal mask provided; using filled bbox as mask (bbox_fallback)")
    return _filled_bbox_mask(bbox_src, sq, size), "bbox_fallback", warns


def validate_alignment(ref_img, cur_img, diff_img, mask_img, bbox_model, size):
    """Per-sample alignment/sanity checks. Returns (ok, warnings)."""
    warns = []
    ok = True
    shapes = set()
    for name, im in (("reference", ref_img), ("current", cur_img), ("difference", diff_img)):
        if im is None or im.size == 0:
            ok = False; warns.append("{} missing/empty".format(name)); continue
        shapes.add((im.shape[0], im.shape[1]))
        if im.shape[0] != size or im.shape[1] != size:
            ok = False; warns.append("{} not {}x{}".format(name, size, size))
    if len(shapes) > 1:
        ok = False; warns.append("reference/current/difference sizes differ")
    if mask_img is None or mask_img.size == 0:
        ok = False; warns.append("mask missing/empty")
    else:
        if mask_img.shape[0] != size or mask_img.shape[1] != size:
            ok = False; warns.append("mask not {}x{}".format(size, size))
        if not set(np.unique(mask_img).tolist()) <= {0, 255}:
            ok = False; warns.append("mask not binary")
    bx, by, bw, bh = bbox_model
    ccx, ccy = bx + bw / 2.0, by + bh / 2.0
    if not (0 <= ccx <= size and 0 <= ccy <= size):
        ok = False; warns.append("bbox center outside model crop")
    if mask_img is not None and np.count_nonzero(mask_img) > 0:
        roi = mask_img[max(0, by):by + bh, max(0, bx):bx + bw]
        if roi.size == 0 or np.count_nonzero(roi) == 0:
            warns.append("candidate mask does not overlap bbox region")
    return ok, warns


def build_model_input(folder, ev, current_frame, reference_src, mask_src_full,
                      bbox_src, args, source_res, scene_meta, label_fields,
                      mask_times):
    """
    Write the clean model_input/ images + sample.json. NO overlays/labels/boxes.
    Returns the sample dict (also used for the training manifest).
    """
    src_w, src_h = source_res
    mi = os.path.join(folder, "model_input")
    os.makedirs(mi, exist_ok=True)
    size = args.model_input_size
    csize = args.context_model_input_size

    sq = build_model_square(bbox_src, args.model_context_padding,
                            args.model_minimum_region_size, src_w, src_h)
    side = sq["full_square"][2]
    ref_img = extract_square_image(reference_src, sq, size, interp_for(side, size))
    cur_img = extract_square_image(current_frame, sq, size, interp_for(side, size)) \
        if current_frame is not None else np.zeros((size, size, 3), np.uint8)
    diff_img, diff_info = make_difference(ref_img, cur_img, args.difference_mode,
                                          args.normalize_difference)
    if scene_meta.get("generated_negative"):
        # Background-only negative: there is no anomaly, so the mask is empty.
        mask_img, mask_source, mwarn = np.zeros((size, size), np.uint8), "background_empty", []
    else:
        mask_img, mask_source, mwarn = candidate_mask_square(mask_src_full, bbox_src, sq, size)

    # Wider context square (clean, aligned).
    csq = scale_square(sq, 2.0, src_w, src_h)
    cside = csq["full_square"][2]
    ref_ctx = extract_square_image(reference_src, csq, csize, interp_for(cside, csize))
    cur_ctx = extract_square_image(current_frame, csq, csize, interp_for(cside, csize)) \
        if current_frame is not None else np.zeros((csize, csize, 3), np.uint8)
    diff_ctx, _ = make_difference(ref_ctx, cur_ctx, args.difference_mode,
                                  args.normalize_difference)

    mask3 = cv2.merge([mask_img, mask_img, mask_img])
    paired_h = np.hstack([ref_img, cur_img, diff_img])
    paired_grid = np.vstack([np.hstack([ref_img, cur_img]),
                             np.hstack([diff_img, mask3])])

    def w(name, img):
        cv2.imwrite(os.path.join(mi, name), img)
        return name

    files = {
        "reference": w("reference.png", ref_img),
        "current": w("current.png", cur_img),
        "difference": w("difference.png", diff_img),
        "mask": w("mask.png", mask_img),
        "context": w("context.png", cur_ctx),
        "reference_context": w("reference_context.png", ref_ctx),
        "current_context": w("current_context.png", cur_ctx),
        "difference_context": w("difference_context.png", diff_ctx),
        "paired_horizontal": w("paired_horizontal.png", paired_h),
        "paired_grid": w("paired_grid.png", paired_grid),
    }

    bbox_model = bbox_in_square_coords(bbox_src, sq, size)
    align_ok, awarn = validate_alignment(ref_img, cur_img, diff_img, mask_img, bbox_model, size)

    npz_path = None
    if args.save_model_array:
        npz_path = "sample.npz"
        np.savez_compressed(os.path.join(mi, npz_path), reference=ref_img,
                            current=cur_img, difference=diff_img, mask=mask_img,
                            context=cur_ctx)

    sample = {
        "candidate_id": ev["candidate_id"],
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "model_input_size": size,
        "context_model_input_size": csize,
        "difference_mode": diff_info["difference_mode"],
        "normalize_difference": diff_info["normalized"],
        "interpolation_policy": INTERP_POLICY,
        "model_source_crop": list(sq["full_square"]),
        "model_clip": list(sq["clip"]),
        "model_pads": list(sq["pads"]),
        "context_source_crop": list(csq["full_square"]),
        "bbox_source_coordinates": list(bbox_src),
        "bbox_model_coordinates": list(bbox_model),
        "mask_source": mask_source,
        "mask_warnings": mwarn,
        "requested_mask_time_seconds": mask_times.get("requested"),
        "actual_mask_time_seconds": mask_times.get("actual"),
        "alignment_valid": align_ok,
        "alignment_warnings": awarn,
        "generated_negative": scene_meta.get("generated_negative", False),
        "camera_id": scene_meta.get("camera_id"),
        "camera_id_source": scene_meta.get("camera_id_source"),
        "scene_id": scene_meta.get("scene_id"),
        "capture_condition": scene_meta.get("capture_condition"),
        "source_video_id": scene_meta.get("source_video_id"),
        "candidate_time_group": scene_meta.get("candidate_time_group"),
        "duplicate_group_id": ev.get("duplicate_group_id"),
        "group_key": scene_meta.get("group_key"),
        "semantic_label": label_fields["semantic_label"],
        "raw_review_label": label_fields["raw_review_label"],
        "normalized_semantic_label": label_fields["normalized_semantic_label"],
        "sample_quality": label_fields["sample_quality"],
        "reviewer_confidence": label_fields["reviewer_confidence"],
        "reviewer_notes": label_fields.get("reviewer_notes", ""),
        "files": files,
        "array_path": npz_path,
    }
    with open(os.path.join(mi, "sample.json"), "w", encoding="utf-8") as fh:
        json.dump(sample, fh, indent=2)
    return sample


def default_label_fields():
    return {"semantic_label": "unreviewed", "raw_review_label": "unreviewed",
            "normalized_semantic_label": "unreviewed", "sample_quality": "unreviewed",
            "reviewer_confidence": "unset", "reviewer_notes": ""}


def extract_candidate(ev, idx, seeker, reference_src, args, paths, logger,
                      scale_x, scale_y, event_res, source_res,
                      temporal_seeker=None, scene_meta_base=None):
    """Build all evidence for one candidate. Returns (metadata, warnings)."""
    warnings = list(ev["warnings"])
    folder = os.path.join(paths["candidates"], "candidate_{:04d}".format(idx))
    os.makedirs(folder, exist_ok=True)

    src_w, src_h = source_res
    bbox_evt = ev["bbox"]
    bbox_src = scale_bbox(bbox_evt, scale_x, scale_y)
    bbox_src = clip_rect(bbox_src, src_w, src_h)
    if bbox_src[2] <= 0 or bbox_src[3] <= 0:
        raise ValueError("bbox outside frame after scaling: {}".format(bbox_evt))

    context_rect = build_context_rect(bbox_src, args.context_padding,
                                      args.minimum_context_size, src_w, src_h)
    crop_rect = build_crop_rect(bbox_src, args.crop_padding, src_w, src_h)

    # Frame times.
    first_t = ev["first_seen_seconds"]
    persist_t = ev["persistent_time_seconds"]
    last_t = ev["last_seen_seconds"]
    before_t = max(0.0, first_t - args.before_seconds)
    dur = seeker.duration if seeker.duration else (last_t + args.clip_after_seconds)
    clip_start = max(0.0, persist_t - args.clip_before_seconds)
    clip_end = min(dur, persist_t + args.clip_after_seconds)

    requested = {"before": before_t, "first_seen": first_t,
                 "persistent": persist_t, "last_seen": last_t}
    actual_times, actual_indices = {}, {}

    def save_context(frame, name):
        ctx = crop_region(frame, context_rect)
        rel = bbox_relative_to_rect(bbox_src, context_rect)
        if args.context_scale and args.context_scale != 1.0:
            ctx = cv2.resize(ctx, None, fx=args.context_scale, fy=args.context_scale,
                             interpolation=cv2.INTER_NEAREST)
            rel = tuple(int(round(v * args.context_scale)) for v in rel)
        draw_bbox(ctx, rel)
        put_labels(ctx, [
            "ID {} | {}".format(ev["candidate_id"], name),
            "t={:.2f}s state={} stat={:.1f}s occ={}".format(
                requested.get(name.split("_")[0], 0.0) if name != "difference" else persist_t,
                ev["state"], ev["stationary_duration"], ev["occlusion_count"]),
        ])
        cv2.imwrite(os.path.join(folder, name + ".jpg"), ctx)
        return ctx

    context_images = {}

    # Reference context (reference resized to source resolution; never overwrite source).
    ref_ctx = crop_region(reference_src, context_rect)
    if args.context_scale and args.context_scale != 1.0:
        ref_ctx = cv2.resize(ref_ctx, None, fx=args.context_scale, fy=args.context_scale,
                             interpolation=cv2.INTER_NEAREST)
    put_labels(ref_ctx, ["ID {} | reference".format(ev["candidate_id"]),
                         "reference background context"])
    cv2.imwrite(os.path.join(folder, "reference_context.jpg"), ref_ctx)
    context_images["reference"] = ref_ctx

    for name, t in (("before", before_t), ("first_seen", first_t),
                    ("persistent", persist_t), ("last_seen", last_t)):
        frame, fidx, ft = seeker.read_at(t)
        if frame is None:
            warnings.append("could not read frame for {} at {:.2f}s".format(name, t))
            actual_times[name] = None
            actual_indices[name] = None
            context_images[name] = np.zeros((40, 40, 3), np.uint8)
            continue
        actual_times[name] = round(ft, 4)
        actual_indices[name] = fidx
        context_images[name] = save_context(frame, name + "_context"
                                            if not name.endswith("context") else name)

    # Crops from the persistent frame (best available).
    persist_frame, _, _ = seeker.read_at(persist_t)
    if persist_frame is None:
        persist_frame, _, _ = seeker.read_at(first_t)
    if persist_frame is not None:
        crop = crop_region(persist_frame, crop_rect)
        cv2.imwrite(os.path.join(folder, "persistent_crop.jpg"), crop)
        up = max(1, args.crop_upscale)
        cv2.imwrite(os.path.join(folder, "persistent_crop_nearest.png"),
                    cv2.resize(crop, None, fx=up, fy=up, interpolation=cv2.INTER_NEAREST))
        cv2.imwrite(os.path.join(folder, "persistent_crop_smooth.png"),
                    cv2.resize(crop, None, fx=up, fy=up, interpolation=cv2.INTER_LANCZOS4))
    else:
        warnings.append("no persistent frame available for crops")
        crop = np.zeros((20, 20, 3), np.uint8)

    # Difference context (visualization only).
    diff_vis = _difference_context(context_images.get("persistent"),
                                   context_images.get("reference"), bbox_src,
                                   context_rect, args)
    cv2.imwrite(os.path.join(folder, "difference_context.jpg"), diff_vis)

    # Comparison panel (3x2).
    nearest_vis = cv2.resize(crop, None, fx=max(1, args.crop_upscale),
                             fy=max(1, args.crop_upscale), interpolation=cv2.INTER_NEAREST)
    smooth_vis = cv2.resize(crop, None, fx=max(1, args.crop_upscale),
                            fy=max(1, args.crop_upscale), interpolation=cv2.INTER_LANCZOS4)
    panel = make_comparison_panel([
        ("reference", context_images.get("reference")),
        ("before t={:.1f}s".format(before_t), context_images.get("before")),
        ("persistent t={:.1f}s".format(persist_t), context_images.get("persistent")),
        ("difference", diff_vis),
        ("crop nearest x{}".format(args.crop_upscale), nearest_vis),
        ("crop smooth (interp only)", smooth_vis),
    ], tile_w=320)
    put_labels(panel, [
        "ID {} state={} src_bbox={} area={}px stat={:.1f}s occ={}".format(
            ev["candidate_id"], ev["state"], bbox_src, bbox_area(bbox_src),
            ev["stationary_duration"], ev["occlusion_count"])])
    cv2.imwrite(os.path.join(folder, "comparison_panel.jpg"), panel)

    # Candidate clip.
    clip_path = os.path.join(folder, "candidate_clip.mp4")
    _write_clip(seeker, clip_start, clip_end, persist_t, context_rect, bbox_src,
                ev, args, clip_path, logger)

    # ---- Clean model-input export (schema 2.0) ----
    # Anomaly mask: read the temporal_filtered_mask frame nearest persist_t and
    # upsize to source resolution so it aligns with the source-space crops.
    mask_src_full = None
    mask_times = {"requested": round(persist_t, 4), "actual": None}
    if temporal_seeker is not None:
        mframe, midx, mft = temporal_seeker.read_at(persist_t)
        if mframe is not None:
            if mframe.ndim == 3:
                mframe = cv2.cvtColor(mframe, cv2.COLOR_BGR2GRAY)
            mask_src_full = cv2.resize(mframe, (src_w, src_h), interpolation=cv2.INTER_NEAREST)
            mask_times["actual"] = round(mft, 4)
        else:
            warnings.append("temporal mask frame unreadable at {:.2f}s".format(persist_t))

    scene_meta = dict(scene_meta_base or {})
    scene_meta["candidate_time_group"] = "{}_{}".format(
        scene_meta.get("source_video_id", "unknown"), int(persist_t // 10))
    label_fields = default_label_fields()
    sample = build_model_input(folder, ev, persist_frame, reference_src,
                               mask_src_full, bbox_src, args, source_res,
                               scene_meta, label_fields, mask_times)
    if not sample["alignment_valid"]:
        warnings.append("model-input alignment invalid: {}".format(sample["alignment_warnings"]))

    # Metadata.
    metadata = {
        "candidate_id": ev["candidate_id"],
        "source_video": ev["source_video"],
        "source_video_filename": os.path.basename(ev["source_video"]) if ev["source_video"] else None,
        "events_json_path": paths["events"],
        "reference_path": paths["reference"],
        "event_state": ev["state"],
        "selected_by_filter": True,
        "first_seen_seconds": first_t,
        "persistent_time_seconds": persist_t,
        "persistent_time_fallback": ev["persistent_time_fallback"],
        "last_seen_seconds": last_t,
        "last_seen_fallback": ev["last_seen_fallback"],
        "stationary_duration_seconds": ev["stationary_duration"],
        "occlusion_count": ev["occlusion_count"],
        "total_occluded_duration_seconds": ev["total_occluded_duration"],
        "resumed_after_occlusion_count": ev["resumed_after_occlusion_count"],
        "bbox_event_coordinates": list(bbox_evt),
        "bbox_source_coordinates": list(bbox_src),
        "event_coordinate_resolution": {"width": event_res[0], "height": event_res[1]},
        "source_video_resolution": {"width": src_w, "height": src_h},
        "bbox_scale_x": scale_x,
        "bbox_scale_y": scale_y,
        "context_bbox_source_coordinates": list(context_rect),
        "crop_bbox_source_coordinates": list(crop_rect),
        "requested_frame_times": requested,
        "actual_frame_times": actual_times,
        "extracted_frame_indices": actual_indices,
        "clip_start_seconds": round(clip_start, 3),
        "clip_end_seconds": round(clip_end, 3),
        "extraction_warnings": warnings,
        # Legacy single label kept for backward compatibility.
        "label": "unreviewed",
        "reviewer_notes": "",
        # Schema 2.0 label fields.
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "semantic_label": label_fields["semantic_label"],
        "raw_review_label": label_fields["raw_review_label"],
        "normalized_semantic_label": label_fields["normalized_semantic_label"],
        "sample_quality": label_fields["sample_quality"],
        "reviewer_confidence": label_fields["reviewer_confidence"],
        # Scene / camera / grouping (leakage-prevention metadata).
        "camera_id": scene_meta.get("camera_id"),
        "camera_id_source": scene_meta.get("camera_id_source"),
        "scene_id": scene_meta.get("scene_id"),
        "capture_condition": scene_meta.get("capture_condition"),
        "source_video_id": scene_meta.get("source_video_id"),
        "candidate_time_group": scene_meta.get("candidate_time_group"),
        "group_key": scene_meta.get("group_key"),
        "generated_negative": scene_meta.get("generated_negative", False),
        # Model-input summary.
        "mask_source": sample["mask_source"],
        "model_source_crop": sample["model_source_crop"],
        "model_input_size": sample["model_input_size"],
        "alignment_valid": sample["alignment_valid"],
        "alignment_warnings": sample["alignment_warnings"],
        "original_event": ev["raw_event"],
    }
    if "duplicate_group_id" in ev:
        metadata["duplicate_group_id"] = ev["duplicate_group_id"]
        metadata["duplicate_is_primary"] = ev["duplicate_is_primary"]
        metadata["duplicate_group_size"] = ev["duplicate_group_size"]

    with open(os.path.join(folder, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    return metadata, warnings, folder, sample


def _difference_context(persist_ctx, ref_ctx, bbox_src, context_rect, args):
    if persist_ctx is None or ref_ctx is None or persist_ctx.size == 0 or ref_ctx.size == 0:
        return np.zeros((40, 40, 3), np.uint8)
    h = min(persist_ctx.shape[0], ref_ctx.shape[0])
    w = min(persist_ctx.shape[1], ref_ctx.shape[1])
    a = cv2.cvtColor(persist_ctx[:h, :w], cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(ref_ctx[:h, :w], cv2.COLOR_BGR2GRAY)
    a = cv2.GaussianBlur(a, (3, 3), 0)
    b = cv2.GaussianBlur(b, (3, 3), 0)
    diff = cv2.absdiff(a, b)
    diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    vis = cv2.applyColorMap(diff.astype(np.uint8), cv2.COLORMAP_JET)
    rel = bbox_relative_to_rect(bbox_src, context_rect)
    if args.context_scale and args.context_scale != 1.0:
        rel = tuple(int(round(v * args.context_scale)) for v in rel)
    draw_bbox(vis, rel)
    put_labels(vis, ["difference (persistent vs reference)", "visualization only"])
    return vis


def _write_clip(seeker, t0, t1, persist_t, context_rect, bbox_src, ev, args,
                out_path, logger):
    rx, ry, rw, rh = context_rect
    out_w = args.clip_width if args.clip_width and args.clip_width > 0 else rw
    scale = out_w / float(rw)
    out_h = max(1, int(round(rh * scale)))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(out_path, fourcc, seeker.fps, (out_w, out_h))
    if not vw.isOpened():
        logger.warn("could not open clip writer for {}".format(out_path))
        return
    rel = bbox_relative_to_rect(bbox_src, context_rect)
    wrote = 0
    for frame, fidx, ft in seeker.iter_range(t0, t1):
        sub = frame[ry:ry + rh, rx:rx + rw].copy()
        if scale != 1.0:
            sub = cv2.resize(sub, (out_w, out_h),
                             interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST)
            r = tuple(int(round(v * scale)) for v in rel)
        else:
            r = rel
        draw_bbox(sub, r)
        phase = "PRE-persistent" if ft < persist_t else "post-persistent"
        put_labels(sub, ["ID {}  t={:.2f}s  {}".format(ev["candidate_id"], ft, phase),
                         "state={} (fixed event bbox)".format(ev["state"])])
        vw.write(sub)
        wrote += 1
    vw.release()
    if wrote == 0:
        logger.warn("clip for candidate {} has no frames".format(ev["candidate_id"]))


# ---------------------------------------------------------------------------
# Manifests / summary / HTML
# ---------------------------------------------------------------------------
def _write_csv(path, rows, fields):
    # UTF-8 with BOM so Korean Windows Excel opens it correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def write_manifests(paths, rows, logger):
    with open(paths["manifest_json"], "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    fields = ["candidate_folder", "candidate_id", "video", "state", "first_seen_seconds",
              "persistent_time_seconds", "last_seen_seconds", "stationary_duration_seconds",
              "source_bbox", "area_pixels", "occlusion_count",
              "semantic_label", "raw_review_label", "sample_quality", "reviewer_confidence",
              "label", "reviewer_notes", "camera_id", "scene_id",
              "duplicate_group_id", "is_duplicate_primary",
              "comparison_panel", "paired_horizontal", "mask", "clip", "metadata"]
    _write_csv(paths["manifest_csv"], rows, fields)


def build_manifest_row(meta, folder, paths, sample=None):
    rel = os.path.relpath(folder, paths["output"]).replace("\\", "/")
    mi = rel + "/model_input"
    return {
        "candidate_folder": rel,
        "candidate_id": meta["candidate_id"],
        "video": meta["source_video_filename"],
        "state": meta["event_state"],
        "first_seen_seconds": meta["first_seen_seconds"],
        "persistent_time_seconds": meta["persistent_time_seconds"],
        "last_seen_seconds": meta["last_seen_seconds"],
        "stationary_duration_seconds": meta["stationary_duration_seconds"],
        "source_bbox": meta["bbox_source_coordinates"],
        "area_pixels": bbox_area(meta["bbox_source_coordinates"]),
        "occlusion_count": meta["occlusion_count"],
        "semantic_label": meta.get("semantic_label", "unreviewed"),
        "raw_review_label": meta.get("raw_review_label", "unreviewed"),
        "sample_quality": meta.get("sample_quality", "unreviewed"),
        "reviewer_confidence": meta.get("reviewer_confidence", "unset"),
        "label": meta.get("label", "unreviewed"),
        "reviewer_notes": meta.get("reviewer_notes", ""),
        "camera_id": meta.get("camera_id"),
        "scene_id": meta.get("scene_id"),
        "duplicate_group_id": meta.get("duplicate_group_id"),
        "is_duplicate_primary": meta.get("duplicate_is_primary"),
        "comparison_panel": rel + "/comparison_panel.jpg",
        "paired_horizontal": mi + "/paired_horizontal.png",
        "mask": mi + "/mask.png",
        "clip": rel + "/candidate_clip.mp4",
        "metadata": rel + "/metadata.json",
    }


# ---------------------------------------------------------------------------
# Training manifest
# ---------------------------------------------------------------------------
def compute_usable_for_training(meta, sample, exclude_poor_quality, allow_unknown=False):
    """Decide usable_for_training + exclusion_reason. Conservative by default:
    unreviewed/unknown semantic labels and failed alignment are NOT training data."""
    reasons = []
    sem = meta.get("semantic_label", "unreviewed")
    quality = meta.get("sample_quality", "unreviewed")
    if sem in ("unreviewed",):
        reasons.append("semantic_label unreviewed")
    if sem == "unknown" and not allow_unknown:
        reasons.append("semantic_label unknown")
    if quality in ("unreviewed",):
        reasons.append("sample_quality unreviewed")
    if quality in ("unusable", "object_not_visible", "bbox_wrong_location"):
        reasons.append("sample_quality {}".format(quality))
    if exclude_poor_quality and quality not in ("good", "unreviewed"):
        reasons.append("excluded poor quality ({})".format(quality))
    if sample is not None and not sample.get("alignment_valid", True):
        reasons.append("alignment invalid")
    return (len(reasons) == 0), reasons


def build_training_row(meta, sample, folder, paths, exclude_poor_quality):
    rel = os.path.relpath(folder, paths["output"]).replace("\\", "/")
    mi = rel + "/model_input"
    usable, reasons = compute_usable_for_training(meta, sample, exclude_poor_quality)
    return {
        "candidate_id": meta["candidate_id"],
        "candidate_folder": rel,
        "source_video": meta.get("source_video"),
        "source_video_filename": meta.get("source_video_filename"),
        "camera_id": meta.get("camera_id"),
        "scene_id": meta.get("scene_id"),
        "source_video_id": meta.get("source_video_id"),
        "candidate_time_group": meta.get("candidate_time_group"),
        "duplicate_group_id": meta.get("duplicate_group_id"),
        "group_key": meta.get("group_key"),
        "semantic_label": meta.get("semantic_label", "unreviewed"),
        "raw_review_label": meta.get("raw_review_label", "unreviewed"),
        "sample_quality": meta.get("sample_quality", "unreviewed"),
        "reviewer_confidence": meta.get("reviewer_confidence", "unset"),
        "reference_path": mi + "/reference.png",
        "current_path": mi + "/current.png",
        "difference_path": mi + "/difference.png",
        "mask_path": mi + "/mask.png",
        "context_path": mi + "/context.png",
        "paired_horizontal_path": mi + "/paired_horizontal.png",
        "paired_grid_path": mi + "/paired_grid.png",
        "npz_path": (mi + "/sample.npz") if (sample and sample.get("array_path")) else None,
        "source_bbox": meta.get("bbox_source_coordinates"),
        "model_source_crop": meta.get("model_source_crop"),
        "model_input_size": meta.get("model_input_size"),
        "stationary_duration": meta.get("stationary_duration_seconds"),
        "occlusion_count": meta.get("occlusion_count"),
        "mask_source": meta.get("mask_source"),
        "event_state": meta.get("event_state"),
        "generated_negative": meta.get("generated_negative", False),
        "usable_for_training": usable,
        "exclusion_reason": "; ".join(reasons) if reasons else None,
    }


def write_training_manifests(paths, rows, logger):
    with open(paths["training_manifest_json"], "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)
    fields = ["candidate_id", "candidate_folder", "source_video", "source_video_filename",
              "camera_id", "scene_id", "source_video_id", "candidate_time_group",
              "duplicate_group_id", "group_key", "semantic_label", "raw_review_label",
              "sample_quality", "reviewer_confidence", "reference_path", "current_path",
              "difference_path", "mask_path", "context_path", "paired_horizontal_path",
              "paired_grid_path", "npz_path", "source_bbox", "model_source_crop",
              "model_input_size", "stationary_duration", "occlusion_count", "mask_source",
              "event_state", "generated_negative", "usable_for_training", "exclusion_reason"]
    _write_csv(paths["training_manifest_csv"], rows, fields)


def write_review_html(paths, rows):
    data_json = json.dumps(rows, ensure_ascii=False)
    html = (_REVIEW_TEMPLATE
            .replace("__DATA__", data_json)
            .replace("__SEMANTIC__", json.dumps([s for s in SEMANTIC_LABELS]))
            .replace("__QUALITY__", json.dumps(QUALITY_LABELS))
            .replace("__CONFIDENCE__", json.dumps(CONFIDENCE_LEVELS))
            .replace("__SCHEMA__", json.dumps(LABEL_SCHEMA_VERSION)))
    with open(paths["review_html"], "w", encoding="utf-8") as fh:
        fh.write(html)


_REVIEW_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Candidate Review (schema 2.0)</title>
<style>
 body{font-family:Arial,Helvetica,sans-serif;margin:0;background:#1d1f24;color:#eee}
 header{position:sticky;top:0;background:#15171b;padding:10px 16px;border-bottom:1px solid #333;z-index:10}
 header input,header select,header button{font-size:14px;padding:4px 8px;margin-right:8px}
 .wrap{padding:16px;display:flex;flex-wrap:wrap;gap:16px}
 .card{background:#262a31;border:1px solid #3a3f49;border-radius:8px;padding:10px;width:380px}
 .card img{width:100%;border-radius:4px;background:#000;margin-bottom:4px}
 .imrow{display:flex;gap:4px}.imrow img{width:50%}
 .meta{font-size:12px;line-height:1.4;margin:6px 0;color:#cfd3da}
 .grp{font-size:11px;color:#9fb;margin-top:6px}
 .grp b{color:#cfe}
 .labels button{font-size:11px;margin:2px;padding:3px 5px;border:1px solid #555;border-radius:4px;background:#333;color:#eee;cursor:pointer}
 .labels.sem button.sel{background:#2d7;color:#000;font-weight:bold}
 .labels.qual button.sel{background:#fb4;color:#000;font-weight:bold}
 .labels.conf button.sel{background:#6cf;color:#000;font-weight:bold}
 textarea{width:100%;box-sizing:border-box;background:#1b1d22;color:#eee;border:1px solid #444;border-radius:4px}
 a{color:#6cf}.count{color:#9aa}
</style></head><body>
<header>
 <strong>Candidate Review &mdash; schema __SCHEMA__</strong>
 <span class="count" id="count"></span><br>
 Search ID: <input id="search" oninput="render()" size="8">
 Filter: <select id="filter" onchange="render()"><option value="">all</option></select>
 <button onclick="prev()">&larr; Prev</button><button onclick="next()">Next &rarr;</button>
 <button onclick="download()">Download review results</button>
 <span class="count">labels are NOT auto-saved to disk &mdash; use Download, then import with --review-results</span>
</header>
<div class="wrap" id="wrap"></div>
<script>
const DATA = __DATA__;
const SEMANTIC = __SEMANTIC__;
const QUALITY = __QUALITY__;
const CONFIDENCE = __CONFIDENCE__;
const SCHEMA = __SCHEMA__;
const review = {};
DATA.forEach(d=>review[String(d.candidate_id)]={
  semantic_label:d.semantic_label||'unreviewed',
  sample_quality:d.sample_quality||'unreviewed',
  confidence:d.reviewer_confidence||'unset',
  notes:d.reviewer_notes||''});
const fsel=document.getElementById('filter');
['unreviewed',...SEMANTIC,...QUALITY,...[...new Set(DATA.map(d=>d.state))]].forEach(v=>{if(v){const o=document.createElement('option');o.value=v;o.textContent=v;fsel.appendChild(o);}});
let focusIdx=0;
function setSem(id,l){review[String(id)].semantic_label=l;render();}
function setQual(id,l){review[String(id)].sample_quality=l;render();}
function setConf(id,l){review[String(id)].confidence=l;render();}
function setNotes(id,v){review[String(id)].notes=v;}
function visible(){const s=document.getElementById('search').value.trim();const f=document.getElementById('filter').value;
 return DATA.filter(d=>{if(s&&String(d.candidate_id).indexOf(s)<0)return false;
  if(f){const r=review[String(d.candidate_id)];
   if(f===d.state||r.semantic_label===f||r.sample_quality===f)return true;return false;}return true;});}
function btns(cls,opts,cur,id,fn){return `<div class="labels ${cls}">`+opts.map(l=>`<button class="${cur===l?'sel':''}" onclick="${fn}('${id}','${l}')">${l}</button>`).join('')+`</div>`;}
function render(){const v=visible();const wrap=document.getElementById('wrap');wrap.innerHTML='';
 document.getElementById('count').textContent=' '+v.length+' / '+DATA.length+' candidates';
 v.forEach((d)=>{const r=review[String(d.candidate_id)];const c=document.createElement('div');c.className='card';c.id='card_'+d.candidate_id;
  c.innerHTML=`<img src="${d.comparison_panel}" loading="lazy" title="human review only (do NOT train on this)">
   <div class="imrow"><img src="${d.paired_horizontal}" loading="lazy" title="model input: reference|current|difference"><img src="${d.mask}" loading="lazy" title="anomaly mask"></div>
   <div class="meta"><b>ID ${d.candidate_id}</b> | state=${d.state} | area=${d.area_pixels}px<br>
   persistent=${d.persistent_time_seconds}s stationary=${d.stationary_duration_seconds}s occ=${d.occlusion_count}<br>
   bbox=${JSON.stringify(d.source_bbox)}<br>
   <a href="${d.clip}" target="_blank">clip</a> &middot; <a href="${d.metadata}" target="_blank">metadata.json</a></div>
   <div class="grp"><b>semantic</b></div>${btns('sem',SEMANTIC,r.semantic_label,d.candidate_id,'setSem')}
   <div class="grp"><b>sample quality</b></div>${btns('qual',QUALITY,r.sample_quality,d.candidate_id,'setQual')}
   <div class="grp"><b>confidence</b></div>${btns('conf',CONFIDENCE,r.confidence,d.candidate_id,'setConf')}
   <textarea rows="2" placeholder="reviewer notes" oninput="setNotes('${d.candidate_id}',this.value)">${r.notes}</textarea>`;
  wrap.appendChild(c);});}
function next(){focusIdx=Math.min(visible().length-1,focusIdx+1);scrollTo(focusIdx);}
function prev(){focusIdx=Math.max(0,focusIdx-1);scrollTo(focusIdx);}
function scrollTo(i){const v=visible();if(v[i]){document.getElementById('card_'+v[i].candidate_id).scrollIntoView({behavior:'smooth',block:'center'});}}
function download(){const out={generated_at:new Date().toISOString(),label_schema_version:SCHEMA,
  results:Object.keys(review).map(id=>({candidate_id:id,semantic_label:review[id].semantic_label,
   sample_quality:review[id].sample_quality,confidence:review[id].confidence,
   notes:review[id].notes,label_schema_version:SCHEMA}))};
 const blob=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});const a=document.createElement('a');
 a.href=URL.createObjectURL(blob);a.download='review_results.json';a.click();}
render();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# Review import mode
# ---------------------------------------------------------------------------
def apply_review_fields(target, fields):
    """Apply merged schema-2.0 review fields onto a metadata/sample/row dict."""
    target["semantic_label"] = fields["semantic_label"]
    target["raw_review_label"] = fields["raw_review_label"]
    target["normalized_semantic_label"] = fields["normalized_semantic_label"]
    target["sample_quality"] = fields["sample_quality"]
    target["reviewer_confidence"] = fields["reviewer_confidence"]
    target["reviewer_notes"] = fields["notes"]
    target["label"] = fields["label"]  # legacy mirror
    return target


def run_review_import(args, paths, logger):
    if not os.path.isfile(paths["manifest_json"]):
        fail("--review-results given but manifest.json not found at {}; run an "
             "extraction first.".format(paths["manifest_json"]))
    with open(paths["manifest_json"], encoding="utf-8") as fh:
        rows = json.load(fh)
    valid_ids = [r["candidate_id"] for r in rows]
    with open(args.review_results, encoding="utf-8") as fh:
        review_doc = json.load(fh)
    merged, unknown, dups, migr, invalid = merge_review_results(review_doc, valid_ids)
    for label, lst in (("unknown candidate ids (ignored)", unknown),
                       ("duplicate candidate ids (last wins)", dups),
                       ("invalid enum values (defaulted)", invalid),
                       ("legacy migrations", migr)):
        if lst:
            logger.warn("{}: {}".format(label, lst))

    updated = 0
    training_rows = []
    for r in rows:
        cid = str(r["candidate_id"])
        folder = os.path.join(paths["output"], r["candidate_folder"])
        meta_path = os.path.join(folder, "metadata.json")
        sample_path = os.path.join(folder, "model_input", "sample.json")
        meta = None
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        if cid in merged:
            f = merged[cid]
            apply_review_fields(r, f)
            if meta is not None:
                apply_review_fields(meta, f)
                meta["label_schema_version"] = LABEL_SCHEMA_VERSION
            if os.path.isfile(sample_path):
                with open(sample_path, encoding="utf-8") as fh:
                    sample = json.load(fh)
                apply_review_fields(sample, f)
                with open(sample_path, "w", encoding="utf-8") as fh:
                    json.dump(sample, fh, indent=2)
            updated += 1
        if meta is not None:
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=2)
            sample = None
            if os.path.isfile(sample_path):
                with open(sample_path, encoding="utf-8") as fh:
                    sample = json.load(fh)
            training_rows.append(build_training_row(
                meta, sample, folder, paths, args.exclude_poor_quality_from_training))

    write_manifests(paths, rows, logger)
    if training_rows:
        write_training_manifests(paths, training_rows, logger)
    write_review_html(paths, rows)
    logger.info("Review import: updated {} / {} candidates ({} unknown, {} duplicate, "
                "{} invalid-enum, {} migrations)."
                .format(updated, len(rows), len(unknown), len(dups), len(invalid), len(migr)))
    return 0


# ---------------------------------------------------------------------------
# Background-only negative samples
# ---------------------------------------------------------------------------
def boxes_overlap(a, b, margin=0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax, ay, aw, ah = ax - margin, ay - margin, aw + 2 * margin, ah + 2 * margin
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def generate_background_negatives(args, paths, seeker, reference_src, temporal_seeker,
                                  scene_meta_base, candidate_boxes, source_res,
                                  start_idx, rows, training_rows, logger):
    """Create background-only negatives in non-candidate regions (deterministic
    via --random-seed). Returns the number generated."""
    src_w, src_h = source_res
    rng = np.random.default_rng(args.random_seed)
    side = int(max(args.model_minimum_region_size,
                   args.model_minimum_region_size + 2 * args.model_context_padding))
    margin = args.model_context_padding + 4
    if src_w <= side or src_h <= side:
        logger.warn("frame too small for background negatives; skipping.")
        return 0
    dur = seeker.duration or 1.0
    made, attempts, idx = 0, 0, start_idx
    max_attempts = args.background_negative_count * 50 + 50
    while made < args.background_negative_count and attempts < max_attempts:
        attempts += 1
        x = int(rng.integers(0, src_w - side))
        y = int(rng.integers(0, src_h - side))
        box = (x, y, side, side)
        if any(boxes_overlap(box, cb, margin) for cb in candidate_boxes):
            continue
        t = float(rng.uniform(0, dur))
        frame, fidx, ft = seeker.read_at(t)
        if frame is None:
            continue
        idx += 1
        made += 1
        folder = os.path.join(paths["candidates"], "candidate_neg_{:04d}".format(idx))
        os.makedirs(folder, exist_ok=True)
        scene_meta = dict(scene_meta_base)
        scene_meta["generated_negative"] = True
        scene_meta["candidate_time_group"] = "{}_{}".format(
            scene_meta.get("source_video_id", "unknown"), int(t // 10))
        cid = "neg_{:04d}".format(idx)
        ev = {"candidate_id": cid, "raw_event": {"generated_negative": True},
              "duplicate_group_id": None, "stationary_duration": 0.0,
              "occlusion_count": 0, "state": "background_negative"}
        label_fields = default_label_fields()
        label_fields.update({"semantic_label": SEMANTIC_LABEL_BACKGROUND,
                             "raw_review_label": SEMANTIC_LABEL_BACKGROUND,
                             "normalized_semantic_label": SEMANTIC_LABEL_BACKGROUND,
                             "sample_quality": "good"})
        sample = build_model_input(folder, ev, frame, reference_src, None, box,
                                   args, source_res, scene_meta, label_fields,
                                   {"requested": round(t, 4), "actual": round(ft, 4)})
        meta = {
            "candidate_id": cid, "source_video": args.video,
            "source_video_filename": scene_meta["source_video_id"],
            "events_json_path": paths["events"], "reference_path": paths["reference"],
            "event_state": "background_negative", "selected_by_filter": False,
            "generated_negative": True, "random_seed": args.random_seed,
            "first_seen_seconds": round(t, 3), "persistent_time_seconds": round(t, 3),
            "last_seen_seconds": round(t, 3), "stationary_duration_seconds": 0.0,
            "occlusion_count": 0, "total_occluded_duration_seconds": 0.0,
            "resumed_after_occlusion_count": 0,
            "bbox_source_coordinates": list(box),
            "source_video_resolution": {"width": src_w, "height": src_h},
            "label": SEMANTIC_LABEL_BACKGROUND, "reviewer_notes": "",
            "label_schema_version": LABEL_SCHEMA_VERSION,
            "semantic_label": SEMANTIC_LABEL_BACKGROUND,
            "raw_review_label": SEMANTIC_LABEL_BACKGROUND,
            "normalized_semantic_label": SEMANTIC_LABEL_BACKGROUND,
            "sample_quality": "good", "reviewer_confidence": "unset",
            "camera_id": scene_meta.get("camera_id"),
            "camera_id_source": scene_meta.get("camera_id_source"),
            "scene_id": scene_meta.get("scene_id"),
            "capture_condition": scene_meta.get("capture_condition"),
            "source_video_id": scene_meta.get("source_video_id"),
            "candidate_time_group": scene_meta.get("candidate_time_group"),
            "group_key": scene_meta.get("group_key"),
            "mask_source": sample["mask_source"],
            "model_source_crop": sample["model_source_crop"],
            "model_input_size": sample["model_input_size"],
            "alignment_valid": sample["alignment_valid"],
            "alignment_warnings": sample["alignment_warnings"],
            "extraction_warnings": [], "original_event": ev["raw_event"],
        }
        with open(os.path.join(folder, "metadata.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        rows.append(build_manifest_row(meta, folder, paths, sample))
        training_rows.append(build_training_row(
            meta, sample, folder, paths, args.exclude_poor_quality_from_training))
    if made < args.background_negative_count:
        logger.warn("only generated {} / {} background negatives (non-overlap attempts exhausted)."
                    .format(made, args.background_negative_count))
    logger.info("Generated {} background-negative sample(s).".format(made))
    return made


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)
    logger = Logger(args.verbose)
    start_clock = time.time()

    if not os.path.isfile(args.events):
        fail("event JSON not found: {}".format(args.events))
    try:
        with open(args.events, encoding="utf-8") as fh:
            doc = json.load(fh)
    except json.JSONDecodeError as exc:
        fail("malformed event JSON: {}".format(exc))

    paths = {
        "output": args.output,
        "events": os.path.abspath(args.events),
        "reference": os.path.abspath(args.reference) if args.reference else None,
        "candidates": os.path.join(args.output, "candidates"),
        "manifest_json": os.path.join(args.output, "manifest.json"),
        "manifest_csv": os.path.join(args.output, "manifest.csv"),
        "training_manifest_json": os.path.join(args.output, "training_manifest.json"),
        "training_manifest_csv": os.path.join(args.output, "training_manifest.csv"),
        "summary": os.path.join(args.output, "extraction_summary.json"),
        "review_html": os.path.join(args.output, "review.html"),
    }
    try:
        os.makedirs(args.output, exist_ok=True)
    except OSError as exc:
        fail("output write failure: {}".format(exc))

    # Review import path may skip extraction entirely.
    if args.review_results and args.update_labels_only:
        return run_review_import(args, paths, logger)

    if not args.video:
        fail("--video is required for extraction.")
    if not os.path.isfile(args.video):
        fail("video file not found: {}".format(args.video))
    if not args.reference or not os.path.isfile(args.reference):
        fail("reference image not found: {}".format(args.reference))

    reference_img = cv2.imread(args.reference, cv2.IMREAD_COLOR)
    if reference_img is None:
        fail("reference image cannot be opened: {}".format(args.reference))

    try:
        seeker = VideoSeeker(args.video, logger)
    except IOError as exc:
        fail(str(exc))
    src_w, src_h = seeker.width, seeker.height
    if src_w <= 0 or src_h <= 0:
        frame, _, _ = seeker.read_at(0)
        if frame is None:
            fail("video frame read failure on first frame.")
        src_h, src_w = frame.shape[:2]

    source_video_path = doc.get("source_video_path", args.video) if isinstance(doc, dict) else args.video
    event_w, event_h, res_source = resolve_event_resolution(doc, args, src_w, src_h, logger)
    scale_x = src_w / float(event_w)
    scale_y = src_h / float(event_h)

    # Reference resized to SOURCE resolution for context cropping (never overwrite source file).
    reference_src = cv2.resize(reference_img, (src_w, src_h), interpolation=cv2.INTER_AREA) \
        if (reference_img.shape[1] != src_w or reference_img.shape[0] != src_h) else reference_img

    logger.info("Inputs:")
    logger.info("  video     : {}".format(args.video))
    logger.info("  events    : {}".format(args.events))
    logger.info("  reference : {}".format(args.reference))
    logger.info("  output    : {}".format(args.output))
    logger.info("Source: {}x{}  fps={:.3f}{}  duration={}".format(
        src_w, src_h, seeker.fps, " (FALLBACK)" if seeker.fps_fallback else "",
        "{:.2f}s".format(seeker.duration) if seeker.duration else "unknown"))
    logger.info("Event coordinate resolution: {}x{} (from {}); scale x{:.4f} y{:.4f}".format(
        event_w, event_h, res_source, scale_x, scale_y))

    # Optional temporal mask video (real anomaly mask source).
    temporal_seeker = None
    if args.temporal_mask_video:
        if not os.path.isfile(args.temporal_mask_video):
            logger.warn("temporal-mask-video not found ({}); using bbox fallback masks."
                        .format(args.temporal_mask_video))
        else:
            try:
                temporal_seeker = VideoSeeker(args.temporal_mask_video, logger)
                logger.info("Temporal mask video: {} ({}x{} @ {:.2f}fps)".format(
                    args.temporal_mask_video, temporal_seeker.width,
                    temporal_seeker.height, temporal_seeker.fps))
            except IOError as exc:
                logger.warn("could not open temporal-mask-video: {}".format(exc))

    # Scene / camera grouping metadata (leakage-prevention).
    src_filename = os.path.basename(source_video_path) if source_video_path else \
        os.path.basename(args.video)
    if args.camera_id:
        camera_id, camera_src = args.camera_id, "explicit"
    else:
        camera_id, camera_src = infer_camera_id(src_filename)
    scene_id = args.scene_id if args.scene_id else "unknown"
    scene_meta_base = {
        "camera_id": camera_id,
        "camera_id_source": camera_src,
        "scene_id": scene_id,
        "capture_condition": args.capture_condition if args.capture_condition else "unknown",
        "source_video_id": src_filename,
        "group_key": "{}/{}".format(camera_id, src_filename),
        "generated_negative": False,
    }
    logger.info("Scene metadata: camera_id={} ({}) scene_id={} group_key={}".format(
        camera_id, camera_src, scene_id, scene_meta_base["group_key"]))

    try:
        raw_events = find_event_list(doc)
    except ValueError as exc:
        fail(str(exc))

    normalized = [normalize_event(e, source_video_path, i) for i, e in enumerate(raw_events)]
    logger.info("Events found: {}".format(len(normalized)))
    if args.verbose:
        for ev in normalized[:50]:
            logger.debug("event id={} state={} first={:.2f} persist={:.2f} bbox={} warn={}".format(
                ev["candidate_id"], ev["state"], ev["first_seen_seconds"],
                ev["persistent_time_seconds"], ev["bbox"], ev["warnings"]))

    candidate_ids = [s.strip() for s in args.candidate_ids.split(",")] if args.candidate_ids else None
    state_filter = [s for s in args.state_filter.split(",")] if args.state_filter else None
    selected, skipped = select_candidates(
        normalized, args.include_non_persistent, state_filter,
        args.min_stationary_seconds, candidate_ids, args.max_candidates)
    logger.info("Candidates selected: {} (skipped {})".format(len(selected), len(skipped)))

    if args.group_nearby_candidates and selected:
        group_duplicates(selected, args.duplicate_center_distance,
                         args.duplicate_time_overlap_seconds)
        ngroups = len(set(e.get("duplicate_group_id") for e in selected))
        logger.info("Duplicate grouping: {} group(s) over {} candidates.".format(ngroups, len(selected)))

    os.makedirs(paths["candidates"], exist_ok=True)
    rows, training_rows = [], []
    extracted, extract_skipped = 0, []
    missing_field_warnings = []
    candidate_boxes_src = []   # for background-negative non-overlap
    next_folder_idx = 0
    for i, ev in enumerate(selected, start=1):
        next_folder_idx = i
        try:
            meta, warns, folder, sample = extract_candidate(
                ev, i, seeker, reference_src, args, paths, logger,
                scale_x, scale_y, (event_w, event_h), (src_w, src_h),
                temporal_seeker=temporal_seeker, scene_meta_base=scene_meta_base)
            rows.append(build_manifest_row(meta, folder, paths, sample))
            training_rows.append(build_training_row(
                meta, sample, folder, paths, args.exclude_poor_quality_from_training))
            candidate_boxes_src.append(meta["bbox_source_coordinates"])
            extracted += 1
            if warns:
                missing_field_warnings.append({"candidate_id": ev["candidate_id"], "warnings": warns})
            logger.info("  [{}/{}] candidate {} -> {} (mask={}, align={})".format(
                i, len(selected), ev["candidate_id"], os.path.basename(folder),
                sample["mask_source"], sample["alignment_valid"]))
        except Exception as exc:  # one bad candidate must not abort the rest
            extract_skipped.append({"candidate_id": ev["candidate_id"], "reason": str(exc)})
            logger.warn("skipping candidate {}: {}".format(ev["candidate_id"], exc))

    # Optional background-only negative samples.
    negatives_made = 0
    if args.background_negative_count > 0:
        negatives_made = generate_background_negatives(
            args, paths, seeker, reference_src, temporal_seeker, scene_meta_base,
            candidate_boxes_src, (src_w, src_h), next_folder_idx, rows, training_rows, logger)

    # Optional in-line review merge (without --update-labels-only): also extract.
    if args.review_results and not args.update_labels_only and os.path.isfile(args.review_results):
        try:
            with open(args.review_results, encoding="utf-8") as fh:
                review_doc = json.load(fh)
            merged, unknown, dups, migr, invalid = merge_review_results(
                review_doc, [r["candidate_id"] for r in rows])
            by_id = {str(r["candidate_id"]): r for r in rows}
            tby_id = {str(r["candidate_id"]): r for r in training_rows}
            for cid, f in merged.items():
                if cid in by_id:
                    apply_review_fields(by_id[cid], f)
                if cid in tby_id:
                    tby_id[cid]["semantic_label"] = f["semantic_label"]
                    tby_id[cid]["raw_review_label"] = f["raw_review_label"]
                    tby_id[cid]["sample_quality"] = f["sample_quality"]
                    tby_id[cid]["reviewer_confidence"] = f["reviewer_confidence"]
                    u, reasons = compute_usable_for_training(
                        {"semantic_label": f["semantic_label"], "sample_quality": f["sample_quality"]},
                        None, args.exclude_poor_quality_from_training)
                    tby_id[cid]["usable_for_training"] = u
                    tby_id[cid]["exclusion_reason"] = "; ".join(reasons) if reasons else None
            if unknown:
                logger.warn("review-results unknown ids: {}".format(unknown))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warn("could not merge review-results: {}".format(exc))

    seeker.release()
    if temporal_seeker is not None:
        temporal_seeker.release()
    write_manifests(paths, rows, logger)
    write_training_manifests(paths, training_rows, logger)
    write_review_html(paths, rows)

    skipped_reasons = {}
    for _, reason in skipped:
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
    for s in extract_skipped:
        skipped_reasons["extraction_error"] = skipped_reasons.get("extraction_error", 0) + 1

    usable_now = sum(1 for r in training_rows if r.get("usable_for_training"))
    summary = {
        "total_events_found": len(normalized),
        "total_candidates_selected": len(selected),
        "total_candidates_extracted": extracted,
        "total_background_negatives_generated": negatives_made,
        "total_candidates_skipped": len(skipped) + len(extract_skipped),
        "skipped_reasons": skipped_reasons,
        "extraction_errors": extract_skipped,
        "missing_field_warnings": missing_field_warnings,
        "usable_for_training_before_review": usable_now,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "mask_source_video": args.temporal_mask_video,
        "model_input_size": args.model_input_size,
        "context_model_input_size": args.context_model_input_size,
        "difference_mode": args.difference_mode,
        "scene_metadata": scene_meta_base,
        "video_fps": seeker.fps,
        "video_fps_fallback": seeker.fps_fallback,
        "video_duration_seconds": seeker.duration,
        "source_resolution": {"width": src_w, "height": src_h},
        "event_resolution": {"width": event_w, "height": event_h, "source": res_source},
        "extraction_start_time": datetime.fromtimestamp(start_clock, timezone.utc).isoformat(),
        "extraction_end_time": datetime.now(timezone.utc).isoformat(),
        "total_processing_duration_seconds": round(time.time() - start_clock, 2),
    }
    with open(paths["summary"], "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    logger.info("Extracted {} candidate(s), {} background negative(s). "
                "{} usable for training (pre-review). Outputs:".format(
                    extracted, negatives_made, usable_now))
    for k in ("manifest_json", "manifest_csv", "training_manifest_json",
              "training_manifest_csv", "summary", "review_html"):
        logger.info("  {}".format(paths[k]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

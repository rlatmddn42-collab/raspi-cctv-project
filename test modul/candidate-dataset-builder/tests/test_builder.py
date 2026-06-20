"""
Unit tests for candidate_dataset_builder pure helpers.

Run from the module folder:
    python -m unittest discover -s tests
or:
    python tests/test_builder.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import candidate_dataset_builder as cdb  # noqa: E402
import numpy as np  # noqa: E402
import cv2  # noqa: E402


class TestNormalization(unittest.TestCase):
    def test_event_json_normalization_basic(self):
        raw = {"region_id": 7, "first_seen_seconds": 1.0,
               "became_persistent_seconds": 3.0, "last_seen_seconds": 9.0,
               "stationary_duration_seconds": 6.0, "state": "persistent",
               "occlusion_count": 2, "last_bbox": {"x": 10, "y": 20, "width": 5, "height": 4}}
        ev = cdb.normalize_event(raw, "v.mp4", 0)
        self.assertEqual(ev["candidate_id"], 7)
        self.assertEqual(ev["bbox"], (10, 20, 5, 4))
        self.assertEqual(ev["persistent_time_seconds"], 3.0)
        self.assertEqual(ev["occlusion_count"], 2)
        self.assertEqual(ev["warnings"], [])

    def test_normalization_id_variations(self):
        for key in ("candidate_id", "track_id", "id"):
            ev = cdb.normalize_event({key: 42, "last_bbox": [1, 2, 3, 4]}, "v", 0)
            self.assertEqual(ev["candidate_id"], 42)

    def test_normalization_missing_fields_fallbacks(self):
        ev = cdb.normalize_event({"last_bbox": [1, 2, 3, 4]}, "v", 4)
        self.assertEqual(ev["candidate_id"], 5)          # index+1
        self.assertEqual(ev["first_seen_seconds"], 0.0)
        self.assertEqual(ev["persistent_time_fallback"], "first_seen")
        self.assertTrue(any("missing id" in w for w in ev["warnings"]))
        self.assertIn("raw_event", ev)                   # raw preserved


class TestBBox(unittest.TestCase):
    def test_bbox_format_conversion(self):
        self.assertEqual(cdb.parse_bbox({"x": 1, "y": 2, "width": 3, "height": 4}), (1, 2, 3, 4))
        self.assertEqual(cdb.parse_bbox({"x": 1, "y": 2, "w": 3, "h": 4}), (1, 2, 3, 4))
        self.assertEqual(cdb.parse_bbox({"x1": 1, "y1": 2, "x2": 6, "y2": 9}), (1, 2, 5, 7))
        self.assertEqual(cdb.parse_bbox([1, 2, 3, 4]), (1, 2, 3, 4))

    def test_invalid_bbox(self):
        with self.assertRaises(ValueError):
            cdb.parse_bbox({"x": 1, "y": 2})
        with self.assertRaises(ValueError):
            cdb.parse_bbox([1, 2, 0, 4])   # non-positive size
        with self.assertRaises(ValueError):
            cdb.parse_bbox("nope")

    def test_invalid_bbox_in_normalization_is_recorded(self):
        ev = cdb.normalize_event({"region_id": 1, "last_bbox": {"x": 1, "y": 2}}, "v", 0)
        self.assertIsNone(ev["bbox"])
        self.assertIsNotNone(ev["bbox_error"])


class TestScaling(unittest.TestCase):
    def test_event_to_source_scaling(self):
        # 960x540 event coords -> 1920x1080 source (x2)
        self.assertEqual(cdb.scale_bbox((95, 270, 11, 3), 2.0, 2.0), (190, 540, 22, 6))

    def test_area(self):
        self.assertEqual(cdb.bbox_area((0, 0, 10, 4)), 40)


class TestContextRect(unittest.TestCase):
    def test_minimum_context_size(self):
        rect = cdb.build_context_rect((100, 100, 4, 4), padding=0,
                                      min_size=160, frame_w=1920, frame_h=1080)
        self.assertGreaterEqual(rect[2], 160)
        self.assertGreaterEqual(rect[3], 160)

    def test_context_rect_clipping_to_frame(self):
        # near the corner -> must stay inside frame
        rect = cdb.build_context_rect((0, 0, 4, 4), padding=80,
                                      min_size=160, frame_w=320, frame_h=240)
        x, y, w, h = rect
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 320)
        self.assertLessEqual(y + h, 240)

    def test_clip_rect(self):
        self.assertEqual(cdb.clip_rect((-5, -5, 20, 20), 10, 10), (0, 0, 10, 10))
        self.assertEqual(cdb.clip_rect((100, 100, 5, 5), 50, 50), (50, 50, 0, 0))


class TestCropAndTime(unittest.TestCase):
    def test_crop_padding(self):
        rect = cdb.build_crop_rect((50, 50, 10, 10), crop_padding=12,
                                   frame_w=1000, frame_h=1000)
        self.assertEqual(rect, (38, 38, 34, 34))

    def test_crop_padding_clipped(self):
        rect = cdb.build_crop_rect((2, 2, 4, 4), crop_padding=12,
                                   frame_w=1000, frame_h=1000)
        self.assertEqual(rect[0], 0)
        self.assertEqual(rect[1], 0)

    def test_time_to_frame_conversion(self):
        self.assertEqual(cdb.time_to_frame(2.0, 30.0), 60)
        self.assertEqual(cdb.time_to_frame(0.0, 30.0), 0)
        self.assertEqual(cdb.time_to_frame(1.0, 0), 30)      # invalid fps -> 30 fallback


class TestSelection(unittest.TestCase):
    def _events(self):
        return [
            cdb.normalize_event({"region_id": 1, "state": "persistent",
                "first_seen_seconds": 0.0, "became_persistent_seconds": 5.0,
                "stationary_duration_seconds": 10.0, "last_bbox": [1, 1, 2, 2]}, "v", 0),
            cdb.normalize_event({"region_id": 2, "state": "cooldown_wait",
                "first_seen_seconds": 1.0, "became_persistent_seconds": 2.0,
                "stationary_duration_seconds": 1.0, "last_bbox": [3, 3, 2, 2]}, "v", 1),
        ]

    def test_state_filter_and_sort(self):
        evs = self._events()
        sel, sk = cdb.select_candidates(evs, state_filter=["persistent"])
        self.assertEqual([e["candidate_id"] for e in sel], [1])

    def test_min_stationary(self):
        evs = self._events()
        sel, sk = cdb.select_candidates(evs, min_stationary_seconds=5.0)
        self.assertEqual([e["candidate_id"] for e in sel], [1])

    def test_empty_event_list(self):
        sel, sk = cdb.select_candidates([])
        self.assertEqual(sel, [])
        self.assertEqual(sk, [])

    def test_find_event_list_missing(self):
        with self.assertRaises(ValueError):
            cdb.find_event_list({"summary_counts": {}})


class TestDuplicates(unittest.TestCase):
    def test_duplicate_group_detection(self):
        evs = [
            cdb.normalize_event({"region_id": 1, "first_seen_seconds": 0.0,
                "last_seen_seconds": 10.0, "stationary_duration_seconds": 8.0,
                "became_persistent_seconds": 1.0, "last_bbox": [100, 100, 4, 4]}, "v", 0),
            cdb.normalize_event({"region_id": 2, "first_seen_seconds": 1.0,
                "last_seen_seconds": 9.0, "stationary_duration_seconds": 3.0,
                "became_persistent_seconds": 2.0, "last_bbox": [105, 102, 4, 4]}, "v", 1),
            cdb.normalize_event({"region_id": 3, "first_seen_seconds": 0.0,
                "last_seen_seconds": 10.0, "stationary_duration_seconds": 5.0,
                "became_persistent_seconds": 1.0, "last_bbox": [900, 700, 4, 4]}, "v", 2),
        ]
        cdb.group_duplicates(evs, center_distance=20.0, time_overlap_seconds=5.0)
        g1 = evs[0]["duplicate_group_id"]
        self.assertEqual(g1, evs[1]["duplicate_group_id"])     # 1 & 2 grouped
        self.assertNotEqual(g1, evs[2]["duplicate_group_id"])  # 3 separate
        self.assertTrue(evs[0]["duplicate_is_primary"])        # longest stationary
        self.assertFalse(evs[1]["duplicate_is_primary"])


class TestReviewMerge(unittest.TestCase):
    def test_review_results_merge_legacy(self):
        doc = {"results": [
            {"candidate_id": "1", "label": "litter", "notes": "tiny"},
            {"candidate_id": "99", "label": "litter"},          # unknown id
            {"candidate_id": "1", "label": "cigarette_butt"},   # duplicate
        ]}
        merged, unknown, dups, migr, invalid = cdb.merge_review_results(doc, valid_ids=[1, 2])
        # last wins; legacy 'cigarette_butt' is already valid semantic
        self.assertEqual(merged["1"]["semantic_label"], "cigarette_butt")
        self.assertEqual(merged["1"]["sample_quality"], "unreviewed")  # legacy default
        self.assertEqual(merged["1"]["reviewer_confidence"], "unset")
        self.assertIn("99", unknown)
        self.assertIn("1", dups)

    def test_legacy_label_migration(self):
        merged, _, _, migr, _ = cdb.merge_review_results(
            [{"region_id": 2, "label": "uncertain"}], [2])
        self.assertEqual(merged["2"]["semantic_label"], "unknown")  # uncertain->unknown
        self.assertTrue(migr)
        merged2, _, _, _, _ = cdb.merge_review_results({"2": {"label": "not_litter"}}, [2])
        self.assertEqual(merged2["2"]["raw_review_label"], "not_litter")  # preserved
        self.assertEqual(merged2["2"]["semantic_label"], "unknown")

    def test_review_schema_2_import(self):
        doc = {"label_schema_version": "2.0", "results": [
            {"candidate_id": "1", "semantic_label": "cigarette_butt",
             "sample_quality": "bbox_too_large", "confidence": "high", "notes": "n"},
            {"candidate_id": "2", "semantic_label": "not_a_real_label",
             "sample_quality": "bogus", "confidence": "nope"},
        ]}
        merged, unknown, dups, migr, invalid = cdb.merge_review_results(doc, [1, 2])
        self.assertEqual(merged["1"]["semantic_label"], "cigarette_butt")
        self.assertEqual(merged["1"]["sample_quality"], "bbox_too_large")
        self.assertEqual(merged["1"]["reviewer_confidence"], "high")
        self.assertEqual(merged["2"]["semantic_label"], "unknown")   # invalid->unknown
        self.assertEqual(merged["2"]["sample_quality"], "unreviewed")
        self.assertEqual(merged["2"]["reviewer_confidence"], "unset")
        self.assertTrue(invalid)


class TestSemanticAndQuality(unittest.TestCase):
    def test_semantic_label_validation(self):
        self.assertEqual(cdb.normalize_semantic_label("cigarette_butt"), ("cigarette_butt", None))
        self.assertEqual(cdb.normalize_semantic_label("litter")[0], "other_litter")
        self.assertEqual(cdb.normalize_semantic_label("uncertain")[0], "unknown")
        self.assertEqual(cdb.normalize_semantic_label("not_litter")[0], "unknown")
        self.assertIsNotNone(cdb.normalize_semantic_label("not_litter")[1])  # warns

    def test_sample_quality_validation(self):
        self.assertEqual(cdb.validate_quality("good"), "good")
        self.assertIsNone(cdb.validate_quality("bogus"))
        self.assertEqual(cdb.validate_confidence("low"), "low")
        self.assertIsNone(cdb.validate_confidence("nope"))


class TestModelCrop(unittest.TestCase):
    def test_square_crop_generation(self):
        sq = cdb.build_model_square((100, 100, 4, 4), padding=24, min_region=48,
                                    frame_w=1920, frame_h=1080)
        fx, fy, w, h = sq["full_square"]
        self.assertEqual(w, h)                       # square
        self.assertGreaterEqual(w, 48)               # min region

    def test_boundary_padding(self):
        # candidate at the corner -> square extends outside -> recorded padding
        sq = cdb.build_model_square((0, 0, 4, 4), padding=24, min_region=48,
                                    frame_w=1920, frame_h=1080)
        pl, pt, pr, pb = sq["pads"]
        self.assertGreater(pl + pt, 0)               # padded on the top-left
        img = cdb.extract_square_image(np.full((1080, 1920, 3), 7, np.uint8),
                                       sq, 64, cv2.INTER_AREA)
        self.assertEqual(img.shape, (64, 64, 3))

    def test_shared_crop_alignment(self):
        frame = np.zeros((200, 200, 3), np.uint8)
        sq = cdb.build_model_square((90, 90, 20, 20), 10, 40, 200, 200)
        a = cdb.extract_square_image(frame, sq, 64, cv2.INTER_AREA)
        b = cdb.extract_square_image(frame, sq, 64, cv2.INTER_AREA)
        self.assertEqual(a.shape, b.shape)           # identical geometry
        bm = cdb.bbox_in_square_coords((90, 90, 20, 20), sq, 64)
        cx = bm[0] + bm[2] / 2.0
        self.assertTrue(0 <= cx <= 64)

    def test_mask_nearest_resize_binary(self):
        mask_full = np.zeros((200, 200), np.uint8)
        cv2.rectangle(mask_full, (90, 90), (110, 110), 255, -1)
        sq = cdb.build_model_square((90, 90, 20, 20), 10, 40, 200, 200)
        m, src, warns = cdb.candidate_mask_square(mask_full, (90, 90, 20, 20), sq, 64)
        self.assertEqual(src, "detector_mask_crop")
        self.assertTrue(set(np.unique(m).tolist()) <= {0, 255})  # binary

    def test_mask_source_fallback(self):
        sq = cdb.build_model_square((90, 90, 20, 20), 10, 40, 200, 200)
        m, src, warns = cdb.candidate_mask_square(None, (90, 90, 20, 20), sq, 64)
        self.assertEqual(src, "bbox_fallback")
        self.assertTrue(warns)
        self.assertGreater(int(np.count_nonzero(m)), 0)          # filled bbox

    def test_difference_modes(self):
        ref = np.full((8, 8, 3), 100, np.uint8)
        cur = np.full((8, 8, 3), 130, np.uint8)
        d1, i1 = cdb.make_difference(ref, cur, "abs_rgb")
        self.assertEqual(int(d1[0, 0, 0]), 30)
        d2, _ = cdb.make_difference(ref, cur, "abs_gray")
        self.assertEqual(d2.shape, (8, 8, 3))
        d3, _ = cdb.make_difference(ref, cur, "signed_centered")
        self.assertEqual(int(d3[0, 0, 0]), 158)                  # 128 + 30

    def test_alignment_validation(self):
        size = 64
        ok_img = np.zeros((size, size, 3), np.uint8)
        mask = np.zeros((size, size), np.uint8)
        ok, warns = cdb.validate_alignment(ok_img, ok_img, ok_img, mask, (10, 10, 8, 8), size)
        self.assertTrue(ok)
        bad_mask = np.full((size, size), 100, np.uint8)          # not binary
        ok2, warns2 = cdb.validate_alignment(ok_img, ok_img, ok_img, bad_mask, (10, 10, 8, 8), size)
        self.assertFalse(ok2)
        # bbox center outside crop
        ok3, _ = cdb.validate_alignment(ok_img, ok_img, ok_img, mask, (200, 200, 8, 8), size)
        self.assertFalse(ok3)


class TestTrainingAndGrouping(unittest.TestCase):
    def test_usable_for_training(self):
        u, reasons = cdb.compute_usable_for_training(
            {"semantic_label": "cigarette_butt", "sample_quality": "good"}, None, False)
        self.assertTrue(u)
        u2, r2 = cdb.compute_usable_for_training(
            {"semantic_label": "unreviewed", "sample_quality": "unreviewed"}, None, False)
        self.assertFalse(u2)
        u3, r3 = cdb.compute_usable_for_training(
            {"semantic_label": "cigarette_butt", "sample_quality": "bbox_too_large"}, None, True)
        self.assertFalse(u3)                                     # excluded poor quality

    def test_camera_source_grouping(self):
        self.assertEqual(cdb.infer_camera_id("E05_024.mp4"), ("E05", "inferred"))
        self.assertEqual(cdb.infer_camera_id("randomclip.mp4")[0], "unknown")

    def test_background_non_overlap(self):
        self.assertTrue(cdb.boxes_overlap((0, 0, 10, 10), (5, 5, 10, 10)))
        self.assertFalse(cdb.boxes_overlap((0, 0, 10, 10), (100, 100, 10, 10)))
        self.assertTrue(cdb.boxes_overlap((0, 0, 10, 10), (12, 0, 10, 10), margin=5))

    def test_deterministic_seed(self):
        import numpy as _np
        a = _np.random.default_rng(42).integers(0, 1000, 5).tolist()
        b = _np.random.default_rng(42).integers(0, 1000, 5).tolist()
        self.assertEqual(a, b)


class TestManifest(unittest.TestCase):
    def test_manifest_creation(self):
        meta = {
            "candidate_id": 3, "source_video_filename": "v.mp4", "event_state": "persistent",
            "first_seen_seconds": 0.0, "persistent_time_seconds": 5.0, "last_seen_seconds": 9.0,
            "stationary_duration_seconds": 8.0, "bbox_source_coordinates": [1, 2, 4, 4],
            "occlusion_count": 0, "label": "unreviewed", "reviewer_notes": "",
        }
        tmp = tempfile.mkdtemp()
        paths = {"output": tmp,
                 "manifest_json": os.path.join(tmp, "manifest.json"),
                 "manifest_csv": os.path.join(tmp, "manifest.csv")}
        folder = os.path.join(tmp, "candidates", "candidate_0001")
        os.makedirs(folder, exist_ok=True)
        row = cdb.build_manifest_row(meta, folder, paths)
        cdb.write_manifests(paths, [row], cdb.Logger(False))
        self.assertTrue(os.path.isfile(paths["manifest_json"]))
        self.assertTrue(os.path.isfile(paths["manifest_csv"]))
        with open(paths["manifest_csv"], "rb") as fh:
            head = fh.read(3)
        self.assertEqual(head, b"\xef\xbb\xbf")   # UTF-8 BOM for Excel
        with open(paths["manifest_json"], encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["candidate_id"], 3)
        self.assertEqual(data[0]["area_pixels"], 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)

import os
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import ocr_paddle
from backend import server


def _make_test_image() -> str:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    Image.new("RGB", (240, 120), "white").save(path, format="PNG")
    return path


def _fake_paddle_result():
    tree = ocr_paddle.build_tree_from_boxes(
        [
            {
                "text": "HELLO TEST",
                "confidence": 0.95,
                "bbox": (20.0, 30.0, 160.0, 60.0),
                "angle_deg": 0.0,
            }
        ],
        240,
        120,
    )
    return {
        "engine": "paddleocr",
        "originalTextFull": "HELLO TEST",
        "originalTree": tree,
        "meta": {"engine": "paddleocr", "boxes": 1, "paragraphs": 1},
    }


class PaddleAdapterTests(unittest.TestCase):
    def test_normalize_old_style_output(self):
        raw = [[
            [[[10, 20], [110, 20], [110, 50], [10, 50]], ("HELLO", 0.94)],
            [[[12, 70], [90, 70], [90, 98], [12, 98]], ("WORLD", 0.88)],
        ]]

        boxes = ocr_paddle.normalize_paddle_output(raw)

        self.assertEqual([b["text"] for b in boxes], ["HELLO", "WORLD"])
        self.assertAlmostEqual(boxes[0]["confidence"], 0.94)
        self.assertEqual(boxes[0]["bbox"], (10.0, 20.0, 110.0, 50.0))

    def test_normalize_dict_style_output(self):
        raw = {
            "rec_texts": ["A", "B"],
            "rec_scores": [0.9, 0.8],
            "rec_boxes": [[1, 2, 30, 12], [40, 3, 80, 15]],
        }

        boxes = ocr_paddle.normalize_paddle_output(raw)

        self.assertEqual([b["text"] for b in boxes], ["A", "B"])
        self.assertEqual(boxes[1]["bbox"], (40.0, 3.0, 80.0, 15.0))

    def test_build_tree_from_boxes_has_required_geometry(self):
        boxes = [
            {"text": "HELLO", "confidence": 0.9, "bbox": (10.0, 20.0, 110.0, 50.0), "angle_deg": 0.0},
            {"text": "WORLD", "confidence": 0.9, "bbox": (12.0, 70.0, 120.0, 100.0), "angle_deg": 0.0},
        ]

        tree = ocr_paddle.build_tree_from_boxes(boxes, 200, 200)

        self.assertEqual(tree["side"], "original")
        self.assertEqual(len(tree["paragraphs"]), 1)
        para = tree["paragraphs"][0]
        self.assertEqual(para["text"], "HELLO\nWORLD")
        self.assertEqual(len(para["items"]), 2)
        item = para["items"][0]
        self.assertIn("box", item)
        self.assertIn("bounds_px", item)
        self.assertEqual(len(item["spans"]), 1)
        self.assertAlmostEqual(item["box"]["left"], 0.05)
        self.assertAlmostEqual(item["box"]["top"], 0.10)

    def test_filter_boxes_drops_low_confidence_and_invalid_geometry(self):
        boxes = [
            {"text": "LOW", "confidence": 0.1, "bbox": (10.0, 10.0, 40.0, 20.0), "angle_deg": 0.0},
            {"text": "TINY", "confidence": 0.9, "bbox": (10.0, 10.0, 11.0, 11.0), "angle_deg": 0.0},
            {"text": "OK", "confidence": 0.9, "bbox": (-5.0, -5.0, 50.0, 30.0), "angle_deg": 0.0},
        ]

        filtered = ocr_paddle._filter_boxes(boxes, 100, 100, 0.35)

        self.assertEqual([b["text"] for b in filtered], ["OK"])
        self.assertEqual(filtered[0]["bbox"], (0, 0, 50.0, 30.0))

    def test_empty_output_builds_empty_tree(self):
        tree = ocr_paddle.build_tree_from_boxes([], 100, 100)

        self.assertEqual(tree, {"side": "original", "paragraphs": []})

    def test_reading_order_sorts_by_line_then_left(self):
        boxes = [
            {"text": "B", "confidence": 0.9, "bbox": (60.0, 10.0, 90.0, 30.0), "angle_deg": 0.0},
            {"text": "A", "confidence": 0.9, "bbox": (10.0, 10.0, 40.0, 30.0), "angle_deg": 0.0},
            {"text": "C", "confidence": 0.9, "bbox": (10.0, 60.0, 40.0, 80.0), "angle_deg": 0.0},
        ]

        tree = ocr_paddle.build_tree_from_boxes(boxes, 100, 100)

        items = [
            item
            for para in tree["paragraphs"]
            for item in para["items"]
        ]
        self.assertEqual([item["text"] for item in items], ["A B", "C"])

    def test_run_paddle_ocr_resizes_and_scales_boxes_back(self):
        class FakeOcr:
            def __init__(self):
                self.paths = []

            def predict(self, path):
                self.paths.append(path)
                return {
                    "rec_texts": ["SCALED"],
                    "rec_scores": [0.99],
                    "rec_boxes": [[10, 20, 50, 40]],
                }

        image_path = _make_test_image()
        fake = FakeOcr()
        old_max_side = os.environ.get("TP_PADDLEOCR_MAX_SIDE")
        try:
            os.environ["TP_PADDLEOCR_MAX_SIDE"] = "120"
            with mock.patch.object(ocr_paddle, "_get_ocr", return_value=fake):
                out = ocr_paddle.run_paddle_ocr(image_path, "en", 240, 120)

            self.assertEqual(out.get("originalTextFull"), "SCALED")
            self.assertTrue(out.get("meta", {}).get("resize", {}).get("resized"))
            self.assertEqual(out.get("meta", {}).get("resize", {}).get("ocr_size"), [120, 60])
            item = out["originalTree"]["paragraphs"][0]["items"][0]
            self.assertEqual(item["bounds_px"], (20.0, 40.0, 100.0, 80.0))
            self.assertNotEqual(fake.paths[0], image_path)
            self.assertFalse(os.path.exists(fake.paths[0]))
        finally:
            if old_max_side is None:
                os.environ.pop("TP_PADDLEOCR_MAX_SIDE", None)
            else:
                os.environ["TP_PADDLEOCR_MAX_SIDE"] = old_max_side
            try:
                os.unlink(image_path)
            except OSError:
                pass

    def test_cache_key_includes_ocr_engine(self):
        a = server._build_cache_key("hash", "en", "lens_text", "text", None, "google_lens")
        b = server._build_cache_key("hash", "en", "lens_text", "text", None, "paddleocr")

        self.assertNotEqual(a, b)
        self.assertIn("google_lens", a)
        self.assertIn("paddleocr", b)

    def test_process_image_path_paddleocr_does_not_call_google_lens(self):
        image_path = _make_test_image()
        try:
            with mock.patch.object(server.core, "get_lens_data_from_image", side_effect=AssertionError("lens called")), \
                    mock.patch.object(ocr_paddle, "run_paddle_ocr", return_value=_fake_paddle_result()):
                out = server.process_image_path(image_path, "en", "lens_text", None, "paddleocr")

            self.assertEqual(out.get("ocrEngine"), "paddleocr")
            self.assertEqual(out.get("originalTextFull"), "HELLO TEST")
            self.assertEqual(
                out.get("original", {}).get("meta", {}).get("engine"),
                "paddleocr",
            )
        finally:
            try:
                os.unlink(image_path)
            except OSError:
                pass

    def test_process_image_path_default_uses_google_lens(self):
        image_path = _make_test_image()
        lens_data = {
            "imageUrl": None,
            "originalContentLanguage": "en",
            "originalTextFull": "",
            "translatedTextFull": "",
            "originalParagraphs": [],
            "translatedParagraphs": [],
        }
        try:
            with mock.patch.object(server.core, "get_lens_data_from_image", return_value=lens_data) as mocked_lens, \
                    mock.patch.object(ocr_paddle, "run_paddle_ocr", side_effect=AssertionError("paddle called")):
                out = server.process_image_path(image_path, "en", "lens_text", None)

            self.assertEqual(out.get("ocrEngine"), "google_lens")
            self.assertEqual(mocked_lens.call_count, 1)
        finally:
            try:
                os.unlink(image_path)
            except OSError:
                pass

    def test_paddleocr_ai_translation_patches_onto_original_tree(self):
        image_path = _make_test_image()
        ai_cfg = server.AiConfig(api_key="test", model="fake", provider="fake")
        try:
            with mock.patch.object(ocr_paddle, "run_paddle_ocr", return_value=_fake_paddle_result()), \
                    mock.patch.object(server, "ai_translate_text", return_value={"aiTextFull": "<<TP_P0>> สวัสดีทดสอบ"}), \
                    mock.patch.object(server.core, "DO_AI_HTML", False), \
                    mock.patch.object(server.core, "DO_ORIGINAL_HTML", False), \
                    mock.patch.object(server.core, "DO_TRANSLATED_HTML", False):
                out = server.process_image_path(image_path, "th", "lens_text", ai_cfg, "paddleocr")

            self.assertEqual(out.get("ocrEngine"), "paddleocr")
            self.assertIn("สวัสดี", out.get("AiTextFull") or "")
            ai_tree = out.get("Ai", {}).get("aiTree") or {}
            self.assertGreater(len(ai_tree.get("paragraphs") or []), 0)
            first = ai_tree["paragraphs"][0]["items"][0]
            self.assertAlmostEqual(first["box"]["left"], 20.0 / 240.0)
        finally:
            try:
                os.unlink(image_path)
            except OSError:
                pass

    def test_paddleocr_warmup_uses_adapter(self):
        with mock.patch.object(ocr_paddle, "warmup_paddle_ocr", return_value={"ready": True, "engine": "paddleocr"}) as mocked:
            result = server.asyncio.run(server.warmup("en", "paddleocr"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["ocrEngine"], "paddleocr")
        self.assertEqual(mocked.call_count, 1)


if __name__ == '__main__':
    unittest.main()

import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

try:
    from backend import server
except ModuleNotFoundError:
    import sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from backend import server


def _make_long_image(path: str) -> None:
    img = Image.new("RGB", (200, 1800), "white")
    img.save(path, format="JPEG")


class LongImageTests(unittest.TestCase):
    def test_process_image_path_splits_and_merges_without_real_ocr(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            image_path = f.name
        try:
            _make_long_image(image_path)

            def fake_single(tile_path, lang, mode, ai_cfg, ocr_engine="google_lens"):
                with Image.open(tile_path) as tile:
                    w, h = tile.size
                return {
                    "mode": mode,
                    "ocrEngine": ocr_engine,
                    "imageUrl": None,
                    "imageDataUri": "",
                    "originalTextFull": "hello",
                    "translatedTextFull": "",
                    "original": {
                        "meta": {
                            "engine": "paddleocr",
                            "raw_boxes": 1,
                            "boxes": 1,
                            "paragraphs": 1,
                            "avg_confidence": 0.9,
                            "lang": "en",
                            "min_confidence": 0.35,
                            "max_concurrency": 1,
                            "resize": {
                                "max_side": 0,
                                "resized": False,
                                "original_size": [w, h],
                                "ocr_size": [w, h],
                            },
                        },
                        "originalTree": {
                            "side": "original",
                            "paragraphs": [
                                {
                                    "side": "original",
                                    "para_index": 0,
                                    "start_raw": 0,
                                    "end_raw": 5,
                                    "text": "hello",
                                    "valid_text": True,
                                    "bounds_px": (10, 10, 100, 30),
                                    "items": [
                                        {
                                            "side": "original",
                                            "para_index": 0,
                                            "item_index": 0,
                                            "start_raw": 0,
                                            "end_raw": 5,
                                            "text": "hello",
                                            "valid_text": True,
                                            "height_raw": 20 / h,
                                            "baseline_p1": {"x": 10 / w, "y": 26 / h},
                                            "baseline_p2": {"x": 100 / w, "y": 26 / h},
                                            "box": {
                                                "left": 10 / w,
                                                "top": 10 / h,
                                                "width": 90 / w,
                                                "height": 20 / h,
                                                "rotation_deg": 0.0,
                                                "rotation_deg_css": 0.0,
                                                "center": {"x": 55 / w, "y": 20 / h},
                                            },
                                            "bounds_px": (10, 10, 100, 30),
                                            "spans": [],
                                        }
                                    ],
                                }
                            ],
                        },
                        "originalTextFull": "hello",
                    },
                    "translated": {"translatedTree": {"side": "translated", "paragraphs": []}},
                }

            with mock.patch.object(server, "TP_TILE_MAX_H", 700), mock.patch.object(
                server, "_process_image_path_single", side_effect=fake_single
            ) as mocked:
                out = server.process_image_path(
                    image_path, "th", "lens_text", None, "paddleocr"
                )

            self.assertGreater(mocked.call_count, 1)
            self.assertEqual(out.get("ocrEngine"), "paddleocr")
            self.assertTrue(str(out.get("imageDataUri") or "").startswith("data:image/"))
            paras = out.get("original", {}).get("originalTree", {}).get("paragraphs", [])
            self.assertGreaterEqual(len(paras), 1)
            ocr_meta = out.get("original", {}).get("meta", {})
            self.assertEqual(ocr_meta.get("engine"), "paddleocr")
            self.assertTrue(ocr_meta.get("split"))
            self.assertEqual(ocr_meta.get("tiles"), mocked.call_count)
            self.assertEqual(ocr_meta.get("raw_boxes"), mocked.call_count)
            self.assertEqual(ocr_meta.get("boxes"), mocked.call_count)
            self.assertIn("ocr", out.get("splitMeta", {}))
        finally:
            try:
                os.unlink(image_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()

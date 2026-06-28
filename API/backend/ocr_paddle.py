import math
import os
import sys
import tempfile
import threading
import importlib.util
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Tuple


_OCR_LOCK = threading.Lock()
_OCR_CACHE: Dict[Tuple[Any, ...], Any] = {}
_OCR_SEM_LOCK = threading.Lock()
_OCR_SEM_CACHE: Dict[int, threading.Semaphore] = {}


def _env_bool(name: str, default: bool = False) -> bool:
    v = str(os.environ.get(name, "")).strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(str(os.environ.get(name, str(default))).strip() or default)
    except Exception:
        return default


@contextmanager
def _ocr_slot():
    max_concurrency = max(1, _env_int("TP_PADDLEOCR_MAX_CONCURRENCY", 1))
    with _OCR_SEM_LOCK:
        sem = _OCR_SEM_CACHE.get(max_concurrency)
        if sem is None:
            sem = threading.Semaphore(max_concurrency)
            _OCR_SEM_CACHE[max_concurrency] = sem
    sem.acquire()
    try:
        yield max_concurrency
    finally:
        sem.release()


def _bbox_from_poly(poly: Iterable[Iterable[float]]) -> Optional[Tuple[float, float, float, float]]:
    pts = []
    for p in poly or []:
        try:
            pts.append((float(p[0]), float(p[1])))
        except Exception:
            continue
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _poly_from_box(box: Iterable[float]) -> Optional[List[Tuple[float, float]]]:
    try:
        left, top, right, bottom = [float(v) for v in list(box)[:4]]
    except Exception:
        return None
    return [(left, top), (right, top), (right, bottom), (left, bottom)]


def _angle_from_poly(poly: List[Tuple[float, float]]) -> float:
    if len(poly) < 2:
        return 0.0
    x1, y1 = poly[0]
    x2, y2 = poly[1]
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
    while angle <= -180.0:
        angle += 360.0
    while angle > 180.0:
        angle -= 360.0
    if angle < -90.0:
        angle += 180.0
    if angle > 90.0:
        angle -= 180.0
    return angle


def _as_poly(value: Any) -> Optional[List[Tuple[float, float]]]:
    if value is None:
        return None
    pts = []
    for p in value:
        try:
            pts.append((float(p[0]), float(p[1])))
        except Exception:
            continue
    return pts if len(pts) >= 4 else None


def normalize_paddle_output(raw: Any) -> List[Dict[str, Any]]:
    """Normalize common PaddleOCR result shapes into text/poly/conf records."""
    out: List[Dict[str, Any]] = []

    def first_present(d: Dict[str, Any], names: Iterable[str]) -> Any:
        for name in names:
            if name not in d:
                continue
            value = d.get(name)
            if value is None:
                continue
            try:
                if len(value) == 0:
                    continue
            except Exception:
                pass
            return value
        return []

    def has_items(value: Any) -> bool:
        try:
            return len(value) > 0
        except Exception:
            return False

    def is_poly_like(value: Any) -> bool:
        pts = _as_poly(value)
        return pts is not None

    def add_record(poly_value: Any, text_value: Any, score_value: Any = 1.0, box_value: Any = None) -> None:
        text = str(text_value or "").strip()
        if not text:
            return
        poly = _as_poly(poly_value)
        if poly is None and box_value is not None:
            poly = _poly_from_box(box_value)
        if poly is None:
            return
        bbox = _bbox_from_poly(poly)
        if bbox is None:
            return
        try:
            confidence = float(score_value)
        except Exception:
            confidence = 1.0
        out.append({
            "text": text,
            "confidence": confidence,
            "poly": poly,
            "bbox": bbox,
            "angle_deg": _angle_from_poly(poly),
        })

    def walk_dict(d: Dict[str, Any]) -> None:
        texts = first_present(d, ("rec_texts", "texts"))
        scores = first_present(d, ("rec_scores", "scores"))
        polys = first_present(d, ("rec_polys", "dt_polys", "polys"))
        boxes = first_present(d, ("rec_boxes", "boxes"))
        if has_items(texts) and (has_items(polys) or has_items(boxes)):
            n = len(texts)
            for i in range(n):
                add_record(
                    polys[i] if i < len(polys) else None,
                    texts[i],
                    scores[i] if i < len(scores) else 1.0,
                    boxes[i] if i < len(boxes) else None,
                )
            return
        for key in ("res", "result", "ocr_res", "data"):
            child = d.get(key)
            if child is not None:
                walk(child)

    def walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            walk_dict(value)
            return
        if not isinstance(value, (list, tuple)):
            return
        if (
            len(value) >= 2
            and is_poly_like(value[0])
            and isinstance(value[1], (list, tuple))
            and len(value[1]) >= 2
        ):
            add_record(value[0], value[1][0], value[1][1])
            return
        for item in value:
            walk(item)

    walk(raw)
    return out


def _filter_boxes(boxes: List[Dict[str, Any]], img_w: int, img_h: int, min_conf: float) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for b in boxes:
        try:
            left, top, right, bottom = b["bbox"]
            conf = float(b.get("confidence", 1.0))
        except Exception:
            continue
        if conf < min_conf:
            continue
        left = _clamp(left, 0, img_w)
        right = _clamp(right, 0, img_w)
        top = _clamp(top, 0, img_h)
        bottom = _clamp(bottom, 0, img_h)
        if right - left < 2 or bottom - top < 2:
            continue
        item = dict(b)
        item["bbox"] = (left, top, right, bottom)
        filtered.append(item)
    return filtered


def _scale_boxes(boxes: List[Dict[str, Any]], scale_x: float, scale_y: float) -> List[Dict[str, Any]]:
    if scale_x == 1.0 and scale_y == 1.0:
        return boxes
    out: List[Dict[str, Any]] = []
    for b in boxes:
        item = dict(b)
        try:
            left, top, right, bottom = item["bbox"]
            item["bbox"] = (left * scale_x, top * scale_y, right * scale_x, bottom * scale_y)
        except Exception:
            pass
        poly = []
        for p in item.get("poly") or []:
            try:
                poly.append((float(p[0]) * scale_x, float(p[1]) * scale_y))
            except Exception:
                continue
        if poly:
            item["poly"] = poly
            item["angle_deg"] = _angle_from_poly(poly)
        out.append(item)
    return out


def _prepare_ocr_image(image_path: str, img_w: int, img_h: int) -> Tuple[str, float, float, Optional[str], Dict[str, Any]]:
    max_side = max(0, _env_int("TP_PADDLEOCR_MAX_SIDE", 0))
    meta = {
        "max_side": max_side,
        "resized": False,
        "original_size": [img_w, img_h],
        "ocr_size": [img_w, img_h],
    }
    longest = max(int(img_w or 0), int(img_h or 0))
    if max_side <= 0 or longest <= max_side:
        return image_path, 1.0, 1.0, None, meta

    ratio = max_side / float(longest)
    new_w = max(1, int(round(img_w * ratio)))
    new_h = max(1, int(round(img_h * ratio)))
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow is required for TP_PADDLEOCR_MAX_SIDE image resizing") from e

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        with Image.open(image_path) as im:
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
            im.resize((new_w, new_h), resample).save(tmp_path, format="PNG")
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    meta.update({
        "resized": True,
        "ocr_size": [new_w, new_h],
    })
    return tmp_path, img_w / float(new_w), img_h / float(new_h), tmp_path, meta


def _line_groups(boxes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    sorted_boxes = sorted(boxes, key=lambda b: ((b["bbox"][1] + b["bbox"][3]) / 2.0, b["bbox"][0]))
    lines: List[List[Dict[str, Any]]] = []
    for b in sorted_boxes:
        left, top, right, bottom = b["bbox"]
        cy = (top + bottom) / 2.0
        h = max(1.0, bottom - top)
        placed = False
        for line in lines:
            centers = [((x["bbox"][1] + x["bbox"][3]) / 2.0) for x in line]
            heights = [max(1.0, x["bbox"][3] - x["bbox"][1]) for x in line]
            line_cy = sum(centers) / len(centers)
            line_h = sum(heights) / len(heights)
            if abs(cy - line_cy) <= max(h, line_h) * 0.55:
                line.append(b)
                placed = True
                break
        if not placed:
            lines.append([b])
    for line in lines:
        line.sort(key=lambda b: b["bbox"][0])
    lines.sort(key=lambda line: min(b["bbox"][1] for b in line))
    return lines


def _paragraph_groups(lines: List[List[Dict[str, Any]]]) -> List[List[List[Dict[str, Any]]]]:
    paras: List[List[List[Dict[str, Any]]]] = []
    prev_bbox = None
    for line in lines:
        left = min(b["bbox"][0] for b in line)
        top = min(b["bbox"][1] for b in line)
        right = max(b["bbox"][2] for b in line)
        bottom = max(b["bbox"][3] for b in line)
        h = max(1.0, bottom - top)
        if not paras or prev_bbox is None:
            paras.append([line])
        else:
            p_left, p_top, p_right, p_bottom = prev_bbox
            gap = top - p_bottom
            overlap = max(0.0, min(right, p_right) - max(left, p_left))
            min_width = max(1.0, min(right - left, p_right - p_left))
            if gap <= h * 0.95 and overlap / min_width >= 0.20:
                paras[-1].append(line)
            else:
                paras.append([line])
        prev_bbox = (left, top, right, bottom)
    return paras


def _box_node(left: float, top: float, right: float, bottom: float, img_w: int, img_h: int, angle: float = 0.0) -> Dict[str, Any]:
    w = max(1.0, right - left)
    h = max(1.0, bottom - top)
    node = {
        "left": left / img_w,
        "top": top / img_h,
        "width": w / img_w,
        "height": h / img_h,
        "rotation_deg": angle,
        "rotation_deg_css": angle,
        "center": {
            "x": (left + w / 2.0) / img_w,
            "y": (top + h / 2.0) / img_h,
        },
    }
    node["left_pct"] = node["left"] * 100.0
    node["top_pct"] = node["top"] * 100.0
    node["width_pct"] = node["width"] * 100.0
    node["height_pct"] = node["height"] * 100.0
    return node


def build_tree_from_boxes(boxes: List[Dict[str, Any]], img_w: int, img_h: int, side: str = "original") -> Dict[str, Any]:
    lines = _line_groups(boxes)
    paras = _paragraph_groups(lines)
    paragraphs: List[Dict[str, Any]] = []
    cursor = 0
    for para_index, para_lines in enumerate(paras):
        items = []
        para_text_parts = []
        para_bounds = None
        for item_index, line in enumerate(para_lines):
            left = min(b["bbox"][0] for b in line)
            top = min(b["bbox"][1] for b in line)
            right = max(b["bbox"][2] for b in line)
            bottom = max(b["bbox"][3] for b in line)
            text = " ".join(str(b.get("text") or "").strip() for b in line if str(b.get("text") or "").strip())
            if not text:
                continue
            start = cursor
            end = start + len(text)
            cursor = end + 2
            angle = sum(float(b.get("angle_deg") or 0.0) for b in line) / max(1, len(line))
            box = _box_node(left, top, right, bottom, img_w, img_h, angle)
            bounds = (left, top, right, bottom)
            baseline_y = (top + (bottom - top) * 0.80) / img_h
            span = {
                "side": side,
                "para_index": para_index,
                "item_index": item_index,
                "span_index": 0,
                "start_raw": start,
                "end_raw": end,
                "t0_raw": 0.0,
                "t1_raw": 1.0,
                "height_raw": (bottom - top) / img_h,
                "baseline_p1": {"x": left / img_w, "y": baseline_y},
                "baseline_p2": {"x": right / img_w, "y": baseline_y},
                "box": box,
                "text": text,
                "valid_text": True,
            }
            item = {
                "side": side,
                "para_index": para_index,
                "item_index": item_index,
                "start_raw": start,
                "end_raw": end,
                "text": text,
                "valid_text": True,
                "height_raw": (bottom - top) / img_h,
                "baseline_p1": span["baseline_p1"],
                "baseline_p2": span["baseline_p2"],
                "box": box,
                "bounds_px": bounds,
                "spans": [span],
            }
            items.append(item)
            para_text_parts.append(text)
            para_bounds = bounds if para_bounds is None else (
                min(para_bounds[0], left), min(para_bounds[1], top),
                max(para_bounds[2], right), max(para_bounds[3], bottom),
            )
        para_text = "\n".join(para_text_parts).strip()
        paragraphs.append({
            "side": side,
            "para_index": para_index,
            "start_raw": items[0]["start_raw"] if items else cursor,
            "end_raw": items[-1]["end_raw"] if items else cursor,
            "text": para_text,
            "valid_text": bool(para_text),
            "bounds_px": para_bounds,
            "items": items,
        })
    return {"side": side, "paragraphs": paragraphs}


def _ocr_lang(lang: str) -> str:
    forced = str(os.environ.get("TP_PADDLEOCR_LANG", "")).strip()
    if forced:
        return forced
    l = str(lang or "").strip().lower()
    if l in ("ja", "jp", "japan", "japanese"):
        return "japan"
    if l in ("ko", "kr", "korean"):
        return "korean"
    if l in ("zh", "zh-cn", "zh-tw", "ch", "chinese"):
        return "ch"
    return "en"


def _patch_paddlex_paddle_dep_check() -> None:
    if importlib.util.find_spec("paddle") is None:
        return
    try:
        import paddlex.utils.deps as deps

        old = deps.is_dep_available

        def is_dep_available(dep, /, check_version=False):
            if dep == "paddlepaddle":
                return True
            return old(dep, check_version=check_version)

        deps.is_dep_available = is_dep_available
    except Exception:
        pass
    try:
        import paddlex.inference.models.engines.paddle as paddle_engine

        old = paddle_engine.is_dep_available

        def is_dep_available(dep, /, check_version=False):
            if dep == "paddlepaddle":
                return True
            return old(dep, check_version=check_version)

        paddle_engine.is_dep_available = is_dep_available
    except Exception:
        pass


def _get_ocr(lang: str):
    ocr_lang = _ocr_lang(lang)
    use_gpu = _env_bool("TP_PADDLEOCR_USE_GPU", False)
    enable_mkldnn = _env_bool("TP_PADDLEOCR_ENABLE_MKLDNN", False)
    use_doc_orientation = _env_bool("TP_PADDLEOCR_USE_DOC_ORIENTATION", False)
    use_doc_unwarping = _env_bool("TP_PADDLEOCR_USE_DOC_UNWARPING", False)
    use_textline_orientation = _env_bool("TP_PADDLEOCR_USE_TEXTLINE_ORIENTATION", False)
    key = (ocr_lang, use_gpu, enable_mkldnn, use_doc_orientation, use_doc_unwarping, use_textline_orientation)
    with _OCR_LOCK:
        if key in _OCR_CACHE:
            return _OCR_CACHE[key]
        if not enable_mkldnn:
            os.environ.setdefault("FLAGS_use_onednn", "0")
            os.environ.setdefault("FLAGS_use_mkldnn", "0")
        local_path = str(os.environ.get("TP_PADDLEOCR_PATH", "")).strip()
        if not local_path:
            local_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "PaddleOCR"))
        if local_path and os.path.isdir(local_path) and local_path not in sys.path:
            sys.path.insert(0, local_path)
        try:
            _patch_paddlex_paddle_dep_check()
            from paddleocr import PaddleOCR
        except Exception as e:
            raise RuntimeError(
                "PaddleOCR is not installed. Install optional PaddleOCR dependencies or switch OCR engine to Google Lens."
            ) from e
        try:
            ocr = PaddleOCR(
                lang=ocr_lang,
                device="gpu" if use_gpu else "cpu",
                enable_mkldnn=enable_mkldnn,
                use_doc_orientation_classify=use_doc_orientation,
                use_doc_unwarping=use_doc_unwarping,
                use_textline_orientation=use_textline_orientation,
            )
        except TypeError:
            ocr = PaddleOCR(use_angle_cls=use_textline_orientation, lang=ocr_lang, use_gpu=use_gpu)
        _OCR_CACHE[key] = ocr
        return ocr


def run_paddle_ocr(image_path: str, lang: str, img_w: int, img_h: int) -> Dict[str, Any]:
    if not _env_bool("TP_PADDLEOCR_ENABLED", True):
        raise RuntimeError("PaddleOCR is disabled by TP_PADDLEOCR_ENABLED")
    ocr = _get_ocr(lang)
    ocr_path, scale_x, scale_y, tmp_path, resize_meta = _prepare_ocr_image(image_path, img_w, img_h)
    max_concurrency = 1
    try:
        with _ocr_slot() as max_concurrency:
            if hasattr(ocr, "predict"):
                raw = ocr.predict(ocr_path)
            else:
                try:
                    raw = ocr.ocr(ocr_path, cls=True)
                except TypeError:
                    raw = ocr.ocr(ocr_path)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    boxes0 = normalize_paddle_output(raw)
    boxes0 = _scale_boxes(boxes0, scale_x, scale_y)
    min_conf = float(os.environ.get("TP_PADDLEOCR_MIN_CONF", "0.35"))
    boxes = _filter_boxes(boxes0, img_w, img_h, min_conf)
    tree = build_tree_from_boxes(boxes, img_w, img_h, "original")
    texts = [str(p.get("text") or "").strip() for p in tree.get("paragraphs") or []]
    texts = [t for t in texts if t]
    avg_conf = sum(float(b.get("confidence") or 0.0) for b in boxes) / len(boxes) if boxes else 0.0
    return {
        "engine": "paddleocr",
        "originalTextFull": "\n\n".join(texts),
        "originalTree": tree,
        "meta": {
            "engine": "paddleocr",
            "raw_boxes": len(boxes0),
            "boxes": len(boxes),
            "paragraphs": len(tree.get("paragraphs") or []),
            "avg_confidence": round(avg_conf, 4),
            "lang": _ocr_lang(lang),
            "min_confidence": min_conf,
            "max_concurrency": max_concurrency,
            "resize": resize_meta,
        },
    }


def warmup_paddle_ocr(lang: str) -> Dict[str, Any]:
    if not _env_bool("TP_PADDLEOCR_ENABLED", True):
        raise RuntimeError("PaddleOCR is disabled by TP_PADDLEOCR_ENABLED")
    ocr = _get_ocr(lang)
    return {
        "engine": "paddleocr",
        "lang": _ocr_lang(lang),
        "ready": True,
        "class": ocr.__class__.__name__,
    }

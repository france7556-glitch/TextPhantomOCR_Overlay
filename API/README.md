---
title: TextPhantom OCR API
emoji: "🪄"
colorFrom: indigo
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

FastAPI backend for TextPhantom (Chrome extension).

## Endpoints

- `GET /health`
- `GET /version`
- `GET /warmup?lang=th`
- `GET /warmup?lang=th&ocr_engine=paddleocr`
- `POST /translate`
- `GET /translate/{job_id}`
- `POST /ai/resolve`
- `GET /ai/models`
- `POST /ws` (WebSocket)

## Environment

- `AI_API_KEY` (optional)
- `SERVER_MAX_WORKERS` (default: 15)
- `JOB_TTL_SEC` (default: 3600)
- `TP_DEBUG` (set to `1` to enable debug logs)
- `TP_OCR_ENGINE_DEFAULT` (default: `google_lens`)
- `TP_PADDLEOCR_ENABLED` (default: `1`, only used when `ocrEngine=paddleocr`)
- `TP_PADDLEOCR_LANG` (optional override, for example `en`, `ch`, `japan`, `korean`)
- `TP_PADDLEOCR_USE_GPU` (default: `0`)
- `TP_PADDLEOCR_ENABLE_MKLDNN` (default: `0`; keep disabled on Windows if PaddlePaddle hits oneDNN runtime errors)
- `TP_PADDLEOCR_USE_DOC_ORIENTATION` (default: `0`)
- `TP_PADDLEOCR_USE_DOC_UNWARPING` (default: `0`)
- `TP_PADDLEOCR_USE_TEXTLINE_ORIENTATION` (default: `0`)
- `TP_PADDLEOCR_MIN_CONF` (default: `0.35`)
- `TP_PADDLEOCR_MAX_CONCURRENCY` (default: `1`)
- `TP_PADDLEOCR_MAX_SIDE` (default: `0`, no resize before OCR)

For Spaces on small CPU, setting `SERVER_MAX_WORKERS=2` is usually enough.

## Optional PaddleOCR

Google Lens remains the default OCR engine. To enable local PaddleOCR as an opt-in engine, install the optional dependencies:

```bash
pip install -r requirements-paddleocr.txt
```

Then choose `PaddleOCR Local` in the extension OCR Engine selector while using text mode, or send `ocrEngine: "paddleocr"` in `/translate` payloads.

For very tall images, `TP_PADDLEOCR_MAX_SIDE=4000` is recommended so TextPhantom handles resize/coordinate scaling before PaddleOCR runs.

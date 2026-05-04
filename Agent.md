# ✨ TextPhantomOCR Overlay - Ultra-Detailed Agent Source of Truth

ไฟล์นี้ประกอบด้วยรายละเอียดเชิงลึกทั้งหมดของโปรเจค เพื่อให้ AI Agent สามารถเริ่มงานได้ทันทีโดยไม่ต้องถามซ้ำ
This is a comprehensive technical specification of the TextPhantomOCR Overlay project for AI agents.

---

## 📖 1. Project Context & Purpose
**TextPhantomOCR Overlay** is a high-performance image-to-image translation system for Chromium browsers. It doesn't just translate text; it attempts to **replace** text within the image while preserving the original layout, fonts, and background using OCR and AI-driven patching.

- **Primary Stack**: Vanilla JS (MV3 Extension), FastAPI (Python Backend), PIL (Image Processing), Google Lens (OCR Source).
- **Core Workflow**:
    1. **Trigger**: Right-click context menu -> `Translate`.
    2. **Capture**: Extension gets image URL or converts to Base64 (DataURI).
    3. **Request**: Extension sends payload to `POST /translate`.
    4. **Processing**: Backend splits large images, performs OCR, calls AI for translation, patches text back into OCR blocks, and generates overlay HTML/CSS.
    5. **Delivery**: Extension polls `GET /translate/{job_id}` or receives via WebSocket.
    6. **Rendering**: `content-service.js` injects a Viewer and overlays the translated content.

---

## 🏗️ 2. Detailed Architecture

### A. Frontend: Browser Extension (MV3)
- **`background-service.js` (The Brain)**: 
    - Manages job queues and concurrency (`MAX_CONCURRENCY`).
    - Handles "Batch" jobs (e.g., translating all images on a MangaDex page).
    - Communicates with the API via REST or WebSockets.
    - Categorizes errors via `classifyJobError()` for user-friendly toasts.
- **`content-service.js` (The Renderer)**: 
    - Injected into every page.
    - Detects images and manages the `Viewer` component.
    - Handles scrolling and resizing to keep overlays aligned.
- **`popup/`**: Manages user settings (API URL, AI Provider keys, Custom Prompts).

### B. Backend: FastAPI Server
- **`API/backend/server.py`**:
    - **Concurrency**: Uses a worker pool (`_worker_loop`) to handle multiple jobs.
    - **Image Splitting**: Images taller than `3000px` are split into tiles, processed individually, and merged.
    - **Caching**: Implements LRU cache for OCR (`_result_cache`) and AI results (`_ai_result_cache`) using SHA256 image hashes.
    - **AI Routing**: Supports OpenAI, Anthropic, Gemini, Hugging Face, and CLI-based tools.
- **`API/backend/lens_core.py`**:
    - Contains the logic for interacting with OCR providers.
    - **`patch()`**: The critical function that maps AI-translated text back into the coordinates of the original OCR paragraphs.
    - **Font Management**: Handles Thai and Latin font fitting for overlays.

---

## 📡 3. Communication Protocol (JSON API)

### Job Submission (`POST /translate`)
**Payload**:
```json
{
  "src": "image_url_or_datauri",
  "mode": "lens_images | lens_text",
  "lang": "th | ja | en | ...",
  "source": "translated | ai | cli_gemini | cli_codex",
  "ai": {
    "api_key": "...",
    "model": "...",
    "provider": "...",
    "prompt": "Custom system instruction"
  },
  "context": { "page_url": "..." }
}
```

### Job Result / Status (`GET /translate/{job_id}`)
**Response**:
```json
{
  "status": "done | running | error",
  "originalTextFull": "...",
  "AiTextFull": "...",
  "imageDataUri": "data:image/png;base64,...", // Background with text erased
  "Ai": {
    "aihtml": "<div class='tp-overlay'>...</div>", // Overlay Layer
    "aiTree": { ... OCR Tree Data ... }
  },
  "htmlCss": ".tp-overlay { ... }",
  "htmlMeta": { "baseW": 1200, "baseH": 1800 }
}
```

---

## 🧩 4. Key Logic & "Magic" Features
1. **Paragraph Markers (`<<TP_P{n}>>`)**: Used when sending text to AI to ensure the AI returns translations in a structured way that the backend can "re-patch" into the exact OCR coordinates.
2. **Text Erasure**: The backend can erase original text from the image using the OCR boxes, creating a clean "blank" image for the extension to overlay new text onto.
3. **MangaDex Special Handling**: Specific logic in `background-service.js` to handle the MangaDex image loading sequence and caching.
4. **Shared Font Fitting**: The backend calculates font sizes that fit all paragraphs consistently within their OCR bounding boxes.

---

## 🛠️ 5. Development Rules for AI Agents
- **Backward Compatibility**: Never break the JSON schema between `server.py` and `background-service.js`.
- **Latency First**: Always check for cache hits before triggering heavy OCR/AI processes.
- **Clean UI**: In `content-service.js`, ensure the overlay doesn't interfere with page interaction (use `pointer-events: none` where appropriate).
- **Error Transparency**: When an API error occurs, pass the full error string to `classifyJobError` so the user knows if it's a "Quota" issue vs "Network" issue.

---
*Last Updated: 2026-05-03*

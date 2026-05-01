import asyncio, base64, copy, hashlib, io, json, os, re, tempfile, time, uuid, httpx, logging

from backend import lens_core as core
from http import HTTPStatus
from collections import OrderedDict
from threading import Lock, Semaphore
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware

SERVER_MAX_WORKERS = int(os.environ.get('SERVER_MAX_WORKERS', '15'))
JOB_TTL_SEC = int(os.environ.get('JOB_TTL_SEC', '3600'))
HTTP_TIMEOUT_SEC = float(os.environ.get(
    'HTTP_TIMEOUT_SEC', str(getattr(core, 'AI_TIMEOUT_SEC', 120))))
SUPPORTED_MODES = {"lens_images", "lens_text"}
BUILD_ID = os.environ.get('TP_BUILD_ID', 'v9-backendfix-20260129')
TP_DEBUG = str(os.environ.get('TP_DEBUG', '')).strip(
).lower() in ('1', 'true', 'yes', 'on')
TP_TRACE = str(os.environ.get('TP_TRACE', '1')).strip(
).lower() in ('1', 'true', 'yes', 'on')

TP_PARA_MARKER_PREFIX = '<<TP_P'
TP_PARA_MARKER_SUFFIX = '>>'

TP_RESULT_CACHE_MAX = int(os.environ.get('TP_RESULT_CACHE_MAX', '24'))
TP_AI_RESULT_CACHE_MAX = int(os.environ.get('TP_AI_RESULT_CACHE_MAX', '16'))
TP_WARMUP_LANG = (os.environ.get('TP_WARMUP_LANG', 'th') or 'th').strip()

_result_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_ai_result_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_jobs: Dict[str, Dict[str, Any]] = {}
_job_queue: asyncio.Queue = asyncio.Queue()
_result_cache_lock = Lock()
_ai_cache_lock = Lock()

HF_AI_MAX_CONCURRENCY = max(
    1, int(os.environ.get('HF_AI_MAX_CONCURRENCY', '1')))
HF_AI_MIN_INTERVAL_SEC = max(0.0, float(
    os.environ.get('HF_AI_MIN_INTERVAL_SEC', '5')))
HF_AI_MAX_RETRIES = max(1, int(os.environ.get('HF_AI_MAX_RETRIES', '6')))
HF_AI_RETRY_BASE_SEC = max(0.2, float(
    os.environ.get('HF_AI_RETRY_BASE_SEC', '2')))
_hf_ai_sem = Semaphore(HF_AI_MAX_CONCURRENCY)
_hf_ai_lock = Lock()
_hf_ai_last_ts = 0.0
_tp_marker_re = re.compile(r'<<TP_P\d+>>')

TP_ACCESS_LOG_MODE = (os.environ.get('TP_ACCESS_LOG_MODE', 'custom') or 'custom').strip().lower()
if TP_ACCESS_LOG_MODE in ('custom', 'tp', 'plain'):
    try:
        _uv = logging.getLogger('uvicorn.access')
        _uv.disabled = True
        _uv.propagate = False
        _uv.setLevel(logging.CRITICAL)
    except Exception:
        pass

def _dbg(tag: str, data=None) -> None:
    if not TP_DEBUG:
        return
    try:
        if data is None:
            print(f'[TextPhantom][dbg] {tag}')
        else:
            s = json.dumps(data, ensure_ascii=False)
            if len(s) > 2000:
                s = s[:2000] + '…'
            print(f'[TextPhantom][dbg] {tag} {s}')
    except Exception:
        try:
            print(f'[TextPhantom][dbg] {tag} {data}')
        except Exception:
            pass

def _trace(tag: str, data=None) -> None:
    if not TP_TRACE:
        return
    try:
        if data is None:
            print(f'[TextPhantom][trace] {tag}', flush=True)
        else:
            s = json.dumps(data, ensure_ascii=False, default=str)
            if len(s) > 2000:
                s = s[:2000] + '...'
            print(f'[TextPhantom][trace] {tag} {s}', flush=True)
    except Exception:
        try:
            print(f'[TextPhantom][trace] {tag} {data}', flush=True)
        except Exception:
            pass

def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)

def _tree_stats(tree) -> dict:
    if not isinstance(tree, dict):
        return {'paras': 0, 'items': 0, 'spans': 0}
    paras = tree.get('paragraphs') or []
    if not isinstance(paras, list):
        return {'paras': 0, 'items': 0, 'spans': 0}
    items = 0
    spans = 0
    for p in paras:
        if not isinstance(p, dict):
            continue
        its = p.get('items') or []
        if not isinstance(its, list):
            continue
        items += len(its)
        for it in its:
            if not isinstance(it, dict):
                continue
            sp = it.get('spans') or []
            if isinstance(sp, list):
                spans += len(sp)
    return {'paras': len(paras), 'items': items, 'spans': spans}

def _tree_to_paragraph_texts(tree: Any) -> List[str]:
    if not isinstance(tree, dict):
        return []
    paras = tree.get('paragraphs') or []
    if not isinstance(paras, list) or not paras:
        return []
    out: List[str] = []
    for p in paras:
        if not isinstance(p, dict):
            out.append('')
            continue
        t = str(p.get('text') or '').strip()
        if not t:
            items = p.get('items') or []
            if isinstance(items, list) and items:
                t = ' '.join(str(it.get('text') or '').strip() for it in items if isinstance(
                    it, dict) and str(it.get('text') or '').strip())
        out.append(t)
    return out

def _apply_para_markers(paras: List[str]) -> str:
    if not paras:
        return ''
    parts: List[str] = []
    for i, t in enumerate(paras):
        parts.append(
            f"{TP_PARA_MARKER_PREFIX}{i}{TP_PARA_MARKER_SUFFIX}\n{(t or '').strip()}")
    return '\n\n'.join(parts)

def _clamp_runaway_repeats(s: str, max_repeat: int = 12) -> str:
    if not s:
        return ''
    pat = re.compile(r"(.)\1{" + str(max_repeat) + r",}")
    return pat.sub(lambda m: m.group(1) * max_repeat, s)

def _extract_marker_indices(s: str) -> set[int]:
    if not s:
        return set()
    out: set[int] = set()
    for m in re.finditer(r"<<TP_P(\d+)>>", s):
        try:
            out.add(int(m.group(1)))
        except Exception:
            continue
    return out

def _needs_ai_retry(ai_text_full: str, expected_paras: int) -> bool:
    if expected_paras <= 0:
        return False
    idx = _extract_marker_indices(ai_text_full)
    if len(idx) >= expected_paras:
        return False

    if (TP_PARA_MARKER_PREFIX in (ai_text_full or '')) and (TP_PARA_MARKER_SUFFIX not in (ai_text_full or '')):
        return True
    return True

def _marker_segment_map(ai_text_full: str, expected: int) -> Dict[int, str]:
    seg_map: Dict[int, str] = {}
    if expected <= 0 or not ai_text_full:
        return seg_map
    found = sorted(_extract_marker_indices(ai_text_full))
    for idx in found:
        if idx < 0 or idx >= expected:
            continue
        marker = f"{TP_PARA_MARKER_PREFIX}{idx}{TP_PARA_MARKER_SUFFIX}"
        m = re.search(rf"{re.escape(marker)}\s*([\s\S]*?)(?={re.escape(TP_PARA_MARKER_PREFIX)}\d+{re.escape(TP_PARA_MARKER_SUFFIX)}|\Z)", ai_text_full)
        seg = _collapse_ws(m.group(1) if m else '')
        if seg and idx not in seg_map:
            seg_map[idx] = seg
    return seg_map

def _repair_marked_ai_text(ai_text_full: str, expected: int, fallback_paras: List[str]) -> tuple[str, dict]:
    if expected <= 0:
        return ai_text_full or '', {
            'marker_repaired': False,
            'marker_expected': 0,
            'marker_found': 0,
            'marker_missing': 0,
        }
    seg_map = _marker_segment_map(ai_text_full, expected)
    missing = 0
    out_lines: List[str] = []
    for i in range(expected):
        seg = seg_map.get(i) or _collapse_ws(
            fallback_paras[i] if i < len(fallback_paras) else '')
        if not seg_map.get(i):
            missing += 1
        out_lines.append(f"{TP_PARA_MARKER_PREFIX}{i}{TP_PARA_MARKER_SUFFIX}")
        out_lines.append(seg)
        out_lines.append('')
    return "\n".join(out_lines).strip("\n"), {
        'marker_repaired': missing > 0,
        'marker_expected': expected,
        'marker_found': len(seg_map),
        'marker_missing': missing,
    }

def _now() -> float:
    return time.time()

def _lru_get(cache: OrderedDict, lock: Lock, key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    with lock:
        v = cache.get(key)
        if v is None:
            return None
        cache.move_to_end(key)
        return copy.deepcopy(v)

def _lru_set(cache: OrderedDict, lock: Lock, key: str, value: Dict[str, Any], max_items: int) -> None:
    if not key or not isinstance(value, dict) or max_items <= 0:
        return
    with lock:
        cache[key] = copy.deepcopy(value)
        cache.move_to_end(key)
        while len(cache) > max_items:
            cache.popitem(last=False)

def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest() if blob else ''

def _ai_prompt_sig(s: str) -> str:
    t = (s or '').strip()
    if not t:
        return ''
    return hashlib.sha256(t.encode('utf-8')).hexdigest()[:12]

def _build_cache_key(img_hash: str, lang: str, mode: str, source: str, ai_cfg: Optional["AiConfig"]) -> str:
    parts = [img_hash, _normalize_lang(
        lang), (mode or '').strip(), (source or '').strip()]
    if ai_cfg and (source or '').strip().lower() == 'ai':
        parts.extend([
            (ai_cfg.provider or '').strip(),
            (ai_cfg.model or '').strip(),
            (ai_cfg.base_url or '').strip(),
            _ai_prompt_sig(ai_cfg.prompt_editable),
        ])
    return '|'.join([p for p in parts if p is not None])

def _b64_to_bytes(b64: str) -> bytes:
    pad = '=' * ((4 - (len(b64) % 4)) % 4)
    return base64.b64decode(b64 + pad)

def _datauri_to_bytes(data_uri: str) -> tuple[bytes, str]:
    s = (data_uri or '').strip()
    if not s.startswith('data:'):
        return b'', ''
    head, _, b64 = s.partition(',')
    mime = ''
    if ';' in head:
        mime = head[5:head.index(';')]
    return _b64_to_bytes(b64), mime or 'application/octet-stream'

def _bytes_to_datauri(blob: bytes, mime: str) -> str:
    b64 = base64.b64encode(blob).decode('ascii')
    return f"data:{mime};base64,{b64}"

def _download_bytes(url: str, referer: str = '') -> tuple[bytes, str]:
    u = (url or '').strip()
    if not u:
        return b'', ''
    headers = {
        'user-agent': 'Mozilla/5.0 (TextPhantomOCR; +https://huggingface.co/spaces)',
    }
    ref = (referer or '').strip()
    if ref:
        headers['referer'] = ref

    with httpx.Client(timeout=HTTP_TIMEOUT_SEC, follow_redirects=True, headers=headers) as client:
        r = client.get(u)
        r.raise_for_status()
        ct = (r.headers.get('content-type') or '').split(';')[0].strip()
        return r.content, ct

def _detect_provider_from_key(api_key: str) -> str:
    return core._canonical_provider(core._detect_ai_provider_from_key(api_key))

def _resolve_provider_defaults(provider: str) -> dict:
    return (getattr(core, 'AI_PROVIDER_DEFAULTS', {}) or {}).get(provider, {})

def _resolve_model(provider: str, model: str) -> str:
    return core._resolve_model(provider, model)

def _has_meaningful_text(s: str) -> bool:
    t = _tp_marker_re.sub('', str(s or ''))
    return bool(t.strip())

def _is_hf_provider(provider: str, base_url: str) -> bool:
    p = (provider or '').strip().lower()
    b = (base_url or '').strip().lower()
    return p == 'huggingface' or 'router.huggingface.co' in b

def _is_hf_rate_limited_error(msg: str) -> bool:
    t = (msg or '').lower()
    if 'rate limit' in t or 'ratelimit' in t or 'too many requests' in t:
        return True
    if 'http 429' in t or ' 429' in t:
        return True
    if 'http 503' in t or ' 503' in t or 'overloaded' in t or 'temporarily' in t:
        return True
    return False

def _hf_throttle_before_call() -> None:
    if HF_AI_MIN_INTERVAL_SEC <= 0:
        return
    global _hf_ai_last_ts
    with _hf_ai_lock:
        now = _now()
        dt = now - float(_hf_ai_last_ts or 0.0)
        wait = HF_AI_MIN_INTERVAL_SEC - dt
        if wait > 0:
            time.sleep(wait)
        _hf_ai_last_ts = _now()

def _openai_compat_generate_with_hf_backoff(api_key: str, base_url: str, model: str, system_text: str, user_parts: List[str]):
    last_err: Optional[Exception] = None
    for attempt in range(int(HF_AI_MAX_RETRIES)):
        try:
            with _hf_ai_sem:
                _hf_throttle_before_call()
                return core._openai_compat_generate_json(api_key, base_url, model, system_text, user_parts)
        except Exception as e:
            last_err = e
            if not _is_hf_rate_limited_error(str(e)):
                raise
            delay = min(15.0, max(float(HF_AI_MIN_INTERVAL_SEC), float(
                HF_AI_RETRY_BASE_SEC) * (2 ** min(attempt, 4))))
            _dbg('ai.hf.backoff', {
                 'attempt': attempt + 1, 'delay_sec': round(delay, 2), 'err': str(e)[:240]})
            time.sleep(delay)
            continue
    if last_err is not None:
        raise last_err
    raise Exception('hf_backoff_failed')

def _normalize_lang(lang: str) -> str:
    return core._normalize_lang(lang)

@dataclass
class AiConfig:
    api_key: str
    model: str = 'auto'
    provider: str = 'auto'
    base_url: str = 'auto'
    prompt_editable: str = ''
    reasoning_effort: str = 'medium'

def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()

def _sanitize_marked_text(marked_text: str) -> str:
    t = str(marked_text or "")
    if not t:
        return ""
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<<TP_P(?!\d+>>)[^\s>]*>?", "", t)
    t = re.sub(r"(?m)^\s*(<<TP_P\d+>>)\s*(\S)", r"\1\n\2", t)

    lines = t.split("\n")
    out0: List[str] = []
    for line in lines:
        if "<<TP_P" not in line:
            out0.append(line)
            continue
        m = re.match(r"^\s*(<<TP_P\d+>>)\s*$", line)
        if m:
            out0.append(m.group(1))
            continue
        m2 = re.match(r"^\s*(<<TP_P\d+>>)\s*(.*)$", line)
        if m2:
            out0.append(m2.group(1))
            rest = (m2.group(2) or "").strip()
            if rest:
                out0.append(rest)
            continue
        out0.append(re.sub(r"<<TP_P\d+>>", "", line))
    t = "\n".join(out0)

    indices = sorted(_extract_marker_indices(t))
    if not indices:
        return _collapse_ws(t)
    out_lines: List[str] = []
    for idx in indices:
        marker = f"<<TP_P{idx}>>"
        m = re.search(
            rf"{re.escape(marker)}\s*([\s\S]*?)(?=<<TP_P\d+>>|\Z)", t)
        seg = m.group(1) if m else ""
        seg = _collapse_ws(seg)
        out_lines.append(marker)
        out_lines.append(seg)
        out_lines.append("")
    return "\n".join(out_lines).strip("\n")


def _has_complete_marker_sequence(ai_text_full: str, expected_paras: int) -> bool:
    if expected_paras <= 0:
        return True
    t = str(ai_text_full or "")
    need = list(range(int(expected_paras)))
    idx = sorted(_extract_marker_indices(t))
    if len(idx) < len(need):
        return False
    if idx[:len(need)] != need:
        return False
    last = -1
    for i in need:
        m = f"<<TP_P{i}>>"
        p = t.find(m)
        if p < 0 or p <= last:
            return False
        last = p
    return True

def _build_ai_prompt_packet_custom(target_lang: str, original_text_full: str, prompt_editable: str, is_retry: bool = False) -> tuple[str, List[str]]:
    lang = _normalize_lang(target_lang)

    base = (getattr(core, "AI_PROMPT_SYSTEM_BASE", "") or "").strip()

    style = (prompt_editable or "").strip()
    if not style:
        style = (
            (getattr(core, "AI_LANG_STYLE", {}) or {}).get(lang)
            or (getattr(core, "AI_LANG_STYLE", {}) or {}).get("default")
            or ""
        ).strip()

    contract_parts: List[str] = [
        "Output ONLY the translated text (no JSON, no markdown, no extra commentary).",
        "Markers: Keep every paragraph marker like <<TP_P0>> unchanged and in order. Do not remove, rename, or add markers.",
        "For each marker, output the marker followed by that paragraph's translated text.",
    ]
    if is_retry:
        contract_parts.append(
            "Retry: You MUST output ALL markers from the first to the last marker in the input."
        )

    system_text = "\n\n".join(
        [p for p in [base, style, "\n".join(contract_parts)] if p]
    )

    user_parts: List[str] = ["Input:\n" + str(original_text_full or "")]
    return system_text, user_parts

def ai_translate_text(original_text_full: str, target_lang: str, ai: AiConfig, is_retry: bool = False) -> dict:
    if not _has_meaningful_text(original_text_full):
        _trace('ai.skip.no_text', {
            'target_lang': target_lang,
            'provider': ai.provider if ai else '',
        })
        return {
            'aiTextFull': '',
            'meta': {
                'skipped': True,
                'skipped_reason': 'no_text',
            },
        }

    api_key = (ai.api_key or '').strip()
    if not api_key:
        raise Exception('AI api_key is required')

    provider = core._canonical_provider((ai.provider or 'auto'))
    if provider in ('', 'auto'):
        provider = _detect_provider_from_key(api_key)

    preset = _resolve_provider_defaults(provider) or {}

    model = _resolve_model(provider, (ai.model or 'auto'))

    base_url = (ai.base_url or 'auto').strip()
    if base_url in ('', 'auto'):
        base_url = (preset.get('base_url') or '').strip()

    if provider not in ('gemini', 'anthropic', 'cli_gemini', 'cli_codex'):
        if not base_url:
            base_url = (_resolve_provider_defaults('openai') or {}).get(
                'base_url') or 'https://api.openai.com/v1'

    system_text, user_parts = _build_ai_prompt_packet_custom(
        target_lang, original_text_full, ai.prompt_editable, is_retry=is_retry
    )

    started = _now()
    used_model = model
    _trace('ai.call.begin', {
        'provider': provider,
        'model': model,
        'base_url': base_url,
        'target_lang': target_lang,
        'is_retry': is_retry,
        'input_len': len(str(original_text_full or '')),
        'system_len': len(system_text),
        'user_parts': len(user_parts),
    })
    if provider == 'cli_gemini':
        raw = core._cli_gemini_generate_json(system_text, user_parts, model)
        used_model = model
    elif provider == 'cli_codex':
        raw = core._cli_codex_generate_json(system_text, user_parts, model, ai.reasoning_effort)
        used_model = model
    elif provider == 'gemini':
        raw = core._gemini_generate_json(
            api_key, model, system_text, user_parts)
    elif provider == 'anthropic':
        raw = core._anthropic_generate_json(
            api_key, model, system_text, user_parts)
    else:
        if _is_hf_provider(provider, base_url):
            raw, used_model = _openai_compat_generate_with_hf_backoff(
                api_key, base_url, model, system_text, user_parts)
        else:
            raw, used_model = core._openai_compat_generate_json(
                api_key, base_url, model, system_text, user_parts)

    ai_text_full = core._parse_ai_textfull_only(
        raw) if core.DO_AI_JSON else core._parse_ai_textfull_text_only(raw)

    ai_text_full = _sanitize_marked_text(ai_text_full)
    _trace('ai.call.done', {
        'provider': provider,
        'used_model': used_model,
        'raw_len': len(str(raw or '')),
        'ai_text_len': len(ai_text_full),
        'latency_sec': round(_now() - started, 3),
        'preview': ai_text_full[:160],
    })

    return {
        'aiTextFull': ai_text_full,
        'meta': {
            'model': used_model,
            'provider': provider,
            'base_url': base_url,
            'latency_sec': round(_now() - started, 3),
        },
    }

def _process_image_path_single(image_path: str, lang: str, mode: str, ai_cfg: Optional[AiConfig]) -> dict:
    t_total = time.perf_counter()
    mode_id = (mode or '').strip()
    if mode_id not in SUPPORTED_MODES:
        mode_id = 'lens_images'

    target_lang = _normalize_lang(lang)

    _trace('image.single.begin', {
        'mode': mode_id,
        'lang': target_lang,
        'ai': bool(ai_cfg),
    })

    t_stage = time.perf_counter()
    data = core.get_lens_data_from_image(
        image_path, getattr(core, 'FIREBASE_URL', ''), target_lang)
    _trace('image.single.stage', {
        'stage': 'lens_ocr',
        'ms': _elapsed_ms(t_stage),
        'has_original_text': bool(isinstance(data, dict) and data.get('originalTextFull')),
        'has_translated_text': bool(isinstance(data, dict) and data.get('translatedTextFull')),
        'original_paras': len((data.get('originalParagraphs') or []) if isinstance(data, dict) else []),
        'translated_paras': len((data.get('translatedParagraphs') or []) if isinstance(data, dict) else []),
    })

    t_stage = time.perf_counter()
    img = core.Image.open(image_path).convert('RGB')
    W, H = img.size
    _trace('image.single.stage', {
        'stage': 'image_open',
        'ms': _elapsed_ms(t_stage),
        'w': W,
        'h': H,
    })

    t_stage = time.perf_counter()
    thai_font = getattr(core, 'FONT_THAI_PATH', 'NotoSansThai-Regular.ttf')
    latin_font = getattr(core, 'FONT_LATIN_PATH', 'NotoSans-Regular.ttf')

    if target_lang == 'ja':
        latin_font = getattr(core, 'FONT_JA_PATH', latin_font)
    elif target_lang in ('zh', 'zh-hans', 'zh_cn', 'zh-cn', 'zh_hans'):
        latin_font = getattr(core, 'FONT_ZH_SC_PATH', latin_font)
    elif target_lang in ('zh-hant', 'zh_tw', 'zh-tw', 'zh_hant'):
        latin_font = getattr(core, 'FONT_ZH_TC_PATH', latin_font)

    if getattr(core, 'FONT_DOWNLOD', True):
        thai_font = core.ensure_font(
            thai_font, getattr(core, 'FONT_THAI_URLS', []))
        if target_lang == 'ja':
            latin_font = core.ensure_font(
                latin_font, getattr(core, 'FONT_JA_URLS', []))
        elif target_lang in ('zh', 'zh-hans', 'zh_cn', 'zh-cn', 'zh_hans'):
            latin_font = core.ensure_font(
                latin_font, getattr(core, 'FONT_ZH_SC_URLS', []))
        elif target_lang in ('zh-hant', 'zh_tw', 'zh-tw', 'zh_hant'):
            latin_font = core.ensure_font(
                latin_font, getattr(core, 'FONT_ZH_TC_URLS', []))
        else:
            latin_font = core.ensure_font(
                latin_font, getattr(core, 'FONT_LATIN_URLS', []))
    _trace('image.single.stage', {
        'stage': 'fonts',
        'ms': _elapsed_ms(t_stage),
    })

    image_url = data.get('imageUrl') if isinstance(data, dict) else None

    out: Dict[str, Any] = {
        'mode': mode_id,
        'imageUrl': image_url,
        'imageDataUri': '',
        'originalContentLanguage': data.get('originalContentLanguage') if isinstance(data, dict) else None,
        'originalTextFull': data.get('originalTextFull') if isinstance(data, dict) else None,
        'translatedTextFull': data.get('translatedTextFull') if isinstance(data, dict) else None,
        'AiTextFull': '',
        'originalParagraphs': (data.get('originalParagraphs') or []) if isinstance(data, dict) else [],
        'translatedParagraphs': (data.get('translatedParagraphs') or []) if isinstance(data, dict) else [],
        'original': {},
        'translated': {},
        'Ai': {},
    }

    if mode_id == 'lens_images':
        t_stage = time.perf_counter()
        if image_url:
            decoded = core.decode_imageurl_to_datauri(str(image_url))
            if decoded:
                out['imageDataUri'] = decoded
            elif isinstance(image_url, str) and image_url.startswith(('http://', 'https://')):
                blob, mime2 = _download_bytes(image_url)
                out['imageDataUri'] = _bytes_to_datauri(
                    blob, mime2 or 'image/jpeg')

        if not out.get('imageDataUri'):
            with open(image_path, 'rb') as f:
                blob = f.read()
            out['imageDataUri'] = _bytes_to_datauri(blob, 'image/jpeg')
        _trace('image.single.done', {
            'mode': mode_id,
            'stage': 'lens_images_payload',
            'ms': _elapsed_ms(t_stage),
            'total_ms': _elapsed_ms(t_total),
            'has_datauri': bool(out.get('imageDataUri')),
        })
        return out

    original_span_tokens = None
    original_tree = None
    translated_tree = None

    def _base_img_for_overlay() -> core.Image.Image:
        if not (getattr(core, 'ERASE_OLD_TEXT_WITH_ORIGINAL_BOXES', True) and original_span_tokens):
            return img
        return core.erase_text_with_boxes(
            img,
            original_span_tokens,
            pad_px=getattr(core, 'ERASE_PADDING_PX', 2),
            sample_margin_px=getattr(core, 'ERASE_SAMPLE_MARGIN_PX', 6),
        )

    if getattr(core, 'DO_ORIGINAL', True):
        t_stage = time.perf_counter()
        tree, _ = core.decode_tree(
            out.get('originalParagraphs') or [],
            out.get('originalTextFull') or '',
            'original',
            W,
            H,
            want_raw=False,
        )
        original_tree = tree
        original_span_tokens = core.flatten_tree_spans(tree)
        _dbg('tree.original', _tree_stats(original_tree))
        out['original'] = {
            'originalTree': tree,
            'originalTextFull': out.get('originalTextFull') or '',
        }
        _trace('image.single.stage', {
            'stage': 'decode_original_tree',
            'ms': _elapsed_ms(t_stage),
            'stats': _tree_stats(original_tree),
        })

    if getattr(core, 'DO_TRANSLATED', True):
        t_stage = time.perf_counter()
        tree, _ = core.decode_tree(
            out.get('translatedParagraphs') or [],
            out.get('translatedTextFull') or '',
            'translated',
            W,
            H,
            want_raw=False,
        )
        translated_tree = tree
        translated_span_tokens = core.flatten_tree_spans(tree)
        _dbg('tree.translated', _tree_stats(translated_tree))
        out['translated'] = {
            'translatedTree': tree,
            'translatedTextFull': out.get('translatedTextFull') or '',
        }
        _trace('image.single.stage', {
            'stage': 'decode_translated_tree',
            'ms': _elapsed_ms(t_stage),
            'stats': _tree_stats(translated_tree),
        })

    def _tree_score(tree: Any) -> int:
        if not isinstance(tree, dict):
            return -1
        paragraphs = tree.get('paragraphs') or []
        if not isinstance(paragraphs, list) or not paragraphs:
            return -1

        para_count = len(paragraphs)
        item_count = 0
        span_count = 0
        for p in paragraphs:
            if not isinstance(p, dict):
                continue
            items = p.get('items') or []
            if not isinstance(items, list):
                continue
            item_count += len(items)
            for it in items:
                if not isinstance(it, dict):
                    continue
                spans = it.get('spans') or []
                if isinstance(spans, list):
                    span_count += len(spans)

        return item_count * 10000 + para_count * 100 + span_count

    def _pick_ai_template_tree() -> Optional[Dict[str, Any]]:
        tr_score = _tree_score(translated_tree)
        og_score = _tree_score(original_tree)

        if tr_score < 0 and og_score < 0:
            return None
        if og_score > tr_score:
            return original_tree
        return translated_tree or original_tree

    ai_tree = None
    if ai_cfg and (ai_cfg.api_key or '').strip() and getattr(core, 'DO_AI', True):
        t_ai_total = time.perf_counter()
        t_stage = time.perf_counter()
        src_paras = _tree_to_paragraph_texts(original_tree or {})
        src_text = _apply_para_markers(src_paras) if src_paras else str(
            out.get('originalTextFull') or '')
        _trace('image.single.stage', {
            'stage': 'ai_prepare_input',
            'ms': _elapsed_ms(t_stage),
            'paras': len(src_paras),
            'input_len': len(str(src_text or '')),
            'provider': ai_cfg.provider,
            'model': ai_cfg.model,
        })
        if not _has_meaningful_text(src_text):
            out['AiTextFull'] = ''
            out['Ai'] = {
                'meta': {
                    'skipped': True,
                    'skipped_reason': 'no_text',
                }
            }
            _trace('image.single.stage', {
                'stage': 'ai_skipped_no_text',
                'ms': _elapsed_ms(t_ai_total),
            })
        else:
            ai = ai_translate_text(src_text, target_lang, ai_cfg)
            if src_paras and _needs_ai_retry(str(ai.get('aiTextFull') or ''), len(src_paras)):
                retry_found = len(_extract_marker_indices(str(ai.get('aiTextFull') or '')))
                _trace('ai.retry.begin', {
                    'expected_paras': len(src_paras),
                    'found_markers': retry_found,
                    'provider': ai_cfg.provider,
                    'model': ai_cfg.model,
                })
                t_retry = time.perf_counter()
                retry_paras = [_clamp_runaway_repeats(p) for p in src_paras]
                retry_text = _apply_para_markers(retry_paras) or src_text
                ai = ai_translate_text(
                    retry_text, target_lang, ai_cfg, is_retry=True)
                _trace('ai.retry.done', {
                    'ms': _elapsed_ms(t_retry),
                    'expected_paras': len(src_paras),
                    'found_markers': len(_extract_marker_indices(str(ai.get('aiTextFull') or ''))),
                })

            ai_text_full = str(ai.get('aiTextFull') or '')
            meta0 = ai.get('meta') or {}
            if src_paras:
                expected = len(src_paras)
                if not _has_complete_marker_sequence(ai_text_full, expected):
                    fallback_paras = _tree_to_paragraph_texts(translated_tree or {})
                    if len(fallback_paras) < expected:
                        fallback_paras = (fallback_paras + src_paras)[:expected]
                    else:
                        fallback_paras = fallback_paras[:expected]

                    found = sorted(_extract_marker_indices(ai_text_full))
                    seg_map: Dict[int, str] = {}
                    for idx in found:
                        if idx < 0 or idx >= expected:
                            continue
                        marker = f"<<TP_P{idx}>>"
                        m = re.search(rf"{re.escape(marker)}\s*([\s\S]*?)(?=<<TP_P\d+>>|\Z)", ai_text_full)
                        seg = _collapse_ws(m.group(1) if m else '')
                        if seg and idx not in seg_map:
                            seg_map[idx] = seg

                    missing = 0
                    out_lines: List[str] = []
                    for i in range(expected):
                        seg = seg_map.get(i) or _collapse_ws(fallback_paras[i] if i < len(fallback_paras) else '')
                        if not seg_map.get(i):
                            missing += 1
                        out_lines.append(f"<<TP_P{i}>>")
                        out_lines.append(seg)
                        out_lines.append('')
                    ai_text_full = "\n".join(out_lines).strip("\n")
                    _dbg('ai.marker.repaired', {
                        'expected_paras': expected,
                        'found_markers': len(seg_map),
                        'missing': missing,
                    })

                    meta0 = {
                        **meta0,
                        'marker_repaired': True,
                        'marker_expected': expected,
                        'marker_found': len(seg_map),
                        'marker_missing': missing,
                    }

            template_tree = _pick_ai_template_tree()
            _dbg('ai.template.pick', {
                'score_original': _tree_score(original_tree),
                'score_translated': _tree_score(translated_tree),
                'picked': 'original' if template_tree is original_tree else ('translated' if template_tree is translated_tree else 'none'),
            })
            if not isinstance(template_tree, dict):
                template_tree = original_tree if isinstance(original_tree, dict) else (
                    translated_tree if isinstance(translated_tree, dict) else {})
            t_stage = time.perf_counter()
            patched = core.patch(
                {'Ai': {'aiTextFull': str(
                    ai_text_full or ''), 'aiTree': template_tree}},
                W,
                H,
                thai_font or '',
                latin_font or '',
                lang=target_lang,
            )
            ai_tree = (patched.get('Ai') or {}).get('aiTree') or {}
            _trace('image.single.stage', {
                'stage': 'ai_patch_tree',
                'ms': _elapsed_ms(t_stage),
                'stats_ai': _tree_stats(ai_tree),
            })
            _dbg('ai.patched', {
                'ai_text_len': len(ai_text_full),
                'stats_ai': _tree_stats(ai_tree),
                'stats_original': _tree_stats(original_tree or {}),
                'stats_translated': _tree_stats(translated_tree or {}),
                'mode': mode_id,
                'lang': target_lang,
            })

            t_stage = time.perf_counter()
            shared_para_sizes = core._compute_shared_para_sizes(
                [original_tree or {}, translated_tree or {}, ai_tree or {}],
                thai_font or '',
                latin_font or '',
                W,
                H,
            )
            core._apply_para_font_size(original_tree or {}, shared_para_sizes)
            core._apply_para_font_size(
                translated_tree or {}, shared_para_sizes)
            core._apply_para_font_size(ai_tree or {}, shared_para_sizes)
            core._rebuild_ai_spans_after_font_resize(
                ai_tree or {}, W, H, thai_font or '', latin_font or '', lang=target_lang)
            _trace('image.single.stage', {
                'stage': 'shared_font_fit',
                'ms': _elapsed_ms(t_stage),
                'paras': len(shared_para_sizes or {}),
            })

            out['AiTextFull'] = ai_text_full
            out['Ai'] = {
                'aiTextFull': ai_text_full,
                'aiTree': ai_tree,
                'meta': meta0,
            }
            if getattr(core, 'DO_AI_HTML', True):
                t_stage = time.perf_counter()
                core.fit_tree_font_sizes_for_tp_html(
                    ai_tree, thai_font or '', latin_font or '', W, H)
                out['Ai']['aihtml'] = core.ai_tree_to_tp_html(ai_tree, W, H)
                out['Ai']['aihtmlMeta'] = {
                    'baseW': int(W),
                    'baseH': int(H),
                    'format': 'tp',
                }
                _trace('image.single.stage', {
                    'stage': 'ai_html',
                    'ms': _elapsed_ms(t_stage),
                    'html_len': len(str(out['Ai'].get('aihtml') or '')),
                })
            _trace('image.single.stage', {
                'stage': 'ai_total',
                'ms': _elapsed_ms(t_ai_total),
            })

    if getattr(core, 'DO_ORIGINAL', True) and getattr(core, 'DO_ORIGINAL_HTML', True) and isinstance(original_tree, dict):
        t_stage = time.perf_counter()
        core.fit_tree_font_sizes_for_tp_html(
            original_tree, thai_font or '', latin_font or '', W, H)
        if isinstance(out.get('original'), dict):
            out['original']['originalhtml'] = core.ai_tree_to_tp_html(
                original_tree or {}, W, H)
        _trace('image.single.stage', {
            'stage': 'original_html',
            'ms': _elapsed_ms(t_stage),
            'html_len': len(str((out.get('original') or {}).get('originalhtml') or '')),
        })

    if getattr(core, 'DO_TRANSLATED', True) and getattr(core, 'DO_TRANSLATED_HTML', True) and isinstance(translated_tree, dict):
        t_stage = time.perf_counter()
        core.fit_tree_font_sizes_for_tp_html(
            translated_tree, thai_font or '', latin_font or '', W, H)
        if isinstance(out.get('translated'), dict):
            out['translated']['translatedhtml'] = core.ai_tree_to_tp_html(
                translated_tree or {}, W, H)
        _trace('image.single.stage', {
            'stage': 'translated_html',
            'ms': _elapsed_ms(t_stage),
            'html_len': len(str((out.get('translated') or {}).get('translatedhtml') or '')),
        })

    if getattr(core, 'HTML_INCLUDE_CSS', True) and (getattr(core, 'DO_ORIGINAL_HTML', True) or getattr(core, 'DO_TRANSLATED_HTML', True) or getattr(core, 'DO_AI_HTML', True)):
        out['htmlCss'] = core.tp_overlay_css()
        out['htmlMeta'] = {
            'baseW': int(W),
            'baseH': int(H),
            'format': 'tp',
        }
    t_stage = time.perf_counter()
    base_img = _base_img_for_overlay()
    buf = io.BytesIO()
    base_img.save(buf, format='PNG')
    out['imageDataUri'] = _bytes_to_datauri(buf.getvalue(), 'image/png')
    _trace('image.single.stage', {
        'stage': 'base_image_encode',
        'ms': _elapsed_ms(t_stage),
        'datauri_len': len(str(out.get('imageDataUri') or '')),
    })

    _trace('image.single.done', {
        'mode': mode_id,
        'total_ms': _elapsed_ms(t_total),
        'w': W,
        'h': H,
        'has_ai_text': bool(out.get('AiTextFull')),
    })

    return out

def _shift_tree_y(tree: dict, offset_y_px: int, total_h_px: int, tile_h_px: int):
    if not isinstance(tree, dict) or 'paragraphs' not in tree:
        return
    for p in (tree.get('paragraphs') or []):
        if not isinstance(p, dict): continue
        if 'bounds_px' in p and isinstance(p['bounds_px'], (list, tuple)) and len(p['bounds_px']) == 4:
            bpx = list(p['bounds_px'])
            bpx[1] += offset_y_px
            bpx[3] += offset_y_px
            p['bounds_px'] = tuple(bpx)
            
        for it in (p.get('items') or []):
            if not isinstance(it, dict): continue
            
            # Shift baseline points
            for bp_key in ('baseline_p1', 'baseline_p2'):
                if bp_key in it and isinstance(it[bp_key], dict) and 'y' in it[bp_key]:
                    old_y_px = it[bp_key]['y'] * tile_h_px
                    new_y_px = old_y_px + offset_y_px
                    it[bp_key]['y'] = new_y_px / total_h_px

            if 'bounds_px' in it and isinstance(it['bounds_px'], (list, tuple)) and len(it['bounds_px']) == 4:
                bpx = list(it['bounds_px'])
                bpx[1] += offset_y_px
                bpx[3] += offset_y_px
                it['bounds_px'] = tuple(bpx)

            b = it.get('box')
            if isinstance(b, dict):
                if 'top' in b:
                    old_top_px = b['top'] * tile_h_px
                    b['top'] = (old_top_px + offset_y_px) / total_h_px
                    b['top_pct'] = b['top'] * 100.0
                if 'height' in b:
                    old_h_px = b['height'] * tile_h_px
                    b['height'] = old_h_px / total_h_px
                    b['height_pct'] = b['height'] * 100.0
                if 'center' in b and isinstance(b['center'], dict) and 'y' in b['center']:
                    old_cy_px = b['center']['y'] * tile_h_px
                    b['center']['y'] = (old_cy_px + offset_y_px) / total_h_px
                    
            for sp in (it.get('spans') or []):
                if not isinstance(sp, dict): continue
                for bp_key in ('baseline_p1', 'baseline_p2'):
                    if bp_key in sp and isinstance(sp[bp_key], dict) and 'y' in sp[bp_key]:
                        old_y_px = sp[bp_key]['y'] * tile_h_px
                        new_y_px = old_y_px + offset_y_px
                        sp[bp_key]['y'] = new_y_px / total_h_px
                sb = sp.get('box')
                if isinstance(sb, dict):
                    if 'top' in sb:
                        old_top_px = sb['top'] * tile_h_px
                        sb['top'] = (old_top_px + offset_y_px) / total_h_px
                        sb['top_pct'] = sb['top'] * 100.0
                    if 'height' in sb:
                        old_h_px = sb['height'] * tile_h_px
                        sb['height'] = old_h_px / total_h_px
                        sb['height_pct'] = sb['height'] * 100.0
                    if 'center' in sb and isinstance(sb['center'], dict) and 'y' in sb['center']:
                        old_cy_px = sb['center']['y'] * tile_h_px
                        sb['center']['y'] = (old_cy_px + offset_y_px) / total_h_px

def process_image_path(image_path: str, lang: str, mode: str, ai_cfg: Optional[AiConfig]) -> dict:
    t_total = time.perf_counter()
    img = core.Image.open(image_path)
    W, H = img.size
    MAX_H = 3000
    
    if H <= MAX_H:
        out = _process_image_path_single(image_path, lang, mode, ai_cfg)
        _trace('image.process.done', {
            'split': False,
            'w': W,
            'h': H,
            'total_ms': _elapsed_ms(t_total),
        })
        return out
        
    # Split image into vertical tiles
    _trace('image.split.begin', {
        'w': W,
        'h': H,
        'max_h': MAX_H,
        'mode': mode,
        'ai': bool(ai_cfg),
    })
    tiles = []
    y = 0
    while y < H:
        tile_h = min(MAX_H, H - y)
        box = (0, y, W, y + tile_h)
        tile_img = img.crop(box)
        tiles.append((y, tile_h, tile_img))
        y += tile_h
    _trace('image.split.done', {
        'tiles': len(tiles),
        'total_ms': _elapsed_ms(t_total),
    })

    results = []
    tile_ai_cfg = None if (ai_cfg and str(mode or '').strip() == 'lens_text') else ai_cfg
    if ai_cfg and tile_ai_cfg is None:
        _trace('image.split.ai_batch.enabled', {
            'tiles': len(tiles),
            'provider': ai_cfg.provider,
            'model': ai_cfg.model,
        })
    for tile_index, (offset_y, tile_h, tile_img) in enumerate(tiles):
        t_tile = time.perf_counter()
        _trace('image.tile.begin', {
            'index': tile_index,
            'tiles': len(tiles),
            'offset_y': offset_y,
            'tile_h': tile_h,
        })
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
            t_save = time.perf_counter()
            tile_img.convert("RGB").save(f, format="JPEG", quality=95)
            tmp_tile_path = f.name
            save_ms = _elapsed_ms(t_save)
        try:
            res = _process_image_path_single(tmp_tile_path, lang, mode, tile_ai_cfg)
            results.append((offset_y, tile_h, res))
            _trace('image.tile.done', {
                'index': tile_index,
                'tiles': len(tiles),
                'offset_y': offset_y,
                'tile_h': tile_h,
                'save_ms': save_ms,
                'total_ms': _elapsed_ms(t_tile),
                'has_original_text': bool(res.get('originalTextFull') if isinstance(res, dict) else ''),
                'has_ai_text': bool(res.get('AiTextFull') if isinstance(res, dict) else ''),
            })
        finally:
            try:
                os.unlink(tmp_tile_path)
            except:
                pass

    if not results:
        raise Exception("Failed to process any image tiles")

    # Merge results
    t_merge = time.perf_counter()
    merged = results[0][2].copy()
    
    merged_original_text = []
    merged_translated_text = []
    merged_ai_text = []
    
    merged_original_tree = {"side": "original", "paragraphs": []}
    merged_translated_tree = {"side": "translated", "paragraphs": []}
    merged_ai_tree = {"side": "Ai", "paragraphs": []}
    
    merged_images = []
    
    para_idx_offset = {"original": 0, "translated": 0, "Ai": 0}

    for offset_y, tile_h, res in results:
        # Merge texts
        if res.get('originalTextFull'):
            merged_original_text.append(res['originalTextFull'].strip())
        if res.get('translatedTextFull'):
            merged_translated_text.append(res['translatedTextFull'].strip())
        if res.get('AiTextFull'):
            merged_ai_text.append(res['AiTextFull'].strip())
            
        # Shift and merge trees
        for tree_key, result_tree_key, role in [
            ('original', 'originalTree', 'original'),
            ('translated', 'translatedTree', 'translated'),
            ('Ai', 'aiTree', 'Ai')
        ]:
            if isinstance(res.get(tree_key), dict) and result_tree_key in res[tree_key]:
                t = res[tree_key][result_tree_key]
                if t:
                    _shift_tree_y(t, offset_y, H, tile_h)
                    
                    # Fix paragraph indices to be monotonically increasing
                    for p in (t.get('paragraphs') or []):
                        p['para_index'] = para_idx_offset[role]
                        para_idx_offset[role] += 1
                        for sp in (p.get('items') or []):
                            sp['para_index'] = p['para_index']
                            for s in (sp.get('spans') or []):
                                s['para_index'] = p['para_index']
                                
                    if role == 'original':
                        merged_original_tree['paragraphs'].extend(t.get('paragraphs') or [])
                    elif role == 'translated':
                        merged_translated_tree['paragraphs'].extend(t.get('paragraphs') or [])
                    elif role == 'Ai':
                        merged_ai_tree['paragraphs'].extend(t.get('paragraphs') or [])

        # Read rendered overlay image for this chunk
        uri = res.get('imageDataUri')
        if uri:
            img_bytes, _ = _datauri_to_bytes(uri)
            chunk_img = core.Image.open(io.BytesIO(img_bytes)).convert("RGB")
            merged_images.append((offset_y, chunk_img))

    merged['originalTextFull'] = "\n\n".join(merged_original_text)
    merged['translatedTextFull'] = "\n\n".join(merged_translated_text)
    merged['AiTextFull'] = "\n\n".join(merged_ai_text)
    
    if 'original' in merged and isinstance(merged['original'], dict):
        merged['original']['originalTree'] = merged_original_tree
        merged['original']['originalTextFull'] = merged['originalTextFull']
    if 'translated' in merged and isinstance(merged['translated'], dict):
        merged['translated']['translatedTree'] = merged_translated_tree
        merged['translated']['translatedTextFull'] = merged['translatedTextFull']

    thai_font = getattr(core, 'FONT_THAI_PATH', 'NotoSansThai-Regular.ttf')
    latin_font = getattr(core, 'FONT_LATIN_PATH', 'NotoSans-Regular.ttf')

    target_lang = _normalize_lang(lang)
    if target_lang == 'ja':
        latin_font = getattr(core, 'FONT_JA_PATH', latin_font)
    elif target_lang in ('zh', 'zh-hans', 'zh_cn', 'zh-cn', 'zh_hans'):
        latin_font = getattr(core, 'FONT_ZH_SC_PATH', latin_font)
    elif target_lang in ('zh-hant', 'zh_tw', 'zh-tw', 'zh_hant'):
        latin_font = getattr(core, 'FONT_ZH_TC_PATH', latin_font)

    if ai_cfg and str(mode or '').strip() == 'lens_text' and getattr(core, 'DO_AI', True):
        t_ai_batch = time.perf_counter()
        src_paras = _tree_to_paragraph_texts(merged_original_tree)
        src_text = _apply_para_markers(src_paras) if src_paras else ''
        _trace('image.split.ai_batch.begin', {
            'tiles': len(results),
            'paras': len(src_paras),
            'input_len': len(src_text),
            'provider': ai_cfg.provider,
            'model': ai_cfg.model,
        })
        if _has_meaningful_text(src_text):
            ai = ai_translate_text(src_text, target_lang, ai_cfg)
            if src_paras and _needs_ai_retry(str(ai.get('aiTextFull') or ''), len(src_paras)):
                _trace('image.split.ai_batch.retry.begin', {
                    'expected_paras': len(src_paras),
                    'found_markers': len(_extract_marker_indices(str(ai.get('aiTextFull') or ''))),
                })
                t_retry = time.perf_counter()
                retry_paras = [_clamp_runaway_repeats(p) for p in src_paras]
                retry_text = _apply_para_markers(retry_paras) or src_text
                ai = ai_translate_text(retry_text, target_lang, ai_cfg, is_retry=True)
                _trace('image.split.ai_batch.retry.done', {
                    'ms': _elapsed_ms(t_retry),
                    'found_markers': len(_extract_marker_indices(str(ai.get('aiTextFull') or ''))),
                })

            ai_text_full = str(ai.get('aiTextFull') or '')
            meta0 = ai.get('meta') or {}
            expected = len(src_paras)
            if expected and not _has_complete_marker_sequence(ai_text_full, expected):
                fallback_paras = _tree_to_paragraph_texts(merged_translated_tree)
                if len(fallback_paras) < expected:
                    fallback_paras = (fallback_paras + src_paras)[:expected]
                else:
                    fallback_paras = fallback_paras[:expected]
                ai_text_full, repair_meta = _repair_marked_ai_text(
                    ai_text_full, expected, fallback_paras)
                meta0 = {**meta0, **repair_meta}
                _trace('image.split.ai_batch.marker_repaired', repair_meta)

            template_tree = merged_original_tree if (merged_original_tree.get('paragraphs') or []) else merged_translated_tree
            t_patch = time.perf_counter()
            patched = core.patch(
                {'Ai': {'aiTextFull': ai_text_full, 'aiTree': template_tree}},
                W,
                H,
                thai_font or '',
                latin_font or '',
                lang=target_lang,
            )
            merged_ai_tree = (patched.get('Ai') or {}).get('aiTree') or {}
            merged_ai_text = [ai_text_full] if ai_text_full else []
            merged['AiTextFull'] = ai_text_full
            merged['Ai'] = {
                'aiTextFull': ai_text_full,
                'aiTree': merged_ai_tree,
                'meta': {
                    **meta0,
                    'batched_tiles': len(results),
                    'batched_paras': len(src_paras),
                },
            }
            _trace('image.split.ai_batch.patch_done', {
                'ms': _elapsed_ms(t_patch),
                'stats_ai': _tree_stats(merged_ai_tree),
            })
        else:
            merged['AiTextFull'] = ''
            merged['Ai'] = {
                'meta': {
                    'skipped': True,
                    'skipped_reason': 'no_text',
                    'batched_tiles': len(results),
                }
            }
        _trace('image.split.ai_batch.done', {
            'ms': _elapsed_ms(t_ai_batch),
            'has_ai_text': bool(merged.get('AiTextFull')),
        })

    if 'Ai' in merged and isinstance(merged['Ai'], dict) and not (ai_cfg and str(mode or '').strip() == 'lens_text'):
        merged['Ai']['aiTree'] = merged_ai_tree
        merged['Ai']['aiTextFull'] = merged['AiTextFull']
        merged['Ai']['meta'] = results[-1][2].get('Ai', {}).get('meta', {}) # Give meta from last tile

    # Re-generate HTML

    # Regenerate translated HTML if present
    if merged.get('translated') and getattr(core, 'DO_TRANSLATED_HTML', True):
        core.fit_tree_font_sizes_for_tp_html(merged_translated_tree, thai_font, latin_font, W, H)
        merged['translated']['translatedhtml'] = core.ai_tree_to_tp_html(merged_translated_tree, W, H)

    # Regenerate original HTML if present
    if merged.get('original') and getattr(core, 'DO_ORIGINAL_HTML', True):
        core.fit_tree_font_sizes_for_tp_html(merged_original_tree, thai_font, latin_font, W, H)
        merged['original']['originalhtml'] = core.ai_tree_to_tp_html(merged_original_tree, W, H)

    # Regenerate AI HTML if present
    if merged.get('Ai') and getattr(core, 'DO_AI_HTML', True):
        core.fit_tree_font_sizes_for_tp_html(merged_ai_tree, thai_font, latin_font, W, H)
        merged['Ai']['aihtml'] = core.ai_tree_to_tp_html(merged_ai_tree, W, H)
        merged['Ai']['aihtmlMeta'] = {'baseW': int(W), 'baseH': int(H), 'format': 'tp'}

    # Combine rendered images
    if merged_images:
        t_combine = time.perf_counter()
        final_img = core.Image.new("RGB", (W, H))
        for y, chunk_img in merged_images:
            final_img.paste(chunk_img, (0, y))
        buf = io.BytesIO()
        final_img.save(buf, format="PNG")
        merged['imageDataUri'] = _bytes_to_datauri(buf.getvalue(), "image/png")
        _trace('image.merge.stage', {
            'stage': 'combine_images',
            'ms': _elapsed_ms(t_combine),
            'chunks': len(merged_images),
            'datauri_len': len(str(merged.get('imageDataUri') or '')),
        })

    # htmlMeta fixes
    merged['htmlMeta'] = {
        'baseW': int(W),
        'baseH': int(H),
        'format': 'tp',
    }
    _trace('image.merge.done', {
        'tiles': len(results),
        'merge_ms': _elapsed_ms(t_merge),
        'total_ms': _elapsed_ms(t_total),
        'original_text_len': len(merged.get('originalTextFull') or ''),
        'translated_text_len': len(merged.get('translatedTextFull') or ''),
        'ai_text_len': len(merged.get('AiTextFull') or ''),
    })
    
    return merged

app = FastAPI(title='TextPhantom OCR API', version='1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

@app.middleware("http")
async def _tp_access_log(request: Request, call_next):
    resp = await call_next(request)
    if TP_ACCESS_LOG_MODE in ('uvicorn', 'off', 'none'):
        return resp
    try:
        path = request.url.path
        if request.method == 'GET' and path.startswith("/translate/"):
            client = request.client
            host = client.host if client else "-"
            port = client.port if client else 0
            ver = request.scope.get("http_version") or "1.1"
            phrase = HTTPStatus(resp.status_code).phrase
            print(f'{host}:{port} - "{request.method} {path} HTTP/{ver}" {resp.status_code} {phrase}', flush=True)
    except Exception:
        pass
    return resp

async def _cleanup_jobs_loop():
    while True:
        await asyncio.sleep(60)
        cutoff = _now() - JOB_TTL_SEC
        dead = [jid for jid, j in _jobs.items() if float(
            j.get('ts', 0)) < cutoff]
        for jid in dead:
            _jobs.pop(jid, None)

async def _worker_loop(worker_id: int):
    while True:
        jid, payload = await _job_queue.get()
        try:
            _trace('job.running', {
                'id': jid,
                'worker': worker_id,
                'mode': str(payload.get('mode') or ''),
                'lang': str(payload.get('lang') or ''),
                'source': str(payload.get('source') or ''),
                'has_ai': isinstance(payload.get('ai'), dict),
                'has_datauri': bool(payload.get('imageDataUri')),
                'has_src': bool(payload.get('src')),
            })
            _jobs[jid] = {'status': 'running', 'ts': _now()}
            result = await asyncio.to_thread(_process_payload, payload)
            _jobs[jid] = {'status': 'done', 'result': result, 'ts': _now()}
            _trace('job.done', {
                'id': jid,
                'worker': worker_id,
                'result_keys': list(result.keys()) if isinstance(result, dict) else [],
                'has_ai_text': bool(isinstance(result, dict) and (result.get('AiTextFull') or (result.get('Ai') or {}).get('aiTextFull'))),
                'perf': result.get('perf') if isinstance(result, dict) else None,
            })
        except Exception as e:
            _jobs[jid] = {'status': 'error', 'result': str(e), 'ts': _now()}
            _trace('job.error', {
                'id': jid,
                'worker': worker_id,
                'error': str(e),
            })
        finally:
            _job_queue.task_done()

def _process_payload(payload: dict) -> dict:
    t_all = time.perf_counter()
    mode = (payload.get('mode') or 'lens_images')
    lang = (payload.get('lang') or 'en')

    context = payload.get('context') if isinstance(
        payload.get('context'), dict) else {}
    page_url = str((context or {}).get('page_url') or '').strip()

    src = (payload.get('src') or '').strip()
    img_bytes = b''
    mime = ''
    _trace('payload.start', {
        'mode': mode,
        'lang': lang,
        'source': str(payload.get('source') or ''),
        'has_datauri': bool(payload.get('imageDataUri')),
        'src_prefix': src[:80],
        'page_url': page_url[:120],
    })

    try:
        if payload.get('imageDataUri'):
            img_bytes, mime = _datauri_to_bytes(payload.get('imageDataUri'))
        elif src.startswith('data:'):
            img_bytes, mime = _datauri_to_bytes(src)
        else:
            img_bytes, mime = _download_bytes(src, page_url)
    except Exception as e:
        raise Exception(f'[download] {e}') from e

    t_img = time.perf_counter()

    if not img_bytes:
        raise Exception('[download] No image data')
    _trace('payload.image.ready', {
        'bytes': len(img_bytes),
        'mime': mime,
        'download_ms': round((t_img - t_all) * 1000, 1),
    })

    ai_cfg = None
    ai = payload.get('ai') or None
    source = str(payload.get('source') or '').strip().lower() or 'translated'
    is_ai_source = source == 'ai' or source.startswith('cli_')
    if mode == 'lens_text' and is_ai_source:
        if source.startswith('cli_'):
            ai_cfg = AiConfig(
                api_key=source,
                model=str(ai.get('model') if isinstance(ai, dict) else 'auto').strip() or 'auto',
                provider=source,
                base_url='auto',
                prompt_editable=str(ai.get('prompt') if isinstance(ai, dict) else ''),
                reasoning_effort=str(ai.get('reasoning_effort') if isinstance(ai, dict) else 'medium').strip() or 'medium',
            )
        elif isinstance(ai, dict):
            api_key = str(ai.get('api_key') or '').strip() or (
                os.getenv('AI_API_KEY') or '').strip()
            ai_cfg = AiConfig(
                api_key=api_key,
                model=str(ai.get('model') or 'auto').strip() or 'auto',
                provider=str(ai.get('provider') or 'auto').strip() or 'auto',
                base_url=str(ai.get('base_url') or 'auto').strip() or 'auto',
                prompt_editable=str(ai.get('prompt') or '').strip(),
                reasoning_effort=str(ai.get('reasoning_effort') or 'medium').strip() or 'medium',
            )
    _trace('payload.ai.config', {
        'mode': mode,
        'source': source,
        'is_ai_source': is_ai_source,
        'has_ai_cfg': ai_cfg is not None,
        'provider': ai_cfg.provider if ai_cfg else '',
        'model': ai_cfg.model if ai_cfg else '',
        'prompt_len': len(ai_cfg.prompt_editable) if ai_cfg else 0,
    })

    core.DO_AI_JSON = False

    img_hash = _sha256_hex(img_bytes)
    cache_key = ''
    if mode == 'lens_text' and img_hash:
        cache_source = 'ai' if is_ai_source else 'text'
        cache_key = _build_cache_key(
            img_hash, lang, mode, cache_source, ai_cfg)
        cached = None
        if is_ai_source:
            cached = _lru_get(_ai_result_cache, _ai_cache_lock, cache_key)
        else:
            cached = _lru_get(_result_cache, _result_cache_lock, cache_key)
        if cached:
            _trace('payload.cache.hit', {'source': source, 'cache_key_len': len(cache_key)})
            cached['perf'] = {
                'cache': 'hit',
                'total_ms': round((time.perf_counter() - t_all) * 1000, 1),
                'img_ms': round((t_img - t_all) * 1000, 1),
            }
            return cached

    suffix = '.png' if (mime or '').endswith('png') else '.jpg'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(img_bytes)
        tmp_path = f.name
    t_tmp = time.perf_counter()
    _trace('payload.process.begin', {
        'tmp_suffix': suffix,
        'source': source,
        'mode': mode,
        'lang': lang,
    })
    try:
        try:
            out = process_image_path(tmp_path, lang, mode, ai_cfg)
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ('ai ', 'ai_', 'openai', 'gemini', 'anthropic', 'api_key', 'api key',
                                             'rate limit', 'ratelimit', '429', 'quota',
                                             'usage limit', 'resource exhausted', 'daily limit', 'limit reached',
                                             'codex cli', 'gemini cli',
                                             'model', 'generate', 'chat/completions')):
                raise Exception(f'[ai] {e}') from e
            elif any(kw in err_str for kw in ('cannot identify image', 'image file is truncated',
                                                'unsupported', 'decode', 'pixel')):
                raise Exception(f'[ocr] {e}') from e
            else:
                raise Exception(f'[render] {e}') from e
        _trace('payload.process.done', {
            'source': source,
            'has_original_text': bool(isinstance(out, dict) and out.get('originalTextFull')),
            'has_translated_text': bool(isinstance(out, dict) and out.get('translatedTextFull')),
            'has_ai_text': bool(isinstance(out, dict) and (out.get('AiTextFull') or (out.get('Ai') or {}).get('aiTextFull'))),
            'total_ms': round((time.perf_counter() - t_all) * 1000, 1),
        })
        out['perf'] = {
            'cache': 'miss' if cache_key else 'off',
            'total_ms': round((time.perf_counter() - t_all) * 1000, 1),
            'img_ms': round((t_img - t_all) * 1000, 1),
            'tmp_ms': round((t_tmp - t_img) * 1000, 1),
        }
        if cache_key and isinstance(out, dict):
            if is_ai_source:
                _lru_set(_ai_result_cache, _ai_cache_lock,
                         cache_key, out, TP_AI_RESULT_CACHE_MAX)
            else:
                _lru_set(_result_cache, _result_cache_lock,
                         cache_key, out, TP_RESULT_CACHE_MAX)
        return out
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.on_event('startup')
async def _startup():
    print(
        f'[TextPhantom][api] starting build={BUILD_ID} workers={SERVER_MAX_WORKERS}')
    for i in range(max(1, SERVER_MAX_WORKERS)):
        asyncio.create_task(_worker_loop(i))
    asyncio.create_task(_cleanup_jobs_loop())

@app.get('/health')
async def health():
    return {'ok': True, 'build': BUILD_ID}

@app.get('/version')
async def version():
    return {'ok': True, 'build': BUILD_ID, 'core': 'lens_core'}

@app.get('/warmup')
async def warmup(lang: str = TP_WARMUP_LANG):
    t0 = time.perf_counter()
    r = core.warmup(lang)
    return {'ok': True, 'build': BUILD_ID, 'dt_ms': round((time.perf_counter() - t0) * 1000, 1), 'result': r}

@app.get('/meta')
async def meta():
    langs = getattr(core, 'UI_LANGUAGES', None) or []
    sources = [
        {'id': 'original', 'name': 'Original'},
        {'id': 'translated', 'name': 'Translated'},
        {'id': 'ai', 'name': 'Ai (API Key)'},
        {'id': 'cli', 'name': 'CLI Tools'},
    ]
    env_key = (os.getenv('AI_API_KEY') or '').strip()
    return {'ok': True, 'languages': langs, 'sources': sources, 'has_env_ai_key': bool(env_key)}

@app.post('/translate')
async def translate(payload: Dict[str, Any]):
    jid = str(uuid.uuid4())
    _trace('rest.enqueue', {
        'id': jid,
        'mode': str(payload.get('mode') or ''),
        'lang': str(payload.get('lang') or ''),
        'source': str(payload.get('source') or ''),
        'ai_provider': str(((payload.get('ai') or {}) if isinstance(payload.get('ai'), dict) else {}).get('provider') or ''),
        'ai_key_marker': str(((payload.get('ai') or {}) if isinstance(payload.get('ai'), dict) else {}).get('api_key') or '')[:40],
        'has_datauri': bool(payload.get('imageDataUri')),
        'has_src': bool(payload.get('src')),
    })
    _dbg('rest.enqueue', {
        'id': jid,
        'mode': str(payload.get('mode') or ''),
        'lang': str(payload.get('lang') or ''),
        'source': str(payload.get('source') or ''),
        'has_datauri': bool(payload.get('imageDataUri')),
        'has_src': bool(payload.get('src')),
    })
    _jobs[jid] = {'status': 'queued', 'ts': _now()}
    await _job_queue.put((jid, payload))
    return {'id': jid}

@app.get('/translate/{job_id}')
async def translate_status(job_id: str):
    j = _jobs.get(job_id)
    if not j:
        return {'status': 'error', 'result': 'job_not_found'}
    return j

@app.post('/ai/resolve')
async def ai_resolve(payload: Dict[str, Any]):
    requested_provider = core._canonical_provider(str(payload.get('provider') or 'auto'))
    api_key = str(payload.get('api_key') or '').strip() or (
        os.getenv('AI_API_KEY') or '').strip()
    lang = _normalize_lang(str(payload.get('lang') or 'en'))
    style_default = ((getattr(core, 'AI_LANG_STYLE', {}) or {}).get(lang) or (getattr(core, 'AI_LANG_STYLE', {}) or {}).get('default') or '').strip()
    if requested_provider == 'cli_gemini':
        requested_model = str(payload.get('model') or 'auto').strip() or 'auto'
        resolved_model = _resolve_model('cli_gemini', requested_model)
        models = list(getattr(core, 'CLI_GEMINI_MODELS', ['auto']))
        if resolved_model not in models:
            models.append(resolved_model)
        return {
            'ok': True,
            'provider': 'cli_gemini',
            'base_url': '',
            'default_model': 'auto',
            'model': resolved_model,
            'models': models,
            'reasoning_effort': str(payload.get('reasoning_effort') or 'medium').strip() or 'medium',
            'lang': lang,
            'prompt_editable_default': style_default,
        }
    if requested_provider == 'cli_codex':
        requested_model = str(payload.get('model') or 'auto').strip() or 'auto'
        resolved_model = _resolve_model('cli_codex', requested_model)
        models = list(getattr(core, 'CLI_CODEX_MODELS', ['auto']))
        if resolved_model not in models:
            models.append(resolved_model)
        return {
            'ok': True,
            'provider': 'cli_codex',
            'base_url': '',
            'default_model': 'auto',
            'model': resolved_model,
            'models': models,
            'lang': lang,
            'prompt_editable_default': style_default,
        }
    if not api_key:
        return {
            'ok': False,
            'error': 'missing_api_key',
            'error_detail': 'No API key provided. Please enter your AI API key.',
            'provider': '',
            'default_model': '',
            'models': [],
            'lang': lang,
            'prompt_editable_default': style_default,
        }

    provider = requested_provider
    if provider in ('', 'auto'):
        provider = _detect_provider_from_key(api_key)

    preset = _resolve_provider_defaults(provider) or {}
    requested_model = str(payload.get('model') or 'auto').strip() or 'auto'
    resolved_model = _resolve_model(provider, requested_model)

    models: List[str] = []
    base_url = (str(payload.get('base_url') or 'auto')).strip()
    if base_url in ('', 'auto'):
        base_url = (preset.get('base_url') or '').strip()

    validation_error = None

    try:
        if provider == 'huggingface':
            if base_url:
                models = core._hf_router_available_models(api_key, base_url)
            if requested_model.lower() in ('', 'auto'):
                fallback = core._pick_hf_fallback_model(models)
                if fallback:
                    resolved_model = fallback

        elif provider == 'gemini':
            models = getattr(core, '_gemini_available_models',
                             lambda _k: [])(api_key)
            if not models:
                models = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro',
                          'gemini-2.0-flash', 'gemini-3-flash-preview', 'gemini-3-pro-preview',
                          'gemma-2-2b-it', 'gemma-2-9b-it', 'gemma-2-27b-it',
                          'gemma-3-4b-it', 'gemma-3-12b-it', 'gemma-3-27b-it', 'gemma-4-preview',
                          'gemma-4-31b-it', 'gemma-4-26b-a4b-it']

        elif provider == 'anthropic':
            models = getattr(core, '_anthropic_available_models',
                             lambda _k, _b=None: [])(api_key, base_url)

        elif provider == 'local':
            if not base_url:
                base_url = (core.AI_PROVIDER_DEFAULTS.get('local') or {}).get(
                    'base_url') or 'http://127.0.0.1:8080/v1'
            try:
                models_url = base_url.rstrip('/') + '/models'
                with httpx.Client(timeout=8.0) as client:
                    r = client.get(models_url)
                    if r.status_code == 200:
                        data = r.json()
                        for m in (data.get('data') or []):
                            mid = (m.get('id') if isinstance(m, dict) else None)
                            if isinstance(mid, str) and mid.strip():
                                models.append(mid.strip())
                    else:
                        validation_error = {
                            'error': 'connection_error',
                            'error_detail': f'Local AI server returned HTTP {r.status_code}. Make sure the server is running at {base_url}',
                        }
            except httpx.ConnectError:
                validation_error = {
                    'error': 'connection_error',
                    'error_detail': f'Cannot connect to local AI server at {base_url}. Make sure it is running.',
                }
            except Exception as e:
                validation_error = {
                    'error': 'connection_error',
                    'error_detail': f'Error connecting to local AI: {str(e)[:200]}',
                }

        else:
            if not base_url:
                base_url = (core.AI_PROVIDER_DEFAULTS.get('openai') or {}).get(
                    'base_url') or 'https://api.openai.com/v1'
            models = getattr(core, '_openai_compat_available_models',
                             lambda _k, _b: [])(api_key, base_url)

    except Exception as e:
        err_str = str(e).lower()
        err_detail = str(e)[:300]

        if '401' in err_str or 'unauthorized' in err_str or 'invalid.*key' in err_str.replace(' ', ''):
            validation_error = {
                'error': 'invalid_api_key',
                'error_detail': f'API key rejected by {provider or "provider"}: {err_detail}',
            }
        elif '403' in err_str or 'forbidden' in err_str or 'permission' in err_str:
            validation_error = {
                'error': 'auth_error',
                'error_detail': f'Access denied by {provider or "provider"}: {err_detail}',
            }
        elif '429' in err_str or 'rate limit' in err_str or 'too many' in err_str:
            validation_error = {
                'error': 'rate_limited',
                'error_detail': f'Rate limited by {provider or "provider"}. Wait a moment and try again.',
            }
        elif 'connect' in err_str or 'timeout' in err_str or 'resolv' in err_str:
            validation_error = {
                'error': 'connection_error',
                'error_detail': f'Cannot reach {provider or "provider"} API: {err_detail}',
            }
        else:
            validation_error = {
                'error': 'provider_error',
                'error_detail': f'Error from {provider or "provider"}: {err_detail}',
            }

    if validation_error and not models:
        return {
            'ok': False,
            'provider': provider or '',
            'base_url': base_url or '',
            'default_model': (preset.get('model') or ''),
            'models': [],
            'lang': lang,
            'prompt_editable_default': style_default,
            **validation_error,
        }

    if provider == 'huggingface' and not models:
        models = [
            'google/gemma-3-27b-it:featherless-a',
            'google/gemma-3-27b-it',
            'google/gemma-2-2b-it',
            'google/gemma-2-9b-it',
        ]

    if provider != 'huggingface' and not models:
        fallback_models: List[str] = []
        preset_model = str(preset.get('model') or '').strip()
        if preset_model:
            fallback_models.append(preset_model)

        provider_defaults = (getattr(core, 'AI_PROVIDER_DEFAULTS', {}) or {}).get(
            provider, {}) or {}
        provider_model = str(provider_defaults.get('model') or '').strip()
        if provider_model:
            fallback_models.append(provider_model)

        if provider == 'gemini':
            fallback_models.extend([
                'gemini-2.5-flash',
                'gemini-2.5-flash-lite',
                'gemini-2.5-pro',
                'gemini-2.0-flash',
                'gemini-3-flash-preview',
                'gemini-3-pro-preview',
                'gemma-2-2b-it',
                'gemma-2-9b-it',
                'gemma-2-27b-it',
                'gemma-3-4b-it',
                'gemma-3-12b-it',
                'gemma-3-27b-it',
                'gemma-4-preview',
                'gemma-4-31b-it',
                'gemma-4-26b-a4b-it',
            ])

        models = sorted(set([m for m in fallback_models if m]), key=str.lower)

        if not models:
            all_models: List[str] = []
            for _, v in (getattr(core, 'AI_PROVIDER_DEFAULTS', {}) or {}).items():
                m2 = str((v or {}).get('model') or '').strip()
                if m2:
                    all_models.append(m2)
            models = sorted(set(all_models), key=str.lower)

    if models:
        models = sorted(
            {m.strip() for m in models if isinstance(m, str) and m.strip()},
            key=str.lower,
        )

    if models and resolved_model not in models:
        resolved_model = models[0]

    prompt_default = style_default

    return {
        'ok': True,
        'provider': provider,
        'base_url': base_url,
        'default_model': (preset.get('model') or ''),
        'model': resolved_model,
        'models': models,
        'prompt_editable_default': prompt_default,
    }

@app.get('/ai/prompt/default')
async def ai_prompt_default(lang: str = 'en'):
    l = _normalize_lang(lang)
    base = (getattr(core, 'AI_PROMPT_SYSTEM_BASE', '') or '').strip()
    style = (getattr(core, 'AI_LANG_STYLE', {}) or {}).get(l) or (
        getattr(core, 'AI_LANG_STYLE', {}) or {}).get('default') or ''
    style = (style or '').strip()
    contract = "\n".join([
        'Return ONLY valid JSON (no markdown, no extra text).',
        'Output JSON MUST have exactly one key: "aiTextFull".',
        'Schema example: {"aiTextFull":"..."}',
        'Markers: Keep every paragraph marker like <<TP_P0>> unchanged and in order. Do not remove or add markers.',
        "aiTextFull must include all markers, each followed by that paragraph's translated text.",
    ])
    system_text = "\n\n".join([p for p in [base, style, contract] if p])
    return {
        'ok': True,
        'lang': l,
        'prompt_editable_default': style,
        'lang_style': style,
        'system_base': base,
        'contract': contract,
        'system_text': system_text,
    }

@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps({'type': 'ack'}))
    try:
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)
            if data.get('type') != 'job':
                continue
            jid = str(data.get('id') or '')
            payload = data.get('payload') or {}
            _dbg('ws.job', {
                'id': jid,
                'mode': str(payload.get('mode') or ''),
                'lang': str(payload.get('lang') or ''),
                'source': str(payload.get('source') or ''),
                'has_datauri': bool(payload.get('imageDataUri')),
                'has_src': bool(payload.get('src')),
            })
            try:
                result = await asyncio.to_thread(_process_payload, payload)
                try:
                    await ws.send_text(json.dumps({'type': 'result', 'id': jid, 'result': result}))
                except WebSocketDisconnect:
                    return
            except Exception as e:
                try:
                    await ws.send_text(json.dumps({'type': 'error', 'id': jid, 'error': str(e)}))
                except (WebSocketDisconnect, RuntimeError):
                    return
    except WebSocketDisconnect:
        return

def main():
    image_path = getattr(core, 'IMAGE_PATH', '')
    lang = getattr(core, 'LANG', 'en')
    mode = os.environ.get('MODE', 'lens_text')
    ai_key = os.environ.get('AI_API_KEY', getattr(core, 'AI_API_KEY', ''))
    ai_model = os.environ.get('AI_MODEL', getattr(core, 'AI_MODEL', 'auto'))
    ai_prompt = os.environ.get('AI_PROMPT', '')

    ai_cfg = AiConfig(api_key=ai_key, model=ai_model,
                      prompt_editable=ai_prompt) if ai_key and mode == 'lens_text' else None
    out = process_image_path(image_path, lang, mode, ai_cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

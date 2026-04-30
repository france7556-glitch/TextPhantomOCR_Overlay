import { normalizeUrl } from "../shared/url.js";
import { ensureApiDefaults } from "../shared/api_defaults.js";
import { AI_PROMPT_MAX_CHARS, makePromptKey, migratePromptMap, normalizeAiModel, normalizePrompt } from "../shared/prompt.js";
import { filterImageFiles, saveLocalSession, sortLocalPages, toLocalPageRecord } from "../shared/local_gallery.js";

const MODES = [
  { id: "lens_images", name: "Google Lens (image)", needLang: true },
  { id: "lens_text", name: "Google Lens (text)", needLang: true },
];

const FALLBACK_LANGS = [
  { code: "en", name: "English" },
  { code: "th", name: "Thai" },
  { code: "ja", name: "Japanese" },
  { code: "ko", name: "Korean" },
  { code: "zh-CN", name: "Chinese (Simplified)" },
  { code: "zh-TW", name: "Chinese (Traditional)" },
  { code: "vi", name: "Vietnamese" },
  { code: "id", name: "Indonesian" },
  { code: "ms", name: "Malay" },
  { code: "tl", name: "Tagalog" },
  { code: "fil", name: "Filipino" },
  { code: "hi", name: "Hindi" },
  { code: "bn", name: "Bengali" },
  { code: "ur", name: "Urdu" },
  { code: "ta", name: "Tamil" },
  { code: "te", name: "Telugu" },
  { code: "ml", name: "Malayalam" },
  { code: "mr", name: "Marathi" },
  { code: "gu", name: "Gujarati" },
  { code: "kn", name: "Kannada" },
  { code: "pa", name: "Punjabi" },
  { code: "ne", name: "Nepali" },
  { code: "si", name: "Sinhala" },
  { code: "my", name: "Myanmar (Burmese)" },
  { code: "km", name: "Khmer" },
  { code: "lo", name: "Lao" },
  { code: "jv", name: "Javanese" },
  { code: "su", name: "Sundanese" },
  { code: "es", name: "Spanish" },
  { code: "fr", name: "French" },
  { code: "de", name: "German" },
  { code: "it", name: "Italian" },
  { code: "pt", name: "Portuguese" },
  { code: "nl", name: "Dutch" },
  { code: "pl", name: "Polish" },
  { code: "ro", name: "Romanian" },
  { code: "ru", name: "Russian" },
  { code: "uk", name: "Ukrainian" },
  { code: "cs", name: "Czech" },
  { code: "sk", name: "Slovak" },
  { code: "sl", name: "Slovenian" },
  { code: "hr", name: "Croatian" },
  { code: "sr", name: "Serbian" },
  { code: "bs", name: "Bosnian" },
  { code: "bg", name: "Bulgarian" },
  { code: "mk", name: "Macedonian" },
  { code: "el", name: "Greek" },
  { code: "tr", name: "Turkish" },
  { code: "hu", name: "Hungarian" },
  { code: "fi", name: "Finnish" },
  { code: "sv", name: "Swedish" },
  { code: "da", name: "Danish" },
  { code: "no", name: "Norwegian" },
  { code: "et", name: "Estonian" },
  { code: "lv", name: "Latvian" },
  { code: "lt", name: "Lithuanian" },
  { code: "is", name: "Icelandic" },
  { code: "ga", name: "Irish" },
  { code: "cy", name: "Welsh" },
  { code: "mt", name: "Maltese" },
  { code: "sq", name: "Albanian" },
  { code: "hy", name: "Armenian" },
  { code: "ka", name: "Georgian" },
  { code: "az", name: "Azerbaijani" },
  { code: "kk", name: "Kazakh" },
  { code: "ky", name: "Kyrgyz" },
  { code: "tg", name: "Tajik" },
  { code: "uz", name: "Uzbek" },
  { code: "tk", name: "Turkmen" },
  { code: "mn", name: "Mongolian" },
  { code: "ar", name: "Arabic" },
  { code: "fa", name: "Persian" },
  { code: "iw", name: "Hebrew" },
  { code: "ps", name: "Pashto" },
  { code: "ug", name: "Uyghur" },
  { code: "ku", name: "Kurdish (Kurmanji)" },
  { code: "sw", name: "Swahili" },
  { code: "am", name: "Amharic" },
  { code: "ha", name: "Hausa" },
  { code: "ig", name: "Igbo" },
  { code: "yo", name: "Yoruba" },
  { code: "zu", name: "Zulu" },
  { code: "xh", name: "Xhosa" },
  { code: "so", name: "Somali" },
  { code: "rw", name: "Kinyarwanda" },
  { code: "mg", name: "Malagasy" },
  { code: "af", name: "Afrikaans" },
  { code: "ca", name: "Catalan" },
  { code: "eu", name: "Basque" },
  { code: "gl", name: "Galician" },
  { code: "eo", name: "Esperanto" },
  { code: "be", name: "Belarusian" },
  { code: "ceb", name: "Cebuano" },
  { code: "co", name: "Corsican" },
  { code: "fy", name: "Frisian" },
  { code: "haw", name: "Hawaiian" },
  { code: "hmn", name: "Hmong" },
  { code: "ht", name: "Haitian Creole" },
  { code: "lb", name: "Luxembourgish" },
  { code: "la", name: "Latin" },
  { code: "mi", name: "Maori" },
  { code: "or", name: "Odia (Oriya)" },
  { code: "gd", name: "Scots Gaelic" },
  { code: "sm", name: "Samoan" },
  { code: "sn", name: "Shona" },
  { code: "st", name: "Sesotho" },
  { code: "sd", name: "Sindhi" },
  { code: "tt", name: "Tatar" },
  { code: "yi", name: "Yiddish" },
  { code: "ny", name: "Chichewa" }
];

const FALLBACK_SOURCES = [
  { id: "original", name: "Original" },
  { id: "translated", name: "Translated" },
  { id: "ai", name: "Ai" },
  { id: "cli", name: "CLI Tools" },
];

const HEALTH_PATH = "/health";
const META_PATH = "/meta";
const AI_RESOLVE_PATH = "/ai/resolve";
const AI_PROMPT_DEFAULT_PATH = "/ai/prompt/default";
const WARMUP_PATH = "/warmup";

const HEALTH_TIMEOUT_MS = 5000;
const AI_META_TIMEOUT_MS = 8000;
const PROMPT_TIMEOUT_MS = 8000;
const WARMUP_TIMEOUT_MS = 2500;
const RETRY_DELAYS_MS = [600, 1200, 2500, 5000];

const CLI_GEMINI_MODELS = [
  "auto",
  "pro",
  "flash",
  "flash-lite",
  "gemini-3.1-pro-preview",
  "gemini-3-pro-preview",
  "gemini-3-flash-preview",
  "gemini-2.5-pro",
  "gemini-2.5-flash",
  "gemini-2.5-flash-lite",
];

const CLI_CODEX_MODELS = [
  "auto",
  "gpt-5.5",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.3-codex",
  "gpt-5.2",
];

const modeSel = document.getElementById("mode");
const langSel = document.getElementById("lang");
const sourcesSel = document.getElementById("sources");
const langWrap = document.getElementById("lang-wrap");
const sourcesWrap = document.getElementById("sources-wrap");
const cliToolWrap = document.getElementById("cli-tool-wrap");
const cliToolSel = document.getElementById("cli-tool");
const aiKeyWrap = document.getElementById("ai-key-wrap");
const aiKeyInput = document.getElementById("ai-key");
const aiBaseUrlWrap = document.getElementById("ai-baseurl-wrap");
const aiBaseUrlInput = document.getElementById("ai-baseurl");
const aiModelWrap = document.getElementById("ai-model-wrap");
const aiModelSel = document.getElementById("ai-model");
const codexEffortWrap = document.getElementById("codex-effort-wrap");
const codexEffortSel = document.getElementById("codex-effort");
const aiPromptWrap = document.getElementById("ai-prompt-wrap");
const aiPromptInput = document.getElementById("ai-prompt");
const aiPromptCountEl = document.getElementById("ai-prompt-count");
const aiPromptResetBtn = document.getElementById("ai-prompt-reset");
const aiKeyStatusEl = document.getElementById("ai-key-status");
const aiKeyErrorEl = document.getElementById("ai-key-error");
const apiInput = document.getElementById("api-url");
const emojiEl = document.getElementById("api-status-emoji");
const resetBtn = document.getElementById("reset-api");
const openLocalImagesBtn = document.getElementById("open-local-images");
const openLocalFolderBtn = document.getElementById("open-local-folder");
const localImagesInput = document.getElementById("local-images-input");
const localFolderInput = document.getElementById("local-folder-input");

const runStatusTextEl = document.getElementById("run-status-text");
const runProgressEl = document.querySelector(".run-progress");
const runProgressBarEl = document.getElementById("run-progress-bar");
const runStatusSubEl = document.getElementById("run-status-sub");

aiPromptResetBtn?.addEventListener("click", async () => {
  await resetPromptForLang(langSel.value);
});

let userInteractedApi = false;
let lastApiOk = false;
let lastSavedApiUrl = "";
let retryTimer = null;
let metaCache = null;
let modelDirty = false;
let aiMetaSeq = 0;
let promptSeq = 0;
let lastResolvedProvider = "";
let lastResolvedKey = "";

let desiredLang = "en";
let desiredSources = "translated";
let desiredCliTool = "cli_gemini";
let desiredAiModel = "auto";
let desiredAiBaseUrl = "";
let desiredCodexEffort = "medium";

let aiPromptByLangState = {};
let aiPromptDefaultsByLang = {};
let aiPromptDirtyByLang = {};

let pendingApiSave = false;
let pendingAiSave = false;
let aiResolveDebounce = null;

let apiDefaults = { defaultApiUrl: "", resetApiUrl: "", fetchedAt: 0 };

const inFlight = {
  seq: 0,
  controller: null,
};

function updatePromptCount(text = null) {
  if (!aiPromptCountEl) return;
  const s = typeof text === "string" ? text : String(aiPromptInput?.value || "");
  aiPromptCountEl.textContent = `${s.length}/${AI_PROMPT_MAX_CHARS}`;
}

function buildUrl(path, params = null) {
  const base = normalizeUrl(apiInput?.value);
  if (!base) return "";
  const u = new URL(`${base}${path}`);
  if (params && typeof params === "object") {
    for (const [k, v] of Object.entries(params)) {
      const vv = String(v ?? "").trim();
      if (vv) u.searchParams.set(k, vv);
    }
  }
  return u.toString();
}

function setEmojiStatus(type, detail) {
  if (!emojiEl) return;
  if (type === "loading") {
    emojiEl.textContent = "⏳";
    emojiEl.title = detail || "Checking API...";
  } else if (type === "ok") {
    emojiEl.textContent = "✅";
    emojiEl.title = detail || "Online";
  } else {
    emojiEl.textContent = "❌";
    emojiEl.title = detail || "Offline / Not reachable";
  }
}

function setAiKeyStatus(type, detail, errorDetail) {
  if (!aiKeyStatusEl) return;
  if (type === "loading") {
    aiKeyStatusEl.textContent = "⏳";
    aiKeyStatusEl.title = detail || "Validating key...";
  } else if (type === "ok") {
    aiKeyStatusEl.textContent = "✅";
    aiKeyStatusEl.title = detail || "Key valid";
  } else if (type === "error") {
    aiKeyStatusEl.textContent = "❌";
    aiKeyStatusEl.title = detail || "Key invalid";
  } else if (type === "warning") {
    aiKeyStatusEl.textContent = "⚠️";
    aiKeyStatusEl.title = detail || "Warning";
  } else {
    aiKeyStatusEl.textContent = "";
    aiKeyStatusEl.title = "";
  }

  if (aiKeyErrorEl) {
    if (errorDetail && (type === "error" || type === "warning")) {
      aiKeyErrorEl.textContent = errorDetail;
      aiKeyErrorEl.className = "ai-status-msg status-" + type;
      aiKeyErrorEl.style.display = "";
    } else if (type === "ok" && detail) {
      aiKeyErrorEl.textContent = detail;
      aiKeyErrorEl.className = "ai-status-msg status-ok";
      aiKeyErrorEl.style.display = "";
    } else {
      aiKeyErrorEl.style.display = "none";
      aiKeyErrorEl.textContent = "";
      aiKeyErrorEl.className = "ai-status-msg";
    }
  }
}

function renderBatchStatus(b) {
  if (!runStatusTextEl || !runProgressEl || !runProgressBarEl) return;
  const batch = b && typeof b === "object" ? b : null;
  const stats = batch && batch.stats && typeof batch.stats === "object" ? batch.stats : null;
  const total = Number(stats?.total) || 0;
  const finished = Number(stats?.finished) || 0;
  const msg = typeof batch?.message === "string" && batch.message ? batch.message : "Idle";
  runStatusTextEl.textContent = msg;
  const pct = total ? Math.max(0, Math.min(100, Math.round((finished / total) * 100))) : 0;
  runProgressBarEl.style.width = pct + "%";
  runProgressEl.setAttribute("aria-valuenow", String(pct));
  if (runStatusSubEl) {
    if (total) {
      const pass = Number(batch?.pass) || 1;
      const stage = typeof batch?.stage === "string" ? batch.stage : "";
      const extra = stage ? `• ${stage}` : "";
      runStatusSubEl.textContent = `pass ${pass} • ${finished}/${total} ${extra}`.trim();
    } else {
      runStatusSubEl.textContent = "";
    }
  }
}

function initRunStatus() {
  try {
    chrome.runtime.sendMessage({ type: "GET_BATCH_STATUS" }, (resp) => {
      renderBatchStatus(resp?.batch);
    });
  } catch {}

  try {
    chrome.runtime.onMessage.addListener((msg) => {
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "BATCH_STATUS_UPDATE") renderBatchStatus(msg.batch);
    });
  } catch {}
}


const warmedApi = new Set();
async function warmupApi(base) {
  const b = normalizeUrl(base);
  if (!b || warmedApi.has(b)) return;
  warmedApi.add(b);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), WARMUP_TIMEOUT_MS);
  try {
    await fetch(`${b}${WARMUP_PATH}`, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
  } catch {
  } finally {
    clearTimeout(timeout);
  }
}

function abortInFlight() {
  if (inFlight.controller) {
    try {
      inFlight.controller.abort();
    } catch {}
  }
  inFlight.controller = null;
}

function scheduleRetry(url, attemptIndex) {
  clearTimeout(retryTimer);
  if (attemptIndex >= RETRY_DELAYS_MS.length) return;
  const delay = RETRY_DELAYS_MS[attemptIndex];
  retryTimer = setTimeout(() => {
    if (normalizeUrl(apiInput.value) === url) checkHealth(url, attemptIndex);
  }, delay);
}

async function parseHealth(res) {
  try {
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return await res.json();
  } catch {}
  try {
    const txt = await res.text();
    return { ok: /\bok\b/i.test(txt), raw: txt };
  } catch {
    return null;
  }
}

async function checkHealthOnce(url, seq) {
  const controller = new AbortController();
  inFlight.controller = controller;
  const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    const res = await fetch(`${url}${HEALTH_PATH}`, {
      method: "GET",
      headers: { accept: "application/json, text/plain;q=0.8" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = await parseHealth(res);
    if (!data || !data.ok) throw new Error("unhealthy");
    if (seq !== inFlight.seq) return false;
    return true;
  } finally {
    clearTimeout(timeout);
  }
}

async function checkHealth(url, attemptIndex = 0) {
  const cleaned = normalizeUrl(url);
  if (!cleaned) return;
  inFlight.seq += 1;
  const seq = inFlight.seq;
  abortInFlight();
  setEmojiStatus(
    userInteractedApi ? "loading" : "loading",
    userInteractedApi ? "Checking API..." : "Waiting…",
  );
  try {
    const healthy = await checkHealthOnce(cleaned, seq);
    if (seq !== inFlight.seq) return;
    lastApiOk = healthy;
    if (healthy) {
      clearTimeout(retryTimer);
      setEmojiStatus("ok", "Online");
      warmupApi(cleaned);
      refreshMeta(cleaned);
    } else {
      setEmojiStatus("error", userInteractedApi ? "Health failed" : "Waiting…");
      scheduleRetry(cleaned, attemptIndex);
    }
  } catch (err) {
    if (seq !== inFlight.seq) return;
    lastApiOk = false;
    const msg =
      err && err.name === "AbortError"
        ? "Timed out"
        : err?.message || "Offline";
    setEmojiStatus(
      userInteractedApi ? "error" : "loading",
      userInteractedApi ? msg : "Waiting…",
    );
    scheduleRetry(cleaned, attemptIndex);
  }
}

async function fetchJson(url, body, timeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: body ? "POST" : "GET",
      headers: body
        ? { "Content-Type": "application/json", accept: "application/json" }
        : { accept: "application/json" },
      cache: "no-store",
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`status ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timeout);
  }
}

function setSelectOptions(
  sel,
  list,
  { valueKey = "id", labelKey = "name", keepValue = "" } = {},
) {
  const prev = keepValue || sel.value || "";
  sel.innerHTML = "";
  const items = Array.isArray(list) ? list : [];
  for (const it of items) {
    const opt = document.createElement("option");
    opt.value = String(it?.[valueKey] ?? "");
    opt.textContent = String(it?.[labelKey] ?? opt.value);
    sel.appendChild(opt);
  }
  const canKeep = [...sel.options].some((o) => o.value === prev);
  if (canKeep) sel.value = prev;
}

function populateModes() {
  setSelectOptions(modeSel, MODES, {
    valueKey: "id",
    labelKey: "name",
    keepValue: modeSel.value,
  });
}

function isLocalAiKey(key) {
  const k = (key || "").trim().toLowerCase();
  return ["local", "ollama", "lmstudio", "llama", "llama-server", "localhost", "none", "dummy", "no-key"].includes(k) || k.startsWith("local-") || k.startsWith("local_");
}

function normalizeCodexEffort(effort) {
  const e = String(effort || "").trim().toLowerCase();
  return ["low", "medium", "high", "xhigh"].includes(e) ? e : "medium";
}

function toggleUi() {
  const modeId = modeSel.value || "lens_text";
  const isText = modeId === "lens_text";
  sourcesWrap.style.display = isText ? "" : "none";

  const source = (sourcesSel.value || "").trim() || "translated";
  const needLang = MODES.find((m) => m.id === modeId)?.needLang ?? true;
  const showLang = needLang && !(isText && source === "original");
  langWrap.style.display = showLang ? "" : "none";
  
  const isAiSource = source === "ai" || source === "cli";
  const isCliSource = source === "cli";
  const showAi = isText && isAiSource;

  cliToolWrap.style.display = isCliSource ? "" : "none";

  const hasEnv = Boolean(metaCache?.has_env_ai_key);
  const hasKey = (aiKeyInput.value || "").trim().length > 0;
  const canConfigureAi = (hasKey || hasEnv) && !isCliSource;
  const showBaseUrl = showAi && canConfigureAi && isLocalAiKey(aiKeyInput.value);

  aiKeyWrap.style.display = (showAi && !isCliSource) ? "" : "none";
  if (aiBaseUrlWrap) aiBaseUrlWrap.style.display = showBaseUrl ? "" : "none";
  aiModelWrap.style.display = (showAi && (canConfigureAi || isCliSource)) ? "" : "none";
  if (codexEffortWrap) codexEffortWrap.style.display = showAi && isCliSource && cliToolSel.value === "cli_codex" ? "" : "none";
  aiPromptWrap.style.display = showAi && (canConfigureAi || isCliSource) ? "" : "none";
}

async function refreshMeta(baseUrl) {
  const url = `${baseUrl}${META_PATH}`;
  try {
    const data = await fetchJson(url, null, HEALTH_TIMEOUT_MS);
    if (data && data.ok) {
      metaCache = data;
      const langs =
        Array.isArray(data.languages) && data.languages.length
          ? data.languages
          : FALLBACK_LANGS;
      const sources =
        Array.isArray(data.sources) && data.sources.length
          ? data.sources
          : FALLBACK_SOURCES;
      const beforeLang = langSel.value;
      const beforeSources = sourcesSel.value;
      setSelectOptions(langSel, langs, {
        valueKey: "code",
        labelKey: "name",
        keepValue: desiredLang || beforeLang,
      });
      setSelectOptions(sourcesSel, sources, {
        valueKey: "id",
        labelKey: "name",
        keepValue: desiredSources || beforeSources,
      });

      const afterLang = langSel.value;
      const afterSources = sourcesSel.value;
      const afterCliTool = cliToolSel?.value;
      const patch = {};
      if (afterLang && afterLang !== desiredLang) {
        desiredLang = afterLang;
        patch.lang = afterLang;
      }
      if (afterSources && afterSources !== desiredSources) {
        desiredSources = afterSources;
        patch.sources = afterSources;
      }
      if (afterCliTool && afterCliTool !== desiredCliTool) {
        desiredCliTool = afterCliTool;
        patch.cliTool = afterCliTool;
      }
      if (Object.keys(patch).length) await chrome.storage.local.set(patch);
      toggleUi();
      if (shouldRefreshAiMetaForCurrentUi()) refreshAiMeta({ forcePrompt: false });
    }
  } catch {}
}

async function ensureAiAvailableOrFallback() {
  const modeId = modeSel.value || "lens_text";
  if (modeId !== "lens_text") return true;

  const source = (sourcesSel.value || "").trim() || "translated";
  if (source !== "ai" && source !== "cli") return true;
  if (source === "cli") return true;

  const hasEnv = Boolean(metaCache?.has_env_ai_key);
  const hasKey = (aiKeyInput.value || "").trim().length > 0;
  if (hasKey || hasEnv) return true;

  toggleUi();
  return false;
}

function setModelOptions(models, { keepValue = "", strict = true } = {}) {
  const prev =
    (keepValue || aiModelSel.value || desiredAiModel || "auto").trim() ||
    "auto";
  aiModelSel.innerHTML = "";
  const base = [{ id: "auto", name: "auto" }];
  const seen = new Set(base.map((m) => m.id));
  const list = (Array.isArray(models) ? models : [])
    .map((m) => ({
      id: String(m || ""),
      name: String(m || ""),
    }))
    .filter((m) => m.id && !seen.has(m.id) && seen.add(m.id))
    .sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
    );
  const optionIds = new Set(base.concat(list).map((m) => m.id));
  const canKeep = prev && optionIds.has(prev);
  if (!strict && prev && prev !== "auto" && !canKeep)
    list.unshift({ id: prev, name: prev });
  for (const it of base.concat(list)) {
    const opt = document.createElement("option");
    opt.value = it.id;
    opt.textContent = it.name;
    aiModelSel.appendChild(opt);
  }
  aiModelSel.value = canKeep ? prev : "auto";
}

function shouldRefreshAiMetaForCurrentUi() {
  return (
    (modeSel.value || "lens_text") === "lens_text" &&
    ["ai", "cli"].includes((sourcesSel.value || "").trim())
  );
}

function currentModelOptionsFallback() {
  const source = (sourcesSel.value || "").trim();
  const cliTool = cliToolSel.value || "cli_gemini";
  if (source === "cli" && cliTool === "cli_gemini") {
    return CLI_GEMINI_MODELS;
  }
  if (source === "cli" && cliTool === "cli_codex") {
    return CLI_CODEX_MODELS;
  }
  return [];
}

function selectedAiModelValue() {
  const selected = normalizeAiModel((aiModelSel.value || "").trim());
  const hasOnlyAuto =
    aiModelSel.options.length === 1 &&
    (aiModelSel.options[0]?.value || "") === "auto";
  if (hasOnlyAuto && desiredAiModel && desiredAiModel !== "auto") {
    return desiredAiModel;
  }
  return selected || desiredAiModel || "auto";
}

async function refreshAiMeta({ forcePrompt = false } = {}) {
  const modeId = modeSel.value || "lens_text";
  if (modeId !== "lens_text") return;

  const ok = await ensureAiAvailableOrFallback();
  if (!ok) return;

  const base = normalizeUrl(apiInput.value);
  if (!base) return;

  const source = (sourcesSel.value || "").trim() || "translated";
  if (source !== "ai" && source !== "cli") {
    setModelOptions([], { keepValue: "auto" });
    setAiKeyStatus("none");
    return;
  }

  const fallbackModels = currentModelOptionsFallback();
  if (fallbackModels.length) {
    setModelOptions(fallbackModels, { keepValue: desiredAiModel, strict: true });
  }

  if (source === "cli" && !["cli_gemini", "cli_codex"].includes(cliToolSel.value)) {
    const providerLabel = cliToolSel.value === "cli_gemini" ? "Gemini CLI" : "Codex CLI";
    setAiKeyStatus("ok", `✓ ${providerLabel} ready`);
    setModelOptions([], { keepValue: "auto" });
    if (forcePrompt) await applyPromptForLang(langSel.value, { forceFetch: true });
    toggleUi();
    return;
  }

  const seq = ++aiMetaSeq;
  const isCliSource = source === "cli";
  const aiKey = isCliSource ? (cliToolSel.value || "cli_gemini") : (aiKeyInput.value || "").trim();

  if (!isCliSource && !aiKey) {
    setAiKeyStatus("none");
    return;
  }

  setAiKeyStatus("loading", "Validating key...");

  try {
    const lang = langSel.value || "en";
    const currentModel =
      selectedAiModelValue();

    const aiBaseUrl = (aiBaseUrlInput?.value || "").trim() || "";
    const data = await fetchJson(
      `${base}${AI_RESOLVE_PATH}`,
      {
        api_key: aiKey,
        model: currentModel,
        lang,
        base_url: aiBaseUrl || "auto",
        provider: isCliSource ? (cliToolSel.value || "cli_gemini") : "auto",
        reasoning_effort: normalizeCodexEffort(codexEffortSel?.value || desiredCodexEffort),
      },
      AI_META_TIMEOUT_MS,
    );
    if (seq !== aiMetaSeq) return;

    if (!data || !data.ok) {
      const errCode = String(data?.error || "").trim();
      const errDetail = String(data?.error_detail || "").trim();
      let shortMsg = "Key invalid";
      let longMsg = "";

      if (errCode === "missing_api_key") {
        shortMsg = "No API key provided";
        longMsg = "Please enter your AI API key.";
      } else if (errCode === "invalid_api_key") {
        shortMsg = "Invalid API key";
        longMsg = errDetail || "The API key was rejected by the provider. Please check and re-enter.";
      } else if (errCode === "auth_error") {
        shortMsg = "Authentication failed";
        longMsg = errDetail || "Could not authenticate with the AI provider.";
      } else if (errCode === "rate_limited") {
        shortMsg = "Rate limited";
        longMsg = errDetail || "Too many requests. Please wait a moment and try again.";
        setAiKeyStatus("warning", shortMsg, longMsg);
        setModelOptions([], { keepValue: currentModel, strict: false });
        toggleUi();
        return;
      } else if (errCode === "provider_error") {
        shortMsg = "Provider error";
        longMsg = errDetail || "Could not connect to the AI provider.";
      } else if (errCode === "connection_error") {
        shortMsg = "Connection error";
        longMsg = errDetail || "Could not reach the AI provider's API.";
      } else if (errDetail) {
        longMsg = errDetail;
      } else if (errCode) {
        longMsg = `Error: ${errCode}`;
      }

      setAiKeyStatus("error", shortMsg, longMsg || shortMsg);
      setModelOptions([], { keepValue: currentModel, strict: false });
      toggleUi();
      return;
    }

    const provider = String(data.provider || "").trim();
    const keyChanged = aiKey !== lastResolvedKey;
    const providerChanged = Boolean(
      lastResolvedProvider &&
      provider &&
      provider !== lastResolvedProvider &&
      keyChanged,
    );

    if (provider) lastResolvedProvider = provider;
    lastResolvedKey = aiKey;

    const models = Array.isArray(data.models) ? data.models : [];
    const preferred =
      (modelDirty
        ? (aiModelSel.value || "").trim()
        : (desiredAiModel || "").trim()) ||
      currentModel ||
      "auto";
    setModelOptions(models, { keepValue: preferred, strict: true });

    const optionValues = [...aiModelSel.options].map((o) => o.value);
    let nextModel = (aiModelSel.value || "").trim() || "auto";
    if (!optionValues.includes(nextModel) || nextModel === "") {
      const suggested = String(data.model || "").trim();
      if (suggested && optionValues.includes(suggested)) nextModel = suggested;
      else nextModel = "auto";
    } else if (
      providerChanged &&
      nextModel !== "auto" &&
      !optionValues.includes(nextModel)
    ) {
      nextModel = "auto";
    }

    if ((aiModelSel.value || "").trim() !== nextModel) aiModelSel.value = nextModel;

    if (nextModel !== currentModel) {
      desiredAiModel = nextModel;
      if (isCliSource) await chrome.storage.local.set({ aiModel: nextModel });
      else await chrome.storage.local.set({ aiKey, aiModel: nextModel });
    } else {
      if (!isCliSource) await chrome.storage.local.set({ aiKey });
    }

    // Show success status
    const providerLabel = provider
      ? provider.charAt(0).toUpperCase() + provider.slice(1)
      : "AI";
    const modelCount = models.length;
    const okMsg = modelCount
      ? `✓ ${providerLabel} — ${modelCount} model${modelCount > 1 ? "s" : ""} available`
      : `✓ ${providerLabel} connected`;
    setAiKeyStatus("ok", okMsg, okMsg);

    if (forcePrompt) await applyPromptForLang(lang, { forceFetch: true });

    toggleUi();
  } catch (err) {
    if (seq !== aiMetaSeq) return;
    const msg = err?.message || String(err);
    let shortMsg = "Validation failed";
    let longMsg = msg;

    if (err?.name === "AbortError" || msg.includes("abort")) {
      shortMsg = "Timeout";
      longMsg = "Key validation timed out. The API server may be slow or unreachable.";
    } else if (msg.includes("Failed to fetch") || msg.includes("NetworkError")) {
      shortMsg = "Network error";
      longMsg = "Cannot reach the API server. Make sure it is running.";
    } else if (msg.includes("status 4")) {
      const m = msg.match(/status\s*(\d+)/);
      const code = m ? m[1] : "";
      if (code === "401" || code === "403") {
        shortMsg = "Invalid API key";
        longMsg = `Server returned HTTP ${code}. The key may be wrong or expired.`;
      } else {
        shortMsg = `HTTP error ${code}`;
        longMsg = msg;
      }
    }

    setAiKeyStatus("error", shortMsg, longMsg);
  }
}

function canUseAiUi() {
  const modeId = modeSel.value || "lens_text";
  if (modeId !== "lens_text") return false;
  const source = (sourcesSel.value || "").trim() || "translated";
  return source === "ai" || source === "cli";
}

async function fetchDefaultPromptForLang(lang, model = 'auto') {
  const l = (lang || 'en').trim() || 'en';
  const m2 = normalizeAiModel(model);
  const url = buildUrl(AI_PROMPT_DEFAULT_PATH, { lang: l, model: m2 });
  if (!url) return '';
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROMPT_TIMEOUT_MS);
  const resp = await fetch(url, { signal: ctrl.signal }).catch(() => null);
  clearTimeout(timer);
  const data = resp ? await resp.json().catch(() => null) : null;
  const p2 = data && data.ok ? String(data.prompt_editable_default || '').trim() : '';
  return normalizePrompt(p2);
}

async function resetPromptForLang(lang) {
  if (!canUseAiUi()) return;
  const l = (lang || desiredLang || langSel.value || 'en').trim() || 'en';
  const model = normalizeAiModel(desiredAiModel);
  const key = makePromptKey(l, model);
  const seq = ++promptSeq;

  const cached = String(aiPromptDefaultsByLang[key] || '').trim();
  const def = cached ? normalizePrompt(cached) : await fetchDefaultPromptForLang(l, model);
  if (seq !== promptSeq) return;

  aiPromptDefaultsByLang[key] = def;
  aiPromptByLangState[key] = def;
  aiPromptDirtyByLang[key] = false;

  aiPromptInput.value = def;
  updatePromptCount(def);
  await chrome.storage.local.set({ aiPromptByLang: aiPromptByLangState });
  chrome.runtime.sendMessage({ type: 'AI_SETTINGS_CHANGED' });
}

async function applyPromptForLang(lang, { forceFetch = false } = {}) {
  if (!canUseAiUi()) return;
  const l = (lang || desiredLang || langSel.value || 'en').trim() || 'en';
  const model = normalizeAiModel(desiredAiModel);
  const key = makePromptKey(l, model);
  if (aiPromptDirtyByLang[key]) return;
  if (Object.prototype.hasOwnProperty.call(aiPromptByLangState, key) && !forceFetch) {
    const saved = String(aiPromptByLangState[key] || '');
    aiPromptInput.value = saved;
    updatePromptCount(saved);
    return;
  }
  if (Object.prototype.hasOwnProperty.call(aiPromptDefaultsByLang, key) && !forceFetch) {
    const def = String(aiPromptDefaultsByLang[key] || '');
    aiPromptInput.value = def;
    updatePromptCount(def);
    return;
  }
  const def = await fetchDefaultPromptForLang(l, model);
  aiPromptDefaultsByLang[key] = def;
  aiPromptInput.value = def;
  updatePromptCount(def);
}

async function flushPromptForLang(lang, model = null) {
  if (!canUseAiUi()) return;
  const l = (lang || desiredLang || langSel.value || 'en').trim() || 'en';
  const m2 = normalizeAiModel(model || desiredAiModel);
  const key = makePromptKey(l, m2);
  if (!aiPromptDirtyByLang[key]) return;
  const prompt = normalizePrompt(String(aiPromptInput.value || ''));
  aiPromptByLangState[key] = prompt;
  aiPromptDirtyByLang[key] = false;
  await chrome.storage.local.set({ aiPromptByLang: aiPromptByLangState });
}

let debounceTimer = null;
function scheduleSaveApi(raw) {
  clearTimeout(debounceTimer);
  pendingApiSave = true;
  debounceTimer = setTimeout(async () => {
    pendingApiSave = false;
    const normalized = normalizeUrl(raw);
    if (!normalized) return;

    if (normalized === lastSavedApiUrl) {
      checkHealth(normalized);
      return;
    }

    userInteractedApi = true;
    await chrome.storage.local.set({ customApiUrl: normalized });
    lastSavedApiUrl = normalized;
    chrome.runtime.sendMessage({ type: "API_URL_CHANGED" });
    setEmojiStatus("loading", "Checking API...");
    checkHealth(normalized);
    refreshAiMeta({ forcePrompt: false });
  }, 800);
}

let aiDebounce = null;
function scheduleSaveAi() {
  clearTimeout(aiDebounce);
  pendingAiSave = true;
  aiDebounce = setTimeout(async () => {
    pendingAiSave = false;
    const modeId = modeSel.value || "lens_text";
    const aiBaseUrl = (aiBaseUrlInput?.value || "").trim();
    desiredAiBaseUrl = aiBaseUrl;
    if (modeId !== "lens_text") {
      const aiKey = (aiKeyInput.value || "").trim();
      const aiModel = selectedAiModelValue();
      desiredAiModel = aiModel;
      const codexEffort = normalizeCodexEffort(codexEffortSel?.value || desiredCodexEffort);
      desiredCodexEffort = codexEffort;
      await chrome.storage.local.set({ aiKey, aiModel, aiBaseUrl, codexEffort });
      chrome.runtime.sendMessage({ type: "AI_SETTINGS_CHANGED" });
      return;
    }

    const source = (sourcesSel.value || "").trim() || "translated";
    const lang = desiredLang || langSel.value || "en";
    const aiKey = (aiKeyInput.value || "").trim();
    const aiModel = selectedAiModelValue();
    const codexEffort = normalizeCodexEffort(codexEffortSel?.value || desiredCodexEffort);
    desiredAiModel = aiModel;
    desiredCodexEffort = codexEffort;

    const key = makePromptKey(lang, aiModel);
    if (aiPromptDirtyByLang[key]) {
      const prompt = normalizePrompt(String(aiPromptInput.value || ""));
      aiPromptByLangState[key] = prompt;
      aiPromptDirtyByLang[key] = false;
    }

    await chrome.storage.local.set({
      aiKey,
      aiModel,
      aiBaseUrl,
      codexEffort,
      aiPromptByLang: aiPromptByLangState,
    });
    chrome.runtime.sendMessage({ type: "AI_SETTINGS_CHANGED" });
    modelDirty = true;
    toggleUi();
    if (source === "ai" || source === "cli") refreshAiMeta({ forcePrompt: false });
  }, 400);
}

function scheduleResolveAiMeta({ immediate = false } = {}) {
  if (aiResolveDebounce) clearTimeout(aiResolveDebounce);
  const run = () => {
    if (!shouldRefreshAiMetaForCurrentUi()) return;
    refreshAiMeta({ forcePrompt: false });
  };
  if (immediate) {
    run();
    return;
  }
  aiResolveDebounce = setTimeout(run, 350);
}


function resetFileInput(input) {
  if (input) input.value = "";
}

async function openLocalViewerFromFiles(fileList, sourceLabel) {
  const images = filterImageFiles(fileList);
  if (!images.length) return;
  const session = await saveLocalSession({
    id: crypto.randomUUID(),
    createdAt: Date.now(),
    title: sourceLabel,
    pages: sortLocalPages(images.map((file, index) => toLocalPageRecord(file, index))),
  });
  const url = chrome.runtime.getURL(
    `viewer/viewer.html?sid=${encodeURIComponent(session.id)}`,
  );
  await chrome.tabs.create({ url });
  window.close();
}

async function handleLocalPickerChange(input, sourceLabel) {
  const files = [...(input?.files || [])];
  resetFileInput(input);
  await openLocalViewerFromFiles(files, sourceLabel);
}

function handleWsStatus(status) {
  if (lastApiOk) return;
  if (status === "connected") setEmojiStatus("ok", "WS connected");
  else if (status === "connecting") setEmojiStatus("loading", "Connecting…");
  else setEmojiStatus("error", "WS disconnected");
}

async function loadSettings() {
  populateModes();
  setEmojiStatus("loading", "Initializing…");

  const stored = await chrome.storage.local.get([
    "mode",
    "lang",
    "sources",
    "customApiUrl",
    "aiKey",
    "aiModel",
    "aiBaseUrl",
    "aiPromptByLang",
    "cliTool",
    "codexEffort",
  ]);

  modeSel.value = stored.mode || "lens_text";
  desiredLang =
    typeof stored.lang === "string" && stored.lang ? stored.lang : "en";
  desiredSources =
    typeof stored.sources === "string" && stored.sources
      ? stored.sources
      : "translated";
  desiredAiModel =
    typeof stored.aiModel === "string" && stored.aiModel
      ? stored.aiModel
      : "auto";
  desiredCliTool =
    typeof stored.cliTool === "string" && stored.cliTool
      ? stored.cliTool
      : "cli_gemini";
  desiredCodexEffort = normalizeCodexEffort(stored.codexEffort || "medium");

  setSelectOptions(langSel, FALLBACK_LANGS, {
    valueKey: "code",
    labelKey: "name",
    keepValue: desiredLang,
  });
  setSelectOptions(sourcesSel, FALLBACK_SOURCES, {
    valueKey: "id",
    labelKey: "name",
    keepValue: desiredSources,
  });

  langSel.value = desiredLang;
  sourcesSel.value = desiredSources;
  cliToolSel.value = desiredCliTool;
  if (codexEffortSel) codexEffortSel.value = desiredCodexEffort;

  const storedCustom = String(stored.customApiUrl || "");
  lastSavedApiUrl = storedCustom;
  apiInput.value = storedCustom;

  if (storedCustom) userInteractedApi = true;

  const aiKey = String(stored.aiKey || "");
  desiredAiBaseUrl = String(stored.aiBaseUrl || "");
  aiPromptByLangState =
    stored.aiPromptByLang && typeof stored.aiPromptByLang === "object"
      ? stored.aiPromptByLang
      : {};
  const mig = migratePromptMap(aiPromptByLangState);
  aiPromptByLangState = mig.map;
  if (mig.changed) await chrome.storage.local.set({ aiPromptByLang: aiPromptByLangState });

  const key = makePromptKey(desiredLang, desiredAiModel);
  const prompt = Object.prototype.hasOwnProperty.call(aiPromptByLangState, key)
    ? String(aiPromptByLangState[key] || "")
    : "";

  aiKeyInput.value = aiKey;
  if (aiBaseUrlInput) aiBaseUrlInput.value = desiredAiBaseUrl;
  setModelOptions(currentModelOptionsFallback(), { keepValue: desiredAiModel });
  aiPromptInput.value = prompt;
  updatePromptCount(prompt);

  toggleUi();

  const initial = normalizeUrl(apiInput.value);
  if (initial) checkHealth(initial);

  ensureApiDefaults()
    .then((d) => {
      apiDefaults = d || apiDefaults;
      if (storedCustom) return;
      const def = apiDefaults.defaultApiUrl || "";
      if (!def) return;
      if (!normalizeUrl(apiInput.value)) {
        apiInput.value = def;
        checkHealth(def);
        if (shouldRefreshAiMetaForCurrentUi()) refreshAiMeta({ forcePrompt: false });
      }
    })
    .catch(() => {});

  if (shouldRefreshAiMetaForCurrentUi()) {
    applyPromptForLang(desiredLang, { forceFetch: false }).catch(() => {});
    refreshAiMeta({ forcePrompt: false });
  }

  chrome.runtime.sendMessage({ type: "GET_API_STATUS" }, (resp) => {
    if (chrome.runtime.lastError) return;
    if (resp && typeof resp.ok === "boolean" && resp.ok) {
      lastApiOk = true;
      setEmojiStatus("ok", "Online");
    }
  });

  chrome.runtime.sendMessage({ type: "GET_WS_STATUS" }, (resp) => {
    if (chrome.runtime.lastError) return;
    if (resp && typeof resp.status === "string") handleWsStatus(resp.status);
  });
}

window.addEventListener("offline", () => {
  lastApiOk = false;
  setEmojiStatus("error", "No internet");
});
window.addEventListener("online", () => {
  if (apiInput.value) checkHealth(apiInput.value);
});

window.addEventListener("pagehide", () => {
  try {
    if (pendingApiSave) {
      const normalized = normalizeUrl(apiInput.value);
      if (normalized) chrome.storage.local.set({ customApiUrl: normalized });
    }

    const modeId = modeSel.value || "lens_text";
    const aiKey = (aiKeyInput.value || "").trim();
    const aiModel = selectedAiModelValue();
    const codexEffort = normalizeCodexEffort(codexEffortSel?.value || desiredCodexEffort);
    const aiBaseUrl = (aiBaseUrlInput?.value || "").trim();
    desiredAiModel = aiModel;
    desiredCodexEffort = codexEffort;

    if (modeId === "lens_text") {
      const lang = desiredLang || langSel.value || "en";
      const key = makePromptKey(lang, aiModel);
      const needSave = pendingAiSave || Boolean(aiPromptDirtyByLang[key]);
      if (aiPromptDirtyByLang[key]) {
        const prompt = normalizePrompt(String(aiPromptInput.value || ""));
        aiPromptByLangState[key] = prompt;
        aiPromptDirtyByLang[key] = false;
      }
      if (needSave)
        chrome.storage.local.set({
          aiKey,
          aiModel,
          aiBaseUrl,
          codexEffort,
          aiPromptByLang: aiPromptByLangState,
        });
    } else if (pendingAiSave) {
      chrome.storage.local.set({ aiKey, aiModel, aiBaseUrl, codexEffort });
    }
  } catch {}
});

chrome.runtime.onMessage?.addListener((msg) => {
  if (msg.type === "WS_STATUS_UPDATE") handleWsStatus(msg.status);
  else if (msg.type === "API_STATUS_UPDATE") {
    if (typeof msg.ok === "boolean") {
      lastApiOk = msg.ok;
      if (msg.ok) setEmojiStatus("ok", "Online");
      else
        setEmojiStatus(
          userInteractedApi ? "error" : "loading",
          userInteractedApi ? "API unhealthy" : "Waiting…",
        );
    }
  }
});

modeSel.addEventListener("change", async () => {
  await chrome.storage.local.set({ mode: modeSel.value });
  modelDirty = false;
  toggleUi();
  await applyPromptForLang(desiredLang, { forceFetch: false });
  refreshAiMeta({ forcePrompt: false });
});

langSel.addEventListener("change", async () => {
  const prevLang = desiredLang;
  desiredLang = langSel.value || desiredLang;
  if (canUseAiUi()) await flushPromptForLang(prevLang, desiredAiModel);
  await chrome.storage.local.set({ lang: desiredLang });
  modelDirty = false;
  await applyPromptForLang(desiredLang, { forceFetch: false });
  toggleUi();
  refreshAiMeta({ forcePrompt: false });
});

sourcesSel.addEventListener("change", async () => {
  if (canUseAiUi()) await flushPromptForLang(desiredLang, desiredAiModel);
  modelDirty = false;
  const ok = await ensureAiAvailableOrFallback();
  desiredSources = sourcesSel.value || desiredSources;
  await chrome.storage.local.set({ sources: desiredSources });
  toggleUi();
  if (ok) await applyPromptForLang(desiredLang, { forceFetch: false });
  refreshAiMeta({ forcePrompt: false });
  chrome.runtime.sendMessage({ type: "AI_SETTINGS_CHANGED" });
});

cliToolSel.addEventListener("change", async () => {
  desiredCliTool = cliToolSel.value || desiredCliTool;
  await chrome.storage.local.set({ cliTool: desiredCliTool });
  toggleUi();
  refreshAiMeta({ forcePrompt: false });
  chrome.runtime.sendMessage({ type: "AI_SETTINGS_CHANGED" });
});

codexEffortSel?.addEventListener("change", async () => {
  desiredCodexEffort = normalizeCodexEffort(codexEffortSel.value || desiredCodexEffort);
  await chrome.storage.local.set({ codexEffort: desiredCodexEffort });
  chrome.runtime.sendMessage({ type: "AI_SETTINGS_CHANGED" });
});

apiInput.addEventListener("input", (e) => scheduleSaveApi(e.target.value));
apiInput.addEventListener("blur", (e) => scheduleSaveApi(e.target.value));

let lastKnownEmpty = true;
aiKeyInput.addEventListener("input", () => {
  const v = (aiKeyInput.value || "").trim();
  if (lastKnownEmpty && v && sourcesSel && modeSel) {
    if (sourcesSel.value !== "ai" || modeSel.value !== "lens_text") {
      sourcesSel.value = "ai";
      modeSel.value = "lens_text";
      desiredSources = "ai";
      chrome.storage.local.set({ mode: "lens_text", sources: "ai" });
    }
  }
  lastKnownEmpty = (v === "");
  modelDirty = false;
  toggleUi();
  scheduleSaveAi();
  scheduleResolveAiMeta();
});
aiKeyInput.addEventListener("blur", () => {
  toggleUi();
  scheduleSaveAi();
  scheduleResolveAiMeta({ immediate: true });
});

if (aiBaseUrlInput) {
  aiBaseUrlInput.addEventListener("input", () => {
    scheduleSaveAi();
    scheduleResolveAiMeta();
  });
  aiBaseUrlInput.addEventListener("blur", () => {
    scheduleSaveAi();
    scheduleResolveAiMeta({ immediate: true });
  });
}

aiModelSel.addEventListener("change", async () => {
  const prevModel = desiredAiModel;
  desiredAiModel = normalizeAiModel(aiModelSel.value || prevModel);
  if (canUseAiUi()) await flushPromptForLang(desiredLang, prevModel);
  modelDirty = true;
  await applyPromptForLang(desiredLang, { forceFetch: false });
  scheduleSaveAi();
});

aiPromptInput.addEventListener("input", () => {
  const key = makePromptKey(desiredLang, desiredAiModel);
  aiPromptDirtyByLang[key] = true;
  updatePromptCount();
  scheduleSaveAi();
});
aiPromptInput.addEventListener("blur", async () => {
  const key = makePromptKey(desiredLang, desiredAiModel);
  aiPromptDirtyByLang[key] = true;
  updatePromptCount();
  await flushPromptForLang(desiredLang, desiredAiModel);
  scheduleSaveAi();
});



openLocalImagesBtn?.addEventListener("click", () => {
  resetFileInput(localImagesInput);
  localImagesInput?.click();
});

openLocalFolderBtn?.addEventListener("click", () => {
  resetFileInput(localFolderInput);
  localFolderInput?.click();
});

localImagesInput?.addEventListener("change", async () => {
  await handleLocalPickerChange(localImagesInput, "images");
});

localFolderInput?.addEventListener("change", async () => {
  await handleLocalPickerChange(localFolderInput, "folder");
});

resetBtn.addEventListener("click", () => {
  ensureApiDefaults({ force: true }).then((d) => {
    apiDefaults = d;
    const def = apiDefaults.resetApiUrl || apiDefaults.defaultApiUrl || "";
    apiInput.value = def;
    const normalized = normalizeUrl(def);
    chrome.storage.local.set({ customApiUrl: normalized });
    lastSavedApiUrl = normalized;
    userInteractedApi = Boolean(normalized);
    setEmojiStatus("loading", "Reset to default");
    chrome.runtime.sendMessage({ type: "API_URL_CHANGED" });
    checkHealth(normalized);
    apiInput.focus();
  });
});

loadSettings();
initRunStatus();

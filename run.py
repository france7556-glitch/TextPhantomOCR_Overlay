import json

path = r'd:\TextPhantomOCR_Overlay\background-service.js'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target = '''  let replaceResp = null;
  if (newImg && mode !== "lens_text") {
    ev("job.result.image", { id: jobId });
    replaceResp = await requestFromTabEnsured(
      tabId,
      { type: "REPLACE_IMAGE", original: imgUrl, newSrc: newImg },
      frameId,
    );
  }

  let overlayResp = null;
  if (hasHtml) {
    ev("job.result.html", { id: jobId });
    overlayResp = await requestFromTabEnsured(
      tabId,
      {
        type: "OVERLAY_HTML",
        original: imgUrl,
        result,
        mode: mode || "",
        source: ctx?.source || "",
      },
      frameId,
    );
  }

  let ok = true;
  let errMsg = "";
  if (!hasHtml && !(newImg && mode !== "lens_text")) ok = false;
  if (newImg && mode !== "lens_text" && !replaceResp?.ok) {
    ok = false;
    errMsg = "DOM replace failed";
  }
  if (hasHtml && !overlayResp?.ok) {
    ok = false;
    errMsg = "Overlay insert failed";
  }'''

replacement = '''  const DOM_INSERT_MAX_RETRIES = 3;
  const DOM_INSERT_RETRY_DELAY_MS = 2500;

  let replaceApplied = false;
  let overlayApplied = false;
  let replaceResp = null;
  let overlayResp = null;
  const needReplace = !!(newImg && mode !== "lens_text");
  const needOverlay = !!hasHtml;

  for (let attempt = 0; attempt < DOM_INSERT_MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      ev("job.result.dom_retry", { id: jobId, attempt, replaceApplied, overlayApplied });
      if (batch) batchUpdateToast(batch, แทรกกลับ (ลองครั้งที่ ));
      await new Promise((r) => setTimeout(r, DOM_INSERT_RETRY_DELAY_MS));
    }

    if (needReplace && !replaceApplied) {
      ev("job.result.image", { id: jobId, attempt });
      replaceResp = await requestFromTabEnsured(
        tabId,
        { type: "REPLACE_IMAGE", original: imgUrl, newSrc: newImg },
        frameId,
      );
      if (replaceResp?.applied) replaceApplied = true;
    }

    if (needOverlay && !overlayApplied) {
      ev("job.result.html", { id: jobId, attempt });
      overlayResp = await requestFromTabEnsured(
        tabId,
        {
          type: "OVERLAY_HTML",
          original: imgUrl,
          result,
          mode: mode || "",
          source: ctx?.source || "",
        },
        frameId,
      );
      if (overlayResp?.applied) overlayApplied = true;
    }

    const allDone = (!needReplace || replaceApplied) && (!needOverlay || overlayApplied);
    if (allDone) break;
  }

  let ok = true;
  let errMsg = "";
  if (!needReplace && !needOverlay) ok = false;
  if (needReplace && !replaceApplied) {
    ok = false;
    errMsg = "DOM replace failed";
  }
  if (needOverlay && !overlayApplied) {
    ok = false;
    errMsg = errMsg ? errMsg + " + Overlay insert failed" : "Overlay insert failed";
  }'''

if target in content:
    new_content = content.replace(target, replacement)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS")
else:
    print("TARGET NOT FOUND. Trying with \r\n")
    target_rn = target.replace('\n', '\r\n')
    if target_rn in content:
        new_content = content.replace(target_rn, replacement.replace('\n', '\r\n'))
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("SUCCESS (with \\r\\n)")
    else:
        print("TARGET NOT FOUND AT ALL")

/*
 * MoneySuperMarket rate-table capture bookmarklet.
 *
 * MSM's live results page (/mortgages/rates-table/...) fetches its data from
 * POST /mortgages/rates-table/api/v1/enquiry. That endpoint is behind Cloudflare
 * bot management and blocks automated requests (verified: fails identically in
 * headless AND headed Playwright, even with a valid session/XSRF token, on the
 * very first request - it's a browser-fingerprint block, not a rate limit).
 *
 * Running this from a real, human-driven browser tab sidesteps that entirely -
 * the request is made by the actual page's own JS, in your actual session, and
 * this script only listens in on the response.
 *
 * HOW TO INSTALL:
 *   1. Run `node build.js` (or see README) to produce the minified `javascript:`
 *      one-liner, OR just copy this whole file's content, prefix it with
 *      "javascript:" and paste that as a new bookmark's URL.
 *   2. Name the bookmark something like "MSM Capture".
 *
 * HOW TO USE:
 *   1. Go to the MSM rates-table URL with your desired filters (see README for
 *      recommended filter settings).
 *   2. Click the bookmark. It installs the capture hook and shows a small
 *      badge in the bottom-right corner.
 *   3. Browse through the result pages using MSM's own pagination controls.
 *      Each new page's data is captured automatically as it loads.
 *   4. Click the badge at any time to download everything captured so far as
 *      a single JSON file.
 *   5. Repeat for each LTV band / product type you want (see README) - the
 *      capture accumulates across page loads within the same browser profile,
 *      so you can do this over several separate visits if needed.
 */
(function () {
  var KEY = "msmCapture";
  var ENDPOINT_MATCH = "/rates-table/api/v1/enquiry";

  if (window.__msmCaptureInstalled) {
    var current = JSON.parse(localStorage.getItem(KEY) || "[]");
    alert("Already capturing on this page load. " + current.length + " response(s) stored so far.");
    return;
  }
  window.__msmCaptureInstalled = true;

  var stored = JSON.parse(localStorage.getItem(KEY) || "[]");
  var seenKeys = new Set(
    stored.map(function (entry) {
      return entry.__requestBody || "";
    })
  );

  function persist() {
    localStorage.setItem(KEY, JSON.stringify(stored));
    updateBadge();
  }

  var originalFetch = window.fetch;
  window.fetch = function () {
    var args = arguments;
    var url = typeof args[0] === "string" ? args[0] : args[0] && args[0].url;
    var isTarget = url && url.indexOf(ENDPOINT_MATCH) !== -1;
    var reqBody = null;
    if (isTarget && args[1] && args[1].body) {
      reqBody = args[1].body;
    }

    return originalFetch.apply(this, args).then(function (res) {
      if (isTarget) {
        res
          .clone()
          .json()
          .then(function (data) {
            var dedupeKey = reqBody || JSON.stringify(data).slice(0, 200);
            if (seenKeys.has(dedupeKey)) return;
            seenKeys.add(dedupeKey);
            stored.push({
              __capturedAt: new Date().toISOString(),
              __requestBody: reqBody,
              __pageUrl: window.location.href,
              response: data,
            });
            persist();
            console.log("[MSM capture] captured a page. total stored:", stored.length);
          })
          .catch(function (e) {
            console.error("[MSM capture] failed to read response JSON", e);
          });
      }
      return res;
    });
  };

  function updateBadge() {
    var badge = document.getElementById("__msmCaptureBadge");
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "__msmCaptureBadge";
      badge.style.cssText =
        "position:fixed;bottom:16px;right:16px;background:#111;color:#0f0;" +
        "padding:10px 14px;border-radius:6px;font:12px monospace;z-index:2147483647;" +
        "cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.5);";
      badge.title = "Click to download everything captured so far as JSON";
      badge.onclick = exportData;
      document.body.appendChild(badge);
    }
    badge.textContent = "MSM capture: " + stored.length + " page(s) - click to export";
  }

  function exportData() {
    var blob = new Blob([JSON.stringify(stored, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "msm_capture_" + new Date().toISOString().slice(0, 10) + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function clearData() {
    if (confirm("Clear all " + stored.length + " captured page(s)? This cannot be undone.")) {
      stored = [];
      localStorage.removeItem(KEY);
      updateBadge();
    }
  }

  // Shift-click the badge to clear instead of export.
  document.addEventListener(
    "click",
    function (e) {
      if (e.target && e.target.id === "__msmCaptureBadge" && e.shiftKey) {
        e.stopPropagation();
        clearData();
      }
    },
    true
  );

  updateBadge();
  alert(
    "MSM capture installed.\n\n" +
      "Browse through result pages with MSM's own pagination - each new page is " +
      "saved automatically.\n\nClick the badge (bottom-right) anytime to export as JSON.\n" +
      "Shift-click the badge to clear stored data and start over."
  );
})();

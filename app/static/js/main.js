/* FieldWise — page wiring: dataset info, layers, search, bookmarks, selection, AI. */
(function () {
  "use strict";

  const cfg = window.FIELDWISE;
  const { h } = FW.render;
  const $ = (id) => document.getElementById(id);

  const panel = $("panel");
  const panelBody = $("panel-body");
  let selectCtrl = null;
  let selectSeq = 0;
  let canSelect = false;
  let currentSelection = null;

  const map = FW.map.init("map");

  /* ---------- toast / banner ---------- */
  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), 3500);
  }
  function banner(msg) {
    const b = $("banner");
    b.textContent = msg;
    b.hidden = false;
    setTimeout(() => (b.hidden = true), 9000);
  }
  FW.map.on("providerError", (e) => banner(e.message));

  /* ---------- dataset info + legend ---------- */
  async function loadDataset() {
    const badge = $("dataset-badge");
    try {
      const d = await FW.api.get("/api/dataset");
      const ds = d.dataset;
      badge.classList.add(ds.status === "live" ? "live" : "fallback");
      $("dataset-label").replaceChildren(
        h("span", {}, "USDA Cropland Data Layer "), h("strong", {}, String(ds.year)),
        h("span", {}, ds.resolution_m ? ` · ${ds.resolution_m} m` : ""));
      badge.title = ds.status === "live" ? `Newest year confirmed with the USDA service at ${ds.checked_at}` : ds.status_note;
      if (ds.status !== "live") banner(ds.status_note);
      const legend = $("legend");
      legend.replaceChildren(...d.legend.map((l) => h("li", { "data-group": l.group },
        h("span", { class: "swatch", style: `background:${l.color}`, "aria-hidden": "true" }), l.label)));
      $("processing-overview").textContent = d.processing.overview;
      $("processing-outlines").textContent = d.processing.outlines;
    } catch (err) {
      badge.classList.add("error");
      $("dataset-label").textContent = "USDA dataset information unavailable";
      banner("Could not confirm the USDA dataset. Crop layers may be unavailable.");
    }
  }
  loadDataset();

  /* ---------- layers ---------- */
  for (const crop of ["corn", "wheat"]) {
    $("toggle-" + crop).addEventListener("change", (e) => {
      const on = e.target.checked;
      const apply = () => FW.map.setLayerVisible(crop, on);
      map.loaded() ? apply() : map.once("load", apply);
      document.querySelectorAll(`#legend li[data-group="${crop}"]`).forEach((li) => li.classList.toggle("off", !on));
    });
  }
  $("layers-collapse").addEventListener("click", (e) => {
    const card = document.querySelector(".layers-card");
    const collapsed = card.classList.toggle("collapsed");
    e.currentTarget.setAttribute("aria-expanded", String(!collapsed));
  });
  if (window.matchMedia("(max-width: 760px)").matches) {
    document.querySelector(".layers-card").classList.add("collapsed");
    $("layers-collapse").setAttribute("aria-expanded", "false");
  }

  FW.map.on("zoomHint", (z) => {
    canSelect = z.canSelect;
    let msg = z.message;
    if (!z.canSelect && z.zoom >= 4) msg += " Zoom in further to select a crop area.";
    else if (z.canSelect && !msg) msg = "Click a colored crop area to select it.";
    else if (z.canSelect) msg += " Click a colored crop area to select it.";
    $("zoom-hint").textContent = msg;
    map.getCanvas().style.cursor = z.canSelect ? "crosshair" : "";
  });

  /* ---------- search ---------- */
  const input = $("search-input");
  const list = $("search-results");
  let searchTimer, searchCtrl, results = [], active = -1;

  function closeList() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }
  function renderResults(items, emptyMsg) {
    results = items;
    active = -1;
    if (!items.length) {
      list.replaceChildren(h("li", { class: "empty", role: "option", "aria-disabled": "true" }, emptyMsg));
    } else {
      list.replaceChildren(...items.map((r, i) => h("li", {
        id: "sr-" + i, role: "option", "aria-selected": "false",
        onmousedown: (e) => { e.preventDefault(); choose(i); },
      }, h("span", {}, r.label), h("span", { class: "kind" }, r.kind === "zip" ? "ZIP area" : "Town / place"))));
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }
  function setActive(i) {
    const lis = list.querySelectorAll("li[role=option]:not(.empty)");
    if (!lis.length) return;
    active = (i + lis.length) % lis.length;
    lis.forEach((li, j) => li.setAttribute("aria-selected", String(j === active)));
    input.setAttribute("aria-activedescendant", "sr-" + active);
    lis[active].scrollIntoView({ block: "nearest" });
  }
  function choose(i) {
    const r = results[i];
    if (!r) return;
    input.value = r.label;
    closeList();
    FW.map.flyToBbox(r.bbox);
    toast(`Showing ${r.label}. Zoom in and click a colored area to select it.`);
  }
  async function runSearch(q) {
    if (searchCtrl) searchCtrl.abort();
    searchCtrl = new AbortController();
    try {
      const d = await FW.api.get("/api/search?q=" + encodeURIComponent(q), searchCtrl.signal);
      renderResults(d.results, "No matching U.S. town or ZIP code.");
    } catch (err) {
      if (err.name === "AbortError") return;
      renderResults([], err.code === "rate_limited" ? "Too many searches — please wait a moment." : "Search is unavailable right now.");
    }
  }
  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = input.value.trim();
    if (q.length < 2) { closeList(); return; }
    searchTimer = setTimeout(() => runSearch(q), 250); // debounce
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden && input.value.trim().length >= 2) runSearch(input.value.trim()); else setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); if (!list.hidden && results.length) choose(active >= 0 ? active : 0); }
    else if (e.key === "Escape") { closeList(); }
  });
  input.addEventListener("blur", () => setTimeout(closeList, 120));

  /* ---------- bookmarks ---------- */
  $("bookmark-select").addEventListener("change", (e) => {
    const b = cfg.bookmarks.find((x) => x.id === e.target.value);
    e.target.value = "";
    if (!b) return;
    FW.map.flyTo(b.lon, b.lat, b.zoom);
    map.once("moveend", () => select({ lng: b.lon, lat: b.lat }));
  });

  /* ---------- selection ---------- */
  function openPanel() {
    panel.hidden = false;
    panel.classList.remove("collapsed");
  }
  function clearSelection() {
    if (selectCtrl) selectCtrl.abort();
    selectSeq++;
    currentSelection = null;
    FW.map.setSelection(null);
    panel.hidden = true;
    panelBody.replaceChildren();
    map.getCanvas().focus();
  }
  $("clear-selection").addEventListener("click", clearSelection);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden && document.activeElement !== input) clearSelection();
  });
  $("sheet-handle").addEventListener("click", () => {
    if (panel.classList.contains("collapsed")) panel.classList.remove("collapsed");
    else if (panel.classList.contains("expanded")) { panel.classList.remove("expanded"); panel.classList.add("collapsed"); }
    else panel.classList.add("expanded");
  });

  FW.map.on("select", (e) => {
    if (e.tooFar) { toast("Zoom in further to select a crop area."); return; }
    select(e.lngLat);
  });

  async function select(lngLat) {
    if (selectCtrl) selectCtrl.abort(); // cancel stale lookups
    const ctrl = new AbortController();
    selectCtrl = ctrl;
    const seq = ++selectSeq;
    openPanel();
    panelBody.setAttribute("aria-busy", "true");
    panelBody.replaceChildren(FW.render.loading("Checking the USDA classification at this point…"));
    FW.map.setSelection(null);
    try {
      const data = await FW.api.post("/api/crop-at", { lat: lngLat.lat, lon: lngLat.lng }, ctrl.signal);
      if (seq !== selectSeq) return;
      currentSelection = data;
      panelBody.replaceChildren(FW.render.renderSelection(data));
      panelBody.scrollTop = 0;
      $("panel-title").textContent = data.supported ? "Selected crop area" : "Selected location";
      if (data.region && data.region.available) FW.map.setSelection(data.region.geometry, data.region.clipped);
      if (data.supported) await loadRecommendations(data, ctrl, seq);
    } catch (err) {
      if (err.name === "AbortError" || seq !== selectSeq) return;
      panelBody.replaceChildren(FW.render.errorState(err));
    } finally {
      if (seq === selectSeq) panelBody.setAttribute("aria-busy", "false");
    }
  }

  async function loadRecommendations(data, ctrl, seq, answers) {
    answers = answers || {};
    const slot = $("recs-slot");
    if (!slot) return;
    const formSlot = h("div", { id: "ctx-slot" });
    const listSlot = h("div", { id: "recs-list" }, FW.render.loading("Loading practices to consider…"));
    slot.replaceChildren(formSlot, listSlot);
    const apply = (newAnswers) => {
      if (seq !== selectSeq) return;
      loadRecommendations(data, ctrl, seq, newAnswers).then(() => {
        const list = $("recs-list");
        if (list) list.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    };
    formSlot.appendChild(FW.render.renderContextForm(cfg.contextQuestions, answers, apply, () => apply({})));
    try {
      const recs = await FW.api.post("/api/recommendations", { selection_token: data.selection_token, context: answers }, ctrl.signal);
      if (seq !== selectSeq) return;
      listSlot.replaceChildren(FW.render.renderRecommendations(recs));
      setupAI(data, recs, answers);
    } catch (err) {
      if (err.name === "AbortError" || seq !== selectSeq) return;
      listSlot.replaceChildren(FW.render.errorState(err));
    }
  }

  /* ---------- AI audit (Turnstile-protected) ---------- */
  let turnstilePromise = null;
  function loadTurnstile() {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    if (!turnstilePromise) {
      turnstilePromise = new Promise((resolve, reject) => {
        window.fwTurnstileReady = () => resolve(window.turnstile);
        const s = document.createElement("script");
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=fwTurnstileReady";
        s.async = true;
        s.onerror = () => { turnstilePromise = null; reject(new Error("turnstile_load_failed")); };
        document.head.appendChild(s);
      });
    }
    return turnstilePromise;
  }

  function setupAI(data, recs, answers) {
    const slot = $("ai-slot");
    slot.replaceChildren(FW.render.renderAIIntro(cfg.ai));
    if (!cfg.ai.available) return;
    if (!recs.recommendation_ids.length) {
      slot.replaceChildren(h("p", { class: "state info" }, "There are no suggestions to audit for these answers."));
      return;
    }
    const button = $("ai-button");
    const out = $("ai-output");
    const recIndex = {};
    recs.groups.forEach((g) => g.recommendations.forEach((r) => (recIndex[r.id] = r.action)));
    let token = "";
    let widgetId = null;

    loadTurnstile().then((ts) => {
      if (!document.body.contains(slot)) return;
      widgetId = ts.render("#turnstile-slot", {
        sitekey: cfg.turnstileSiteKey,
        callback: (t) => { token = t; button.disabled = false; },
        "expired-callback": () => { token = ""; button.disabled = true; },
        "error-callback": () => { out.replaceChildren(h("p", { class: "state error" }, "The verification check failed to load. Suggestions above are unaffected.")); },
      });
    }).catch(() => {
      out.replaceChildren(h("p", { class: "state error" }, "The verification service could not be loaded, so the AI audit is unavailable. Suggestions above are unaffected."));
    });

    button.addEventListener("click", async () => {
      button.disabled = true;
      out.replaceChildren(h("p", { class: "state info" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Running the AI audit…"));
      try {
        const res = await FW.api.post("/api/audit", { selection_token: data.selection_token, turnstile_token: token, context: answers });
        out.replaceChildren(FW.render.renderAIResult(res, recIndex));
      } catch (err) {
        const msg = err.code === "rate_limited"
          ? "AI audit limit reached. Please try again later."
          : (err.message || "AI audit unavailable.") + " The suggestions above are unaffected.";
        out.replaceChildren(h("p", { class: "state error", role: "alert" }, msg));
      } finally {
        token = "";
        if (window.turnstile && widgetId !== null) window.turnstile.reset(widgetId); // tokens are single-use
      }
    });
  }
})();

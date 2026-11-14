/* FieldWise — selection panel rendering. All text is inserted with textContent (no HTML injection). */
(function () {
  "use strict";

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    return el;
  }

  function safeLink(url, text) {
    if (typeof url !== "string" || !url.startsWith("https://")) return h("span", {}, text);
    return h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, text);
  }

  const CROP_SWATCH = { corn: "swatch-corn", wheat: "swatch-wheat" };

  function fmtDate(iso) {
    try {
      return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    } catch (_) {
      return iso;
    }
  }

  function section(num, title, ...content) {
    return h("section", { class: "section" }, h("h3", {}, h("span", { class: "num", "aria-hidden": "true" }, String(num)), title), ...content);
  }

  /* ---------- states ---------- */
  function loading(msg) {
    return h("div", {},
      h("p", { class: "state info" }, h("span", { class: "spinner", "aria-hidden": "true" }), msg),
      h("div", { class: "skeleton" }), h("div", { class: "skeleton", style: "width:70%" }), h("div", { class: "skeleton", style: "width:85%" }));
  }

  function errorState(err) {
    const map = {
      usda_unavailable: "The USDA Cropland Data Layer service is not responding right now. No classification is shown rather than a guess. Please try again shortly.",
      unsupported_geography: "This point is outside the contiguous United States, which is the only area FieldWise covers.",
      rate_limited: "Rate limit reached. Please wait a moment before selecting again.",
      network_error: "Could not reach the FieldWise server. Check your connection and try again.",
    };
    return h("p", { class: "state error", role: "alert" }, map[err.code] || err.message || "Something went wrong.");
  }

  /* ---------- selection ---------- */
  function renderSelection(data) {
    const c = data.classification;
    const ds = data.dataset;
    const loc = data.location;
    const frag = h("div", {});

    frag.appendChild(h("div", { class: "statements" }, data.statements.map((s) => h("p", { class: "statement" }, s))));

    if (!data.supported) {
      frag.appendChild(h("p", { class: "state info" }, data.message));
      frag.appendChild(factsList(data, ds, loc, c));
      return frag;
    }

    frag.appendChild(h("div", { class: "crop-headline" },
      h("span", { class: "crop-chip" }, h("span", { class: "swatch " + CROP_SWATCH[c.crop], "aria-hidden": "true" }), c.official_name),
      h("span", { class: "subtle" }, "USDA CDL " + ds.year)));

    frag.appendChild(section(1, "What the data tells us", factsList(data, ds, loc, c), regionNotes(data.region)));
    frag.appendChild(section(2, "What it does not tell us", h("ul", { class: "not-list" }, data.does_not_tell.map((t) => h("li", {}, t))),
      h("p", { class: "subtle" }, "If you know some of these, you can add them under “Tell FieldWise what you know” below.")));
    frag.appendChild(section(3, "Practices to consider", h("div", { id: "recs-slot" }, loading("Loading practices to consider…"))));
    frag.appendChild(section(4, "Optional AI audit", h("div", { id: "ai-slot" })));
    return frag;
  }

  function factsList(data, ds, loc, c) {
    const place = [loc.county, loc.state].filter(Boolean).join(", ");
    const region = data.region;
    let areaText = null;
    if (region && region.available) {
      areaText = region.mapped_area
        ? `${region.mapped_area.acres.toLocaleString()} acres (${region.mapped_area.hectares.toLocaleString()} ha)`
        : `Not shown — region extends beyond the ${region.window_km} km analysis window`;
    }
    const dl = h("dl", { class: "facts" },
      h("dt", {}, "Classified crop"), h("dd", {}, c.group === "corn" || c.group === "wheat" ? (c.group === "corn" ? "Corn" : "Wheat") : (c.official_name || "No data")),
      c.subtype ? [h("dt", {}, "Subtype"), h("dd", {}, c.subtype)] : null,
      h("dt", {}, "USDA class"), h("dd", {}, c.code !== null ? `${c.official_name || "Unknown"} (code ${c.code})` : "No data"),
      h("dt", {}, "Classification year"), h("dd", {}, String(ds.year)),
      h("dt", {}, "Approximate location"), h("dd", {}, (place ? place + " · " : "") + `${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`),
      areaText ? [h("dt", {}, "Mapped crop-area size"), h("dd", {}, areaText)] : null,
      h("dt", {}, "Source"), h("dd", {}, safeLink(ds.source_url, ds.title)),
      h("dt", {}, "Dataset check"), h("dd", {},
        ds.status === "live" ? `Newest year confirmed with USDA service ${fmtDate(ds.checked_at)}` : ds.status_note),
    );
    return dl;
  }

  function regionNotes(region) {
    if (!region) return null;
    if (!region.available) return h("p", { class: "state warn" }, region.reason);
    return h("ul", { class: "notes" }, region.notes.map((n) => h("li", {}, n)),
      h("li", {}, "The outlined region joins all touching pixels of this class, so it may span several fields or only part of one."));
  }

  /* ---------- recommendations ---------- */
  function renderRecommendations(recs) {
    const frag = h("div", {});
    for (const w of recs.warnings || []) frag.appendChild(h("p", { class: "state warn" }, w));
    frag.appendChild(h("p", { class: "framing" }, recs.framing));
    if (recs.reported_context && recs.reported_context.length) {
      frag.appendChild(h("div", { class: "reported-box" },
        h("strong", {}, "Reported by you — not verified by FieldWise"),
        h("ul", {}, recs.reported_context.map((c) => h("li", {}, `${c.question} — ${c.answer}`)))));
    }
    for (const g of recs.groups) {
      frag.appendChild(h("h4", { class: "cat-title" }, g.label));
      for (const r of g.recommendations) frag.appendChild(card(r));
    }
    if (recs.not_shown && recs.not_shown.length) {
      frag.appendChild(h("details", { class: "not-shown" },
        h("summary", {}, `${recs.not_shown.length} suggestion${recs.not_shown.length > 1 ? "s" : ""} hidden based on your answers`),
        h("ul", {}, recs.not_shown.map((n) => h("li", {}, h("strong", {}, n.action), " ", h("span", { class: "subtle" }, n.reason))))));
    }
    if (!recs.recommendation_ids.length) {
      frag.appendChild(h("p", { class: "state info" }, "Based on your answers, none of FieldWise's current suggestions apply. Discuss further options with a local agricultural adviser."));
    }
    frag.appendChild(h("p", { class: "subtle" }, `Ruleset ${recs.ruleset_version} · USDA CDL ${recs.dataset_year} · same inputs always give the same suggestions in the same order.`));
    return frag;
  }

  function card(r) {
    const cases = r.case_studies.length
      ? r.case_studies.map((cs) => h("div", { class: "case" },
          h("strong", {}, safeLink(cs.source_url, cs.name)), h("span", { class: "subtle" }, " · " + cs.region),
          h("p", {}, cs.summary),
          h("p", { class: "subtle" }, "Applicability: " + cs.applicability_limits)))
      : [h("span", {}, r.case_study_note)];
    return h("article", { class: "card", id: "rec-" + r.id, "aria-labelledby": "rec-title-" + r.id },
      r.conditional ? h("span", { class: "cond" }, r.conditional_prefix) : null,
      h("h4", { id: "rec-title-" + r.id }, r.action),
      h("dl", {},
        h("dt", {}, "Why it may help"), h("dd", {}, r.why, " ", h("span", { class: "subtle" }, r.general_context)),
        h("dt", {}, "Supporting observations"), h("dd", {}, h("ul", {}, r.supporting_observations.map((o) => h("li", {}, o)))),
        r.reported_by_user && r.reported_by_user.length
          ? [h("dt", {}, "Reported by you (not verified)"), h("dd", {}, h("ul", {}, r.reported_by_user.map((o) => h("li", {}, o))))]
          : null,
        h("dt", {}, "Example from another farm"), h("dd", {}, cases),
        h("dt", {}, "Cost and effort"), h("dd", {}, h("span", { class: "effort" }, r.cost_effort.level), r.cost_effort.explanation),
        h("dt", {}, "What to verify before acting"), h("dd", {}, h("ul", {}, r.verify_before_acting.map((v) => h("li", {}, v)))),
        r.limitations.length ? [h("dt", {}, "Limitations"), h("dd", {}, h("ul", {}, r.limitations.map((v) => h("li", {}, v))))] : null,
      ),
      h("ul", { class: "sources", "aria-label": "Sources" },
        r.sources.map((s) => h("li", {}, "Source: ", safeLink(s.url, s.title), h("span", { class: "subtle" }, ` — ${s.publisher} (checked ${s.verified_on})`)))),
      h("span", { class: "rid" }, r.id));
  }

  /* ---------- optional user-reported context ---------- */
  function renderContextForm(qdoc, answers, onApply, onReset) {
    const anyAnswered = Object.values(answers).some((v) => v && v !== "unknown");
    const selects = qdoc.questions.map((q) => {
      const id = "ctx-" + q.id;
      const sel = h("select", { id, name: q.id },
        q.options.map((o) => h("option", { value: o.value, selected: (answers[q.id] || "unknown") === o.value }, o.label)));
      return h("div", { class: "ctx-field" }, h("label", { for: id }, q.label), sel);
    });
    const form = h("form", { class: "ctx-form", onsubmit: (e) => {
      e.preventDefault();
      const out = {};
      new FormData(form).forEach((v, k) => { if (v !== "unknown") out[k] = String(v); });
      onApply(out);
    } },
      h("p", { class: "subtle" }, qdoc.intro),
      h("div", { class: "ctx-grid" }, selects),
      h("div", { class: "ctx-actions" },
        h("button", { type: "submit", class: "btn-primary" }, "Update suggestions"),
        h("button", { type: "button", class: "btn-ghost", onclick: onReset }, "Reset answers")));
    return h("details", { class: "ctx-details", open: anyAnswered },
      h("summary", {}, "Tell FieldWise what you know (optional)",
        anyAnswered ? h("span", { class: "ctx-count" }, `${Object.keys(answers).length} answered`) : null),
      form);
  }

  /* ---------- AI ---------- */
  const AI_CATEGORY_LABELS = {
    soil_health: "Soil health", water_efficiency: "Water efficiency", rotation_cover_crops: "Rotation & cover crops",
    nutrient_management: "Nutrient management", other: "Other",
  };

  function renderAIIntro(status) {
    if (!status.available) {
      return h("div", { class: "ai-box" }, h("p", { class: "state warn" }, "AI audit unavailable: " + status.message + " All suggestions above remain fully usable."));
    }
    return h("div", { class: "ai-box" },
      h("p", {}, "Run an AI audit of this crop area. It explains each suggestion above, reviews any practices you reported, adds further considerations worth investigating, and lists questions for a local adviser."),
      h("p", { class: "subtle" }, "Tip: answering the optional questions above makes the audit more specific."),
      h("div", { id: "turnstile-slot" }),
      h("button", { type: "button", class: "btn-primary", id: "ai-button", disabled: true }, "Run AI audit"),
      h("div", { id: "ai-output", class: "ai-output", "aria-live": "polite" }));
  }

  function aiBlock(title, ...children) {
    return h("section", { class: "ai-block" }, h("h5", { class: "ai-block-title" }, title), ...children);
  }

  function renderAIResult(res, recIndex) {
    const e = res.explanation;
    return h("div", {},
      h("p", { class: "ai-disclaimer" }, res.disclaimer),
      aiBlock("Overview", h("p", {}, e.overview)),
      aiBlock("Your reported practices", h("p", {}, e.reported_practices_review)),
      aiBlock("FieldWise suggestions, explained",
        e.explanations.map((x) => h("div", { class: "ai-item" },
          h("h6", {}, (recIndex[x.recommendation_id] || x.recommendation_id)),
          h("p", {}, x.plain_language),
          h("p", {}, h("strong", {}, "Tradeoffs: "), x.tradeoffs),
          h("p", {}, h("strong", {}, "Uncertainty: "), x.uncertainty)))),
      e.additional_considerations.length
        ? aiBlock("Additional considerations from the AI",
            h("p", { class: "ai-flag" }, "AI-generated — not from FieldWise's verified rules or sources. Investigate with a local adviser before acting."),
            e.additional_considerations.map((c) => h("div", { class: "ai-item ai-extra" },
              h("span", { class: "ai-cat" }, AI_CATEGORY_LABELS[c.category] || "Other"),
              h("h6", {}, c.title),
              h("p", {}, c.detail),
              h("p", {}, h("strong", {}, "Why it may be relevant: "), c.why_relevant))))
        : null,
      e.questions_for_adviser.length
        ? aiBlock("Questions to ask a local adviser", h("ol", { class: "ai-list" }, e.questions_for_adviser.map((q) => h("li", {}, q))))
        : null,
      aiBlock("What to verify before acting", h("ul", { class: "ai-list" }, e.verify_summary.map((v) => h("li", {}, v)))),
      h("p", { class: "subtle" }, `Model: ${res.model}${res.cached ? " · cached audit for identical inputs" : ""}`));
  }

  window.FW = window.FW || {};
  window.FW.render = { h, loading, errorState, renderSelection, renderRecommendations, renderContextForm, renderAIIntro, renderAIResult };
})();

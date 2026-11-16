# FieldWise

**Explore farmland. Understand better practices.**

FieldWise is a full-screen satellite map of the contiguous United States. You can search a town or ZIP code, see real USDA corn and wheat coverage, click a mapped crop area, and read deterministic, evidence-linked farming practices worth investigating. An optional AI audit is available.

It is an **educational decision-support prototype**. The USDA classification is a satellite-based estimate for one growing season. It is not a property boundary, an ownership record, proof of the current crop, or a measurement of soil, water, fertilizer, disease or yield. The suggestions are practices worth looking into, not diagnoses or prescriptions.

Stack: Python 3.12+, Flask, Jinja2, plain CSS, vanilla JavaScript, and MapLibre GL JS 4.7.1 from a CDN. There is no Node build step.

---

## Judge journey (under 2 minutes)

1. Open the app. You see 2025 USDA corn (yellow) and wheat (violet) coverage over the whole country.
2. Type **Ames, IA** in the search box and press Enter. Or choose an entry from **Example locations…**, which flies there and selects the area automatically.
3. Zoom in. Crop-area outlines appear from zoom 13. Click a colored area.
4. The panel shows **What the data tells us**, **What it does not tell us**, **Practices to consider** (cards with sources and case studies), and **Optional AI audit**.
5. Optionally answer the dropdowns under **Tell FieldWise what you know**, then click **Run AI audit** after the verification check.

---

## The real data pipeline (verified 2026-11-14)

| Step | Integration | Status |
|---|---|---|
| Newest CDL year | CroplandCROS ImageServer `query` on `https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer` (USDA ARS SCINet, hosts NASS CDL) | **Verified live.** Newest raster is `2025_10m_cdls`. The year is discovered at runtime and is not hard-coded. |
| Cross-check | CropScape `GetCDLValue?year=2026` | **Verified.** Service replies "year must be between 1997 and 2025". |
| Release check | NASS announcements page | 2025 CDL released Feb 27, 2026, at 10 m. |
| Overview tiles | ImageServer `exportImage` (raw U8 class codes in EPSG:3857), colored server-side | **Verified live.** |
| Point classification | ImageServer `identify`, with the mosaic locked to the newest raster | **Verified live.** Matches CropScape at the test point. |
| Outlines and selected region | Raw-class windows polygonized with `rasterio.features.shapes` | **Verified live.** |
| County/state | U.S. Census Geocoder `geographies/coordinates` | **Verified live.** |
| Town/ZIP search | U.S. Census 2025 Gazetteer (places + ZCTAs), served locally from `app/data/gazetteer.json` | **Verified.** |
| Satellite basemap | USGS The National Map `USGSImageryOnly` tile service: public domain, no key, attribution shown | **Verified live.** |

Integrations I rejected after testing, and why:

- **CropScape WMS** supports only EPSG:4326 and EPSG:5070 (no Web Mercator). It returns rendered colors, and several double-crop classes share colors with corn and wheat (for example, 225 "Dbl Crop WinWht/Corn" uses corn's yellow).
- **CropScape `GetCDLFile`** timed out or returned HTTP 502 after 90–180 s, so it is unusable for interactive outlines.

`app/data/dataset_manifest.json` records the dataset title, year, official URLs, service endpoint, check timestamp and evidence, category codes, coverage, limitations, and the fallback policy. If the live catalog is unreachable, the app uses the last verified record. It labels this in the UI ("last verified record" plus timestamp) and never silently swaps in a different year.

To re-verify after USDA publishes a new year:

```bash
python scripts/check_dataset.py --write
python scripts/verify_bookmarks.py
```

### Crop classes (official names from the service's raster attribute table)

| Group | Codes |
|---|---|
| Corn | 1 Corn · 12 Sweet Corn · 13 Pop or Orn Corn |
| Wheat | 22 Durum Wheat · 23 Spring Wheat · 24 Winter Wheat |
| **Excluded** (double-crop, never labeled corn or wheat) | 26, 225, 226, 228, 230, 234, 236, 237, 238, 241 |

Subtypes are kept throughout. When you click a double-crop pixel, the app reports the official class name and shows no crop-specific suggestions.

### How the map draws coverage and outlines

- **Overview, zoom 4–11:** 256 px tiles. Each pixel takes the majority class of the 10 m data beneath it (`RSP_Majority`), so small or narrow areas can disappear. The legend explains this.
- **Close-up, zoom 12–15:** nearest-neighbor resampling of the raw classes.
- **Outlines, zoom 13 and above:** polygonized from 512 px raw windows on a fixed z13 tile grid, which gives about 7–9 m pixels in CONUS. The outlines use 4-connectivity and are simplified by about 0.5 px. Regions under 12 px are dropped. Lines along tile edges are removed so tile seams never look like boundaries.
- **Selection:**
  - The clicked point is checked with `identify` first.
  - The app then traces the connected region of that exact class in a ~5 km window, widening to ~10 km if needed.
  - If the region still touches the window edge, it is drawn dashed, marked **incomplete**, and shown without a size.
  - The size is labeled "mapped crop-area size" and computed geodesically from the unsimplified outline.
- **Caching and limits:** all raster requests are bounded (≤1024 px) and cached on disk, keyed by raster ID. The browser cancels stale outline and selection requests, debounces panning, and caps outline requests at 24 tiles per view.

---

## Recommendations, sources and case studies

- `app/rules/engine.py` is a deterministic engine. The only inputs are the verified crop, subtype, dataset year, and the state, which only geographically scoped rules use. Categories always appear in this order: Soil health → Water efficiency → Crop rotation & cover crops. Within a category, rules are ordered by `display_order` and then ID.
- `app/data/recommendation_rules.json` holds ruleset `1.0.0`. Each rule has an ID, version, crops, geographic scope, prerequisites, trigger, display order, content, qualitative cost/effort, source IDs, case-study IDs, limitations and "verify before acting" items. A rule whose prerequisite is unknown, such as "irrigated", is either omitted or shown with an explicit condition ("If this area is irrigated: …").
- `app/data/sources.json` lists 9 sources: USDA NASS, SARE (USDA-funded), Penn State, University of Minnesota and University of Missouri extension, and the Midwest Cover Crops Council. Each URL was fetched and its content checked against the claim on 2026-11-14.
- `app/data/case_studies.json` has 5 SARE farmer profiles: IL, OH, IN, OK and ND. Summaries were checked against the pages. They carry no outcome figures, and each has an applicability limit. Profiles are matched to cards by practice and crop.
- To check that links are still live: `python scripts/check_links.py`. All 14 returned 200 on 2026-11-14.

NRCS pages could not be reached from the build environment because requests timed out, so no NRCS page is cited.

## Optional "Tell FieldWise what you know" (user-reported context)

Under **Practices to consider**, users can optionally answer up to 9 dropdowns covering things the USDA data cannot show:

- current crop
- soil texture
- recent soil test
- irrigation
- tillage
- residue
- cover crops
- previous crop
- nutrient source

Every answer defaults to "Not sure", and the app works fully without any answers.

- **Dropdowns only (`app/data/context_questions.json`):** there is no free text, so no personal data is collected and nothing can be injected into the AI. The server rejects any value outside the fixed options (HTTP 422).
- **Answers are always labeled "Reported by you — not verified by FieldWise".** They are kept separate from the verified USDA observations on every card and in the AI context.
- **The deterministic engine uses them.** Each rule prerequisite has an `answered_by` mapping:
  - An answer that meets the prerequisite removes the "If…" condition. Example: "Irrigated" removes it from the soil-moisture card.
  - An answer that rules it out hides the rule and lists it under "N suggestions hidden based on your answers". Examples: "No-till" hides the reduced-tillage card; "Not irrigated" hides the soil-moisture card.
  - Unknown answers keep the original behavior.
- Same answers always give the same output, regardless of key order. The ruleset is now `1.1.0`.
- Answering "a different crop" for this season adds a warning that the suggestions are based on the USDA classification.
- The AI receives the answers labeled as unverified user reports. It is told to say "you reported" and to treat them only as data. All existing output checks still apply.

This is an intentional, user-requested change to the original "no farmer questionnaire" requirement. It is strictly optional.

## AI audit

Button: **Run AI audit**. Endpoint: `POST /api/audit`.

Guards run in this order:

1. AI kill switch
2. API key check
3. Rate limit
4. Server-side Cloudflare Turnstile verification
5. Signed selection token, so the client cannot invent a crop

**What the audit contains:**

| Part | Grounded in |
|---|---|
| Overview | Classification, location, the user's answers, and the suggestions |
| Your reported practices | A review of how the user's reported answers fit together, labeled "you reported" |
| FieldWise suggestions, explained | Every deterministic suggestion, keyed by its ID (a schema enum), with tradeoffs and uncertainty |
| **Additional considerations from the AI** | Up to 5 further practices or issues worth investigating, each with a category and "why it may be relevant" |
| Questions to ask a local adviser | Up to 6 |
| What to verify before acting | Up to 8 |

**What the model receives:**

- the structured selection (crop, subtype, year, county/state; no coordinates)
- the rule-generated suggestions
- the user's dropdown answers, labeled unverified
- the suggestions hidden by those answers
- approved source excerpts
- explicit limitations

**About the AI's own additions:** the "Additional considerations" section deliberately goes beyond FieldWise's rules. This is a user-requested change from the original spec, which limited the AI to explaining existing suggestions. Those items are AI-generated and **not from FieldWise's verified rules, sources or case studies**, and the UI flags them that way. Citations and case studies are still rendered only from curated data, never from the model.

**Checks on the AI's answer:** the output must match a strict JSON schema. The server then validates it again and rejects any answer that contains:

- unknown, missing or duplicate suggestion IDs, or a category outside the fixed list
- links
- money, percentages, rates or amounts (lbs, bushels, inches, gallons…)
- "will increase/improve" claims
- diagnosis phrasing
- pesticide or herbicide application instructions
- uncited "research shows / a study" claims

Each request makes up to 2 attempts, then fails gracefully; the suggestions always stay usable. Audits for identical inputs are cached, and the cache key holds no user data.

Schema and pattern checks do **not** guarantee factual accuracy. The AI's additions are general agronomic reasoning that has not been verified.

**Provider: Anthropic Claude.** `app/services/ai_provider.py` calls `claude-haiku-5-5`, a low-cost model, through the official Anthropic Python SDK. It uses JSON-schema structured output (`output_config.format`) with `effort: low` and an output cap of 4000 tokens. SDK retries are disabled because the app runs its own bounded retries. Override the model with `AI_MODEL`.

---

## Local development

```bash
# 1. Create and activate a virtual environment (Python 3.12+; tested on 3.14 locally)
python3 -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

# 2. Install requirements (rasterio/pyproj/shapely wheels bundle GDAL/PROJ/GEOS — no system GDAL needed)
pip install -r requirements-dev.txt

# 3. Configure .env
cp .env.example .env
# Generate a value and paste it into SECRET_KEY in .env:
python -c "import secrets; print(secrets.token_hex(32))"
# Optional: add ANTHROPIC_API_KEY (https://console.anthropic.com/settings/keys) to enable "Run AI audit".
# The Turnstile keys in .env.example are Cloudflare's official always-pass TEST keys and work on localhost.

# 4. Run locally (development server) -> open http://127.0.0.1:5000
flask --app wsgi run --debug
#    or production-like -> open http://127.0.0.1:8000
gunicorn -c gunicorn.conf.py wsgi:app

# 5. Run tests (93 unit/API tests, all external services mocked)
pytest
# Optional browser smoke test (real network; needs a running server):
pip install playwright && python -m playwright install chromium
python tests/e2e/smoke_browser.py http://127.0.0.1:5000 /tmp/fieldwise-shots
```

Search data is already built. To rebuild it: `python scripts/build_gazetteer.py 2025`.

## Deployment: Render (one documented target)

`render.yaml` is a Render Blueprint.

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint** and select the repository. Render reads `render.yaml`.
3. When prompted, enter `ANTHROPIC_API_KEY`, `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`. `SECRET_KEY` is generated automatically.
4. Render builds the service and starts it with the settings below.

- Build: `pip install -r requirements.txt`
- Start: `gunicorn -c gunicorn.conf.py wsgi:app`. The Flask dev server is never used in production.
- Health check: `/healthz`
- Python: `PYTHON_VERSION=3.12.8`. All pinned packages have manylinux x86_64 wheels for CPython 3.12; this was checked with `pip download --only-binary`.

**Turnstile (production):**

1. In the Cloudflare dashboard, open Turnstile and choose **Add widget**.
2. Add your Render hostname (for example `fieldwise.onrender.com`) and any custom domain.
3. Choose the Managed mode.
4. Paste the site key and secret key into Render's environment settings.

The test keys only work for testing.

**Public keys:** the only value ever sent to the browser is `TURNSTILE_SITE_KEY`, and it is domain-restricted in Cloudflare. The basemap (USGS) and search (local Census data) need no tokens. `ANTHROPIC_API_KEY`, `TURNSTILE_SECRET_KEY` and `SECRET_KEY` stay on the server.

**Rate limiting and cache:**

- The blueprint runs one gunicorn process (`WEB_CONCURRENCY=1`) with 4 threads, so the in-memory limiter is shared within that process. It resets when the service restarts or spins down, and it is **not** reliable across multiple instances.
- If you scale beyond one process or instance, set `RATELIMIT_STORAGE_URI` to a Redis URL, such as a Render Key Value instance or any Redis provider.
- The disk cache lives in `/tmp` and is lost on restart. It holds genuine USDA data and rebuilds on demand.

## Accounts, billing and costs ($20 budget)

| Service | Account? | Billing info? | Usage-based charges | Notes |
|---|---|---|---|---|
| USDA CroplandCROS ImageServer, CropScape | No | No | None | Public government services; no stated SLA |
| USGS National Map imagery | No | No | None | Public domain; attribution shown |
| U.S. Census Geocoder and Gazetteer | No | No | None | Public |
| Cloudflare Turnstile | Yes (free Cloudflare account) | No | None for standard use | Test keys need no account |
| Anthropic API (AI audit) | Yes | **Yes**: prepaid credits | **Yes**: per token | Optional; the app works fully without it |
| Render | Yes | Free web services can be created without payment info, but going over free limits suspends services; paid plans need a card | Free: 750 instance-hours per month; spins down after 15 idle minutes (about 1 min cold start); ephemeral disk | Terms checked 2026-11-14; plans change, so re-check before relying on them |

**Spending controls:**

- **Anthropic:** buy a small prepaid credit amount (for example $10) and leave **auto-reload off**; the prepaid balance is the hard cap. You can also set a monthly spend limit in the Anthropic Console (Settings → Limits). Rough guide only, not a guarantee: one audit is about 4–6K input tokens and up to 4K output tokens. At Claude Haiku 5.5's listed $0.10 / $0.50 per million input/output tokens, that's about $0.002 per uncached audit, so $10 covers several thousand audits. Repeat audits for identical inputs are served from cache at no cost.
- **App-side limits:** `AI_ENABLED=false` switches the AI audit off instantly. `RATELIMIT_AI` (default 5/min and 40/day per IP), `AI_MAX_OUTPUT_TOKENS` and `AI_MAX_INPUT_CHARS` bound each request. These are not a dollar cap; the prepaid balance is.
- **Render:** stay on the Free plan, or Starter for always-on. Render does not auto-upgrade plans.

## Privacy

- No accounts and no cookies are set by the app. Cloudflare Turnstile sets its own as part of the challenge.
- Selected coordinates are sent in the POST body, not the URL, so they do not appear in access logs. The gunicorn access log format **omits client IPs**. `LOG_COORDINATES` is off by default.
- The rate limiter keeps client IPs in memory only, for the limit window.
- Coordinates (rounded to 5 decimals) are sent to the U.S. Census Geocoder to look up the county and state. The AI provider receives no coordinates and no user data.

## Known limitations

- The CDL is a classification with errors. NASS reports producer's accuracy of "generally 85% to 95%" for major crops, and accuracy varies by state and crop. Field edges are less reliable.
- Connected regions join adjacent fields of the same class and split a field where classes differ. They are not parcels.
- At broad zooms, majority resampling can hide small areas.
- Imagery dates vary by area and are not synchronized with the CDL year.
- The ImageServer is a USDA research host with no published SLA. If it is down, the app shows "USDA service unavailable" instead of fabricated data.
- ZCTAs approximate ZIP Codes. Search covers Census places and ZCTAs only, with no street addresses.
- The rules are deliberately general. FieldWise knows nothing about soil, management or irrigation.
- Optional weather was not implemented, since it is a stretch goal.

## What remains unverified

(The AI audit was verified live on 2026-11-14 with `claude-haiku-5-5`: real audits for Iowa corn, Kansas winter wheat and North Dakota spring wheat each returned HTTP 200 in about 12 s, passed server-side validation on the first attempt, rendered in the browser, and repeat requests were served from cache.)


- **Turnstile with production keys and domain:** implemented but unverified. Tested with mocks; the official test keys are documented.
- **The Render deployment itself:** not performed, because it needs your account. Wheels resolve and gunicorn starts locally.

## Project layout

```
app/
  __init__.py  config.py  errors.py  cache.py  selection.py
  routes/      pages.py crops.py recommendations.py ai.py
  services/    usda.py geocoding.py ai_provider.py turnstile.py
  rules/       engine.py
  data/        dataset_manifest.json recommendation_rules.json sources.json case_studies.json bookmarks.json gazetteer.json
  templates/   index.html
  static/      css/styles.css  js/{api,map,recommendations,main}.js
scripts/       check_dataset.py verify_bookmarks.py check_links.py build_gazetteer.py
tests/         pytest suite + e2e/smoke_browser.py (Playwright)
wsgi.py  gunicorn.conf.py  render.yaml  requirements*.txt  .env.example
```

**CDN dependencies:**

- `https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.{js,css}` (pinned)
- `https://challenges.cloudflare.com/turnstile/v0/api.js`, loaded only when the AI section appears, as Cloudflare requires

# FieldWise

**Explore farmland. Understand better practices.**

FieldWise is a satellite map of the contiguous United States that shows where corn and wheat were grown, according to real USDA satellite data. Click any mapped crop area to get climate-smart farming practices worth investigating: soil health, water efficiency, and crop rotation and cover crops. Each practice links to evidence. You can then run an **AI audit** that explains the suggestions, reviews what you told FieldWise about the land, and lists what to check with a local adviser.

> **Track: AI + Climate**

---

## For judges: try it in under 2 minutes

1. Open the app. The 2025 USDA corn (yellow) and wheat (violet) coverage loads across the whole country.
2. Search **Ames, IA**, or choose an entry from **Example locations…**.
3. Zoom in until crop-area outlines appear, then click a colored area.
4. The side panel shows:
   - **What the data tells us**: the official USDA crop class, the year, county and state, and the mapped area size.
   - **What it does not tell us**: the honest limits of satellite data.
   - **Practices to consider**: cards with sources and real farmer case studies.
5. Optionally answer the **Tell FieldWise what you know** dropdowns (tillage, irrigation, cover crops and so on), then click **Run AI audit**.

| | |
|---|---|
| **Live demo** | _add Render URL_ |
| **Demo video** | https://youtu.be/Vy-Bu-6TMTs |
| **Run locally** | See [Run it locally](#run-it-locally) below |

---

## Why this is a Climate project

Corn and wheat cover a large share of U.S. cropland, so how those acres are managed matters for the climate. Practices such as cover crops, reduced tillage, keeping crop residue on the field, and efficient irrigation are widely promoted by USDA programs and university extension. They protect soil from erosion, build soil organic matter and conserve water. These matter for **mitigation**, because soil carbon and fertilizer use affect emissions. They also matter for **adaptation**, because healthier soils cope better with heavy rain and drought.

The problem is that this guidance is scattered across extension PDFs and is rarely tied to a specific place. FieldWise connects three things:

1. **Where:** real, satellite-derived crop maps (USDA Cropland Data Layer, 10 m resolution).
2. **What:** a transparent rules engine that matches the crop and region to climate-relevant practices.
3. **Why:** a verified source and a real farmer case study for every suggestion, plus an AI audit that turns all of it into plain language and questions to ask.

It is built for students, extension educators, landowners and curious members of the public who want to understand climate-smart agriculture on real land. It is an **educational decision-support prototype**. It does not prescribe treatments for anyone's field.

---

## How AI is used, responsibly

FieldWise deliberately splits the work between deterministic code and AI:

| Layer | What it does | Can it hallucinate? |
|---|---|---|
| **USDA data pipeline** | Classifies the clicked point and traces the crop-area outline from the raw satellite classification | No. These are real government data, and the app labels when the data service is unavailable. |
| **Rules engine** | Picks practices from a versioned JSON ruleset using only the verified crop, year and state, plus any optional dropdown answers | No. The same inputs always give the same output. |
| **Sources and case studies** | 9 verified extension and USDA sources and 5 SARE farmer profiles, each checked by hand | No. Only curated data is shown. |
| **AI audit (Claude Haiku 5.5)** | Explains each suggestion, reviews the user's reported practices, adds up to 5 extra considerations, and lists questions for a local adviser | It can, so it is constrained and labeled. |

**Guardrails on the AI audit:**

- **Strict output schema.** The AI must return JSON that matches a schema. It can only explain suggestions that exist, because their IDs are a fixed enum.
- **Server-side validation.** The server rejects any answer that contains links, dollar figures, percentages, application rates, yield guarantees, diagnoses, pesticide instructions, or uncited "research shows" claims.
- **No coordinates or personal data are sent to the model.** User answers come only from dropdowns, so there is no free text to inject instructions into, and they are labeled "reported by you, not verified".
- **Clear labeling.** Anything the AI adds beyond FieldWise's rules is marked as AI-generated and not from verified sources.
- **Abuse and cost protection.** The audit sits behind Cloudflare Turnstile, per-IP rate limits, a kill switch and a response cache.

If the AI is off or fails, everything else still works.

---

## Features

- Full-screen satellite basemap (USGS National Map imagery).
- Live USDA corn and wheat coverage, with the newest data year found automatically at runtime.
- Crop-area outlines traced from the raw satellite classes, with honest "incomplete" labeling at the edges.
- Search by town or ZIP code (U.S. Census Gazetteer), plus curated example locations.
- Crop subtypes are kept: sweet corn, durum, spring and winter wheat. Double-crop classes are never mislabeled.
- Optional dropdowns that refine the suggestions. For example, "No-till" hides the reduced-tillage card.
- An AI audit with an overview, a review of your practices, explained suggestions, extra considerations, adviser questions and a verification checklist.
- Privacy by design: no accounts and no app cookies, IPs are left out of logs, and the AI never receives coordinates.
- 93 automated tests with all external services mocked, plus a browser smoke test.

---

## Tech stack

- **Backend:** Python 3.12, Flask, Gunicorn, Pydantic, Flask-Limiter
- **Geospatial:** rasterio, shapely, pyproj, NumPy, Pillow
- **Frontend:** vanilla JavaScript, plain CSS, MapLibre GL JS 4.7.1. There is no build step.
- **AI:** Anthropic Claude Haiku 5.5 (`claude-haiku-5-5`) through the official Anthropic Python SDK, with structured JSON output
- **Security:** Cloudflare Turnstile and signed selection tokens (itsdangerous)
- **Deployment:** Render Blueprint (`render.yaml`)

The full architecture, data-pipeline verification, rules design and deployment notes are in **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.

---

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Put a random SECRET_KEY in .env. Optionally add ANTHROPIC_API_KEY to enable the AI audit.
flask --app wsgi run --debug
# Then open http://127.0.0.1:5000
```

Run the tests with `pytest`.


## Credits

### Datasets and data services

- **USDA NASS Cropland Data Layer (CDL), 2025, 10 m.** Served through the USDA ARS CroplandCROS ImageServer.
  - https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php
  - https://croplandcros.scinet.usda.gov/
  - https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer
- **USDA NASS CropScape**, used to cross-check the newest available year: https://nassgeodata.gmu.edu/CropScape/
- **USGS The National Map imagery basemap** (public domain): https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer
- **U.S. Census Bureau Gazetteer Files, 2025** (places and ZCTAs), used for town and ZIP search: https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
- **U.S. Census Bureau Geocoder**, used for county and state lookup: https://geocoding.geo.census.gov/geocoder/

### Evidence sources behind the suggestions

- USDA NASS: [Cropland Data Layer FAQ](https://www.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php)
- SARE: [Building Soils for Better Crops, 4th ed.](https://www.sare.org/resources/building-soils-for-better-crops/)
- SARE: [Cover Crops for Sustainable Crop Rotations](https://www.sare.org/resources/cover-crops/)
- SARE: [Managing Cover Crops Profitably, 3rd ed.](https://www.sare.org/resources/managing-cover-crops-profitably-3rd-edition/)
- University of Missouri Extension: [Field crops soil testing](https://extension.missouri.edu/programs/soil-and-plant-testing-laboratory/spl-soil-analysis/spl-field-crops-soil-test)
- University of Missouri Extension: [Tools for monitoring soil moisture](https://extension.missouri.edu/programs/irrigation/tools-for-monitoring-soil-moisture)
- Penn State Extension: [No-till and the Soil](https://extension.psu.edu/no-till-and-the-soil)
- University of Minnesota Extension: [Soil moisture sensors for irrigation scheduling](https://blog-crop-news.extension.umn.edu/2019/04/soil-moisture-sensors-for-irrigation.html)
- [Midwest Cover Crops Council](https://www.midwestcovercrops.org/)

### Farmer case studies (SARE farmer profiles)

- [Ralph "Junior" Upton, Illinois](https://www.sare.org/publications/cover-crop-book/junior-upton-illinois/)
- [David Brandt, Ohio](https://www.sare.org/publications/cover-crop-book/david-brandt-ohio/)
- [Dan DeSutter, Indiana](https://www.sare.org/publications/cover-crop-book/dan-desutter-indiana/)
- [Jimmy and Ginger Emmons, Oklahoma](https://www.sare.org/publications/cover-crop-book/jimmy-and-ginger-emmons-oklahoma/)
- [Justin and Molly Zahradka, North Dakota](https://www.sare.org/publications/cover-crop-book/justin-and-molly-zahradka-north-dakota/)

### Pretrained models

- **Anthropic Claude Haiku 5.5** (`claude-haiku-5-5`), called at runtime for the AI audit: https://docs.anthropic.com/

### AI tools used to build the project

- **Claude Code** (Anthropic), powered by **Claude Opus 5.5**, helped write code, tests and documentation: https://claude.com/claude-code

### Open-source libraries

- [Flask](https://flask.palletsprojects.com/)
- [Flask-Limiter](https://flask-limiter.readthedocs.io/)
- [Gunicorn](https://gunicorn.org/)
- [Pydantic](https://docs.pydantic.dev/)
- [Requests](https://requests.readthedocs.io/)
- [python-dotenv](https://github.com/theskumar/python-dotenv)
- [rasterio](https://rasterio.readthedocs.io/)
- [Shapely](https://shapely.readthedocs.io/)
- [pyproj](https://pyproj4.github.io/pyproj/)
- [NumPy](https://numpy.org/)
- [Pillow](https://python-pillow.org/)
- [MapLibre GL JS](https://maplibre.org/)
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/)

### Tutorials

- _None used._

---

## Limitations

- **The CDL is a satellite-based estimate.** USDA reports accuracy of generally 85–95% for major crops, and field edges are less reliable.
- **Mapped areas are not parcels.** They are not property boundaries or ownership records, and they are not proof of what is planted today.
- **The suggestions are general.** They are practices worth investigating, not prescriptions. FieldWise does not know the soil, management or finances of any field.
- **The AI audit is constrained, not guaranteed.** Its extra considerations are general reasoning that has not been verified.

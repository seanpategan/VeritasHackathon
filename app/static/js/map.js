/* FieldWise — MapLibre map: satellite basemap, USDA crop overview tiles, outlines, selection highlight. */
(function () {
  "use strict";

  const OUTLINE_Z = 13;            // server-side outline grid
  const OUTLINE_MIN_VIEW_Z = 13;   // show outlines from this map zoom
  const SELECT_MIN_Z = 12;         // allow selection from this map zoom
  const MAX_OUTLINE_TILES = 24;    // bound requests per view
  const CONUS_BOUNDS = [[-125.0, 24.4], [-66.9, 49.5]];
  // Strong overlay for the national overview; lighter close up so the imagery stays readable.
  const OVERLAY_OPACITY = ["interpolate", ["linear"], ["zoom"], 6, 0.75, 12, 0.55, 15, 0.35];

  const listeners = { select: [], zoomHint: [], providerError: [] };
  const emit = (ev, payload) => listeners[ev].forEach((fn) => fn(payload));

  let map;
  const outlineCache = new Map(); // tileKey -> features (insertion-ordered LRU)
  let outlineAbort = null;
  let outlineTimer = null;
  let errorCounts = { imagery: 0, corn: 0, wheat: 0, outlines: 0 };

  function lon2tile(lon, z) { return Math.floor(((lon + 180) / 360) * 2 ** z); }
  function lat2tile(lat, z) {
    const r = (lat * Math.PI) / 180;
    return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
  }

  function style() {
    return {
      version: 8,
      sources: {
        imagery: {
          type: "raster",
          tiles: ["https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}"],
          tileSize: 256,
          maxzoom: 16,
          attribution:
            'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map" target="_blank" rel="noopener">USGS The National Map</a> (dates vary; not synchronized with the CDL year)',
        },
        corn: {
          type: "raster",
          tiles: [location.origin + "/api/tiles/corn/{z}/{x}/{y}.png"],
          tileSize: 256, minzoom: 4, maxzoom: 15,
          bounds: [-125.0, 24.4, -66.9, 49.5],
          attribution: 'Crops: <a href="https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php" target="_blank" rel="noopener">USDA NASS Cropland Data Layer</a> via CroplandCROS',
        },
        wheat: {
          type: "raster",
          tiles: [location.origin + "/api/tiles/wheat/{z}/{x}/{y}.png"],
          tileSize: 256, minzoom: 4, maxzoom: 15,
          bounds: [-125.0, 24.4, -66.9, 49.5],
        },
        outlines: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
        selection: { type: "geojson", data: { type: "FeatureCollection", features: [] } },
      },
      layers: [
        { id: "imagery", type: "raster", source: "imagery" },
        { id: "corn", type: "raster", source: "corn", paint: { "raster-opacity": OVERLAY_OPACITY, "raster-resampling": "nearest" } },
        { id: "wheat", type: "raster", source: "wheat", paint: { "raster-opacity": OVERLAY_OPACITY, "raster-resampling": "nearest" } },
        {
          id: "outlines-casing", type: "line", source: "outlines", minzoom: OUTLINE_MIN_VIEW_Z,
          paint: { "line-color": "rgba(10,20,15,0.55)", "line-width": 2.6 },
        },
        {
          id: "outlines", type: "line", source: "outlines", minzoom: OUTLINE_MIN_VIEW_Z,
          paint: {
            "line-color": ["match", ["get", "crop"], "corn", "#ffe27a", "wheat", "#d9c4ff", "#ffffff"],
            "line-width": 1.2,
          },
        },
        { id: "selection-fill", type: "fill", source: "selection", paint: { "fill-color": "#ffffff", "fill-opacity": 0.18 } },
        { id: "selection-casing", type: "line", source: "selection", paint: { "line-color": "#0b1a12", "line-width": 6, "line-opacity": 0.7 } },
        {
          id: "selection-line", type: "line", source: "selection",
          filter: ["!=", ["get", "clipped"], true],
          paint: { "line-color": "#ffffff", "line-width": 3 },
        },
        {
          id: "selection-line-clipped", type: "line", source: "selection",
          filter: ["==", ["get", "clipped"], true],
          paint: { "line-color": "#ffffff", "line-width": 3, "line-dasharray": [2, 1.5] },
        },
      ],
    };
  }

  function visibleOutlineTiles() {
    const b = map.getBounds();
    const w = Math.max(b.getWest(), CONUS_BOUNDS[0][0]);
    const e = Math.min(b.getEast(), CONUS_BOUNDS[1][0]);
    const s = Math.max(b.getSouth(), CONUS_BOUNDS[0][1]);
    const n = Math.min(b.getNorth(), CONUS_BOUNDS[1][1]);
    if (w >= e || s >= n) return [];
    const x0 = lon2tile(w, OUTLINE_Z), x1 = lon2tile(e, OUTLINE_Z);
    const y0 = lat2tile(n, OUTLINE_Z), y1 = lat2tile(s, OUTLINE_Z);
    const tiles = [];
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) tiles.push([x, y]);
    tiles.sort((a, b2) => Math.hypot(a[0] - cx, a[1] - cy) - Math.hypot(b2[0] - cx, b2[1] - cy));
    return tiles.slice(0, MAX_OUTLINE_TILES);
  }

  function refreshOutlineSource(tiles) {
    const feats = [];
    for (const [x, y] of tiles) {
      const f = outlineCache.get(x + "/" + y);
      if (f) feats.push(...f);
    }
    map.getSource("outlines").setData({ type: "FeatureCollection", features: feats });
  }

  async function loadOutlines() {
    const z = map.getZoom();
    updateZoomHint();
    if (z < OUTLINE_MIN_VIEW_Z) return;
    if (outlineAbort) outlineAbort.abort(); // cancel stale requests
    const ctrl = new AbortController();
    outlineAbort = ctrl;
    const tiles = visibleOutlineTiles();
    refreshOutlineSource(tiles);
    const missing = tiles.filter(([x, y]) => !outlineCache.has(x + "/" + y));
    let i = 0;
    const worker = async () => {
      while (i < missing.length && !ctrl.signal.aborted) {
        const [x, y] = missing[i++];
        try {
          const fc = await FW.api.get(`/api/outlines/${OUTLINE_Z}/${x}/${y}.json`, ctrl.signal);
          outlineCache.set(x + "/" + y, fc.features);
          if (outlineCache.size > 120) outlineCache.delete(outlineCache.keys().next().value);
          if (!ctrl.signal.aborted) refreshOutlineSource(tiles);
        } catch (err) {
          if (err.name === "AbortError") return;
          errorCounts.outlines++;
          if (errorCounts.outlines === 3) emit("providerError", { kind: "usda", message: "Crop-area outlines could not be loaded from the USDA service right now." });
        }
      }
    };
    await Promise.all([worker(), worker(), worker(), worker()]); // at most 4 concurrent
  }

  function updateZoomHint() {
    const z = map.getZoom();
    let msg = "";
    if (z < 4) msg = "Zoom in to view crop coverage.";
    else if (z < OUTLINE_MIN_VIEW_Z) msg = "Zoom in to view crop-area outlines.";
    else msg = "";
    const canSelect = z >= SELECT_MIN_Z;
    emit("zoomHint", { message: msg, canSelect, zoom: z });
  }

  function init(container) {
    map = new maplibregl.Map({
      container,
      style: style(),
      bounds: CONUS_BOUNDS,
      fitBoundsOptions: { padding: { top: 90, bottom: 40, left: 20, right: 20 } },
      maxBounds: [[-140, 15], [-50, 58]],
      minZoom: 2.5,
      maxZoom: 17.5,
      attributionControl: { compact: false },
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "top-left");

    map.on("moveend", () => {
      clearTimeout(outlineTimer);
      outlineTimer = setTimeout(loadOutlines, 350); // debounce while panning
    });
    map.on("load", () => { updateZoomHint(); loadOutlines(); });
    map.on("click", (e) => {
      const z = map.getZoom();
      if (z < SELECT_MIN_Z) {
        emit("select", { tooFar: true, lngLat: e.lngLat });
        return;
      }
      emit("select", { lngLat: e.lngLat });
    });
    map.on("error", (e) => {
      const id = e.sourceId || (e.source && e.source.id);
      if (!id || !(id in errorCounts)) return;
      errorCounts[id]++;
      if (id === "imagery" && errorCounts.imagery === 4) {
        emit("providerError", { kind: "imagery", message: "Satellite imagery tiles from USGS are not loading. Crop overlays may still work." });
      }
      if ((id === "corn" || id === "wheat") && errorCounts[id] === 4) {
        emit("providerError", { kind: "usda", message: "The USDA crop service is not responding, so some crop coverage tiles are missing." });
      }
    });
    map.on("sourcedata", (e) => {
      if (e.isSourceLoaded && e.sourceId === "imagery") errorCounts.imagery = 0;
    });
    return map;
  }

  function setLayerVisible(crop, visible) {
    const v = visible ? "visible" : "none";
    map.setLayoutProperty(crop, "visibility", v);
    const cropsOn = ["corn", "wheat"].filter((c) => map.getLayoutProperty(c, "visibility") !== "none");
    const filter = ["in", ["get", "crop"], ["literal", cropsOn]];
    map.setFilter("outlines", filter);
    map.setFilter("outlines-casing", filter);
  }

  function setSelection(geometry, clipped) {
    const data = geometry
      ? { type: "FeatureCollection", features: [{ type: "Feature", properties: { clipped: !!clipped }, geometry }] }
      : { type: "FeatureCollection", features: [] };
    map.getSource("selection").setData(data);
  }

  function flyToBbox(bbox) {
    map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 60, maxZoom: 14, duration: 1200 });
  }

  function flyTo(lon, lat, zoom) {
    map.flyTo({ center: [lon, lat], zoom, duration: 1400 });
  }

  window.FW = window.FW || {};
  window.FW.map = {
    init, setLayerVisible, setSelection, flyToBbox, flyTo,
    on: (ev, fn) => listeners[ev].push(fn),
    get instance() { return map; },
    SELECT_MIN_Z,
  };
})();

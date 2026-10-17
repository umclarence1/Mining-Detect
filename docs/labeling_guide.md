# Labelling guide

Consistent labels matter more than model choice. Agree on these rules before labelling and update this file if a rule changes.

## Class: mining (1)
Label as mining:
- Bare, excavated ground with pits or spoil heaps
- Water-filled pits and settling ponds (often brown, green or milky)
- Disturbed river channels and banks where dredging or washing has happened

## Class: background (0)
Do **not** label as mining:
- Farmland, fallow or freshly cleared fields (regular shapes, no pits)
- Roads, villages, towns, construction sites
- Natural sandbars and riverbanks without pits
- Burn scars
- Rehabilitated sites that have clearly regrown vegetation

## What it looks like in Tarkwa imagery
- **True colour** is best for galamsey: thin, branching **yellow-tan or orange-brown scars following streams**, often with small ponds.
- **SWIR false colour (B12/B8/B4)**: galamsey shows mainly as **blue-cyan lines and ponds** (wet sediment, muddy water) along streams; industrial pits and waste dumps are **grey or brown**; forest is bright green.
- Industrial mines (big pits, square tailings ponds, terraced dumps) are obvious; label them too.

## Rules
- Label on the same dry-season period as the imagery (baseline labels on 2019–2020 imagery).
- Use high-resolution imagery (Planet/NICFI or Google satellite basemap) to decide, then draw on the Sentinel-2 composite.
- Draw the outer edge of the disturbed area; don't split one site into many tiny polygons.
- If unsure, skip it and note the location in `labels/uncertain.geojson`.
- Licensed industrial mines (e.g. Gold Fields Tarkwa, Iduapriem) are still labelled **mining** — legality is handled later using concession boundaries.

## Output
Save polygons to `labels/hand_labels.geojson` (EPSG:4326) with fields:
`class` (1 = mining, 0 = not mining), `period` (baseline/recent), `labeller`, `confidence` (high/medium), `notes`.

Class 0 polygons are useful too: draw them over things the provisional labels or the model wrongly call mining (town edges, farms, roads). They override the rule-based labels.

## Completely labelled squares (for honest scores)
Accuracy can only be measured where *every* mining patch has been drawn. So instead of labelling the whole 400 km² Tarkwa block, pick **6–8 squares** (2.56 km each) from `labels/test_squares.geojson` and label each one completely, **for both 2020 and 2026**:
- Choose a mix: 2–3 with stream galamsey, 1–2 with industrial mine, 1 with town edge, 1–2 mostly forest.
- Inside a finished square, draw every mining patch (class 1). Anything not drawn counts as "not mining".
- When a square is finished for both years, copy its outline into `labels/hand_label_areas.geojson`.

Inside those squares the rule-based labels are ignored, and test scores are computed only there.

## How to label in QGIS
1. **Layers.** Drag in `outputs/predictions/baseline_rgb.tif` (2020), `recent_rgb.tif` (2026) and `labels/test_squares.geojson` (style: no fill, yellow outline, label by `square`).
   High-res basemap: Browser panel → XYZ Tiles → right-click → New Connection → URL
   `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
   (it shows recent imagery, so use it for 2026 and to confirm what you see in Sentinel-2).
   Optional: `recent_label.tif` / `recent_mask.tif` to see what the rule and the model think.
2. **Label layer.** Layer → Create Layer → New GeoJSON… (or Shapefile), Polygon, EPSG:4326, saved as `labels/hand_labels.geojson`. Fields: `class` (integer), `period` (text), `labeller` (text), `confidence` (text), `notes` (text).
3. **Draw.** Select the layer → pencil (Toggle Editing) → Add Polygon Feature → click around the edge → right-click to finish → fill in the fields (`period` = `baseline` for 2020, `recent` for 2026). Save edits often.
   Tip: Settings → Options → Digitizing → enable snapping so neighbouring polygons don't overlap or leave gaps.
4. **Squares done.** Select finished squares in `test_squares` → Edit → Copy Features → paste into a new layer saved as `labels/hand_label_areas.geojson`.
5. **Then**, with internet (it re-downloads only the tiles you labelled):
   `python run_pipeline.py --relabel`

Budget: about 30–45 minutes per square for both years.

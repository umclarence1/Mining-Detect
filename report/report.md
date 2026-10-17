# Galamsey Detector: mapping small-scale gold mining around Tarkwa, Ghana, with Sentinel-2 and a U-Net

*Draft, with results from the first full run (provisional labels). Numbers come from `report/results.md`, `report/change.json` and `outputs/maps/alerts.csv`; update them after hand labelling.*

## 1. Problem
Illegal small-scale gold mining (*galamsey*) strips forest, digs pits along streams and fills rivers with sediment and mercury. Sites are usually noticed months after the damage, when rivers are already polluted and water-treatment plants have had to cut production. Free satellite imagery is captured over Ghana every five days, so mining could be mapped as it happens rather than after the fact.

This project asks:
1. Can a segmentation model trained on Sentinel-2 imagery map mining at 10 m resolution?
2. Do the 11 non-RGB bands (red-edge, near- and short-wave infrared) help, compared with RGB alone?
3. How much land around Tarkwa was newly disturbed by mining between the 2020 and 2026 dry seasons?
4. Which new sites should be looked at first?

## 2. Study area and data
- **Training region:** about 130 x 180 km covering the Ankobra, Pra and Offin basins (Western, Central and Ashanti regions).
- **Test block:** about 20 x 20 km around Tarkwa, never used for training, with a 2 km buffer between it and every training tile.
- **Imagery:** Sentinel-2 Level-2A surface reflectance, 12 bands, via Google Earth Engine. Cloudy pixels are removed with Cloud Score+ (`cs_cdf >= 0.6`) and the remaining pixels are combined into dry-season (Nov–Feb) median composites for 2019–20 and 2025–26. Every pixel had at least about 12 clear observations in both periods (Tarkwa: 24 and 19), so the composites have no cloud gaps.
- **Labels:** see section 3.
- **Supporting data:** MERIT Hydro (stream network), ESA WorldCover 2021 (built-up areas), WDPA (protected areas, including forest reserves).

## 3. Labels
The Maus et al. (2022) global mining polygons cover the large industrial mines around Tarkwa, but their outlines are coarse (they include forest inside the mine boundary) and they miss almost all stream-side galamsey. Training on them alone would teach a model to ignore galamsey.

Provisional labels therefore combine:
- **Maus polygons, restricted to bare ground and water inside them**, and
- **a galamsey rule:** bare soil (NDVI < 0.38, not water) or muddy water (MNDWI > 0, red reflectance > 0.07) within 300 m of a stream (MERIT Hydro upstream area >= 0.5 km²), excluding built-up areas; thin features and patches under 0.1 ha are removed.

The rule thresholds were tuned by eye on the Tarkwa block, where the rule picks up most pits, tailings and stream scars, with some false positives at the edge of town.

**Hand labels** drawn in QGIS (`docs/labeling_guide.md`) override the provisional labels. Until the Tarkwa test block is hand-labelled, test scores measure *agreement with the rule*, not true accuracy. **[Update when hand labels are in.]**

## 4. Method
- **Tiles:** 256 x 256 pixels (2.56 km) on a UTM 30N grid. From the training region, up to 300 tiles containing mining and 150 without are sampled per period; all 64 tiles of the Tarkwa block are exported for both periods.
- **Splits:** tiles are grouped into 10 km blocks, and whole blocks are assigned to training or validation (15%), so near-identical neighbouring tiles never sit on both sides of the split.
- **Model:** U-Net with a ResNet-18 encoder pre-trained on ImageNet (`segmentation_models_pytorch`); for 12 bands the first layer is adapted from the pretrained weights. Dice + binary cross-entropy loss (mining pixels are rare), AdamW with a one-cycle schedule, random 128 px crops, flips and rotations, 15 epochs on a laptop CPU. The checkpoint with the best validation IoU is kept.
- **Experiments:** RGB (B4, B3, B2) vs all 12 bands.
- **Baseline:** NDVI < 0.3 labelled as mining.
- **Change:** the model is applied to both composites of the Tarkwa block; *new mining* = mining in 2026 and not in 2020, after removing patches under 0.1 ha.
- **Area and accuracy:** pixel counts are biased by the model's errors, so a stratified random sample of 180 points (new mining / stable mining / no mining) is interpreted visually and used for error-adjusted area with a 95% confidence interval (Olofsson et al., 2014), and for point-based accuracy of each year's map.
- **Alerts:** each new-mining patch is ranked by area, with higher priority within 500 m of a stream or inside a protected area, and lower inside the Maus industrial footprint (most likely licensed).
- **Turbidity:** mean NDTI = (red − green)/(red + green) on water pixels of major rivers (upstream area >= 1000 km²), per period.

## 5. Results
### 5.1 Detection accuracy (Tarkwa test block)
Training used 752 tiles, with 148 tiles in separate geographic blocks for validation. Scores are on the 128 Tarkwa test tiles (64 per period), **against the provisional labels**:

| Model | IoU | F1 | Precision | Recall |
|---|---|---|---|---|
| Baseline (NDVI < 0.3) | 0.600 | 0.750 | 0.641 | 0.903 |
| U-Net, RGB | 0.711 | 0.831 | 0.828 | 0.834 |
| U-Net, all 12 bands | **0.757** | **0.861** | **0.851** | **0.872** |

Best validation IoU was 0.777 (RGB) and 0.801 (12 bands). The 12-band model beats RGB on every measure, consistent with the short-wave infrared bands helping to separate bare and wet mined ground from other surfaces. Both U-Nets beat the baseline mainly on precision (0.83–0.85 vs 0.64): the baseline marks every bare surface, including towns and roads, as mining.

**Caveat:** these scores measure how well the models reproduce the provisional labels, not true accuracy. They will be recomputed inside hand-labelled squares.

### 5.2 Change 2020 to 2026
Over the 41,943 ha Tarkwa block (U-Net, 12 bands, patches under 0.1 ha removed; pixel counts, not yet error-adjusted):

| | Hectares | Share of area |
|---|---|---|
| Mining 2020 | 3,731 | 8.9% |
| Mining 2026 | 5,735 | 13.7% |
| Net increase | +2,004 | +54% |
| Newly disturbed (mining in 2026, not 2020) | 3,045 | |
| ... outside the Maus industrial footprint | 1,879 | |
| ... inside the Maus industrial footprint | 1,166 | |
| No longer mining (mining in 2020, not 2026) | 1,041 | |

**Error-adjusted area.** A stratified random sample of 180 points (60 in mapped new mining, 30 in stable mining, 90 elsewhere) was interpreted visually for mining in 2020 and in 2026, without seeing the model output. 23 points were too uncertain to call and were left out, leaving 157. Using Olofsson et al. (2014):

| | Value |
|---|---|
| Newly disturbed by mining, error-adjusted | **4,540 ± 2,060 ha** (95% CI ≈ 2,480–6,600 ha) |
| Pixel-count estimate (for comparison) | 3,045 ha |
| Share of mapped "new mining" that is truly new (user's accuracy) | 61% |
| Point agreement with the model, 2026 map | 88% (153 points) |
| Point agreement with the model, 2020 map | 88% (151 points) |

The two errors pull in opposite directions. About 39% of the pixels mapped as new were not new (mostly ground already mined in 2020 at the edges of existing sites, or reshaped industrial ground). But 6 of 84 points in the large "no mining" stratum were in fact new mining, mostly thin stream scars the model missed. That stratum covers about 36,000 ha, so this omission outweighs the false alarms. Net result: **the pixel count probably understates new mining**. The interval is wide because only 157 points were used; more points, especially in the "no mining" stratum, would narrow it.

**Who labelled the points:** the reference points were interpreted by an AI assistant (Claude) from the 10 m Sentinel-2 composites, blind to the model output and the strata, and not checked by a human or in the field. This is weaker than independent human or field validation (see Limitations).

The "no longer mining" area mixes real revegetation and reshaped industrial sites with model error.

Visually the pattern is clear: in 2020 the streams east and south of Tarkwa are mostly forested; by 2026 mining scars follow nearly every stream.

### 5.3 Alerts
New mining **outside** the Maus industrial footprint forms **1,105 sites totalling 1,874 ha**. **1,060 sites (96%) lie within 500 m of a stream**, consistent with alluvial galamsey, and **84 sites lie inside forest reserves** (Bonsa River, Neung North and Neung South).

A visual check of the top four alerts: #3 and #4 are typical galamsey (forest in 2020, branching scars along a stream in 2026). #1 and #2 are new industrial works (a large new facility and a pit expansion) just outside the Maus outlines, which were traced from 2019 imagery. This shows the main weakness of using Maus as a stand-in for licensed areas; concession boundaries would move such sites out of the alert list.

### 5.4 River turbidity
Mean NDTI on major rivers barely changed (+0.078 in 2020, +0.075 in 2026), while mean red reflectance of river water rose from 0.216 to 0.267 and the area classed as river water grew by about 60%. These figures are **inconclusive**: the water mask likely includes wet banks and mining ponds next to rivers. A stricter mask, or sampling fixed points along each river, is needed before drawing conclusions.

## 6. Limitations
- **Provisional labels.** The model learns from a spectral rule, and the IoU/F1 scores in 5.1 measure agreement with that rule. The point-based check in 5.2 is the more independent accuracy measure.
- **AI-interpreted reference points.** The 180 validation points were interpreted by an AI assistant from 10 m imagery, not by a human expert or in the field. Thin scars and edges are hard to judge at 10 m, so 23 points were left out as unsure. Human review of the points (`outputs/predictions/area_sample.csv`), ideally with high-resolution imagery or local knowledge, would strengthen the results.
- **Legal vs illegal.** The model detects mining disturbance, not legality. The Maus footprint is only a rough proxy for licensed mines; Minerals Commission concession boundaries are needed to separate galamsey from licensed operations.
- **Look-alikes.** Fresh farm clearings, construction, sandbars and burn scars can look like mining at 10 m.
- **Two dates.** Two dry-season composites show net change over six years, not when each site started; monthly runs would be needed for early warning.
- **Small compute.** Trained on a laptop CPU with about 1,000 tiles and a small encoder; more data and a GPU would likely improve results.

## 7. From detection to action
Detection alone does not stop galamsey; the output is useful as evidence that can be dated and checked. The ranked alert list is aimed at agencies that can act on it (NAIMOS, the Minerals Commission, the Forestry Commission, the Water Resources Commission and the EPA), and at journalists and NGOs tracking enforcement. Because many miners are poor and enforcement has sometimes been violent, exact coordinates of active sites should be shared with vetted partners rather than published openly.

## 8. Reproducing
See `README.md`. `python run_pipeline.py` runs every step; `python run_pipeline.py --relabel` re-runs with hand labels.

## References
- Maus, V. et al. (2022). An update on global mining land use. *Scientific Data* 9, 433. Data: PANGAEA 942325.
- Olofsson, P. et al. (2014). Good practices for estimating area and assessing accuracy of land change. *Remote Sensing of Environment* 148, 42–57.
- Pasquarella, V. et al. (2023). Comprehensive quality assessment of optical satellite imagery using weakly supervised video learning (Cloud Score+). *CVPR Workshops*.
- Ronneberger, O. et al. (2015). U-Net: Convolutional networks for biomedical image segmentation. *MICCAI*.
- Yamazaki, D. et al. (2019). MERIT Hydro: a high-resolution global hydrography map. *Water Resources Research* 55.

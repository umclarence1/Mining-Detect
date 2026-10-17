# Results on the held-out Tarkwa test block

Test tiles: 128 (2020 and 2026). Scored against PROVISIONAL rule-based labels (agreement with the rule, not true accuracy).

| Model | IoU | F1 | Precision | Recall |
|---|---|---|---|---|
| baseline_ndvi | 0.600 | 0.750 | 0.641 | 0.903 |
| unet_rgb | 0.711 | 0.831 | 0.828 | 0.834 |
| unet_all_bands | 0.757 | 0.861 | 0.851 | 0.872 |

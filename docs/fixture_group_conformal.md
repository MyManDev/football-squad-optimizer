# Fixture-group conformal calibration on the control's residuals

Position-only (the operational `projection_uncertainty_v1` grouping) against
position by fixture group (`single`, `double_plus`; pooled fallback per position
under the observation floor), both fitted on the earlier folds and scored on the
later folds of the operational control's out-of-sample residual export. Blank rows
are zero by construction and excluded. Nominal coverage 0.90. Measurement only; no contract changes here.

- Calibration folds: 88 (2021-22-gw02 … 2023-24-gw16); evaluation folds: 59 (2023-24-gw17 … 2024-25-gw38).
- Rows: 57877 calibrate, 43570 evaluate, 0 blank excluded.
- Result fingerprint `25fb6307c3f6e5d6…`; configuration `3ecf0d22f9deab83…`.

## Held-out coverage and width

| Population | Rows | Position-only coverage | Position-only width | Fixture-group coverage | Fixture-group width | MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | 43570 | 0.9179 | 7.25 | 0.9145 | 6.99 | 1.04 |
| single | 42305 | 0.9200 | 7.25 | 0.9149 | 6.90 | 1.02 |
| double_plus | 1265 | 0.8490 | 7.24 | 0.9012 | 10.12 | 1.67 |
| GK/single | 4577 | 0.9248 | 6.00 | 0.9248 | 6.00 | 0.72 |
| DEF/single | 13978 | 0.9336 | 8.00 | 0.9250 | 7.60 | 1.05 |
| MID/single | 18739 | 0.9118 | 6.80 | 0.9087 | 6.40 | 1.04 |
| FWD/single | 5011 | 0.9084 | 8.00 | 0.9004 | 7.60 | 1.15 |
| GK/double_plus | 147 | 0.8844 | 6.00 | 0.9048 | 8.00 | 1.12 |
| DEF/double_plus | 412 | 0.8544 | 8.00 | 0.9272 | 11.60 | 1.69 |
| MID/double_plus | 558 | 0.8387 | 6.80 | 0.8853 | 9.20 | 1.74 |
| FWD/double_plus | 148 | 0.8378 | 8.00 | 0.8851 | 11.60 | 1.88 |

## Calibrated radii

| Position | Position-only radius (n) | Single radius (n, source) | Double-plus radius (n, source) |
| --- | ---: | ---: | ---: |
| GK | 3.00 (6421) | 3.00 (5985, position_fixture_group) | 4.00 (436, position_fixture_group) |
| DEF | 4.00 (19649) | 3.80 (18358, position_fixture_group) | 5.80 (1291, position_fixture_group) |
| MID | 3.40 (24529) | 3.20 (22914, position_fixture_group) | 4.60 (1615, position_fixture_group) |
| FWD | 4.00 (7278) | 3.80 (6773, position_fixture_group) | 5.80 (505, position_fixture_group) |

## Provenance

- Residual export: `calendar_blind_baseline` (deterministic_baseline@form_window_05_v1, contract `oos_residual_export_v1`), table SHA-256 `1ed41f94f245b06d…` verified against the file.
- The 2025-26 holdout was not read.

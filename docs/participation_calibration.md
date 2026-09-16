# Participation calibration

Pre-registration: `docs/participation_model_prereg.md`. Descriptive only: nothing is promoted, no threshold moves, the operational control is unchanged, and the locked 2025-26 holdout was not read.

Fitted on 2023-24 over 10746 appeared and labelled rows, then scored on 2024-25 (26919 rows, 11431 of them appearances).

## `q_start_given_appearance`, on appeared rows

11089 rows, mean probability 0.7298 against an observed rate of 0.7249 (bias +0.0049), Brier 0.1311, log loss 0.4087.

| Bin | Observations | Mean probability | Observed rate |
| --- | --- | --- | --- |
| 0.0 to 0.1 | 6 | 0.0890 | 0.0000 |
| 0.1 to 0.2 | 261 | 0.1683 | 0.1494 |
| 0.2 to 0.3 | 780 | 0.2545 | 0.2603 |
| 0.3 to 0.4 | 1234 | 0.3512 | 0.3298 |
| 0.4 to 0.5 | 529 | 0.4466 | 0.4688 |
| 0.5 to 0.6 | 540 | 0.5517 | 0.5944 |
| 0.6 to 0.7 | 690 | 0.6505 | 0.7130 |
| 0.7 to 0.8 | 703 | 0.7544 | 0.7070 |
| 0.8 to 0.9 | 1526 | 0.8572 | 0.8178 |
| 0.9 to 1.0 | 4820 | 0.9533 | 0.9508 |

## `p_start = p_appearance * q`

26135 rows, mean probability 0.3057 against an observed rate of 0.3076 (bias -0.0018), Brier 0.0929, log loss 0.3009.

| Bin | Observations | Mean probability | Observed rate |
| --- | --- | --- | --- |
| 0.0 to 0.1 | 13904 | 0.0295 | 0.0268 |
| 0.1 to 0.2 | 1651 | 0.1459 | 0.2217 |
| 0.2 to 0.3 | 1004 | 0.2460 | 0.3048 |
| 0.3 to 0.4 | 729 | 0.3501 | 0.3663 |
| 0.4 to 0.5 | 717 | 0.4502 | 0.4589 |
| 0.5 to 0.6 | 878 | 0.5533 | 0.5581 |
| 0.6 to 0.7 | 865 | 0.6466 | 0.6139 |
| 0.7 to 0.8 | 1070 | 0.7543 | 0.6617 |
| 0.8 to 0.9 | 4088 | 0.8624 | 0.8645 |
| 0.9 to 1.0 | 1229 | 0.9243 | 0.9235 |

`p_appearance` is not re-measured here. `docs/phase_c_component_evaluation.json` reports it on its own population, and re-reading it under this one would invite a comparison that is not like-for-like.

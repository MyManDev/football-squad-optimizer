# Strategy bench: the pre-registered gates, applied

- Contract: `strategy_bench_v1`; gates fixed in `strategy_bench_prereg.md` (#279) before the catalogue existed
- Population: {'seasons': ['2021-22', '2022-23', '2023-24', '2024-25'], 'is_declared_population': True, 'horizons': [1, 3, 5], 'folds_built': 147, 'clipped_windows': 24}
- Bands: {'high_overlap': {'strategy': 'ortak-koru', 'overlap_floor': 9}, 'differential': {'strategy': 'fark-yarat', 'overlap_ceiling': 5}, 'control': {'strategy': 'saf-puan'}}
- The locked holdout was not accessed by this run.

## h=1 (gated) — 147 folds

- Feasibility: {'high_overlap': 1.0, 'differential': 1.0, 'control': 1.0}
- Gate 1 (separation): {'paired_folds': 147, 'mean_difference': -0.027210884353741496, 'interval_90': [-0.07482993197278912, 0.027210884353741496], 'passes': False}
- Gate 2 (direction): frequencies {'high_overlap': 0.24489795918367346, 'differential': 0.24489795918367346, 'control': 0.24489795918367346}, passes: True
- Gate 3 (price honesty): {'high_overlap': {'paired_folds': 147, 'mean_realized_minus_claimed': -5.286961451247167, 'interval_90': [-6.220385487528347, -3.864756235827664], 'passes': True}, 'differential': {'paired_folds': 147, 'mean_realized_minus_claimed': 0.03265306122448997, 'interval_90': [-0.016326530612244646, 0.10748299319727898], 'passes': True}}
- Band binding (diagnostic): {'high_overlap': {'share_cost_zero': 0.02040816326530612, 'mean_overlap_count': 9.0}, 'differential': {'share_cost_zero': 0.9523809523809523, 'mean_overlap_count': 3.564625850340136}}

## h=3 (gated) — 140 folds

- Feasibility: {'high_overlap': 0.9285714285714286, 'differential': 1.0, 'control': 1.0}
- Gate 1 (separation): {'paired_folds': 130, 'mean_difference': 0.046153846153846156, 'interval_90': [0.0, 0.1], 'passes': False}
- Gate 2 (direction): frequencies {'high_overlap': 0.2076923076923077, 'differential': 0.24285714285714285, 'control': 0.24285714285714285}, passes: True
- Gate 3 (price honesty): {'high_overlap': {'paired_folds': 130, 'mean_realized_minus_claimed': -4.800512820512823, 'interval_90': [-6.36955128205128, -2.464185897435899], 'passes': True}, 'differential': {'paired_folds': 140, 'mean_realized_minus_claimed': 0.05428571428571445, 'interval_90': [-0.002857142857142695, 0.13285714285714262], 'passes': True}}
- Band binding (diagnostic): {'high_overlap': {'share_cost_zero': 0.023076923076923078, 'mean_overlap_count': 9.0}, 'differential': {'share_cost_zero': 0.95, 'mean_overlap_count': 3.5285714285714285}}

## h=5 (reported) — 114 folds

- Feasibility: {'high_overlap': 0.7543859649122807, 'differential': 1.0, 'control': 1.0}
- Gate 1 (separation): {'paired_folds': 86, 'mean_difference': 0.011627906976744186, 'interval_90': [-0.03488372093023256, 0.06976744186046512], 'passes': False}
- Gate 2 (direction): frequencies {'high_overlap': 0.19767441860465115, 'differential': 0.22807017543859648, 'control': 0.23684210526315788}, passes: False
- Gate 3 (price honesty): {'high_overlap': {'paired_folds': 86, 'mean_realized_minus_claimed': -5.063953488372093, 'interval_90': [-6.9448546511627915, -2.111366279069768], 'passes': True}, 'differential': {'paired_folds': 114, 'mean_realized_minus_claimed': 0.08421052631578968, 'interval_90': [0.027982456140350713, 0.1719298245614037], 'passes': False}}
- Band binding (diagnostic): {'high_overlap': {'share_cost_zero': 0.03488372093023256, 'mean_overlap_count': 9.0}, 'differential': {'share_cost_zero': 0.9385964912280702, 'mean_overlap_count': 3.517543859649123}}

## Gate 4 (h=1 not sacrificed): {'mirrored_folds': 147, 'mismatches': [], 'passes': True}

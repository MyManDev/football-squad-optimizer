# Paper package

| Item | Value |
| --- | --- |
| Issue | #1152 |
| Records | [measurements index](../measurements_index.md) |
| Related work | [verbatim quotes](related_work.md) |
| Requirements | Python 3.11 or later (standard library only), git on `PATH`, no network; the tests: the development install of [contributing](../../CONTRIBUTING.md) |
| Outputs in git | none; written under `artifacts/` (git-ignored) or outside the checkout |
| Records read at | `144e3f7be824115b64ec8321d8b60c6831092973` (develop) |

## Commands from a clean clone

| Step | Command |
| --- | --- |
| 1 | `git clone https://github.com/MyManDev/football-squad-optimizer.git` |
| 2 | `cd football-squad-optimizer` |
| 3 | `python -m scripts.paper_record_tables --output-dir artifacts/paper/tables` |
| 4 | `python -m scripts.paper_figures --tables artifacts/paper/tables --output-dir artifacts/paper/figures` |
| Check | `python -m scripts.paper_figures --check docs/paper/README.md` |
| Tests | `python -m pytest tests/unit/test_paper_record_tables.py tests/unit/test_paper_figures.py tests/unit/test_paper_related_work.py` |

| Command | Prints | Exit |
| --- | --- | --- |
| Step 3 | `83 of 83 record checks hold` | 0 |
| Step 4 | `Wrote 5 paper figures to ...` | 0 |
| Check | `83 of 83 record checks hold`; `34 of 36 manifest rows match`, two `unpinned` | 0 |

## Inputs

| Key | File | Git blob | SHA-256 |
| --- | --- | --- | --- |
| R1 | `docs/phase_c_component_evaluation.json` | `decb2bafb0246e582993380e6433b3be7d3d9403` | `8e5250c0f1259bd824eea37621ca8a7abd6a5a6001fdfc5b698c7d0560f3e079` |
| R2 | `docs/phase_d_component_squad_calibration.json` | `137303f84901b0d13b363b4fd0954989ffb40d1c` | `9457128eebeb109f5fcb917d0fdc05ceac7360d171538d317e64c230d03cd907` |
| R3 | `docs/research/mean_reversion_discount.json` | `19b3ca33e3550b6f3c4c3dcad51b55205461e0f9` | `a03e459e54af17984c17fe8e17f2f8fc28c542d4fc9d2e73ff21ae2ea2f59653` |
| R4 | `docs/research/moe_mixture.json` | `52f4cad022d80efb7c7af6ab4f1c625fb648400c` | `03b322946bf2283f99b20d646c44aaeb59ea7e5a83d5fefcd676df629faf51fe` |
| R5 | `docs/research/moe_regime.json` | `8968e4097f29e47d124ef56b3bd804755fd9df8b` | `2329fedb1207117bc39b520a9ece0cb6ba27ca80708b122162254a8b9a29d372` |
| R6 | `docs/research/moe_sampler.json` | `65e5b97114a1b580d6608563447601b09d1e2347` | `d1c4cfb55ac27b5c6582faa85fc78555a268b0863f19d50909f1798bb36cf510` |
| R7 | `docs/research/phase_c_feature_contract_v2_comparison.json` | `631d119451fe265661bf7f16e469c7eabfba0cd1` | `7679f11d3c374714c751b133e2bbc77b2ee02b7b46b56ab512baacbf21086728` |
| R8 | `docs/research/phase_c_gradient_boosting_comparison.json` | `8343a539fbbfd78f3a42c0e03f2b26ef4a995900` | `304f4d929ddd226301157a7bb9b670cffd19bb80345ee30063176fa747a157ed` |
| R9 | `docs/research/phase_c_gradient_boosting_points_comparison.json` | `2a6e52847f75d4213347d820203680abdca84c76` | `293707748aa55eb61785137232ee82f943da7fe0f35858ca7894d70ac0e9a983` |
| R10 | `docs/research/rank_conditional_shrinkage.json` | `bddfcb03976c73cf53bf2c7706f5386bbc9c315a` | `31d487322ef15a713751f1577c83242c09f5bd5186ff2ab2909e2a052a6272d7` |
| R11 | `docs/research/team_match_block_sampler.json` | `f70dc6a4061297870541a9a484364799b603e26e` | `797264048f2a14658a8ecac89d5c82fae466e504392da4231159d10848cf1173` |
| C1 | `scripts/paper_record_tables.py` | `4b550890a40ca801ba4b15d1cbf1e99480173f71` | `f5e3c5608c8e991d147ac992cf6c173ccb48e1f101e2c5548eedbd09c5cc19b9` |
| C2 | `scripts/paper_figures.py` | `86070cde648d9658b748b484ca14ff461df3c2b3` | `2a0f98dcafcfa101d01f970d3b0318100e24a61aa55e0c3147898f5f999fbc11` |

## Tables (step 3)

| Output | Step | Inputs | SHA-256 |
| --- | --- | --- | --- |
| `tables/checks.csv` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, C1 | `8dddc7341b2903b2aa4ab9b06afa33fb4e9b07d588dfffaeec41b184632c4543` |
| `tables/figure_decision_by_season.csv` | 3 | R4, R5, R7, R8, R9, C1 | `3f8537d3067ce4c2bb68e724d3b30232089afbf653f92e013b7ba576214ad3c0` |
| `tables/figure_decision_fold_differences.csv` | 3 | R4, R5, R7, R8, R9, C1 | `1d20d93c1799fd1e09f9493265cd9e33f792c16271cde420e017a0c5034966f5` |
| `tables/figure_points_mae_against_squad_points.csv` | 3 | R4, R5, R7, R8, R9, C1 | `56fe2658592779e8f55ae45e6ea2e6bc6d5e5dcfe8564c6ed0c1c3b736f4afdf` |
| `tables/figure_s2_counts.csv` | 3 | R2, R6, R11, C1 | `1e9e8dbcaa84d44b261a439540eb31e580a19273b75dad53aa2f512a5af86b2b` |
| `tables/figure_sampler_pit.csv` | 3 | R2, R6, R11, C1 | `81e9b36ddaad14cb5baaa014914cc8208c586f5baa0669c20769e6a6e1c7d527` |
| `tables/provenance.csv` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, C1 | `8a171e58f9250c1a8a677ceb6eafdcd33bcce2ec0a70db32198a326148b368b0` |
| `tables/records.csv` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, C1 | names the checked-out commit |
| `tables/table_candidates_decision_level.csv` | 3 | R1, R4, R5, R7, R8, R9, C1 | `e837229887dbd30b01d0fc91d954a15c3c90a5624f3ff28507b1c217da6aea16` |
| `tables/table_candidates_player_level.csv` | 3 | R4, R5, R7, R8, R9, C1 | `c358c43a8980519c387d46ab10a2a9ead17fae5f284febe66847dfc783f8e6ea` |
| `tables/table_candidates_reading_status.csv` | 3 | R4, R5, R7, R8, R9, C1 | `1002e408054d119fbeef59511c56c34411e1a02a0f3c81a40768fd20182447fc` |
| `tables/table_joint_sampler_seed_summary.csv` | 3 | R6, C1 | `924fffb6412b1764003d01f005efa82755f0d8f6cfd0232401b45799a23dae7e` |
| `tables/table_joint_sampler_seeds.csv` | 3 | R6, C1 | `51aeea06ea82d8cc18e43facbb4b71639cfb9d589d696ebca91f5858fd8c2f9c` |
| `tables/table_mixture_distribution.csv` | 3 | R4, C1 | `e2f499b51bed13fee85251fdc1039dc15269471760c6dbc3e32750d5523559e3` |
| `tables/table_mixture_log_score_folds.csv` | 3 | R4, C1 | `53422aa3030223390bef3fa1a3e96d6a3097fc968d13f88fc32e461b0ba6cc85` |
| `tables/table_planning_measurements.csv` | 3 | R3, R10, C1 | `58abc76707286bc6c8cedaf6ed391752d4f5782c473bab44e60f04b9f3ae6705` |
| `tables/table_sampler_calibration.csv` | 3 | R2, R6, R11, C1 | `990c10383e91f8721cba87809cb835aad11337f9c9c17e8eb81d3c057b3fc0bc` |
| `tables/tables.md` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, C1 | names the checked-out commit |

## Figures (step 4)

| Output | Step | Inputs | SHA-256 |
| --- | --- | --- | --- |
| `figures/fig1_decision_fold_differences.svg` | 4 | `tables/figure_decision_fold_differences.csv`, C2 | `99e8bc75c1d5d88af3223c4b2a1695a6d2ec599dbd9e75e7db9d70d0203171a7` |
| `figures/fig2_decision_by_season.svg` | 4 | `tables/figure_decision_by_season.csv`, C2 | `fd06c34b2584ddd60ec4fa38329eb62de0de7b776cb9113abc2d7fbcdd726b0c` |
| `figures/fig3_points_mae_against_squad_points.svg` | 4 | `tables/figure_points_mae_against_squad_points.csv`, `tables/figure_decision_by_season.csv`, C2 | `74dedb0327be994a9df988ccbeff91abbee342d1995129262928a20337f3e2b4` |
| `figures/fig4_sampler_pit.svg` | 4 | `tables/figure_sampler_pit.csv`, C2 | `ec8182a7261ef2f5d3f5a642b44f0fd1d8b703451e1ae4259731022704e3a1f2` |
| `figures/fig5_s2_counts.svg` | 4 | `tables/figure_s2_counts.csv`, `tables/table_sampler_calibration.csv`, C2 | `a4e4fd7a6cd3b87d43c462412f759bf448441840419a205ef9c2d99a63c26b6c` |

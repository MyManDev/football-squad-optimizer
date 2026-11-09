# Paper package

| Item | Value |
| --- | --- |
| Issue | #1152 |
| Records | [measurements index](../measurements_index.md) |
| Related work | [verbatim quotes](related_work.md) |
| Requirements | Python 3.11 or later (standard library only), git on `PATH`, no network; the tests: the development install of [contributing](../../CONTRIBUTING.md) |
| Outputs in git | none; written under `artifacts/` (git-ignored) or outside the checkout |
| Records read at | `144e3f7be824115b64ec8321d8b60c6831092973` (develop) |
| Manuscript | [squadopt_walk_forward_paper.tex](squadopt_walk_forward_paper.tex), built by steps 5 and 6 below; the manuscript and this package move together on the branch `docs/paper-manuscript`, and a submission is pinned by a tag `paper/<venue>-<date>` on that branch |
| Tool versions used for the manuscript | Python 3.13.5 for steps 3 and 4 (standard library only); PyMuPDF 1.27.2.3 for step 5; Tectonic 0.17.0 (XeTeX, fontspec) for step 6 |

## Commands from a clean clone

| Step | Command |
| --- | --- |
| 1 | `git clone https://github.com/MyManDev/football-squad-optimizer.git` |
| 2 | `cd football-squad-optimizer` |
| 2b | `git checkout docs/paper-manuscript` (or the submission tag); the records read at the commit named below are on that branch |
| 3 | `python -m scripts.paper_record_tables --output-dir artifacts/paper/tables` |
| 4 | `python -m scripts.paper_figures --tables artifacts/paper/tables --output-dir artifacts/paper/figures` |
| Check | `python -m scripts.paper_figures --check docs/paper/README.md` |
| 5 | `python -c "import fitz, pathlib; [pathlib.Path('artifacts/paper/figures-pdf', p.stem + '.pdf').write_bytes(fitz.open(p).convert_to_pdf()) for p in pathlib.Path('artifacts/paper/figures').glob('*.svg')]"` after `mkdir -p artifacts/paper/figures-pdf` (PyMuPDF; `pip install pymupdf`) |
| 6 | `cd docs/paper && tectonic --outdir ../../artifacts/paper squadopt_walk_forward_paper.tex` (the PDF lands in `artifacts/paper/`) |
| Tests | `python -m pytest tests/unit/test_paper_record_tables.py tests/unit/test_paper_figures.py tests/unit/test_paper_related_work.py` |

| Command | Prints | Exit |
| --- | --- | --- |
| Step 3 | `110 of 110 record checks hold` | 0 |
| Step 4 | `Wrote 5 paper figures to ...` | 0 |
| Step 6 | a 29-page `squadopt_walk_forward_paper.pdf` | 0 |
| Check | `110 of 110 record checks hold`; `41 of 43 manifest rows match`, two `unpinned` | 0 |

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
| R12 | `docs/measurement_instrument.json` | `e9b946d962fe16a082dae0a2d509cca12bd7fe4f` | `da987a13c0d74b164175f5baf1018929f0634c3d7373ef367f336af00ebdc845` |
| R13 | `docs/research/phase_c_solver_budget_cards.json` | `8e1a8a7b9b227a85303a704d505126f47b14787a` | `a652493821077f0f9271be4a041db18bbab9db187437974cec3be751cd6bedfb` |
| C1 | `scripts/paper_record_tables.py` | `c7234d405910b80b8819218df85511e41a706795` | `faaf04face315bd1d61b85c58aa87616fdab0a839877b0cac2089aa00178ac19` |
| C2 | `scripts/paper_figures.py` | `247540ac734db572db1680480d6967653068b57d` | `f142e0cd4bcf1935c709e2ae6b0755e0e271da19b32f8b1c9df87ca6444f5830` |

## Tables (step 3)

| Output | Step | Inputs | SHA-256 |
| --- | --- | --- | --- |
| `tables/checks.csv` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, C1 | `12b0bdeadabbc9a38c640b686275c9403ecc5c27ee1fdde2bd6cf66fff728043` |
| `tables/figure_accuracy_against_decision.csv` | 3 | R4, R5, R7, R8, R9, C1 | `a36b6cf86f2b4869415f00f4b64b5d68735c91e9466a007ea57c4026842471c9` |
| `tables/figure_decision_by_season.csv` | 3 | R4, R5, R7, R8, R9, C1 | `3f8537d3067ce4c2bb68e724d3b30232089afbf653f92e013b7ba576214ad3c0` |
| `tables/figure_decision_fold_differences.csv` | 3 | R4, R5, R7, R8, R9, C1 | `1d20d93c1799fd1e09f9493265cd9e33f792c16271cde420e017a0c5034966f5` |
| `tables/figure_sampler_pit.csv` | 3 | R2, R6, R11, C1 | `81e9b36ddaad14cb5baaa014914cc8208c586f5baa0669c20769e6a6e1c7d527` |
| `tables/provenance.csv` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, C1 | `c3762dd6f2070b7f0d53bbd7faaf38d622f75c1befddbaba27ac06688694ad95` |
| `tables/records.csv` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, C1 | names the checked-out commit |
| `tables/table_candidates_block_sensitivity.csv` | 3 | R4, R5, R7, R8, R9, C1 | `c33f512412424f72f75c804cc55cfa790bac29c526913fff710a2b80fac3c9ec` |
| `tables/table_candidates_decision_level.csv` | 3 | R1, R4, R5, R7, R8, R9, C1 | `e837229887dbd30b01d0fc91d954a15c3c90a5624f3ff28507b1c217da6aea16` |
| `tables/table_candidates_player_level.csv` | 3 | R4, R5, R7, R8, R9, C1 | `c358c43a8980519c387d46ab10a2a9ead17fae5f284febe66847dfc783f8e6ea` |
| `tables/table_candidates_precision.csv` | 3 | R4, R5, R7, R8, R9, R12, C1 | `e54d2058f440b4414b27ff7f56ea5b2cc6f3b352a0882158a1677b4ab834203a` |
| `tables/table_candidates_reading_status.csv` | 3 | R4, R5, R7, R8, R9, C1 | `1002e408054d119fbeef59511c56c34411e1a02a0f3c81a40768fd20182447fc` |
| `tables/table_candidates_same_period.csv` | 3 | R4, R5, R7, R8, R9, C1 | `599520c1d3400309cc14816e8a1106b7e09ce8b36ff73b664f472e1b5a23e3da` |
| `tables/table_joint_sampler_seed_summary.csv` | 3 | R6, C1 | `924fffb6412b1764003d01f005efa82755f0d8f6cfd0232401b45799a23dae7e` |
| `tables/table_joint_sampler_seeds.csv` | 3 | R6, C1 | `51aeea06ea82d8cc18e43facbb4b71639cfb9d589d696ebca91f5858fd8c2f9c` |
| `tables/table_mixture_distribution.csv` | 3 | R4, C1 | `e2f499b51bed13fee85251fdc1039dc15269471760c6dbc3e32750d5523559e3` |
| `tables/table_mixture_log_score_folds.csv` | 3 | R4, C1 | `53422aa3030223390bef3fa1a3e96d6a3097fc968d13f88fc32e461b0ba6cc85` |
| `tables/table_planning_measurements.csv` | 3 | R3, R10, C1 | `58abc76707286bc6c8cedaf6ed391752d4f5782c473bab44e60f04b9f3ae6705` |
| `tables/table_sampler_calibration.csv` | 3 | R2, R6, R11, C1 | `990c10383e91f8721cba87809cb835aad11337f9c9c17e8eb81d3c057b3fc0bc` |
| `tables/table_sampler_calibration_by_season.csv` | 3 | R6, R11, C1 | `74b30879267c17c2cefdf71f7f1a67273cfc08faf49a471815274c7b8b2059e2` |
| `tables/table_solver_budget_cards.csv` | 3 | R13, C1 | `9293c5a43c9a8f48452a45d2bdb23d2cd248e9a0b2d68f6fff6ff071c2dbef92` |
| `tables/table_solver_status.csv` | 3 | R1, R9, C1 | `e8e938acf040eb5fc1a86b51f06cc0983ec6410deb998f6339c112048f6fc62d` |
| `tables/tables.md` | 3 | R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, C1 | names the checked-out commit |

## Figures (step 4)

| Output | Step | Inputs | SHA-256 |
| --- | --- | --- | --- |
| `figures/fig1_decision_fold_differences.svg` | 4 | `tables/figure_decision_fold_differences.csv`, C2 | `99e8bc75c1d5d88af3223c4b2a1695a6d2ec599dbd9e75e7db9d70d0203171a7` |
| `figures/fig2_decision_by_season.svg` | 4 | `tables/figure_decision_by_season.csv`, C2 | `fd06c34b2584ddd60ec4fa38329eb62de0de7b776cb9113abc2d7fbcdd726b0c` |
| `figures/fig3_accuracy_against_decision.svg` | 4 | `tables/figure_accuracy_against_decision.csv`, `tables/figure_decision_by_season.csv`, C2 | `db1c1cce5c165de159893ac02014d9ca0c1bf9ff25996f1f847b770507b37db9` |
| `figures/fig4_sampler_pit.svg` | 4 | `tables/figure_sampler_pit.csv`, C2 | `ec8182a7261ef2f5d3f5a642b44f0fd1d8b703451e1ae4259731022704e3a1f2` |
| `figures/fig5_seed_counts.svg` | 4 | `tables/table_joint_sampler_seeds.csv`, C2 | `50fedb99884abc582ee636de5e9cb915cfdc892e52ec0aefc73ae4e09298f6a8` |
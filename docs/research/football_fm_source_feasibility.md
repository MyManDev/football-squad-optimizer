# Football Manager source feasibility

Research date: 2026-10-09. This records public source evidence and a schema audit. No FPL history or protected outcomes were opened and no real model was fitted. The initial archives remain in the owned worktree's `.codex-tmp/research/`; the expanded private catalog is in the project's ignored `.codex-tmp/datasets/` directory. Neither location is the repository's `data/` tree, a Git-tracked dataset or a public forecast artifact.

The owner's 2026-10-09 decision retains the local datasets and FM adapter for private training preparation and keeps every dataset outside Git. Exact permitted source/model rights, authentic historical vintage, scoped temporal FPL mapping and the accepted evaluation protocol still determine which rows may actually train a forecast. This decision is recorded on #1057; no unknown license is inferred to be a training grant.

Three publicly declared licensed datasets were downloaded through version-pinned public endpoints and streamed as CSV without extracting archives or executing provider code. No audited source establishes complete, correctly dated Premier League attribute coverage for every development season or the current 2026-27 season. There are useful candidates, but source rights, historical vintage and identity evidence still need acceptance before model ingestion.

## Audited sources

The licenses below are the uploaders' declarations. They do not independently establish Sports Interactive's permission to redistribute its underlying database or use it in this project's models. Counts are our streamed observations of the downloaded bytes, not the cards' advertised totals.

| Source and declared license | Observed publication/version | Actual schema and identity | Exact Premier League slice | Practical use |
| --- | --- | --- | --- | --- |
| [Caesario Oktanto: FM20](https://www.kaggle.com/datasets/ktyptorio/football-manager-2020), CC0 | v1, 2021-07-16T04:26:18.05Z | 144,750 rows, 64 columns; playing attributes, CA/PA, age, club; no FM UID or DOB | `Division == "English Premier Division"`: 1,099 rows, 32 club labels | Quality-vector and parser research; needs a reviewed identity source and exact editor/database vintage |
| [Siddhraj Thakor: FM23](https://www.kaggle.com/datasets/siddhrajthakor/football-manager-2023-dataset), CC BY-SA 4.0 | v1 first release 2025-10-01T17:55:40.05Z; audited v2 2025-10-01T18:34:21.197Z | 91,672 rows, 88 columns; 87,163 unique positive UIDs; DOB and quality traits | `Based == "England (Premier Division)"`: 1,345 rows, 1,290 unique UIDs, 19 club labels | Best audited identity/trait schema; publication too late to establish predeadline availability in 2020-21 through 2024-25 |
| [Yash: FM24 salary data](https://www.kaggle.com/datasets/ultimus/football-salaries-dataset), Apache 2.0 | Audited v4, 2024-04-15T17:56:44Z; earlier publication not established | Raw: 40,791 rows, 16 columns; cleaned: 40,791 rows, 11 columns; no UID, DOB or technical/mental/physical traits | Raw exact England Premier League label: 1,201 rows; every `Club` is `-` | Salary research only; cannot supply the requested player-quality attributes |

The FM20 card identifies real players and references a [pr0/FMTU community database update](https://www.fmscout.com/a-fm20-transfer-data-update-by-pr0-fmtu.html). That update page describes optional changes to attributes, CA/PA, transfers and players, and a 20.4.0 base. The card does not identify the selected editor files, exact update or save date. The page's November 2020 update date is not evidence that these CSV bytes existed before a November 2020 deadline.

FM20's 32 club labels comprise 20 groups with at least 10 rows and 12 singleton labels. The latter include clubs outside England. A division label therefore cannot substitute for a captured real-club roster. The empty first CSV column is an index; it is not established as a persistent FM person identifier.

FM23 has 4,509 duplicate UID excess rows. After excluding the empty CSV index, no duplicate UID has conflicting semantic columns. Deduplication must still be explicit and recorded. All DOB strings parse as `day/month/year (N years old)`; 58 embedded ages disagree with the separate `Age` column. Birth year plus recorded age yields 2021 or 2022, which is a consistency warning rather than a proven capture date. No game patch, database patch, save date or actual snapshot timestamp is supplied. Edition names are not vintage evidence.

FM23's 19 clubs are Arsenal, Aston Villa, Bournemouth, Brentford, Brighton, Chelsea, Crystal Palace, Everton, Fulham, Leeds, Leicester, Liverpool, Man City, Newcastle, Nottm Forest, Southampton, Tottenham, West Ham and Wolves. Manchester United-related English club naming variants were absent across the archive. The 157 goalkeeper rows are raw rows, including duplicates. A follow-up checked all 47 visible playing-attribute columns across every one of the 91,672 rows: every value is an exact integer from 1 to 20, and no duplicate UID has conflicting visible attributes. This verifies those fields' range, not full real-player coverage.

The FM24 raw schema is `Name, Club, Division, Based, Nat, EU National, Caps, AT Apps, Position, Age, CR, Begins, Expires, Last Club, Last Trans. Fee, Salary`. Its cleaned schema removes name and club. Contract start/end fields are not snapshot timestamps. Public metadata requests for versions 1, 2 and 3 returned only the v4 record, so v4's date is the earliest observed version date, not a verified first publication.

## Exact club counts

These counts use the source's exact division label. They do not reconcile loan clubs, parent clubs, registration lists or current-season FPL coverage.

| Club label | FM20 rows | FM23 rows |
| --- | ---: | ---: |
| Arsenal | 52 | 74 |
| Aston Villa | 51 | 74 |
| Bournemouth | 0 | 62 |
| Brentford | 0 | 48 |
| Brighton | 55 | 71 |
| Burnley | 47 | 0 |
| Chelsea | 54 | 75 |
| Crystal Palace | 59 | 71 |
| Everton | 44 | 77 |
| Fulham | 56 | 63 |
| Leeds | 55 | 67 |
| Leicester | 56 | 79 |
| Liverpool | 65 | 82 |
| Man City | 53 | 68 |
| Man Utd | 54 | 0 |
| Newcastle | 58 | 75 |
| Nottm Forest | 0 | 75 |
| Sheff Utd | 53 | 0 |
| Southampton | 54 | 73 |
| Tottenham | 60 | 77 |
| West Brom | 55 | 0 |
| West Ham | 54 | 65 |
| Wolves | 52 | 69 |

FM20 has one row each for Atlas (ARG), Bolton, Coventry, Cruzeiro, Dundee Utd, Forest Green, Norwich, Oklahoma City, Osasuna, Sabah (AZE), San Francisco Glens and Watford. These account for the remaining 12 rows and labels. Zero in the table means absent from the exact audited slice, not a claim that the whole archive has no player associated with that club.

## Further concrete candidates

| Candidate | Provider evidence | Remaining work |
| --- | --- | --- |
| [Furkan Ulutas multi-edition bundle](https://www.kaggle.com/datasets/furkanuluta/football-manager-22-complete-player-dataset) | v4 updated 2023-07-10T18:55:20.693Z; license is `Unknown`. Original bundle was downloaded and audited under the later owner request; structured FM21/22/23 workbooks yield 174,909/176,748/189,252 records with 47 native traits. | Bytes and schema are audited; obtain actual model-use rights, immutable historical vintage and reviewed temporal identities. Edition filenames and public upload time alone do not establish original predeadline availability. |
| [Furkan Ulutas standalone FM21](https://www.kaggle.com/datasets/furkanuluta/football-manager-2021-dataset) | Advertised 165,000 players; v1 initial release 2022-08-14T18:24:32.38Z; `worldfmdata.csv`, 86,016,343 bytes; license is `Unknown` | No predeadline availability in 2020-21 or 2021-22 is established. Resolve rights, source vintage and exact identity/PL counts; metadata only was inspected. |
| [Gabriel Abilleira FM22](https://www.kaggle.com/datasets/gabrielabilleira/football-manager-2022-player-data) | Declared CC0; v3 updated 2022-07-26T09:49:50.567Z. Later byte audit finds simulated match performance, zero of the 47 quality traits, and no UID/DOB/club/position. | Retained as a descriptive appendix; it cannot supply the requested quality vector or a real historical PL crosswalk. |
| [Jin FM23](https://www.kaggle.com/datasets/platinum22/foot-ball-manager-2023-dataset) | 8,452 advertised players; v1 updated 2022-12-12; license is `Unknown` | Resolve data rights, vintage and filtered coverage. [GitHub mirror](https://github.com/ygtaltndg/FM23-Dataset-Clustering) has UID/trait headers but no verified data license. |
| [FM26-Database repository](https://github.com/choehyeonjun741-debug/FM26-Database) | README calls it an FM26-style game database; [manifest](https://github.com/choehyeonjun741-debug/FM26-Database/blob/main/data/raw/PROCESSING_MANIFEST.json) reports 4,313 players and 1,010 PL rows | No LICENSE, official FM export proof or capture/patch date was found. Raw header includes `_source_uid` and outfield traits but no GK traits. Processed row-generated IDs do not establish persistent FM identity. Manifest counts are publisher claims, not our audited current PL completeness. |

The multi-edition bundle is a practical route to investigate older snapshots, but an unknown license and an edition filename do not satisfy the source contract. Further FM24 repositories did not resolve the full PL attribute gap: [one study](https://github.com/E2J1/STAT-499----Senior-project/blob/main/README.md) filters ages 15 to 23, uses ten-year simulated outcomes and explicitly withholds raw FM database files; [another](https://github.com/dannllabore411/football-manager-scouting) uses a Bulgarian First League game export. Neither supplies a complete historical PL snapshot. These searches do not establish that no other suitable dataset exists.

## Season and cutoff eligibility

The later expanded catalog independently verifies 117 files and ten full tables
with 814,096 source records; people repeated across editions are not unique
people. Its FM26 candidate has 34,644 records and 35 of 47 native traits, with
11 GK traits and Natural Fitness explicitly missing. Four small FM24 samples do
not establish complete PL coverage. The 2025 fan patch privately downloaded from
its creator is an FM24 editor delta, not a complete trait table. No game or editor
was executed. A bounded additional FM26 search found no inspected full-PL
replacement with established better traits, rights and vintage.

The frozen private catalog manifest SHA256 is
`95a8a2d2cac8ec17237118cb86f746791917c0652a35376d1836e47ae019490e`.
An independent 25,433,204-cell native-trait audit has zero mismatches; final
readback passes 68 checks, including source-admission refusals. This proves
normalization and byte preservation, not permission or forecasting benefit.
Exact expanded receipts and remaining gates are linked from #1057. No raw rows,
private receipt files or trait-bearing player examples are committed here.

An admissible earliest gameweek is the first target whose deadline follows the exact source version's established knowledge/capture cutoff, after the applicable source protocol and rights have been accepted. No gameweek number is inferred from an edition name. A retrospective public-release timestamp and a real predeadline capture are separate evidence fields; the experiment must declare which evidence its historical protocol accepts.

| Project period | Evidence available now | Permitted conclusion |
| --- | --- | --- |
| 2020-21 | FM20 public v1 was published in July 2021, after the season; no earlier CSV snapshot is proved | No audited FM attribute source establishes predeadline development inputs for this season |
| 2021-22 | FM20's immutable public version predates this season; FM21 bundle exists but rights/vintage are unverified | FM20 is a possible stale prior after identity, upstream permission and historical-source protocol approval; no complete FM21 snapshot is accepted |
| 2022-23 | Broad FM22 bytes now preserve 47 traits; the separate CC0 performance dataset has none; FM20 remains available | Unknown bundle rights and unproved original publication/knowledge clocks remain admission gates; no full PL quality source is accepted |
| 2023-24 and 2024-25 | Broad older FM21/22/23 bytes are audited; FM24 samples are partial; audited Thakor FM23 first appeared in October 2025 | Older frozen priors are a hypothesis, not proof of matching seasonal attributes; complete dated FM24 traits remain missing |
| Protected 2025-26 | No outcomes or training inputs were opened | Remains excluded from fitting, threshold choice, preprocessing and model selection |
| Current 2026-27 | A 34,644-record FM26 candidate is audited with 35 traits; no verified complete, dated current PL quality snapshot | Source acceptance must precede prospective use; these downloads do not establish season-wide historical availability or current PL completeness |

Using today's FM26 values for earlier seasons would introduce later knowledge. Using an old frozen snapshot after its known publication can be causally plausible, but requires explicit staleness/missingness and a reviewed identity mapping; it must not be silently relabeled as a newer edition. A modern upload of an old game edition does not prove that the same values were known before historical deadlines.

## Trait meaning and forecast connection

The [official FM24 player manual](https://community.sports-interactive.com/sigames-manual/football-manager-2024/players-r4958/) describes native ratings from 1 to 20, with scouting intervals for incompletely known attributes. Heading concerns use of the head; Jumping Reach concerns an outfield player's reach. Goalkeeper Aerial Reach is a separate attribute. Positioning is defensive, while Off the Ball concerns attacking movement. Anticipation concerns reading events. Preserve these meanings, native scales and intervals rather than treating displayed ratings as observed match frequencies.

The following are testable feature hypotheses. None has a demonstrated FPL gain in this project.

| Feature channel | Possible learned connection | Required surrounding input |
| --- | --- | --- |
| Heading plus Jumping Reach | Attacking aerial threat and defensive replacement loss | Captured real-club eligible roster, aerial opportunity/role context, compatible replacement positions |
| Positioning, Anticipation, Marking, Tackling | Change in the defensive unit when a player is absent | Predeadline absence evidence and a causally projected replacement, rather than a game's simulated lineup |
| GK Aerial Reach, Handling, Reflexes | Goalkeeper quality interacting with defensive exposure | Actual eligible goalkeeper identity; separate GK mask and feature schema |
| Finishing, Technique, Composure, Off the Ball | Sparse-history attacking player prior | Learned attacking share/shot-context model, conserving team totals and distinguishing opportunity from conversion |
| Passing, Vision, Crossing, Corners, Free Kick Taking | Creative contribution prior | Confirmed or captured real set-piece/role evidence; attribute skill alone does not establish who takes the kick |

In FM23, `Nat` is nationality and `Nat.1` is the Natural Fitness attribute. In FM20, `Nation` and `Nat` fill those different roles. Mapping must be version-specific. FM role/duty labels, injury-proneness ratings and game status fields do not replace real medical, club-selection or FPL availability evidence. The accepted captured availability multiplier remains applied once.

The audited FM23 visible-field mapping is as follows. The private receipt preserves the exact mapping and per-column range counts. These are source aliases, not weights or predicted outcomes.

| Attribute group | Source column to canonical name |
| --- | --- |
| Technical | `Cor` Corners; `Cro` Crossing; `Dri` Dribbling; `Fin` Finishing; `Fir` First Touch; `Fre` Free Kick Taking; `Hea` Heading; `Lon` Long Shots; `L Th` Long Throws; `Mar` Marking; `Pas` Passing; `Pen` Penalty Taking; `Tck` Tackling; `Tec` Technique |
| Mental | `Agg` Aggression; `Ant` Anticipation; `Bra` Bravery; `Cmp` Composure; `Cnt` Concentration; `Dec` Decisions; `Det` Determination; `Fla` Flair; `Ldr` Leadership; `OtB` Off the Ball; `Pos` Positioning; `Tea` Teamwork; `Vis` Vision; `Wor` Work Rate |
| Physical | `Acc` Acceleration; `Agi` Agility; `Bal` Balance; `Jum` Jumping Reach; `Nat.1` Natural Fitness; `Pac` Pace; `Sta` Stamina; `Str` Strength |
| Goalkeeping | `Aer` Aerial Reach; `Cmd` Command of Area; `Com` Communication; `Ecc` Eccentricity; `Han` Handling; `Kic` Kicking; `1v1` One on Ones; `Pun` Punching (Tendency); `Ref` Reflexes; `TRO` Rushing Out (Tendency); `Thr` Throwing |

## Primary research and useful use cases

[Mahmudlu, Karakus and Arkadas (2025)](https://arxiv.org/html/2511.23072v1) use FM17 ratings as hierarchical Bayesian priors with real 2015-16 shot events, including counterfactual player substitutions. This supports investigating sparse-player priors and player-context interactions. Their ratings reflect that same season's performance, so the study is retrospective evidence rather than a predeadline forecasting validation.

[Chazan-Pantzalis (2019), chapter 5](https://core.ac.uk/download/328007195.pdf) compares FM17 traits with actual season ratings for 59 Premier League central defenders. It provides a concrete defensive-quality research use case, but its small seasonal cross-section does not validate weekly future forecasts or this project's scoring target.

[Yigit, Samak and Kaya (2020)](https://research.itu.edu.tr/en/publications/an-xgboost-lasso-ensemble-modeling-approach-to-football-player-va/) use FM features to assess player market value. That is evidence of a valuation use case, not proof that market value or FM traits improve FPL points prediction. Do not import reported coefficients or assume gains transfer across targets.

## ANN-ready acceptance contract

Before a source affects a forecast, persist provider/card reference, actual data license, original-source permission evidence, game/database patch, save or base-database status, real-player flag, schema version, native attribute units, source UID, source version, publication/knowledge evidence, capture UTC and immutable content hash. Missing values and scouting intervals need explicit masks. Refuse ambiguous identity, simulated future attributes or a source version later than the target cutoff.

Use a reviewed temporal crosswalk from native FM UID to this project's stable FPL person code, with verified DOB/name aliases and real-club membership evidence. A seasonal FPL element number is insufficient as a permanent key. FM20's missing UID/DOB requires additional identity evidence; its CSV index and name-only matching cannot supply that crosswalk. Do not infer a loan player's real current club from the game's division field.

ANN input columns and their units must be fixed per version. Normalize, impute, select features and learn positional/replacement weights using training folds only. Use chronological development folds within 2020-21 through 2024-25, restricted to genuinely eligible source versions. Validation and test folds must not influence preprocessing or threshold choice. A vector must carry snapshot age, unknown-player and missing-trait masks; GK and outfield aerial channels stay distinct. A proposed ANN is not an accepted evaluation protocol: target, primary metric, threshold, fold boundaries and source rights still need the applicable issue's preregistration/owner decision before real fitting.

Sports Interactive offers a concrete licensed-data route through [FMDB Pro](https://www.sports-interactive.com/news/revolutionising-recruitment-fmdb-pro-now-live). Its [published data supply terms](https://cdn.sports-interactive.com/site/2024-11/SI%20-%20FMDB%20Portal%20-%20Data%20Supply%20License%20Terms%20-%2015%20November%202024%20-%20JC%20%28FINAL%29.pdf) describe contracted subsets for professional clubs and internal analysis, with combination, disclosure and processing restrictions. They are not a general open-data license. A project-specific agreement would need to cover historical snapshots, model training/inference, identity joins, retention and derived outputs. No provider was contacted and no access contract was assumed.

## Reproducible research receipts

Each folder contains `source_metadata.json`, a compact `coverage_audit.json` and its pinned archive. ZIP paths were checked for traversal, absolute paths and symlinks. The audit streamed CSV content, checked declared entries and bounded sizes, and did not extract files or execute code.

| Research file, relative to owned worktree | SHA256 |
| --- | --- |
| `.codex-tmp/research/fm20-cc0/football-manager-2020-v1.zip` | `3bb0c4250c7f8f030fc09df70b620e746b9e7be05d38e2f56fd3d77ba092f7df` |
| FM20 archive member `datafm20.csv` | `8e8277f53e4e4e614da71c0186dffe54dbe4b43ebe599d0f2b865068892548bc` |
| `.codex-tmp/research/fm23-ccby-sa/football-manager-2023-v2.zip` | `3eb4ec080e56d290efb0875be8392f737f65a85593e18eeb97a9edc14327f423` |
| FM23 archive member `merged_players (1).csv` | `131a23608cde3126b02984af0baed87f997239df269aa8f2bb21145869d5ad9f` |
| `.codex-tmp/research/fm24-apache/football-salaries-fm24-v4.zip` | `875a4cab1a716bb734719b45e5a144578941ed2ca37a47cfb3c2909ab971fe3c` |
| FM24 archive member `raw_wages.csv` | `fdb273ce435249ca608143fdb10bf536406a44fb0fe35257921820dc991c944d` |
| FM24 archive member `wages_cleaned.csv` | `f86fb634cc602266c473b59c6ec83746148a63bb262282a8b347952a8d83b1c4` |

Metadata was obtained from the cards' public `api/v1/datasets/view` and `api/v1/datasets/list` endpoints; download requests pinned dataset versions 1, 2 and 4 respectively. The private audit JSON records exact headers, row counts and club counts. No downloaded CSV or private research receipt is a public member artifact or a default forecast input.

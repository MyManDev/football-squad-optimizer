# Related work: verbatim quotes

Issue: #1152. Cell format: `[Ln] "fragment"`, the fragment verbatim on line n of the source file named above the table; `not stated in the document`: no fragment. Check: `python -m pytest tests/unit/test_paper_related_work.py`.

## Literature review

Source: `docs/research/literature_forecast_accuracy_2026_10.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `779803bb5159ea14035ffcde323b68e1de46fe5d`, SHA-256 `7f785db4e4d1b4168a651cd3e885188254e8bfdbab9e5c213ed7b3cc12e0e549`.

### Source

| id | authors | year | venue | title | url |
| --- | --- | --- | --- | --- | --- |
| E1 | [L146] "Groos, D." | [L146] "2025" | [L146] "Author preprint" | [L146] "OpenFPL: An open-source forecasting method rivaling state-of-the-art Fantasy Premier League services" | [L146] "https://arxiv.org/html/2508.09992v1" |
| E2 | [L147] "Egidi, L. and Gabry, J." | [L147] "2017"; "Related journal article (2018)" | [L147] "Author-hosted MathSport proceedings"; "DOI [10.1515/jqas-2017-0066]" | [L147] "Bayesian hierarchical models for predicting individual performance in football (soccer)" | [L147] "https://www.research.unipd.it/handle/11577/3253949?mode=complete" |
| E3 | [L148] "Rossi, A. et al." | [L148] "2018" | [L148] "PLOS ONE 13(7), e0201264" | [L148] "Effective injury forecasting in soccer with GPS training data and machine learning" | [L148] "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0201264" |
| E4 | [L149] "Scholtes, A. and Karakus, O." | [L149] "2023 preprint; published 2024" | not stated in the document | [L149] "Bayes-xG: Player and Position Correction on Expected Goals using Bayesian Hierarchical Approach" | [L149] "https://arxiv.org/pdf/2311.13707" |
| E5 | [L150] "Whitaker, G. A. et al." | [L150] "2017 preprint, revised 2020" | not stated in the document | [L150] "A Bayesian inference approach for determining player abilities in football" | [L150] "https://arxiv.org/pdf/1710.00001" |
| E6 | [L151] "Egidi, L., Pauli, F. and Torelli, N." | [L151] "2018" | [L151] "Statistical Modelling 18(5-6), 436-459; author manuscript" | [L151] "Combining historical data and bookmakers' odds in modelling football scores" | [L151] "https://arxiv.org/abs/1802.08848" |
| E7 | [L152] "Premier League" | [L152] "2026" | [L93] "official glossary" | [L152] "FPL glossary: Fantasy talk explained" | [L152] "https://www.premierleague.com/en/news/2683145" |
| E8 | [L153] "Bonello, N., Beel, J., Lawless, S. and Debattista, J." | [L153] "2019" | [L153] "AICS proceedings" | [L153] "Multi-stream Data Analytics for Enhanced Performance Prediction in Fantasy Football" | [L153] "https://arxiv.org/pdf/1912.07441" |
| E9 | [L154] "Matthews, T., Ramchurn, S. and Chalkiadakis, G." | [L154] "2012" | [L154] "AAAI 26, 1394-1400" | [L154] "Competing with Humans at Fantasy Football: Team Formation in Large Partially-Observable Domains" | [L154] "https://ojs.aaai.org/index.php/AAAI/article/download/8259/8118" |
| E10 | [L155] "Duan, T. et al." | [L155] "2020" | [L155] "ICML" | [L155] "NGBoost: Natural Gradient Boosting for Probabilistic Prediction" | [L155] "https://arxiv.org/abs/1910.03225" |
| E11 | [L156] "Gneiting, T. and Raftery, A." | [L156] "2007" | [L156] "JASA 102(477), 359-378" | [L156] "Strictly Proper Scoring Rules, Prediction, and Estimation" | [L156] "https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf" |
| E12 | [L157] "Gupta, A." | [L157] "2019 preprint" | [L157] "arXiv:1909.12938, v1 deposited 19 September 2019"; "The PDF is headed International Conference on Sports Engineering (ICSE-2017), Jaipur, India, 23-25 October 2017."; "arXiv gives no proceedings reference" | [L157] "Time Series Modeling for Dream Team in Fantasy Premier League" | [L157] "https://arxiv.org/abs/1909.12938" |

### Method, metric, evaluation design, baseline and reported finding

Source: `docs/research/literature_forecast_accuracy_2026_10.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `779803bb5159ea14035ffcde323b68e1de46fe5d`, SHA-256 `7f785db4e4d1b4168a651cd3e885188254e8bfdbab9e5c213ed7b3cc12e0e549`.

| id | review section | method | metric | evaluation design | baseline | reported finding |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | [L47] "1. Position-specific tree ensembles and conditional residual correction" | [L49] "combines position-specific Random Forest/XGBoost models using FPL and Understat histories" | [L49] "one-week RMSE" | [L49] "Development covers 2020-21 to 2023-24; prospective evaluation is only 2024-25 GW32-38."; "Development folds split by club, and missing 2020-21 Understat values borrow from later seasons." | [L49] "Last 5"; "commercial FPL Review" | [L49] "Table 4 reports one-week RMSE 1.517 versus Last 5's 2.136 on 3-4 point returns, and 5.142 versus 5.613 on 5+ returns."; "On non-players, OpenFPL is worse: 0.818 versus 0.791, and commercial FPL Review is 0.689." |
| E2 | [L57] "2. Hierarchical player models, form and regression" | [L59] "use hierarchical Bayesian models for Italian fantasy ratings, explicitly modeling missing appearances"; "player, team and position nesting" | not stated in the document | [L59] "the first half of Serie A 2015-16 trains second-half predictions" | not stated in the document | [L59] "Their author-hosted proceedings explain player, team and position nesting, not an FPL decision gain."; "No transferable points-per-week effect is available from that evidence." |
| E3 | [L67] "3. Availability, rotation, injury news and workload" | [L69] "predict next-session/game injuries from an elite club's GPS training workload"; "their decision tree" | [L69] "precision"; "recall"; "F1" | [L69] "In 10,000 repeated two-fold cross-validations"; "In a week-by-week simulation of one season" | [L69] "the ACWR and monotony forecasters"; "four simple baselines" | [L69] "their decision tree averages 50 percent precision and 80 percent recall, against below 4 percent precision for the ACWR and monotony forecasters and at most about 6 percent for four simple baselines"; "In a week-by-week simulation of one season it reaches precision 0.56 and F1 0.60, detecting 9 of 14 injuries from week 6." |
| E4 | [L75] "4. Player xG/xA, fixture scoring and projected lineups" | [L77] "studies position/player effects using StatsBomb shot events" | [L77] "Brier" | [L77] "Its non-Bayesian feature comparison"; "over 63,309 shots" | [L77] "the basic model"; "versus StatsBomb" | [L77] "Its non-Bayesian feature comparison reports Brier 0.086 for the basic model and 0.076 for the richer model over 63,309 shots, versus StatsBomb 0.075." |
| E5 | [L75] "4. Player xG/xA, fixture scoring and projected lineups" | [L79] "infer player abilities for event types from EPL touch-by-touch data, add them to the Baio and Blangiardo team goal model, and predict whether 2014-15 EPL matches go over 2.5 goals"; "use expert-predicted starting line-ups (86 percent accurate over the season)" | [L79] "over/under AUC"; "the betting return"; "predictive goal log-likelihood" | [L79] "They refit in expanding blocks on all of 2013-14 plus the earlier 2014-15 games"; "all five prediction blocks" | [L79] "the Baio and Blangiardo team goal model"; "the team baseline" | [L79] "The player model raised over/under AUC in all five prediction blocks (for example 0.68 against 0.55 in block 4) and the betting return."; "Its predictive goal log-likelihood on the second 80-game block of 2014-15 was worse than the team baseline's (-163.1 against -159.6), and the authors report similar results for the other blocks." |
| E6 | [L83] "5. Clean sheets, fixture difficulty and changing team strength" | [L85] "combine historical team parameters and betting information in a hierarchical Poisson model" | not stated in the document | [L85] "fitting nine seasons and predicting a tenth across major European leagues" | not stated in the document | [L85] "The paper reports comparative predictive checks, not a transferable FPL decision uplift." |
| E7 | [L91] "6. Defensive contributions and the current scoring rules" | [L93] "This is a scoring definition" | not stated in the document | not stated in the document | not stated in the document | [L93] "The Premier League's 2026-27 explanation awards two points for 10 defender CBIT actions or 12 midfielder/forward CBIRT actions, with recoveries included for the latter group"; "This is a scoring definition, with no reported forecasting-method effect." |
| E8 | [L97] "7. Blending with game, crowd and market forecasts" | [L99] "combine historical statistics, betting and human/social information" | not stated in the document | [L99] "in 2018-19"; "Their section 3.3 permits a fresh lineup each week without real transfer penalties" | [L99] "their statistical comparator" | [L99] "reporting over 300 points and about 11 points per week above their statistical comparator in 2018-19" |
| E9 | [L97] "7. Blending with game, crowd and market forecasts" | [L99] "a Bayesian sequential manager" | not stated in the document | [L99] "trained on 2009-10 and evaluated on 2010-11" | [L99] "against 2.5 million managers" | [L99] "Matthews et al. [E9] report approximately top-percentile performance against 2.5 million managers for a Bayesian sequential manager trained on 2009-10 and evaluated on 2010-11." |
| E10 | [L105] "8. Full point distributions rather than means alone" | [L107] "learns conditional distribution parameters with natural-gradient boosting" | not stated in the document | [L107] "evaluates probabilistic regression on non-football benchmarks" | not stated in the document | [L107] "Neither reports an FPL gain." |
| E11 | [L105] "8. Full point distributions rather than means alone" | [L107] "explain proper scoring rules, including logarithmic score and CRPS, and why coverage and narrowness alone do not determine forecast quality" | not stated in the document | not stated in the document | not stated in the document | [L107] "Neither reports an FPL gain." |
| E12 | [L57] "2. Hierarchical player models, form and regression"; [L65] "Time-series alternative." | [L157] "it ensembles ARIMA and LSTM-RNN forecasts (weights 0.4 and 0.6) trained on three seasons, 2013-14 to 2015-16, to forecast 2016-17 for 326 continuing players"; "It chooses one 15-player preseason squad by linear programming, with no transfers." | [L65] "one team-level figure"; "validation RMSEs" | [L65] "tracks the selected fifteen over 2016-17"; [L157] "RMSE is shown only for two players on 2015-16 validation" | [L157] "there is no baseline comparison" | [L65] "their 3718-point forecast total was 87 points too high"; [L157] "The only 2016-17 outcome reported is an 87-point over-forecast for the whole squad (3718 points predicted)." |

### The review's qualification of each work

Source: `docs/research/literature_forecast_accuracy_2026_10.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `779803bb5159ea14035ffcde323b68e1de46fe5d`, SHA-256 `7f785db4e4d1b4168a651cd3e885188254e8bfdbab9e5c213ed7b3cc12e0e549`.

| id | qualification |
| --- | --- |
| E1 | [L49] "Those choices are unsuitable for this repository's temporal test."; [L11] "its seven prospective weeks, feature sources and validation design do not establish a gain here"; [L55] "that is an adaptation, not an isolated published effect from E1"; [L119] "This is an elicited target magnitude, not an expectation justified by OpenFPL." |
| E2 | [L147] "journal full text was not accessible in this review" |
| E3 | [L69] "This is injury prediction with private physical measurements, not a public-data weekly start or minutes forecast."; [L71] "Public FPL histories are not GPS training exposure." |
| E4 | [L77] "That comparison is not a prospective FPL gain or a quantified benefit from hierarchical player effects."; "It needs shot geometry and freeze-frame context." |
| E5 | [L79] "None of this is an FPL squad gain."; "The event and projected-lineup inputs are material parts of the method, not implementation details."; [L150] "Event abilities and team goals are distinct from FPL total points." |
| E6 | [L85] "Its relevance is learning team scoring rates from complementary information, not applying an extra difficulty multiplier." |
| E7 | [L152] "Read 15 October 2026."; [L124] "This is a rule maximum, not recoverable forecast bias" |
| E8 | [L99] "That is a multi-input system result, not an isolated blend effect."; "so the quoted rank is not a legal season-chain result"; "Neither identifies a +11 point forecast improvement under today's rules."; [L153] "multi-source system result" |
| E9 | [L99] "Neither identifies a +11 point forecast improvement under today's rules."; [L154] "The proceedings are 2012 despite the publisher landing page's later upload date." |
| E10 | [L155] "generic probabilistic regression, not football validation" |
| E11 | [L156] "Methodological justification, not an empirical FPL improvement." |
| E12 | [L65] "there is no baseline, paired error or decision effect"; "That supports surveying form dynamics, not expecting a gain." |

## Published football works cited in other documents under docs/research

### `docs/research/football_component_ablation.md`

Source: `docs/research/football_component_ablation.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `225d49deb6680fdef986e0141c8017fdf5f07213`, SHA-256 `60d61b7a8a6b5c9ba0087d0ae6bf6b30709e90cf06f96437db3aa4e60c2d81ec`.

| id | review id | work | url | the document's text |
| --- | --- | --- | --- | --- |
| R1 |  | [L236] "Macri-Demartino, Egidi and Torelli" | [L236] "https://arxiv.org/abs/2508.05891" | [L235] "The adaptive period pooling described by"; [L236] "with a 2026 JRSSC"; [L237] "publication reference, motivates testing change-aware shrinkage instead of one fixed"; [L238] "half-life. The current Gamma working filter is not an implementation of their full"; [L239] "model." |
| R2 |  | [L239] "Baio and Blangiardo" | [L239] "https://discovery.ucl.ac.uk/id/eprint/16040/" | [L239] "discuss"; [L240] "overshrinkage, relevant to elite and newly promoted clubs." |
| R3 | E1 | [L242] "OpenFPL" | [L242] "https://arxiv.org/abs/2508.09992" | [L242] "offers a public FPL/Understat ensemble and"; [L243] "evaluation reference."; "Its reported results are external, not"; [L244] "reproduced here and not evidence of our system's superiority." |

### `docs/research/football_score_state_development.md`

Source: `docs/research/football_score_state_development.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `9d01503566bf5c6b3fa2ab305fc18864e5c773eb`, SHA-256 `0cf9f112de8f16409e18bc5cda5d1b04b09b1e918d16187e3cf11df38ca44266`.

| id | review id | work | url | the document's text |
| --- | --- | --- | --- | --- |
| R4 |  | [L12] "Dixon and Robinson's birth-process study" | [L12] "https://rss.onlinelibrary.wiley.com/doi/pdf/10.1111/1467-9884.00152" | [L13] "motivates modelling scoring as a process whose intensities can change during a"; [L14] "match." |
| R5 |  | [L14] "Maia and colleagues" | [L14] "https://arxiv.org/html/2312.04338v1" | [L14] "estimate"; [L15] "log-linear intensities with predictable match context. Their Brazilian league"; [L16] "results do not supply PL coefficients for this implementation." |

### `docs/research/football_fm_source_feasibility.md`

Source: `docs/research/football_fm_source_feasibility.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `9c82492ab10db8ceeabd683450593d337ce0e269`, SHA-256 `9755d92a4557d4d763f3eb49ccd20d592b86f3cbdf92c5021092764b3f01ccbb`.

| id | review id | work | url | the document's text |
| --- | --- | --- | --- | --- |
| R6 |  | [L132] "Mahmudlu, Karakus and Arkadas (2025)" | [L132] "https://arxiv.org/html/2511.23072v1" | [L132] "use FM17 ratings as hierarchical Bayesian priors with real 2015-16 shot events, including counterfactual player substitutions."; "Their ratings reflect that same season's performance, so the study is retrospective evidence rather than a predeadline forecasting validation." |
| R7 |  | [L134] "Chazan-Pantzalis (2019), chapter 5" | [L134] "https://core.ac.uk/download/328007195.pdf" | [L134] "compares FM17 traits with actual season ratings for 59 Premier League central defenders."; "its small seasonal cross-section does not validate weekly future forecasts or this project's scoring target." |
| R8 |  | [L136] "Yigit, Samak and Kaya (2020)" | [L136] "https://research.itu.edu.tr/en/publications/an-xgboost-lasso-ensemble-modeling-approach-to-football-player-va/" | [L136] "use FM features to assess player market value."; "That is evidence of a valuation use case, not proof that market value or FM traits improve FPL points prediction." |

### `docs/research/football_load_minutes_development.md`

Source: `docs/research/football_load_minutes_development.md` at commit `144e3f7be824115b64ec8321d8b60c6831092973`, git blob `7f96dd1f9459084cf96428d9091c5688213d60be`, SHA-256 `e432b3fb2bbeaa80577322bc2ed9ab93cf6df1c36fd568e7af3101840354116f`.

| id | review id | work | url | the document's text |
| --- | --- | --- | --- | --- |
| R9 |  | [L19] "A prospective 27-team, 11-season study" | [L19] "https://pubmed.ncbi.nlm.nih.gov/23851296/" | [L20] "found congestion associated with muscle injury while team-performance effects"; [L21] "were limited."; [L23] "These studies support measurement definitions and candidate inputs;"; [L24] "they do not supply calibrated FPL appearance values or causal treatment effects." |
| R10 |  | [L21] "A player-level congestion study" | [L21] "https://pubmed.ncbi.nlm.nih.gov/26682867/" | [L22] "explicitly measured an inter-match interval from the end of play to the next"; [L23] "kickoff."; "These studies support measurement definitions and candidate inputs;"; [L24] "they do not supply calibrated FPL appearance values or causal treatment effects." |

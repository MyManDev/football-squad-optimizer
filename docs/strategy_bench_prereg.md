# Pre-registration: the strategy bench, and what a constrained plan must prove before its name means anything

Written **2026-08-27, before any of the strategy catalogue exists** — no `Strategy`
registry, no overlap-banded candidate generation, no bench harness. The gates are fixed
here so they cannot drift toward the numbers once they arrive.

## What is being claimed, and by whom

The strategy catalogue frames every play mode as: **maximise expected points under a
declared structural constraint; the constraint's cost is the price tag.** The recipe
behind `ortak-koru` — hold the shared high scorers, replace the shared low scorers —
is what "maximise expected points subject to overlap ≥ g" produces by itself; the
recipe behind `fark-yarat` is the same machine with the inequality reversed. Those are
theorems about the *solver*. What they do not establish is that the constraint does in
the world what its name promises: that a high-overlap plan actually falls behind its
rival less often, and a low-overlap plan actually wins big more often. That is an
empirical claim, and this document is its pre-registration.

**What is not at stake here.** No outcome of this bench publishes a probability.
The rival-relative window probabilities fell in three pre-registered constructions —
`rival_calibration` (gaps +0.42/+0.55/+0.61, intervals nowhere near zero),
`anchored_calibration` (the shadow family under-claiming 0.09–0.15), and
`overlap_calibration` (the shadow moved the wrong way, −0.149 → −0.171) — and the
line's own stop-rule bound (`measurements_index.md:87-89`). The bench
*measures* realized frequencies as facts about strategies, on development seasons; the
member-facing surface ships expected points, expected gap, overlap and the price tag,
and nothing here can unlock more.

## Declared before measurement

- **Population**: the four development seasons (2021-22 .. 2024-25), every fold the
  windowed machinery yields, windows clipped at season end. The spent 2025-26 holdout
  is not reused; the current season is never touched. Horizons 1, 3 and 5.
- **Rival**: the ownership-template rival (`template_rival_from_ownership`), per fold —
  the archive has no mini-league, and the template is the one rival every development
  fold can name. Its eleven and captain come from the fold's own pre-deadline snapshot.
- **Overlap instrument**: shared members between the candidate's fifteen and the
  rival's known eleven, an integer 0–11. Captain agreement is recorded separately and
  is not part of the band definition. (The captain-weighted starter share
  `crowd_overlap` stays what it is — declared once for the edge scaling, not a knob,
  and not this band.)
- **Bands**, fixed here: **high-overlap** = overlap ≥ 9; **differential** = overlap
  ≤ 5; **control** = unconstrained (today's saf-puan). Finer knob values inside a
  strategy's declared search space are the screening's business
  (`strategy_screening`), but the *gates below are evaluated on these three bands
  only* — a gate whose bands move with the search is no gate.
- **Outcome instrument**: realized window points from the archive's actual per-player
  scores, candidate and rival scored identically; "behind" means candidate window
  points < rival window points; "wins big" means candidate − rival > +5.0. Claimed
  costs are the solver's own expected-points differences at decision time.
- **Comparisons are fold-paired** (same fold, band vs band), intervals are the
  fold-level bootstrap at 90%, as in `windowed_rank_note.md`.

## The gate

1. **Separation.** At each horizon separately (h=1 and h=3 gated; h=5 measured and
   reported under the same rule for the naming decision): the realized fall-behind
   frequency in the high-overlap band is **lower** than in the differential band,
   fold-paired, and the 90% bootstrap interval on the difference excludes zero.
2. **Direction.** The realized frequency of finishing more than 5 points ahead is
   **highest in the differential band** of the three. Same populations, same pairing.
3. **Price honesty.** For each constrained band: the realized cost (control's realized
   window points minus the band's, fold-paired) may exceed the claimed
   `expected_points_cost` — but the 90% bootstrap interval of (realized − claimed)
   must not lie entirely above zero. A price tag that systematically understates what
   the constraint costs is a false label, whatever else passes.
4. **h=1 is not sacrificed.** The control band's plan at h=1 reproduces the published
   saf-puan baseline **bit for bit** on the same inputs, every fold. The catalogue is
   an extension, not a re-pick; if adding strategies moved the one answer that already
   ships, that is a defect, not a finding.

## Declared fall-back, before any number exists

If gate 1 holds at h=1 but fails at h=3 or h=5: windows still publish, but the mode
**names** may not be presented as safer/riskier at the failing horizon — the interface
shows the constraint and the price tag and stops implying direction. The already-shipped
copy about multi-week planning stays quoted (rolling H3 −2.30, H4 −8.32: planning
further ahead has not beaten deciding weekly, and the interface says so).

If gate 3 fails for a band, that band's strategy ships without a price tag until the
tag is honest, or not at all. If gate 4 fails, nothing ships until it passes — that
gate is a regression, not a hypothesis.

## What passing means

A strategy whose band passes 1–3 with 4 intact earns `evidence: gated_pass` in the
registry and may be *named* (koru/yarat language) at the passing horizons. Everything
else registers as `prereg_open` or `diagnostic_only`, renders with its constraint and
price only, and cannot be called safer or riskier than anything — the registry enforces
the naming rule structurally, not editorially.

Measurement only; nothing here touches the live decision path, and `prediction/` is
not involved. The bench harness itself arrives in later PRs (`experiments/design.py`,
the registry, banded candidate generation); this document precedes them all.

---

## Post-run protocol amendment (2026-08-28): the first run crossed the load boundary

**Labelled amendment, written after the first run and before the corrective rerun. It
changes the data-access mechanics only; no gate, threshold, band, horizon, solver
limit, bootstrap rule, seed or declared season moves, and the measured gates are not
reinterpreted here.**

- **First (invalid) run**: commit `8f8d3cba7efd93b27ef81851389a5d8304be34fb`, executed
  2026-08-27T18:47:19Z → 19:50:39Z, exit 0.
- **Discovered**: 2026-08-28, on post-run inspection.
- **Exact defect**: `scripts/measure_strategy_bench.py` called
  `build_panel(archive_root)` without a `seasons` argument; the loader's default is
  every `SUPPORTED_SEASONS` entry, which includes the locked 2025-26 holdout, and the
  script's own holdout check ran only after the panel was already loaded. The artifact
  recorded the access itself (`metadata.provenance.history_seasons` lists 2025-26)
  while hard-coding `holdout_untouched: true`.
- **Why the first run is procedurally invalid**: the declared boundary above is "the
  spent 2025-26 holdout is not reused; the current season is never touched" — a
  no-read protocol. Reading the files is the violation; whether the rows influenced
  any number is a separate question. A run that crossed the declared boundary cannot
  stand as the binding measurement.
- **Downstream-influence evidence**: `build_control_residual_table` drops every row
  beyond the last development season before feature or outcome computation (the rank
  filter producing `visible_panel`), fold construction selects panel rows by
  development season only, and enrichment loads an explicit `DEVELOPMENT_SEASONS`
  list — so the loaded holdout rows appear in no fold, no residual and no score, and
  the corrective run is expected to reproduce the first run's numbers identically.
  The corrective run will report any difference.
- **Corrective data-access boundary**: evaluation seasons are parsed and validated
  before any loader call; requesting 2025-26 refuses before `build_panel` can run;
  the panel is loaded from an explicit history list — 2020-21 as prior cross-season
  history plus 2021-22..2024-25 — and 2025-26 is never requested; provenance records
  the actually loaded seasons; `holdout_untouched` derives from the loaded panel and
  the run aborts without writing artifacts if the holdout is ever present.
- **Rerun declaration**: exactly one corrective binding rerun is allowed, with every
  gate and analytical parameter unchanged. Its result is binding whatever it says.
  The first run's artifacts remain in Git history as the record of the invalid run.

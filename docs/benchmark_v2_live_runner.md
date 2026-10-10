# Benchmark V2 live runner

The live runner implements `docs/benchmark_v2_prereg.md` without reading an archive,
fitting a projection, changing publication output or changing a declared comparison.
It reads one explicit private list of 2026-27 weeks. It never searches for a preferred
week, replaces a cohort member or reads the locked 2025-26 holdout.

Each week supplies five immutable capture ids: `decision`, `freeze`, `cohort`,
`picks` and `outcome`. The caller lists them with `gameweek` in a JSON manifest under
`weeks`, with top-level `season: 2026-27` and the declared range `first_gameweek` and
`last_gameweek`. Every gameweek in that range appears exactly once: with its five ids,
or as `{"gameweek": n, "exclusion": "missing_capture"}` when its captures do not
exist. A gap, a week outside the range or a repeated week refuses the reading before
any capture is opened. The first gameweek is fixed at 7 by the preregistration
amendment of 2026-10-10, accepted by the owner and declared before the GW7 deadline:
`first_gameweek` must be 7, and a range starting at any other week is refused before
any capture is opened. Gameweeks 3 to 6 are not part of the reading. The claim and
the result record the declared range and the manifest's SHA256, and every missing
week appears among the exclusions. Raw manager ids and picks stay in the local
snapshot store and are absent from the resulting committed summary.

The decision capture is the exact pre-deadline `fpl-live` source. The freeze is a
pre-deadline `fpl-benchmark-decision` capture containing that source's unchanged
`bootstrap-static.json`, the already recorded `system-decision.json`, and
`benchmark.json`. The latter binds the season/week, cohort and decision ids,
decision fingerprint, exact system-decision SHA256 and `template_configuration`:
integer-tenths budget, three-per-team limit and deterministic ownership scale 1000.
The weekly collector must record this configuration before the target deadline.
Existing late decisions or unrecorded configurations cannot be reconstructed.

The cohort is the original pre-deadline `fpl-top100` capture with unique rank_sort
1 to 100, taken while the target week is the open one: at or after the previous
gameweek's deadline, whose own instant already closes that week as every deadline
gate here counts it. An older capture is refused as `stale_cohort`. The post-deadline
`fpl-benchmark-picks` capture holds its original members'
target-week picks, histories and bootstrap, plus `benchmark.json` naming that same
cohort, season and week. Unreadable members remain absent. The original bench positions
are recovered from FPL's explicit autosubstitution pairs when its settled positions
have moved. Normal-week multipliers are used throughout. Transfer hits and chip
multipliers do not enter the primary score. The frozen squad remains the captured squad.
Chip rosters follow the preregistration amendment of 2026-10-10, accepted by the
owner. A Wildcard entry is scored on its captured roster, since a Wildcard changes only
the transfer cost, which the primary score excludes. A Free Hit roster is never scored:
the entry is scored on the roster the Free Hit reverts to, its previous week's squad,
starting XI, bench order, captain and vice-captain, against the target week's outcomes.
Those picks are read only from the previous week's `fpl-benchmark-picks` capture listed
in the same manifest, admitted when its `benchmark.json` names that week's frozen cohort
and it was captured at or after that week's deadline. The previous week's recorded
automatic substitutions are reversed as for any other roster. A Free Hit entry whose
previous picks are missing is excluded as `free_hit_previous_missing`. That includes
every Free Hit entry of GW7, since GW6 is outside the reading. An entry whose previous
roster is itself a Free Hit roster, or who played an unrecognized chip, is excluded as
`chip_unresolved`. The runner does not invent a counterfactual squad or
count one toward coverage. Excluded entries count against the 80-member floor like any
other, and a week below it stays out of both comparisons. Each week records how many
valid entries were scored on a Wildcard or a reverted Free Hit roster under
`cohort_chip_rosters`, and the previous week's picks capture it admitted under
`previous_picks`.

The outcome is a completed `fpl-live` capture whose target week is finished and checked
and whose player event points and minutes cover all three primary arms. Every capture
must carry the same target deadline. The ownership template is built from the unchanged
decision-time pool with the configuration frozen before that deadline. No outcome
enters that construction. The preflight validates scoring with zero points before
admitting a week, so malformed squads cannot count toward eight paired weeks.
Template solves use the existing committed-measurement budget of 5.0 deterministic
seconds with a 600-second wall cap; both limits are recorded with each valid week.

At least eight distinct valid paired weeks and at least 80 of the original 100
managers per week are required. All primary means and medians use the identical
gameweek set, in gameweek order. The record carries capture identities, timestamps,
model identity, configuration, the scoring, template and cohort policy versions,
coverage, exclusions with stable reason codes, zero-minute starters, autosub
recovery, vice-captain recovery, bench contribution and V1-to-V2 score changes. Under
`official_autosub_captain_v2` the bench scores only through automatic substitutions,
so `bench_contribution` and `autosub_recovery` hold the same value by definition: the
points the substitutes brought in. Both keep the preregistration's names. The
record's Markdown twin repeats the summary, each week's cohort coverage and the exclusions,
in gameweek order with three fixed decimals. Twelve
weeks remains the preregistration's preferred population for a season interpretation;
the runner introduces no improvement gate or interval threshold.

Below eight valid paired weeks the runner refuses and writes nothing. It has no
season-end mode: the `insufficient_evidence` record that #1016's third box needs
when the season ends without eight valid weeks is not produced here and remains
work for the reading step.

The command has one fixed record root, the repository's `docs/` directory; no caller
chooses another. After preflight admits eight weeks, the runner atomically claims
`docs/benchmark-v2-live-2026-27.reading` before calculating paired scores. A second
invocation refuses before opening captures when that claim, the JSON or Markdown
record, or a `docs/measurements_index.md` row naming the reading already exists, so
once the result PR merges every checkout refuses. A failed claimed reading also stays
claimed; recovery requires an explicit owner-reviewed protocol amendment, not deleting
the claim. A successful reading writes `docs/benchmark-v2-live-2026-27.json` and its
Markdown twin beside the claim. The later result PR commits all three and must add the
measurements-index row. The existing descriptive historical record is preserved.

After the collector has supplied the required immutable inputs, the implementation and
preregistration are committed and the complete quality suite has passed, the reading is:

```powershell
$env:PYTHONPATH="<worktree>/src;<worktree>"
C:/Users/ertug/Desktop/MyManDev/projects/football-squad-optimizer/.venv/Scripts/python.exe -m scripts.read_benchmark_v2_live --manifest <private-manifest.json> --snapshot-root <snapshot-root>
```

The collector and the actual reading remain separate issue steps. No real live reading
was taken to implement or test this runner.

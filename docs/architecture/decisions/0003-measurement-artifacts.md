# ADR 0003 — What a measurement artifact is, and where it lives

- **Status:** accepted
- **Date:** 2026-08-18
- **Deciders:** all three owners
- **Related:** [ADR 0002](0002-contract-versioning.md), `../../measurements_index.md`,
  `../../artifact_preflight_spec.md`

## Context

Measurements are the product here. `measurements_index.md` registers 41 of them, each with what
it found and where it came from, and states the rule that keeps them honest: every artifact is
recommendation-only, and a regenerated artifact must still pass
`scripts.run_measurement_preflight`.

Two conventions for where generated output goes have grown up side by side, and they
contradict each other:

- **`artifacts/` is gitignored.** `.gitignore` calls it "Reproducible local experiment outputs
  (reports are generated, not source data)".
- **`docs/` holds 54 committed JSON artifacts totalling 11.2 MB.** The markdown in `docs/` is
  546 KB — so **95% of `docs/` by size is machine-generated JSON.** The largest single file,
  `docs/transfer_discipline.json`, is 4.7 MB; `season_chain.json` is 1.0 MB; six more exceed
  500 KB.

Nobody decided this. It is what happens when "the record must be in the repository" meets "the
runner writes JSON next to its markdown". The question is not whether committing measurements
is right — it plainly is, for a project whose claims are its output — but which artifact, at
what size, and what that then costs.

The cost is already concrete. Committed artifact paths are load-bearing in code, not just in
prose:

- `tests/unit/test_measurement_preflight.py:92-96` pins **five literal `docs/*.json` paths** and
  asserts they stay conformant.
- `tests/unit/test_uncertainty_fixture_contract.py` reads
  `docs/control_uncertainty_calibration.json` and asserts a configuration fingerprint against it.
- `src/squadopt/backtest/production_benchmark.py:192` sets
  `source_reference="docs/production_prediction_spec.md"` — a docs path **embedded into
  generated artifacts**, so moving that file changes artifact bytes.
- `src/squadopt/live/risk.py:164` bakes `docs/fixture_group_conformal_note.md` into a
  user-facing string.

Which means: **`docs/` is not a documentation directory. It is part of the build surface.**

## Decision

**Three tiers, decided by what the file is for, not by what produced it.**

| Tier | Goes to | Committed | Size guidance |
| --- | --- | --- | --- |
| **Record** — the claim, its finding, its provenance, and enough numbers to check it | `docs/` | yes | markdown, plus JSON under ~250 KB |
| **Evidence** — the full per-fold, per-scenario, per-gameweek expansion behind a record | `artifacts/` | no | any size |
| **Operational state** — captures, ledger, handoffs | `data/` | no | any size, licence-restricted |

Rules:

1. **Every committed artifact has a row in `measurements_index.md`.** No row, no commit. The
   index stays the register; this ADR does not replace it.
2. **A record must be checkable without its evidence.** If a reviewer needs the 4.7 MB
   expansion to confirm the finding, the record is under-specified — add the summary statistics
   to the record rather than committing the expansion.
3. **Over ~250 KB, justify it in the PR.** Not a hard ban: `fw10_screening.json` at 644 KB is
   the frozen screening decision and belongs in the repository. But the default answer for a
   file that size is that it is evidence, and the burden is on committing it.
4. **The existing 54 artifacts are grandfathered.** No retroactive purge. Rewriting history to
   drop megabytes from a repository three people have cloned costs more than it saves, and the
   large files are all genuine records of decisions that were actually made. The rule applies
   from here.
5. **Moving a committed artifact is a code change.** Because of the pinned test paths and the
   embedded `source_reference`, any relocation touches tests and can change artifact bytes. It
   gets the same treatment as a source change, including regeneration where bytes move.
6. **Artifacts are written atomically once the helper exists.** Today every write in the
   repository is direct-to-destination — there is no `os.replace`, `tempfile` or staging
   anywhere in `src/`, `scripts/` or `tests/`, and `_experiment_cli.write_json` writes straight
   onto the target path. A half-written artifact currently looks like a real one. This is
   recorded here as a known defect; the fix belongs with the artifact-writing owner.

## What this means for reorganising `docs/`

A later stage proposes splitting the flat 155-file `docs/` into subdirectories. Rule 5 makes the
cost explicit, and it is much higher than "fix the links":

- ~98 relative markdown links (60 within `docs/`, 36 from `README.md`);
- ~31 references that no link checker can see, because they are bare basenames in prose —
  including the whole `## Process references` block at `measurements_index.md:69-73`;
- ~36 hard-coded `docs/` paths in `scripts/`, `src/` and `tests/`, six of them asserted by tests;
- one path embedded into generated artifact bytes.

There is no link checker in the repository. A reorganisation is therefore not a mechanical
docs-only move, and should not be scheduled as one.

## Why not the alternatives

**Commit everything, including full expansions.** Maximum reproducibility, and it is roughly
today's behaviour. But it puts multi-megabyte machine output in every clone forever, and it
makes review meaningless — nobody diffs a 4.7 MB JSON, so it is committed unread.

**Commit nothing; regenerate on demand.** Clean, and wrong for this project. The claims *are*
the product; a finding nobody can check without a four-season rerun is not a finding. Several
records exist precisely because regenerating them is expensive.

**Move artifacts to a separate store or release assets.** Solves size properly. Rejected for now
as premature: it adds infrastructure and a second place to look, and 11.7 MB is not yet a
problem worth that. Revisit if `docs/` doubles.

**Split records from evidence by file type** (all `.md` committed, all `.json` ignored).
Tempting because it is mechanical, and wrong: the JSON *is* the machine-checkable half of a
record, and `run_measurement_preflight` validates it. The split is by purpose, not extension.

## Consequences

**Accepted:**

- A judgement call per artifact, with a soft threshold rather than a rule a script can enforce.
  Rule 1 is the backstop: the index row forces someone to state what the artifact is for.
- `docs/` keeps its dual nature as documentation and build surface. This ADR names that rather
  than fixing it.
- Grandfathering means the repository stays at 11.7 MB with a 4.7 MB file in it.

**Gained:**

- The contradiction between `artifacts/` being ignored and `docs/` being committed is resolved
  by purpose, so the next runner author has an answer.
- The true cost of a `docs/` reorganisation is written down before someone schedules it as a
  mechanical PR.
- The non-atomic artifact write is recorded as a defect rather than remaining folklore.

## Verification

```bash
git ls-tree -r -l HEAD docs | awk '{split($5,a,"."); e=a[length(a)]; s[e]+=$4; n[e]++} END {for (x in s) printf "%-6s %3d files %8.1f KB\n", x, n[x], s[x]/1024}'
git ls-tree -r -l HEAD docs | sort -k4 -n -r | head -10 | awk '{printf "%8.1f KB  %s\n", $4/1024, $5}'
```

For the coupling that rule 5 exists to protect:

```bash
grep -rn "docs/" tests/ src/ --include='*.py' | grep -v '^\s*#'
```

Last measured against `b031ef1` (PR #110): 155 files, 11.7 MB, 101 markdown and 54 JSON.

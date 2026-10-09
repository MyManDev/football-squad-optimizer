# Prospective football v1 shadow arm

Owner decision 2, recorded on 2026-10-07 in #999 and #1012, authorizes an unserved
`football_team_share_v1` artifact from GW6. This note fixes the interpretation before
GW6's first kickoff, 2026-10-10T11:30:00Z. The frozen
[prospective protocol](football_prospective_prereg.md) is unchanged.

A shadow week is the protocol's v1 arm when the last `fpl-live` capture targeting
that gameweek has its own v1 artifact written before its deadline, with the required
handoff. Each receipt records `served: false`, and every scored shadow week carries
that label. The clause at protocol lines 240-242 about v1 no longer being served
does not make those weeks missing: the same producer still writes the arm's artifact.
All other capture selection, timing, identity and missing-week rules continue to hold.
A missed week is never backfilled. If GW6 is missed, the arm starts at GW7.

## Operator command and receipt

Run from the same commit and checkout as the week's run, after the served forecast
and handoff build and before the weekly run, only with the owner's approval:

```powershell
python -m scripts.build_football_shadow --snapshot-root data/snapshots `
  --snapshot-id <capture> --archive-root data/raw/vaastav-fpl
```

The default root is `artifacts/shadow/football_team_share_v1`. The command has no
model flags. It uses the default v1 producer and publisher with no companion and
validates the resulting file with the production reader. It refuses the repository's
`artifacts` directory and the root the backend selection file names, a non-live capture,
a closed capture deadline or an existing receipt before fitting. The selection file
accepts UTF-8 with or without a BOM; a relative selection is anchored to the repository,
independently of the command's working directory.
It also checks the clock after fitting, before publishing. A forecast's write time
is compared with the deadline independently; a late write never claims timely input.

The two retained files are `<root>/football/<capture>.json` and
`<root>/receipts/<capture>.json`. Receipt contract `football_shadow_receipt_v1` holds
the capture instant, season, own target gameweek and deadline, the reader's model
version and fingerprint, `artifact_sha256`, `artifact_write_utc`,
`written_before_deadline`, `repository_commit`, `repository_tree_clean`,
`python_version`, `library_versions` for numpy, scipy, scikit-learn and pandas,
`wall_seconds`, the document's `archive_hashes`, the same season's complete
same-target usable live inventory in `gameweek_captures`, `skipped_captures`,
`ambiguous_latest`, `newest_for_gameweek` and `served: false`.
Inventory validation runs before fitting. Captures without a bootstrap payload
are skipped and their IDs recorded; other damaged captures still refuse.
The newest flag requires the decision capture to be strictly later than every
other same-target capture. A tie at the latest instant records `ambiguous_latest: true`
and `newest_for_gameweek: false`, matching the input check's ambiguity rule.
Repository status is read with Git's optional locks disabled.
The inventory describes what was present at build time; the
post-deadline input check determines the final selected capture.

Before the deadline, post the capture id, fingerprint and artifact sha256 on #999.
The comment's timestamp provides evidence independent of local modification time.
After the deadline, run the input check on the shadow root with every season capture
and post its JSON on #999. Any later pre-deadline live capture targeting that week
needs its own shadow build and handoff before the deadline, or the week is missing.
After each receipt, back up both files outside the repository, preserving modification
times. The owner runs this step through GW20; the step and preserved files move with
the weekly run when it moves off the PC.

Never give the shadow root to the backend selection file or `-ArtifactRoot`,
`scripts.prepare_football_bundle`, or the planner chain runner and scorer (#923,
#992). It is used only for this prospective arm and its input check and scorer.
The rehearsal uses `artifacts/shadow-rehearsal/football_team_share_v1`, with the
owner's approval; its comparison and wall time are posted on #999. Producer drift
is recorded there rather than pinning old code or changing the frozen protocol.

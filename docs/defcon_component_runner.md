# DEFCON component input check and reading

This is the step 2 command for #1000. Its sole statistical specification is
`defcon_component_prereg.md`. The runner pins that declaration's normalized
SHA-256, verifies #1017's actual GitHub merge time and merged document, and
requires the merged declaration to be an ancestor of a clean committed worktree.
An amended declaration needs review of the runner before any real input check.

The component uses only settled 2026-27 fixture appearances in each published
decision capture. It adds its unconditional term to a copy of that capture's
published base handoff. Both arms use production `project` for availability.
Both candidate versions remain outside the promotion set. There is no weekly
operations integration or member output in this PR.

## Retained inputs

Supply three private roots: retained `fpl-live` snapshots, handoffs with the
existing `by-capture/<snapshot-id>/*.json` layout, and member advice records with
`2026-27/gwNN/entry-<id>/<snapshot-id>/advice.json`. The last pre-deadline
publication selects the exact handoff fingerprint. An absent last capture or
handoff is missing input, never a reason to select an older publication.
The handoff must retain a file write time before its target deadline. A copied
file with a later write time does not establish the required existence proof.

The inventory is restricted to capture identifiers in the 2026-27 season date
range. The bootstrap verifies the season before any event-live file is opened.
Metadata binds every declared checksum; each payload that is opened is checked
against it. The owner must retain the complete capture and publication inventory
so the earliest settled capture and final publication can be selected honestly.

## Input checks after the GW7 and GW10 publishes

Use `scripts/measure_defcon_component.py --check-inputs --check-through 7`
after the GW7 publish, and `--check-through 10` after the GW10 publish. Both
require `--snapshot-root`, `--handoff-root`, `--publication-root` and an explicit
UTC `--as-of`. They print the selected identities, inventory checksums and
missing fixed inputs. They never open an event-live file, calculate a candidate
error, rank players or produce a gate verdict. Post each output on #1000.

## The single reading

After the declared first settled capture exists, the owner invokes the command
without `--check-inputs`, supplying the same three roots, `--as-of`, a persistent
private `--claim-directory`, `--owner-approved` and `--weekly-run-idle`.
Use the same claim directory across worktrees and retain it. A create-once claim
precedes any outcome read and survives a crash or input refusal; the command
never clears a claim or substitutes a later capture. A committed or saved
completed JSON record also refuses another reading.

The command writes the fixed markdown and JSON twins and a row in the existing
measurements index table. The JSON records the code and declaration identity,
every opened input's captured checksum, publication and handoff identities,
weekly pairing or missing reasons, dropped players, all fixed gate constants,
rank groups and diagnostics. A validation refusal after claiming is recorded in
the private claim directory. No output promotes either candidate.

Submit these records as step 4 within seven days of the first settled capture.
Only a passed verdict can support the separate step 5 wiring PR and its required
review. The component and runner PR merges after the GW6 publish; preparing its
synthetic tests does not authorize an input check or the reading.

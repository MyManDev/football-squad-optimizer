# DEFCON component input check and reading

This is the step 2 command for #1000. Its sole statistical specification is
`defcon_component_prereg.md`. The runner pins that declaration's normalized
SHA-256, verifies #1017's actual GitHub merge time and merged document, and
requires the merged declaration to be an ancestor of a clean committed worktree.
An amended declaration needs review of the runner before any real input check.
The authenticated GitHub CLI must be on the invoking shell's PATH. On the owner's
Windows PC its executable is `C:\Program Files\GitHub CLI\gh.exe`; verify
`Get-Command gh` in that shell before invoking this command.

The component uses only settled 2026-27 fixture appearances in each published
decision capture. It adds its unconditional term to a copy of that capture's
published base handoff. Both arms use production `project` for availability.
A present base appearance mapping may omit `direct_control` players; they stay
in both arms with zero term and recorded codes/counts. A legacy absent mapping
remains missing input. Invalid fit fixtures are excluded from both rate counts
with their identity and reason recorded.
Both candidate versions remain outside the promotion set. There is no weekly
operations integration or member output in this PR.

## Retained inputs

Supply three private roots: retained `fpl-live` snapshots, handoffs with the
existing `by-capture/<snapshot-id>/*.json` layout, and member advice records with
`2026-27/gwNN/entry-<id>/<snapshot-id>/advice.json`. The last pre-deadline
publication selects the exact handoff fingerprint. An absent last capture or
handoff is missing input, never a reason to select an older publication.
A hidden staging directory that an interrupted record writer left beside a
capture directory never landed, so it is not a publication.
Deadline proof is the retained publication's `generated_at_utc`, capture identity
and exact handoff fingerprint. Restoring a file with a later modification time
does not invalidate that content proof. Because the game moves deadlines, each
week's deadline comes from the latest retained capture in the input check and
from the declared settled capture in the reading, never from an older bootstrap.

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
missing fixed inputs. They may parse only GW1 to GW5 development event-live
files, reporting excluded fit fixtures and schema disagreements. They never open
a GW6 or later event-live file, calculate candidate error, rank players or
produce a gate verdict. Later fit validity is checked at the single reading. Post each output on #1000.

Ready here describes input presence and identity, not final pairability. The report
lists the development history actually opened, exclusions, absent count diagnostics
and unmapped historical element ids. Missing or malformed inputs for one week leave
the other weeks' rows available.

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
rank groups and diagnostics. The index's Deterministic policy table and its
Direct DEFCON development row are validated before
claiming or opening outcomes. Validation confined to one week makes that week
missing with a named reason. A stopped reading after outcome access saves a
completed `insufficient_evidence` record with error type and message, while its
private claim prevents a rerun. Unreadable capture metadata is skipped and its
identity and reason are included in the report. No output promotes either candidate.
The new reading row follows Direct DEFCON development, as selected on #1000,
and every existing index row retains its order.

If an unreadable metadata file exists at or before the selected reading capture,
the reading refuses before its claim rather than substituting a later capture.
An interrupted directory without metadata remains skippable. Forbidden-season
publication or handoff identities also refuse before the claim. Multiple retained
copies of one handoff fingerprint form one identity and all their byte hashes are
recorded. A malformed realized DEFCON explanation is excluded from diagnostics with
its player, fixture and reason; valid total points still pair that player and week.

Submit these records as step 4 within seven days of the first settled capture.
Only a passed verdict can support the separate step 5 wiring PR and its required
review. The component and runner PR merges after the GW6 publish; preparing its
synthetic tests does not authorize an input check or the reading.

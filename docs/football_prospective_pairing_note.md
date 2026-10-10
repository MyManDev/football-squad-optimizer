# Prospective football pairing rule

Status: accepted. On 2026-10-10 the owner accepted Decision defaults 1 to 5 of
[issue #1007](https://github.com/MyManDev/football-squad-optimizer/issues/1007)
as proposed, with no amendment, answering
[the question in comment 6045899361](https://github.com/MyManDev/football-squad-optimizer/issues/1007#issuecomment-6045899361).
The acceptance came after GW6's first kickoff (2026-10-10T11:30:00Z), so GW6
is not a paired week and GW7 is the first paired week.
Written: 2026-10-07T21:54Z, before any GW6-or-later outcome comparison by this task.

The frozen protocol remains [football_prospective_prereg.md](football_prospective_prereg.md),
merged in #844 at 2026-09-26T06:00:39Z as `ccd803de`. Its first scored week is
GW6; GW1 to GW5 remain spent. Under this rule GW6 stays in both records as a
missing week and GW7 is the first paired week, as the timing section states.
This note does not edit the protocol or change its readings, scored-capture
choice, scoring policy, promotion thresholds or once-only GW20/GW38 reading
schedule.

## Why the pairing needs a durable rule

#1007's pre-declaration evidence reports that capture
`fpl-live-20260922T214539Z-364991a4f832` has pre-deadline member advice records
naming handoff fingerprint prefix `223cd1bab0fb`, while the later rewritten
gameweek alias selects prefix `fb725c1a4f11`. Both identify
`phase_c_control_components_v1`. The record identifies what the published plan
used; a mutable alias can later identify another build. These are the issue's
reported provenance facts, not a new reading of the operator stores.

The owner decided on 2026-10-07, recorded on
[the program](https://github.com/MyManDev/football-squad-optimizer/issues/1012)
and [the shadow issue](https://github.com/MyManDev/football-squad-optimizer/issues/999),
that `football_team_share_v1` is built from GW6 into a separate shadow root and
never served. As the shadow issue records decision 2, shadow weeks are the v1
arm's weeks, and each receipt records `served: false`. #988 route 1 retires the
backend after the GW6 publish. The two arms therefore need preserved inputs
that survive that retirement.

## Default 1: pair Current in this order

**Branch a, the published-plan handoff.** Inspect member advice records for the
scored capture, counting only those whose recorded publication preceded the
target deadline. They must name one common
`provenance.projection_handoff_fingerprint`. Select the handoff carrying that
fingerprint from the gameweek alias or
`data/handoffs/by-capture/<capture>/*.json`, with the same source capture,
season and gameweek. Records with two fingerprints, or a named fingerprint
without a matching file, give a missing week; they do not fall back to branch b.

**Branch b, no eligible advice record.** Use the backend rule pinned to develop
`6e7e6176`: the matching gameweek alias wins; otherwise exactly one matching
retained handoff fingerprint is required. A selected file written at or after
the target deadline makes the week replay. Only this fallback branch applies
the late-handoff rule; branch a's pre-deadline immutable advice records attest
the published handoff's identity.

**Branch c, missing.** If the records disagree, their named handoff is absent,
or the no-record fallback has no unique match, report the protocol's missing
reason, cannot pair the scored capture with exactly one handoff. A missing week
is not repaired by rebuilding a forecast or borrowing another capture's file.

For each week record the branch, selected handoff fingerprint, model version,
file path and write time. Also record the handoff that the backend rule, the
rule `load_capture_identity` applies, selects at reading time, and flag any
difference. The prospective input helper computes it with its own branch b
code, since it does not import the backend module; step 2 names this field
`backend_rule_fingerprint`. That diagnostic changes no score or
classification. Read-time I/O refusals follow the runner's pre-outcome refusal
rules: a handoff file that exists but raises `OSError` when read refuses the
run. A failed read is not a silent opportunity to change inputs.

Implement the pairing using `handoff_path_for` and `read_projection_handoff`
from `squadopt.live`. The prospective input helper/check and runner must not
import `squadopt.platform`. While the backend helper exists, synthetic tests
pin branch b equal to `load_capture_identity` for absent, invalid (`ValueError`
or `DataError` when read) and mismatched files, including alias precedence and
unique retained fingerprints. That helper skips a file that raises `OSError`
and moves on to the remaining copies, so the equality test excludes the
refused case. No backend is started to perform those tests.

## Default 2: the never-served football arm

The football artifact root is `artifacts/shadow/football_team_share_v1`. Every
week read from it is pooled under the protocol's ordinary rules, as decision 2
says. Every such week, replay weeks included, carries `football_served: false`.
Check the immutable receipt at `<shadow-root>/receipts/<capture>.json` against
the artifact bytes, including its fingerprint and SHA256. The required
`--posted-receipts` input carries the pre-deadline SHA256 posts from #999 and
their comment times. Record both those times and the file's write time.

A missing receipt, missing post or digest mismatch is listed beside the week
and introduces no new exclusion into the frozen protocol. The protocol's file
write-time rule decides lateness. Late artifacts are replay, displayed beside
the pooled figures and never pooled. Unusable or missing artifacts retain the
protocol's existing missing status. This note does not permit a different
football version, a newly rebuilt late artifact or a change to the protocol's
classification.

## Default 3: capture and outcome inventory

The runner inventories every 2026-27 `fpl-live` capture in `--snapshot-root` and
records each capture's own target. The scored capture remains the last capture
whose own target is that gameweek, as the protocol declares. An operator-typed
subset must not decide which weeks enter the comparison.

Keep rehearsal captures outside the operator snapshot store. A rehearsal
capture before a deadline could otherwise become that week's scored capture.
The #998 rehearsal capture `fpl-live-20261007T105015Z-4e18c56cbb04` is reported
by #1007 as absent from that store. This note does not copy it there.

For outcomes, select the newest capture taken at or before the reading instant
that marks the target gameweek finished and data_checked and carries its live
event payload. Two distinct eligible captures at the newest instant refuse the
run. No earlier settled capture is substituted for the selected newest one.

At the final reading, load the interim record with
`git show origin/develop:docs/football_prospective_gw20.json`. For each GW6 to
GW20 week whose outcome capture, input fingerprints or realized scores differ,
list both readings' values. Do not conceal settlement corrections or rewrite
the interim record. The once-only and missing/replay rules stay those of #844.

## Default 4: reading two's members

Include every entry whose picks are present in the scored capture, whichever
listed league supplied it. Record the count per week. Entry ids, per-player
rows and per-member plans stay in the ignored private evidence, not the
committed aggregate record. Reading two retains the protocol's normal-week
plan, proof/completeness and scoring rules.

## Default 5: one runner for both readings

The runner records its repository commit and the SHA256 of its own bytes. Its
checkout must be clean and its commit an ancestor of `origin/develop`.
At GW38 it refuses bytes different from those named by the interim record,
unless a change was declared on #1007 before that change's PR merged. The
final record cites that declaration. Fixes stay possible before the interim:
until then the runner's bytes may change without a declaration, and only from
the interim record on does the GW38 byte check apply. This differs from PC1's
scorer, which can run only as the bytes it was added with.

Existing-record refusal checks the working tree, freshly fetched develop and
all Git history. Both JSON and Markdown records are create-once. Render the
twin from written JSON bytes, sorting gameweeks numerically and arms and
populations in fixed order. Stage both files, verify re-render equality, then
land them once and append the measurements-index row last. These are the
runner engineering requirements in #1007, not extra readings or score gates.

## Timing, review and handoff

The early target, a merge before 2026-10-09T10:00:00Z, passed before the
owner answered. The hard limit for merging this note is before GW7's first
kickoff, 2026-10-17T11:30:00Z, and it is never enqueued or merged while a
weekly run (the Tuesday settle or the Friday publish) is under way. The
acceptance covers a merge before that instant only; that is the most
conservative reading of the limit. The merge instant is the one GitHub
records for the pull request that adds this note.

The owner accepted these defaults on 2026-10-10, after GW6's first kickoff at
2026-10-10T11:30:00Z, so this note merges after that kickoff too. GW6 therefore
cannot be a paired week, and GW7 is the first paired week. Both records list
GW6 as a missing week under the protocol's missing reason, cannot pair the
scored capture with exactly one handoff, and state beside it that this rule
was accepted and merged after GW6's first kickoff. GW6 is never pooled, never
shown as replay and never repaired, and the step 2 check reports it the same
way. Listing GW6 under that existing missing reason, rather than under a new
status, is the most conservative reading of the decision.

Step 2 implements the accepted input rule in its own PR, targeting merge before
2026-10-17T10:00:00Z. Step 3 supplies the once-only scorer and mutation evidence,
targeting 2026-11-27 and requiring merge before 2027-01-05T18:00:00Z. The
spent-GW5 rehearsal runs only with the owner's yes and reports timings and
counts only. The interim runs once after GW20 settlement and before
2027-01-16T13:30:00Z, with the heavy slot claimed. No figure from GW6 onward
is calculated before its declared reading.

The step 0 coordination request is on #988. It identifies the four existing
users of `capture_context.py` and asks to keep or move `handoff_fingerprint_for`
while PC1's runner still imports it. The prospective helper/check and new
runner stop depending on the backend after step 2. PC1's scorer remains a
separate program and is not modified here.

All merges require review and an idle weekly-operation window. The owner runs
the Tuesday settle and Friday publish through GW20. A later move off the PC
must preserve captures, handoffs, advice records, shadow artifacts and their
modification times because the protocol uses those times. The note alone
authorizes no collection, rehearsal, reading, release or backend action.

## Acceptance record

The owner accepted these decisions on 2026-10-10, answering
[#1007 comment 6045899361](https://github.com/MyManDev/football-squad-optimizer/issues/1007#issuecomment-6045899361).

| Decision | Accepted rule |
| --- | --- |
| Defaults 1 to 5 | As proposed on #1007, with no amendment. Default 1 to Default 5 above state them. |
| GW6 timing | Accepted after GW6's first kickoff, 2026-10-10T11:30:00Z. GW6 cannot be a paired week; both records list it as missing, with that fact beside it. |
| First paired week | GW7. |
| Merge limit | Before 2026-10-17T11:30:00Z, and never during a weekly run. |

This note fixes only what the protocol left open. It is not an amendment of
the frozen protocol.

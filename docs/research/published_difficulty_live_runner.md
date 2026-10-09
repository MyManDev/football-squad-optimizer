# Published fixture difficulty live runner

This is #1009 part (b), step 2. Its sole statistical specification is the
protocol in [#1033](https://github.com/MyManDev/football-squad-optimizer/pull/1033).
Preparing synthetic code does not accept an unmerged protocol or authorize its
real reading. The executable verifies #1033's actual merged declaration, its
exact digest and clean committed ancestry before opening any real input.
An amended protocol requires corresponding reviewed runner changes.

The candidate reuses `apply_adjustment` and `_squad` from
`src/squadopt/experiments/opponent_projection.py`. Its coefficient values and
the development record's file hash after CRLF to LF normalization are fixed.
Nothing is fitted, and no archive
is an input. Both free-squad arms use the complete optimization configuration
frozen in the protocol. The original `_squad` return value is unchanged; an
optional diagnostic receiver records its actual solver result, full squad, XI
and captain without a second solve.

## Inputs and the one reading

The owner supplies the retained `fpl-live` snapshot root and weekly handoff root.
Inventory reads verified bootstrap and fixtures only, and excludes other season
capture names and future capture instants before opening their payloads. The
bootstrap's season is checked before an event-live payload is opened. No actual
inventory or outcome has been read while preparing this draft.

After the first capture showing GW20 finished and data checked with its actual
fixtures settled, invoke `python -m scripts.measure_published_difficulty_live`
with `--snapshot-root`, `--handoff-root`, `--as-of`, `--output-directory`,
`--owner-approved` and `--weekly-run-idle`. Every instant is
UTC. The output directory must be below this worktree's ignored `artifacts/`.
The executable derives its persistent private claim directory from the Git common
directory, shared by all worktrees; the operator cannot substitute another folder.
Before claiming, it validates every decision capture, paired handoff and projection
join input without opening an outcome. An absent handoff root or no valid paired
week refuses without creating the claim or output. After any outcome reading
begins, retain the claim after refusal or crash; the executable never removes it.
An existing committed verdict record also prevents a second reading.

No real-week comparison is produced before that settled-GW20 condition. The
first eligible settled capture is chosen by capture instant then snapshot id.
For each post-merge deadline through GW20, the latest capture targeting that
deadline supplies both arms. An equal latest instant is ambiguous and the week
is missing. An absent latest handoff never selects an earlier capture instead.
Pair exactly one stored handoff fingerprint; record its version, file hash and
pre-deadline write-time proof. The existing `handoff_fingerprint_for` pairing
function must agree with it. No backend process is needed.

Captured availability is applied once by production `project`, before the fixed
decision-week adjustment. The difficulty signal is minus the club's mean
captured fixture rating. A double averages both ratings without multiplying
the calendar again; a blank leaves the comparator unchanged. Later-week
projections are never adjusted.

Join outcomes by persistent player code, retain observed zero-minute rows and
drop absent players from both arms. Record every eligible week as scored or
missing. A failed solve removes the week from the joint gate. The three
readings use the same scored weeks with equal gameweek weights; squared error
is primary, and absolute error is diagnostic. The JSON includes pooled and
per-handoff-version readings, squad decisions, input identities, fixed
constants and the code commit. Full player evidence stays in private CSV files.

The command writes no committed result or measurements-index row. Those are
the separate step 3 PR after the single owner-approved reading. A passed
verdict still requires the owner's yes and the separate ship PR. This runner
adds no Friday operation, publication, promoted version or member-page text.

The draft still waits for the owner-acknowledged #1033 solver and pairing wording
to merge. Its existing digest pin remains unchanged and refuses an amended text.
Alias preference and the final served-capture selection must follow that accepted
protocol before an actual reading; no statistical method is guessed here.

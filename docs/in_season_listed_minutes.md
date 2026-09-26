# In-season minutes over the weeks a player was listed, on the GW6 capture

The record of a correction, not an experiment. Capture `fpl-live-20260922T214539Z-364991a4f832`,
season 2026-27, target gameweek 6, five played gameweeks. Produced by
`scripts/measure_listed_minutes.py`; the commit, both handoff fingerprints and the numbers below
are in `in_season_listed_minutes.json` beside this file, except the element ids and first-listed
weeks of the 57 players and their match with the `direct_control` set, which were read from the
same capture and handoff separately. It promotes nothing, and nothing was published: the
candidate handoff and both solved advice trees were written to a scratch directory only.

## What was wrong

The in-season blend (`in-season-carry-over-v1`) turns a player's season minutes into minutes
per gameweek by dividing by the gameweeks played, `target - 1`, the same number for every
player. A player registered in gameweek three was therefore charged two zero-minute weeks from
before he existed in the game. The component model sends any player missing from one of its
history payloads to the `direct_control` route, and that route's number is this blend, so the
players the component path was careful not to give invented zeros were priced with them anyway.
`phase_c_operational_component.md` states the rule for that route: missing is not converted to
zero. Found by audit M2 (2026-09-25).

## What changed

- The producer counts, for every player, the played gameweeks whose captured live document
  lists him, and the blend divides his season minutes by that count.
- A player listed in no played gameweek has no in-season record at all, rather than a record
  of zero; a player with season minutes who is listed in none is refused, because the counters
  and the live documents would then describe different seasons.
- A capture without every played week's live document keeps the calendar count, since it
  cannot say who was listed. The handoff diagnostics name the basis
  (`in_season_minutes_denominator`) and, on the listed basis, how many players were listed in
  fewer weeks or in none.

## Who it moves on this capture

- The roster has 667 players. **57** are listed in fewer than five of the played weeks'
  documents: element ids 611 to 667, all registered after the season began (16 first listed in
  gameweek 2, 28 in gameweek 3, 5 in gameweek 4, 8 in gameweek 5). None is listed in no week,
  and none drops out after his first listing.
- These 57 are exactly the 57 players the published handoff routes to `direct_control`: the
  players it states no appearance chance for.
- **28** of them have season minutes, and those 28 are the only players whose number moves.
  The other 29 have zero minutes, which is zero a week over any count.
- Every other player differs from the published handoff by at most `3.3e-14`, the noise of a
  rebuild; the handoff fingerprint keeps nine decimals. The appearance chances cover the same
  players and differ by at most `1.2e-14`.

Across the 28, the change is **+0.165** points on average, from **-0.013** to **+0.690**. The one
fall is Méthalie, whose 90 minutes returned -1 point, so more minutes a week at a negative rate.
The position rank is among every player of that position by expected points, highest first.

| Player | Club | Pos | Price | Weeks listed | Season minutes | Before | After | Change | Position rank |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| Ainsley Maitland-Niles | Everton | DEF | 4.5 | 3, from GW3 | 177 | 2.030 | 2.721 | +0.6901 | 71 to 37 of 217 |
| David Affengruber | Fulham | DEF | 4.5 | 3, from GW3 | 180 | 1.768 | 2.408 | +0.6400 | 76 to 57 of 217 |
| Quinten Timber | Crystal Palace | MID | 5.0 | 3, from GW3 | 253 | 1.644 | 2.224 | +0.5805 | 113 to 87 of 298 |
| José María Andrés Baixauli | Brighton | MID | 5.5 | 3, from GW3 | 109 | 1.863 | 2.324 | +0.4602 | 100 to 81 of 298 |
| Stephen Mfuni | Coventry City | DEF | 4.0 | 2, from GW4 | 90 | 1.198 | 1.648 | +0.4500 | 102 to 82 of 217 |
| Bradley Barcola | Liverpool | MID | 8.0 | 3, from GW3 | 168 | 2.014 | 2.371 | +0.3580 | 94 to 78 of 298 |
| Exequiel Palacios | Ipswich Town | MID | 5.0 | 4, from GW2 | 275 | 1.852 | 2.129 | +0.2775 | 101 to 92 of 298 |
| Matias Fernandez-Pardo | Newcastle | FWD | 6.0 | 3, from GW3 | 157 | 1.430 | 1.626 | +0.1961 | 33 to 28 of 79 |
| Sorba Thomas | Hull City | MID | 5.5 | 3, from GW3 | 119 | 1.388 | 1.551 | +0.1632 | 136 to 124 of 298 |
| Zian Flemming | Ipswich Town | FWD | 5.5 | 3, from GW3 | 60 | 1.566 | 1.711 | +0.1455 | 30 to 26 of 79 |
| Aaron Wan-Bissaka | Aston Villa | DEF | 4.5 | 4, from GW2 | 152 | 1.855 | 1.982 | +0.1272 | 74 to 74 of 217 |
| Ben Chilwell | Crystal Palace | DEF | 4.5 | 3, from GW3 | 29 | 0.774 | 0.896 | +0.1218 | 118 to 116 of 217 |
| Honest Ahanor | Crystal Palace | DEF | 4.5 | 3, from GW3 | 90 | 1.160 | 1.260 | +0.1000 | 107 to 101 of 217 |
| Mohamed-Ali Cho | Hull City | MID | 5.0 | 4, from GW2 | 72 | 1.561 | 1.656 | +0.0947 | 121 to 112 of 298 |
| Malick Fofana | Sunderland | MID | 5.5 | 3, from GW3 | 60 | 1.456 | 1.529 | +0.0727 | 130 to 125 of 298 |
| Hugo Larsson | Fulham | MID | 5.0 | 3, from GW3 | 37 | 1.389 | 1.437 | +0.0482 | 135 to 133 of 298 |
| Ibrahim Mbaye | Aston Villa | MID | 6.0 | 3, from GW3 | 33 | 1.644 | 1.673 | +0.0290 | 112 to 110 of 298 |
| Robinio Vaz | Hull City | FWD | 5.0 | 3, from GW3 | 20 | 1.421 | 1.440 | +0.0184 | 34 to 34 of 79 |
| Brooke Norton-Cuffy | Hull City | DEF | 4.0 | 3, from GW3 | 34 | 1.086 | 1.101 | +0.0149 | 110 to 110 of 217 |
| El Hadji Malick Diouf | Brentford | DEF | 4.5 | 4, from GW2 | 39 | 1.228 | 1.240 | +0.0126 | 100 to 102 of 217 |
| Mahdi Nicoll-Jazuli | Chelsea | MID | 4.5 | 1, from GW5 | 3 | 1.335 | 1.344 | +0.0088 | 148 to 147 of 298 |
| Melvin Bard | Leeds | DEF | 4.5 | 3, from GW3 | 18 | 1.276 | 1.284 | +0.0083 | 99 to 100 of 217 |
| Ayyoub Bouaddi | Man City | MID | 5.5 | 4, from GW2 | 22 | 1.553 | 1.560 | +0.0075 | 122 to 122 of 298 |
| Ryan McAidoo | Man City | MID | 4.5 | 4, from GW2 | 11 | 1.310 | 1.314 | +0.0039 | 151 to 151 of 298 |
| Darío Osorio | Crystal Palace | MID | 5.5 | 3, from GW3 | 1 | 1.641 | 1.642 | +0.0005 | 115 to 116 of 298 |
| Jean-Mattéo Bahoya | Leeds | MID | 5.0 | 3, from GW3 | 1 | 1.492 | 1.493 | +0.0005 | 128 to 130 of 298 |
| Kaden Braithwaite | Man City | DEF | 4.0 | 4, from GW2 | 1 | 1.194 | 1.194 | +0.0002 | 105 to 106 of 217 |
| Dayann Méthalie | Sunderland | DEF | 4.5 | 4, from GW2 | 90 | 0.960 | 0.948 | -0.0125 | 115 to 115 of 217 |

A rank can fall while the player's own number rises, because another corrected player passes
him.

## What it does to each position's order

No corrected player reaches the top 20 of any position, and every position's top 20 is in the
same order before and after. The best rank any corrected player reaches is 37 of 217 among
defenders (Maitland-Niles), 78 of 298 among midfielders (Barcola) and 26 of 79 among forwards
(Flemming). No goalkeeper moves.

## What it does to the advice members were told

Both handoffs were solved through the same league publication calls: the one-week plan and the
three- and five-week plans for every member, and every chip each member still holds. That is
15 members and 86 documents. The rival menu, the Top 100 menu, the manager's word and the
competitive modes were not solved. **The control solves reproduce all 86 published advice record
entries** (captain, vice-captain, moves, eleven, bench and chip), so the control is what members
were told, not an approximation of it.

| Document | Documents | Same decision |
| --- | ---: | ---: |
| One-week plan | 15 | 15 |
| Three-week plan | 15 | 15 |
| Five-week plan | 15 | 8 |
| Bench boost | 9 | 9 |
| Triple captain | 8 | 8 |
| Free hit | 13 | 5 |
| Wildcard | 11 | 5 |

- **Captain:** the same in all 86 documents.
- **Transfers:** the one-week and three-week plans give every member the same transfers, and
  so do the bench boost and triple captain plans. Twenty-one documents differ: 8 free hit,
  6 wildcard and 7 five-week plans.
- **In every one of the 21, at least one of the two solves is unproven** (`FEASIBLE`), and in
  none were both proved. The free hit and wildcard plans carry bound gaps of 4.1 to 5.3 points
  on both sides. **None of the 21 brings in any of the 28 corrected players.** Six documents
  change solver status, five of them proved only on the candidate side and one only on the
  control side.
- The expected points total moves in 10 documents, by at most 1.205. The largest is a
  five-week plan, unproven on both sides, whose total fell although every corrected number but
  one rose: that is where an unproven search stopped, not something the new numbers ask for.

Read together: the corrected numbers belong to players no plan picks. They move where the solver
stops on plans it could not prove within its deterministic budget, and they do not make a late
registration worth picking. The published free hit, wildcard and five-week plans on this capture
were already unproven, so a change to any player's number, picked or not, can move them; this
record shows that it did, and does not say which of the two unproven answers is better.

## Against the audit

Audit M2 reported a mean change of +0.160 and a maximum of +0.640 (Affengruber). This run moves
28 players, the audit's count, by +0.165 on average with a maximum of +0.690, which is
Maitland-Niles (2.030 to 2.721), a player the audit's list does not name. Affengruber, Timber,
Baixauli and Barcola move exactly as the audit states. Affengruber's rank goes from 76 to 57,
not 56, because Maitland-Niles also passes him.

## Whether a pre-registered gate was owed

No repository rule makes this correction wait for one. `production_prediction_spec.md` asks that a
further *candidate* be declared before it is measured and measured once, and
`prediction_ranking_gate.md` is the template for such candidates. This is not a candidate chosen
for accuracy: it enforces the rule `phase_c_operational_component.md` already states for this
route, and the producer's own comment called a recount "a model change that owes a measurement",
which this record is. It is descriptive. The audit's figures were read before the run, nothing
was declared in advance, and no threshold decided anything. Whether the corrected numbers are
closer to outcomes is not measured: gameweek 6 has not been played, and 28 low-projected players
over one week could not establish a direction.

## What it does not change

- The playing-time weight, `played / (played + 6)`, still counts calendar weeks for everyone, so
  three listed weeks earn the same weight as five. Whether it should use the player's own count
  is a model question outside this correction.
- The walk-forward runners (`scripts/measure_in_season_blend.py` and
  `experiments/opening_prior_exposure.py`) call the blend without listed counts and keep the
  calendar count, so no committed measurement moves.
- The model versions, the component model and every contract version are unchanged. The handoff
  fingerprint changes because the numbers do.

## Reproduce

```console
python -m scripts.measure_listed_minutes \
    --snapshot-id fpl-live-20260922T214539Z-364991a4f832 \
    --control-handoff data/handoffs/2026-27-gw06.json \
    --published-records data/advice_records \
    --development-only --workers 6 --work-dir <short scratch directory> \
    --output docs/in_season_listed_minutes.json
```

`--development-only` matches the published handoff, whose diagnostics record the development
training seasons for its fallback. The run took 33 minutes with six workers on the shared
development machine. As a separate check, `origin/develop` at `0f49ba8` rebuilt the published
handoff from the same capture with the same fingerprint, `223cd1ba...`.

The JSON names commit `f1ab1bab` with `working_tree_dirty: true`. What was dirty is this file,
the index row and one sentence in `phase_c_operational_component.md`, written while the run was
going; no file under `src/`, `scripts/` or `tests/` differed from that commit.

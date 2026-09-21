# Experimental football model in member advice

The default remains `current`. Choosing `football` uses the measured
`football_team_share_v1` goal, assist, clean-sheet, DEFCON and minutes model.
It is available in the member page only when a validated forecast exists for the
service's exact capture. Development gains are not independent prospective proof.

The model forecasts each scheduled fixture separately for up to five gameweeks;
blank weeks are zero and doubles sum fixture expectations. The existing transfer
planner can use 1, 3 or 5 weeks, subject to the remaining season. Top100 influence
uses the existing captured elite cohort and selectable weights, including zero.
It changes selection utility; it does not recalibrate the football forecasts.
The rejected role-transition and full-match clean-sheet extensions remain off.

## Produce and activate for a capture

Run from the deployed revision, with operator-selected paths:

```powershell
python scripts/build_football_forecast.py --snapshot-root data/snapshots `
  --snapshot-id <accepted-capture> --archive-root data/raw/vaastav-fpl `
  --artifact-root artifacts
```

Use the backend's configured artifact root if it differs. The producer reads only
the named immutable capture and recorded archive. It validates the complete roster
and horizon, writes atomically, and refuses to replace a different forecast for
the same capture. No training occurs in an API request and no scheduler is added.
Produce this artifact before accepting each new capture. The API discovers it
without restarting; a new capture without its own artifact disables the option.
Old captures' forecasts are never substituted. A missing or invalid artifact yields
`MODEL_INPUTS_UNAVAILABLE`; rollback is selecting `current`.

GET/POST member advice accepts `model=football` / `"model": "football"` alongside
`window` and `top100_weight`. Omission means `current`, retaining its existing
request identity. Jobs and cached results include the football fingerprint;
the response names its version, fingerprint and experimental status. The comparison
button computes the other model with the same member, capture and decision settings.
Its score is first-week expected points under each model, not measured performance.

## Evidence boundaries

- Historical features exclude the target gameweek and unsettled matches.
  Archive input hashes, capture fingerprint and training cutoff are retained.
- Captured event xG is weekly. A played double gameweek with ambiguous per-fixture
  history is refused, rather than splitting its xG or actions artificially. A
  fixture-level source is required before this producer supports that case.
- Current-season club attribution uses only unambiguous fixture explanations;
  missing observations are not filled with zero. Historic roster changes still
  limit current-roster attribution.
- Future availability is the captured state; prices stay fixed. Fixture minutes
  independence, the existing planner's transfer limits and solver status remain
  explicit limitations. This is not a calibrated injury model or full stochastic MDP.
- Compare realized outcomes on future untouched captures before changing the
  default or claiming a live accuracy improvement.

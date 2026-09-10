# Availability and late-capture measurements

Run with the existing Python environment and this checkout on `PYTHONPATH`.
Commands read verified captures and write research output outside the private archive.

```powershell
python -m squadopt.platform.capture_measurement --snapshot-root <capture-archive> --season 2026-27 --out artifacts/availability-calibration.json
python -m squadopt.platform.capture_measurement --snapshot-root <capture-archive> --season 2026-27 --early-snapshot <early-id> --late-snapshot <late-id> --gameweek 5 --out artifacts/late-capture-gw05.json
```

The second command is the optional audit after taking a second capture using the existing
capture command. Both captures must precede the same deadline, the second must be within
24 hours, and their timestamps must be strictly ordered. The table counts changes in
status, official availability, news text and news timestamp; additions/removals are separate.
It measures information changes, not a decision gain, and changes no decision.

Calibration pairs each capture with its next deadline's finished-and-checked event-live
outcome, using persistent player codes and the same season. Status, official 0/25/50/75/100
or unknown, and presence of a news timestamp define buckets. Each capture has its own
denominator, appearance count and research rate. Repeated captures remain separate and
are not independent player-weeks. A missing outcome is skipped with a reason.

Historical GW1–GW4 captures were deleted on 10 September and cannot be recovered.
Historical availability calibration is therefore unavailable. Accumulate new captures
and checked outcomes prospectively before reporting a finding. A committed measurement
record also requires its entry in `docs/measurements_index.md` under ADR 0003.

For the lost weeks, reconcile the committed GW1 publication and surviving GW4 member
advice with freshly collected public outcomes. This command writes outside the archive;
it never creates a historical ledger or backdates a capture:

```powershell
python -m squadopt.platform.recover_scoreboard --publication-root web/public --advice-root <surviving-advice-records> --capture-root artifacts/scoreboard_recovery/captures --out artifacts/scoreboard_recovery/scoreboard.json
```

Use `--snapshot-id <id>` to repeat this reconciliation offline. GW2–GW3 decisions stay
missing; GW4 advice is shown without realized values until its event is finished and
checked. Member picks retain the API's settled multipliers, points and minutes and must
reconcile to the API's gross score. They are separate from the advice a member received.

For the weekly scoreboard, pass `--evidence-root <phase-b-artifacts>` and, when held,
`--baseline-ledger-root <frozen-component-only-ledger>` to `scripts.build_scoreboard`.
The normal weekly publisher supplies its Phase B evidence root automatically.
See [the comparison contract](../contracts/scoreboard_comparisons_v1.md).

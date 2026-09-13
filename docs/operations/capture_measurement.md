# Availability and late-capture measurements

Run with the existing Python environment and this checkout on `PYTHONPATH`.
Commands read verified captures and write research output outside the private archive.
An output path inside the capture archive is refused; output is written atomically.

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

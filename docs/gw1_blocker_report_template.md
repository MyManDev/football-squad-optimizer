# GW1 Evidence Blocker Report — Template

## Purpose

Opening-gameweek (GW1) claims have their own evidence regime: only historical GW1
out-of-sample residuals support GW1 uncertainty or live-risk numbers, and GW2+
residuals cannot be converted into them. When that evidence cannot be produced, the
correct closeout is not a workaround but a structured record of **why**, filed against
the affected issues (#45, and the opening-gameweek limitations register). This template
is that record.

A completed report is an accepted deliverable. It keeps the live-risk state honestly at
`unavailable` (`unsupported_opening_gameweek` / `insufficient_history`) instead of
manufacturing numbers.

## How to use

Copy the template below into the issue or into
`docs/gw1_blocker_report_<season-range>.md`, fill every field, and link the evidence.
"Unknown" is a valid entry only with a note on what was checked. Do not delete fields.

---

## Report

```markdown
# GW1 Evidence Blocker Report

- Reported by:
- Date (UTC):
- Repository commit:
- Affected issues: #45, #...

## 1. Missing evidence

<!-- Name each artifact that cannot be produced, e.g. "historical GW1 out-of-sample
residuals under the current control identity for seasons X..Y". -->

## 2. Affected seasons

<!-- Per season: available / partially available / absent, with the concrete gap. -->

| Season | GW1 status | Gap |
| --- | --- | --- |
| 2021-22 | | |
| 2022-23 | | |
| 2023-24 | | |
| 2024-25 | | |
| 2025-26 | | |

## 3. Unavailable provenance

<!-- Which provenance fields the archive cannot supply for GW1: captured_at_utc,
deadline_timestamp_utc, availability snapshots, price timing, fixture deadlines.
State what was inspected to conclude this. -->

## 4. Why reconstruction would be leaky

<!-- For each tempting reconstruction, state the leak. Examples: rebuilding GW1
availability from post-hoc minutes reads the outcome; inferring prices from GW2
snapshots reads post-deadline state; the archive stores postponed fixtures under the
gameweek they were eventually played, so the pre-deadline calendar is unrecoverable. -->

## 5. Identity mismatch

<!-- Whether the current live availability post-processing identity
(captured_availability_rule_v1) can be matched by any historical GW1 data, and why
not if not. A mismatch alone forces status=unavailable via model_mismatch. -->

## 6. Earliest valid future evidence date

<!-- The first date real evidence can exist (for example: the 2026-27 GW1 deadline
capture plus realized GW1 outcomes), and what must be captured before then for the
evidence to be valid. Convert relative dates to absolute. -->

## 7. Required captures going forward

<!-- The concrete capture list that prevents this blocker from recurring:
pre-deadline snapshot with captured_at_utc, availability states, prices, fixture
deadlines; retention location. -->

## 8. Resulting system behavior

<!-- Confirm: live GW1 risk reports status=unavailable with the specific blockers;
no GW2+ residuals are relabeled; which issues stay open and on what condition. -->
```

---

## What this template must never be used for

- Justifying a silent fallback to GW2+ residuals for a GW1 target.
- Closing #45 without either real GW1 evidence or a completed report agreed by the
  three owners.
- Recording a reconstruction as "good enough" — if section 4 has an entry, the
  reconstruction is out.

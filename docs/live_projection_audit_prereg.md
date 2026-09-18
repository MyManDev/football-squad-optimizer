# Live projection audit: protocol

Status: pre-registered; no reading under this protocol has been taken. This document changes no
projection, gate or live control, and it promotes nothing.

It freezes what an audit of the live 2026-27 projection will read, before any number is read. It
is an instrument and not a test: it has no gate, and its first readings rest on very few
gameweeks. It exists so that the question "where is the projection wrong" is answered from the
same table every week, and so that one free yardstick stands beside it.

## What can be audited, as the disk stands on 2026-09-18

A gameweek is auditable when three things exist: a capture taken before its deadline, a
projection of ours made from that capture, and the realized points of that gameweek in a later
capture's `event-gwNN-live.json`.

| Gameweek | Pre-deadline capture | Our projection | FPL's `ep_next` | Realized |
| --- | --- | --- | --- | --- |
| 1 | gone (lost on 2026-09-10) | the ledger's `projections.csv`, opening carry-over model | none | yes |
| 2, 3 | none | none | none | yes |
| 4 | four, the closest 2.5 hours before | the handoff written before the deadline (`phase-c-component-elite-top100-v1`), and the control handoff written two days after it from the same capture | yes | yes |
| 5 | three, the closest 5 hours before | the control handoff of that capture | yes | not yet |

So the first full reading is gameweek 4 alone, gameweek 5 joins when it settles, and every later
gameweek joins the same way. Gameweek 1 is read for our projection only and is labelled as an
opening-week model with no yardstick. Gameweeks 2 and 3 are not read and the record says why.

## The three forecasts, made comparable

- **Ours, as decided:** the handoff's `expected_points` times the availability multiplier of the
  same capture, which is what `projections.csv` holds and what the solver read.
- **Ours, unconditional:** the handoff's `expected_points` before availability, so that the
  part of the error that is "did he play" can be separated from the rest.
- **FPL's `ep_next`**, from the `bootstrap-static` payload of the same capture. It is the game's
  own forecast for the next gameweek, already adjusted for availability, present for every
  player in every capture, and read nowhere in this repository until now. It is the yardstick
  because it costs nothing and was made with the same information at the same instant.

Players are joined on the FPL `code`. A projection written after the deadline from a
pre-deadline capture is labelled `replay` in every table and is never mixed with a live one.

## What will be read, per gameweek and pooled

For each forecast, over all players of the capture and over each position's top 40 by that
forecast (where the solver buys):

1. mean absolute error and bias (realized minus forecast);
2. Spearman rank agreement within position, and within position and price band (under 5.0,
   5.0 to 7.5, above 7.5), because the solver buys order inside a budget and not level;
3. the split of our error into **appearance** and **points given appearance**: the forecast
   points carried by players who did not appear, and the error over those who did, using the
   realized minutes (0, 1 to 59, 60 and above);
4. by position and by price band, the same error and bias;
5. the paired difference in absolute error, ours as decided minus `ep_next`, with the number of
   players and of gameweeks it rests on stated beside it.

## What will not be claimed

- No statement that one forecast is better than the other before six gameweeks are pooled. Until
  then the record states the differences and the count of gameweeks, and the sentence "this rests
  on N gameweeks" sits beside every pooled number.
- No interval on a single gameweek's difference: players inside one gameweek share fixtures, and
  an interval that ignores that would be too narrow. The pooled reading uses gameweeks as the
  unit once there are enough of them.
- Nothing here moves the projection. A finding becomes a candidate under its own protocol.
- Nothing here is member-facing.

## Reading dates

After every settled gameweek the record is regenerated from the captures on disk (no solver is
involved, so it is deterministic and cheap). Two pooled readings are fixed now: after gameweek 9
(six auditable gameweeks, 4 to 9) and after gameweek 15.

## The record

`docs/live_projection_audit.json` with its markdown twin and a row in `measurements_index.md`.
The record is regenerated, not appended by hand; each regeneration names the captures and
handoffs it read, by id and fingerprint, so that a changed number can be traced to a changed
input.

# What a later capture recovers

Contract: `capture_lead_time_v1`, classifier `news_keywords_v1`

Availability is applied once, from the capture the week was decided from. A note
the platform adds after that capture is not late -- it is absent, and no later
step recovers it. This counts what a capture taken at the later of two stored
instants held that the earlier one could not.

## Per gameweek

| gameweek | captures | earliest lead | latest lead | window | recovered |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2 | 189.3 h | 24.41 h | 164.9 h | 54 |
| 2 | 5 | 157.32 h | 75.91 h | 81.41 h | 18 |

A gameweek captured once has no window, so its recovered count is **not
measured** rather than zero. Those are different claims and only one of them is
true here.

## The split, and what it is

Buckets: `fitness_or_suspension`, `transfer`, `unclassified`.

A note is in a bucket because it matched `news_keywords_v1`'s
declared vocabulary, and the counts are counts of that match -- not a reading of
what the note meant. A note matching nothing stays `unclassified` and is reported
as its own number, because an item we could not classify is not a transfer. The
notes' words are not in this artifact; the player ids are, so any bucket can be
checked against the local capture.

## By bucket, per measured gameweek

| gameweek | fitness_or_suspension | transfer | unclassified |
| ---: | ---: | ---: | ---: |
| 1 | 31 | 19 | 4 |
| 2 | 16 | 0 | 2 |

## What this decides

Nothing on its own, and it licenses no claim about points. It is the evidence
behind the lead-time line in `docs/weekly_runbook.md`: a number for how much a
week's own decision could not see, measured on our own captures rather than
argued. The locked holdout was not read and no gate is evaluated here.

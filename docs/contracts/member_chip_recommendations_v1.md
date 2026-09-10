# Member chip recommendations v1

`chip_recommendations` is an optional field in `advice_read_v1.schema.json` and the
strategy publication allowlist. It accompanies the pure-points 1/3/5-week advice.
Legacy documents without this field remain readable. Each unspent chip window has a
row: play in a named week or hold, with a nullable expected-points difference against
the same member's no-chip plan over the same captured horizon. A window outside that
horizon is unpriced, not worth zero. Availability and last usable gameweek come from
the captured season rules, including the two independently expiring sets.

These are independent alternatives. They do not form a combined schedule and do not
change the existing no-chip weekly decision. Only one chip may be played in a week.
Each available chip window requires at most one additional solve; the no-chip control
is shared. Horizon solves reuse the deterministic work budget and wall-clock safety
stop. A stopped proof retains its status and gap; a wall-clock interruption is refused.

## Mathematics and policy

`member_planning_policy_v3` sets terminal FT value to 1.5 and discount to 0.84, as
initial owner-selected values on 10 September 2026. They are not measured improvements.
The previous hit-margin evidence remains specific to its measured v2 configuration.
The existing CP-SAT objective is reused:

`sum(k=0..H-1, 0.84^k * (XI + captain bonus + bench weight * bench - 8 * paid transfers))
 + 0.84^(H-1) * 1.5 * terminal free transfers`.

The transfer cap comes from the season rules (currently five). Bench weight is the
existing 0.1, or 1 for Bench Boost. Triple Captain adds the third captain copy. The
published price is instead the **undiscounted difference between the two found plans'
expected FPL points**, charging actual hits at 4 and including all Bench Boost bench
points. Terminal FT value and the planning margin are not reported as scored points.
The price is not a proof of optimal gain under a different objective. Both solver
statuses and their objective gaps accompany it. There is no terminal chip holding
value, future availability model or season-long timing claim.

## Boundaries and evidence

`live/chip_advice.py` owns the comparison using typed plans and captured rules, with
no file or network access. `application/chip_publication.py` serializes it using the
same lineup completion as ordinary advice. The record writer freezes that published
field with the advice digest. The web validator and bilingual card consume the versioned
contract. No probability claim is introduced.

Each played alternative freezes its chip-week lineup, captain, vice, ordered bench,
expected points and actual hit charge. A later scoreboard can score that alternative
from checked outcomes without optimizing again. Its realized **chip-week** points are
not a realized **whole-window** gain, nor evidence that the member followed it.

Start-aware bench selection remains dependent on the producer's fitted start model.
No start probability is fabricated while `START_TARGET_SUPPORTED_SEASONS` is empty.


## Failure boundaries

The application-level semantic validator is shared by publication, API reads and
recorded settlement. It rejects contradictory play/hold fields, missing or invalid
15-player lineups, captain metadata mismatches, overlapping chip windows, non-finite
prices and horizons that differ from the parent advice. The browser applies the same
relationships before rendering; legacy documents without the optional block still work.
A play row must carry its complete frozen decision. An invalid block fails validation
before the worker can cache its result; it is never silently converted into a hold.

Chip comparison also checks configuration and horizon identity, the returned chip
window, reconciled weekly hit charges and the no-chip control's solver stop reason.
A wall-clock-stopped control or alternative cannot produce a published price.

The existing one-week advice contract still retains a feasible incumbent with its
status and bound gap. If that control was clock-truncated, the optional chip block is
omitted before comparison; normal advice remains available and no chip price or hold
is invented. Multi-week advice retains its existing refusal of clock-truncated plans.

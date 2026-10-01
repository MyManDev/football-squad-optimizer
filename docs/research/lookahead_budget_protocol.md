# Certified lookahead: preregistered configured-budget comparison

This protocol is committed before the first real solve. One candidate, no tuning
or replacement cases. Engineering forecast utility is not future FPL accuracy.

## Source and information boundary

Use source guard 832084c2 and the exact #898 producer 8d510a03 in a separate study
branch. Owner producer files stay untouched. Capture
`fpl-live-20260922T214539Z-364991a4f832` differs from #904. Its reported 9.34/15.13
shortfalls cannot be reproduced numerically here.

The producer's default archive includes locked 2025-26. This shell restricts BOTH
archive loader and producer provenance hashing to 2022-23, 2023-24, 2024-25 before
any read. The first is prior-only; no 2025-26 paths are listed, hashed or read.
Captured 2026-27 weeks before GW6 remain causal training inputs. This therefore
fits a different forecast from the served artifact. Compare its first five weeks
against an independent five-week rebuild at 1e-10; quantify served differences,
but never require or claim served equivalence. Training/hash provenance is saved.

Supply the actual captured fixture calendar GW6..19. Frozen capture availability
and prices, no invented fixtures or future outcomes. Retain the public reader's
five-week contract; research adapts the longer in-memory horizon separately.
No contextual model, manager text, or new model fit options are compared.

## Cases and caps

Reuse recorded constructed squads from shortlist-matrix-20260928-01, unchanged:
profiles 1000 (bank0/FT1), 900 (bank0/FT0). They are not actual owner portfolios.
All methods use the full roster, same initial state, forecast, preferences and
price paths; fee0.5, discount1, bench0. Initial acquisition bases are unknown and
use supplied sales; purchases within the path preserve their acquisition bases.

Core order: profile1000 then900, decisionwindow3 then5, Top1000, no chips.
User display window remains3/5; all complete paths solve throughGW19.
Control first on even-index cases, candidate first on odd-index cases.

Both arms have total configured deterministic cap280:

- Control: unrestricted279 plus existing hold probe1.
- Candidate: sequential single-week seed28 total, window-then-tail seed84 total;
  certify/polish each full seed at10 each, choose highest actual scaled current
  objective, ties sequential first; final guarded full search148.

All calls use linearization2 and the same deterministic seed. Certification is
charged inside its enclosing call. Construction caps are divided by segment
length. Hold is not added to candidate calls. Save every solver phase, configured
and actual deterministic work, overshoot, statuses and wall times. A seed failure
invalidates that arm, with previous phase evidence retained. Nominal cap equality
is not equality of actual work. Primary OPTIMAL or deterministic-budget exhaustion
is required; unproved early/wall stops invalidate the engineering screen. Incomplete
tie-breaking before deterministic exhaustion also invalidates the screen. The
hold probe must likewise finish with proof or exhaust its recorded deterministic
cap; an unproved early hold stop is not ignored (tolerance1e-6 units).

Each call has a1800second primary/tie wall ceiling, divided by segment length for
construction. Certification has the existing30second ceiling. These are phase
ceilings, not total wall equality. Before a call reserve twice its wall ceiling
plus30seconds. Stop launching when this will not fit before the earlier of six
hours from study start and 1October05:00Z. Preserve incomplete/unrun cases.

## Fixed screen and conditional expansion

All four pairs must be legal with no certified scaled-objective regression;
at least one unrounded weighted forecast utility gain greater than0.1 and no
loss greater than0.1. Failed/incomplete pairs fail. Do not change the threshold,
case list, caps or candidate after seeing results. Preserve raw and weighted
window/tail scores, first action, roles, transfer/hit/bank/FT/chip paths and proof
bounds separately. A restricted certification never proves global optimality.

If core passes, reuse four0% cells, add eight profiles1000/900 x3/5 xTop10020/50,
then four profiles1000/900 x5w20 x(preferences, forcedFH). Preferences keep the
highest current raw-point held outfielder, no hits, save chips; available TC/BB
rights make save meaningful. FH is forced inGW6. Same screen over all16 required
for any subsequent default-off application integration. Top100 is user preference,
not evidence of predictive skill. If core fails/incomplete, no expansion and no
application integration. Report the failure rather than launch a replacement sweep.

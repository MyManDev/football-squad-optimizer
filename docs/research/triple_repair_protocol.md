# Three-week repair candidate, declared before measurement

The prior 16-case repair study is development evidence. Its five weighted losses have squad differences spanning 2-5 weeks; two zero-weight losses differ in GW8-10 with no hit difference. This motivates one prespecified wider neighborhood, not a parameter search.

Keep the same initial full-universe solve, held-plan guard, full-horizon budget/FT/chip/preference constraints and incumbent retention. Free each contiguous triple once in chronological order. On a 3-week horizon that is one full-horizon repair; on five weeks there are three overlapping triples. No adaptive restarts or extra learned bonuses.

Equal configured total caps with the previously defined control: initial 120 wall / 60 deterministic, repairs total 30*(H-1) wall / 15*(H-1) deterministic. Divide that repair budget by H-2 triples: H3 one 60/30 repair, H5 three 40/20 repairs. Unrestricted control is 120+30*(H-1) wall / 60+15*(H-1) deterministic. Same held-plan guard on initial/control, none on repairs. Solver tie phases can each receive the configured wall ceiling; report actual diagnostics and do not claim equal actual CPU use.

Use all 16 original cells and immutable source hashes: constructed budget profiles 1000/900, H3/H5, user-owned Top100 weights0/20/50, plus H5/20 no-hit+keep+save-chip and forced Free Hit for each profile. Compare a fresh equal-cap control and triple repair, alternate order. The pair-repair artifact is a historical diagnostic reference, not an identically timed rerun. The acquisition accounting fix remains disabled in both arms to avoid mixing factors; captured prices do not supply a newly validated future-price model.

Report all results including failures, raw forecast net points, Top100 utility, hits, exact transfer chains, accepted steps, actual wall/deterministic use and restricted/global proof limits. Engineering screen unchanged: 16 valid complete pairs, no incumbent regression, at least one utility gain>0.1 and no loss>0.1 vs control. No realized returns, calibrated probability, unseen holdout or live promotion claim can follow from this capture. No second wider-search candidate if this fails.

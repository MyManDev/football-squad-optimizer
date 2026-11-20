# One-week hard-rule comparison

The [machine-readable record](llmopt_phase4_rule_families.json) contains 140 paired solves across 20 frozen GW8 and GW9 member-weeks. The producing commit is `937e4609022de4d19d0581710ece877a66567469`. Each case uses the published Phase 1 points, prices, sale values, free transfers and effective bank, including both zero-bank controls.

| Rule | Cases | Same transfer decisions and score | Different decisions, tied score | Both infeasible | Mismatches | Different proof statuses | Alternatives checked |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Keep | 20 | 20 | 0 | 0 | 0 | 0 | 40 |
| Avoid | 20 | 20 | 0 | 0 | 0 | 0 | 40 |
| Buy | 20 | 20 | 0 | 0 | 0 | 0 | 40 |
| Club | 20 | 20 | 0 | 0 | 0 | 0 | 40 |
| Bank | 20 | 20 | 0 | 0 | 0 | 0 | 40 |
| Hit | 20 | 10 | 0 | 10 | 0 | 0 | 20 |
| Frozen | 20 | 20 | 0 | 0 | 0 | 0 | 0 |

## Inputs and scope

Every comparison uses a confirmed device-eligible one-week pure-points request, without a chip, news, rival, Top100 weight, or soft preferences. The frozen captures and the original controls remain intact. The new probes replace the original scenario restrictions with one named hard-rule family. They retain the tight-bank scenario's zero bank. Named-chip and original contradictory controls have separate historical evidence.

A cold, isolated in-process server API submits one run-bound job to the normal worker for each pair. The device selector dispatches the same eligible request to the installed WebAssembly solver, with the hard-rule alternatives option enabled and its normal cumulative worker ceiling. This compares the selected device main plan with the server main plan. Device alternatives are also checked against the submitted rules. This local replay measures predicted points.

Rules are fixed before either solver runs. The archived unconstrained plan supplies a departing player to keep, an arriving player to avoid, a different legal player to buy and a bank floor one tenth above its closing bank. GW8 club probes require an exact squad count. GW9 probes require an exact incoming count. The frozen-week probe pins the archive's transfers, XI, captain and chip. All archived unrestricted plans used zero hits. The maximum-hit probes therefore require one purchase beyond the captured free transfers, then allow one hit in GW8 and zero in GW9. Every specified set of purchases has a constructive budget- and club-legal exchange sequence before imposing that ceiling. Each feasible fixture has an independently checked transfer set, XI and captain in the record. Ten GW9 hit fixtures instead require more paid arrivals than their zero ceiling allows. Expected feasibility is checked even if both solvers agree.

The server receipt, actual optimizer settings and proof status are captured per request. Each CP call contributes its observed deterministic units to an independent sum checked against the receipt. Native calls and reservations are recorded separately. Independent verification rebuilds all squads from transfers, checks the XI and captain, club and position limits, bank after sales and purchases, the hit charge and each hard rule. The integer objective sums the frozen XI and captain coefficients and deducts hit points at the published scale. An equal score counts only when both reported values match this reconstruction. Transfer equality uses incoming and outgoing IDs. A different valid decision at the same score counts as a tie. Matching infeasibilities have no numeric objective. Every differing status or failed comparison is listed below.

## Exceptions

All recorded proof statuses matched. No comparison failed.

## Reproduction

Check out the producing commit and install its locked Python and web dependencies. Run from the repository root with the package on the Python path. Keep tests and CI outside the measurement window.

```sh
python -m docs.research.llmopt_phase4.rule_measure --check-inputs
python -m docs.research.llmopt_phase4.rule_measure --producer 937e4609022de4d19d0581710ece877a66567469 --resume
```

A fresh checkpoint lives under `.codex-tmp/`. Resume checks the producer, input digests, source fingerprints and ordered request prefix before starting another pair.

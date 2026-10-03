# Purchase basis in multiweek plans

The planner accepts a supplied sale-price path for each player. That path can
describe an original holding, but cannot describe every later purchase of the
same player. Applying it after a new purchase can overstate the bank and admit
an unaffordable plan.

For example, buy at 50, sell after the market rises to 53, then buy back at 53.
With no spare bank and a 50% profit fee the sale returns 51, so the last purchase
is impossible. A supplied sale price of 53 incorrectly makes it affordable.

`TransferPlanningConfig(acquisition_sell_on_fee=0.5)` enables explicit accounting
for purchases inside the horizon. For current price C, known purchase price P
and retained integer percentage R, sale proceeds are C when C <= P and
P + floor((C - P) * R / 100) otherwise. This uses the existing pricing contract.
The solver tracks the last permanent acquisition week and indexes its sale
value. Extraction independently replays purchases numerically and checks bank
and free-transfer continuity. All week tables have the same ordered player IDs.

Original holdings keep their supplied sale path until sold: an unknown purchase
price is never inferred from a discounted sale price. A subsequent repurchase
starts a new lot. Wildcard retains new lots; Free Hit restores the incoming lots,
squad and bank. The fee must be explicitly supplied for the applicable rules.

The default remains `None`, preserving the existing supplied-path contract and
recorded fingerprints. It is not an instruction to charge a zero fee. Enabling
accounting changes the configuration fingerprint and records the policy in result
diagnostics. The live multiweek adapter explicitly binds the captured season's
fee and rejects a conflicting supplied fee. The supplied old-holding path and
future market prices remain inputs, not price forecasts proved by this correction.

The older research-only `optimize_observed_recourse` retains a separate
compatibility convention: with `None`, it rebases the first action's new permanent
purchases at a 0.5 fee before solving the continuation with supplied sale paths.
Free Hit purchases are not carried forward. This does not provide full acquisition
tracking for later continuation purchases and is not the full-horizon `None`
contract. The member advice observation branch uses the full-horizon observed
planner; the live multiweek adapter supplies the captured fee. Historical research
results must retain their original convention.

Hand-accounted tests cover rising and falling prices, three and five weeks,
zero/full/half fees, original holdings, repurchases, Wildcard, Free Hit and a
false affordability counterexample. This establishes accounting correctness;
it does not establish higher realized FPL points or solve chip continuation value.

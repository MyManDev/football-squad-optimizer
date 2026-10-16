# Club-unit point projection

`project_unit_point` supplies a separately named deterministic XI construction.
It chooses one goalkeeper and ten outfield players from the complete supplied
club roster using the native starter probabilities. Its version is
`native_starter_constrained_map_point_v1`
(`src/squadopt/features/football_unit_point.py:21`,
`src/squadopt/features/football_unit_point.py:48`).

The construction defines an independent Bernoulli starter model and finds its
maximum-mass point subject to those two roster counts. Within a group of fixed
size, selecting the highest probabilities maximizes the product of selected
probabilities and unselected complements. Equal values use persistent player ID
order. This is an explicit modeling assumption, without a claim to have learned
dependence between teammates (`src/squadopt/features/football_unit_point.py:59`,
`src/squadopt/features/football_unit_point.py:90`).

Supply the full current club roster, exactly one starter probability per player
and the exact native artifact SHA256 before any owner-squad selection. The
function rejects duplicate, missing or extra identities and malformed hashes.
The caller must verify the source, decision time, full roster and actual hash;
the pure helper validates shape and performs no source acquisition
(`src/squadopt/features/football_unit_point.py:55`,
`src/squadopt/features/football_unit_point.py:63`).

Zero and one remain structural constraints. If fewer than eleven supported
players, no supported goalkeeper, or too many certain starters make the required
XI impossible, preparation refuses. No probability floor creates a possible XI
(`src/squadopt/features/football_unit_point.py:90`).

Retain `UnitPointReceipt` with the complete probabilities, roster, native basis
hash, policy and unnormalized independent log mass. The chosen XI can be the
single deterministic state that `UnitProjection` supports. Assigning unit mass
to that point describes a point forecast, not calibrated certainty about the
lineup. It does not preserve the input starter marginals or replace the focal
player minute law (`src/squadopt/features/football_unit_point.py:37`,
`src/squadopt/features/football_unit_inputs.py:818`,
`src/squadopt/prediction/football_unit_strength.py:965`).

Independent enumeration checks the selected maximum and its mass. Boundary
checks cover structural impossibility, exact roster coverage, ties and order
invariance (`tests/unit/test_football_unit_point.py:28`,
`tests/unit/test_football_unit_point.py:54`).

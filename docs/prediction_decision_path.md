# One player's forecast to the published bench

M3 of [#749](https://github.com/MyManDev/football-squad-optimizer/issues/749), source snapshot
`054baa56cff8a6390bb5738bca2e36a2141cd140` (20 September 2026). Line references are to that
commit. This traces a symbolic player `p`; it does not read a live queue, rerun a week or
invent a numerical player example. See the [ledger](prediction_inconsistency_ledger.md).

| Step | What happens to player `p` | Source |
| --- | --- | --- |
| Capture | Bootstrap supplies persistent player code, club, position, price and availability. The deadline is resolved against the capture instant. | `src/squadopt/live/recommendation.py:333–374` |
| Producer | Settled prior event history and the declared training population feed the component model. It estimates appearance `a(p)` and conditional points `c(p)`; the normal route composes points as `a(p) × c(p)`, with explicit direct-control fallback. | `src/squadopt/application/projection_handoff.py:182–240`; `src/squadopt/prediction/component_models.py:432–451` |
| **Wide table handoff** | `PredictionSnapshot`/component table can retain the recognized optional tier. `_component_table` returns player ID, points and supplied optional estimates. Empty/blank-only start estimates are not invented. This is an in-memory table, not the persisted live file. | `src/squadopt/prediction/integration.py:107–108,152–153`; `src/squadopt/application/projection_handoff.py:140–168,279–280` |
| **Scalar live handoff** | `build` narrows that table to `expected_points: Mapping[int, float]` and constructs `InSeasonProjection` under `projection_handoff_v1`. The identity includes model/capture/season/week and the rounded per-player scalar map, plus external evidence identity when supplied. Appearance/start have no separate persisted field. | `src/squadopt/application/projection_handoff.py:451–468`; `src/squadopt/live/recommendation.py:95–104,170–209` |
| Live decision pool | The consumer checks season/week/capture and full roster coverage, joins `p`'s scalar with captured metadata, then applies availability. It does not recover appearance from diagnostics. | `src/squadopt/live/recommendation.py:450–501` |
| In-season solve | The held squad, prices, budget, transfer rules and scalar projection determine transfers, XI and captain. The returned plan is checked before any optional risk report. | `src/squadopt/live/report.py:284–311`; `src/squadopt/planning/optimizer.py:697–708` |
| Member publication | The league path reads the same persisted handoff and builds its projection. `lineup_fields` completes the plan: vice by points, goalkeeper first, outfield bench by descending expected points with player-ID ties. `advice.py` includes those fields in the published payload. | `src/squadopt/application/league_publication.py:286–290`; `src/squadopt/application/lineup_publication.py:261–303`; `src/squadopt/application/advice.py:619,689–692` |
| Retention | Current member advice records retain the published scoring-complete lineup. The system ledger separately records both raw bench IDs and the completed autosub order; these are not interchangeable lists. | `src/squadopt/application/advice_record.py:13–26`; `src/squadopt/live/ledger.py:343–347` |

**Which handoff decided GW04 and GW05?** The persisted scalar `InSeasonProjection` is the
operational boundary for both, not the intermediate wide table. Existing committed evidence
says GW04's deciding handoff had the Top-100 uplift; its base-only control is a later replay.
GW05's deciding handoff was component-only (`docs/top100_effect_prereg.md:20–23,35–41`).
The GW04 audit's base table is explicitly marked replay (`docs/live_projection_audit.md:38`).
These are statements from retained documentation, not new verification of runtime files.

**Can the probabilities reach today's solver?** In this pinned tree, appearance influences
the scalar through composition, but its separate column stops at
`application/projection_handoff.py:451–468`; `live/recommendation.py:484–485` reconstructs
only points. The generic table contract can carry appearance and start
(`contracts/players.py:55`), which does not make either survive that live-file seam.
Start is additionally not estimated by the operational component model
(`prediction/component_models.py:441–442`); the separate fitted participation model is a
research caller, not a live promotion. Thus neither probability reaches the operational
solver as an independent value on this path. The member bench still uses unconditional
points. #748 may change transport after review; it is not assumed merged or deployed here.

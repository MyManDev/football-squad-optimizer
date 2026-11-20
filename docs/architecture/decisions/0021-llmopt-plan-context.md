# ADR 0021: Content identities for computed plans

- Status: proposed
- Date: 2026-11-19
- Decider: project owner
- Related: ADR 0020; PR #1468

## Decision

Identify a displayed plan by SHA-256 of its canonical computed content and data
identity. Include every planned week's transfers, chip, lineup, captain, bench
order, points and carried resources. Sort unordered player and transfer lists;
preserve bench order. Exclude elapsed time, proof metadata, translated labels,
request/run identifiers and player names. Identical computed content under the
same data identity keeps its identifier across reload and recomputation.

The server data identity hashes the existing immutable advice context.
An enabled worker records provenance separately from the immutable answer. The receipt
binds each plan's data identifier to the answer address and exact bytes.
The connected and public entry APIs expose `plan_data_id` only when enabled and
the worker supplied provenance. Both settings store the original ordinary answer bytes
under the existing key. On rollback a warm read returns the ordinary answer. Opening
the setting leaves a previously unversioned warm answer unversioned. Device
plans use their checked input-table/member fingerprint. An unversioned legacy
answer may be displayed but is not offered as a conversational plan reference.
The project owner approved this treatment of legacy results.
An ordinary rule or clarification can use the catalogue without reading
capabilities or hashing device inputs. When applying a checked plan command,
the browser reads the current grant once and, for a device result, hashes
the current inputs once. A selected plan requires the current capture. The check
route returns HTTP 422 `PLAN_DATA_CHANGED` for a server plan command whose
data identity is superseded, so the member can recalculate. For a device
plan the browser checks the same input snapshot and current local catalogue
when applying the answer. An invalid reply preserves both the existing
refusal and the earlier clarification. If the prompt route rejects a
catalogue and a fresh matching grant confirms rollback, repeat only the
prompt without the catalogue before making the single provider call.

The browser sends ordered content identities and decisions to the existing
prompt and check routes. The provider sees each plan's weeks and a short
label in catalogue order (`P1`, `P2`, and so on). It also sees the label
of the selected plan. It can return only a presented label and action fields.
The check route resolves the label against that request and validates the
action on the full plan. The browser maps the checked label to the full
identity in the exact catalogue sent. Before applying a reply, it verifies
that the same label still denotes the same content under the same current
data identity. Reordering a catalogue cannot reinterpret an in-flight answer.
Sessions and navigation continue to use the complete SHA-256 identities.
Keep the existing draft translation contract for ordinary instructions.
Every provider-schema branch has an explicit type. Reject unknown plan-command
fields. Ordinary draft replies retain legacy null-extra handling.
Without a plan catalogue, clarification questions retain their previous behavior,
including numbers. With a catalogue, preserve questions about rule inputs,
weeks and plan labels in both languages, including their numbers. Replace a
numerical claim about a computed plan's outcomes with the neutral question.

Retain at most twelve checked, explicitly whitelisted computed plans in the
existing safe session. Selecting, undoing and returning to a retained plan
starts no solve. Freeze commands derive exact transfers and weeks from that
plan; substitutions create the existing comparison request and use its computed
differences. Reuse unaffected results and preserve the shared run admission
limit. Old data is removed from the conversational catalogue, not relabelled as
current. No credential enters the catalogue, identity, history or storage.

The existing comparison table remains available in both modes. Only a current grant
adds the total transfer penalty and the weekly net points, penalty, budget and free
transfers to revision and scenario comparisons. The closed check endpoint rejects
any top-level `plan_command` property, including null.

A substitution fixes both the old player's exclusion and the replacement's
inclusion in the new main calculation. Retain the selected computed reference
with an internal `compareOnly` marker: automatic roll/bank menus are disabled
for that calculation. The table compares the existing reference directly with
the requested replacement, rather than another unconstrained intermediate plan.

## Validation

Test content stability and sensitivity, unknown/stale identifiers, strict schemas,
numeric-output refusal, full-window comparison arithmetic, and retained-plan
navigation through reload and undo. Run desktop/mobile English/Turkish browser
flows with intercepted provider calls and no live service measurements.

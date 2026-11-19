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

The server data identity hashes the existing immutable advice context, without
changing its cache key. Carry it on computed advice and capabilities. Device
plans use their checked input-table/member fingerprint. An unversioned legacy
answer may be displayed but is not offered as a conversational plan reference.
The browser rechecks the current input identity before sending a plan command.
The check route refuses a plan outside the supplied current catalogue, a plan
with another data identity, and a server identity superseded by the current
advice context when that context is available. Late replies are also checked
against the page's current catalogue before applying them.

Only prompt and check carry the plan catalogue to the member's provider. The
catalogue contains identifiers and decisions, never point/resource outcomes.
The provider selects a plan identifier and an action/rule; it cannot supply a
computed result. Keep the existing draft translation contract for ordinary
instructions. Every new provider-schema field has an explicit type. Reject
unknown fields. Replace a clarification containing numerical claims with a
fixed short question, so provider text cannot introduce displayed figures.

Retain at most twelve checked, explicitly whitelisted computed plans in the
existing safe session. Selecting, undoing and returning to a retained plan
starts no solve. Freeze commands derive exact transfers and weeks from that
plan; substitutions create the existing comparison request and use its computed
differences. Reuse unaffected results and preserve the shared run admission
limit. Old data is removed from the conversational catalogue, not relabelled as
current. No credential enters the catalogue, identity, history or storage.

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

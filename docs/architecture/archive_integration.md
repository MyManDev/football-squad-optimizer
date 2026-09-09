# Archived fixes integrated into the published baseline

This records the R01 comparison on 2026-09-09 against the enterprise branch's starting
commit `4ce5702db16759e7af89ea12c394e0edcd891f33`. The archive pointer is
`fe3fe34c` (`archive/pre-main-alignment-20260909`). The archive as a whole was neither
merged nor cherry-picked. Only the missing behavior identified below was applied to
the current files, preserving the later member-facing UI and the concurrent platform work.

## Evidence matrix

| Archived correction | State in the starting baseline | Integration decision and verification |
| --- | --- | --- |
| #440 member-supplied names: local `1254fa5a`, remote `c8d61eba` | Standings names and registry labels passed directly into public member, entry and rival views. | Restore the shared text rule and publisher normalization, 64-character bound, entry-ID stand-in for refused text, and per-member report notes. The builder test sends markup, controls, bidi overrides, overlong names and prohibited claim text through the actual output path. |
| #440 missing optimality bounds: local `a27c6512`, remote `4f717ac5` | Already implemented by the later publication-state work. `LeagueMemberPage.tsx` uses `finiteNumber` for both plan and control gaps and displays localized missing-bound text. | Do not reapply the older UI patch. Existing `LeagueMemberPage.errors.test.tsx` cases preserve unknown values and genuine zero separately in both languages. |
| #440 pure-points description: local `acf63395`, remote `2529cdd3` | The catalogue and member strategy card still claimed the highest expected points. | Restore the catalogue and TR/EN member-card correction plus regression tests. The displayed XI/captain projection is not the complete optimization objective, which also includes weighted bench value and transfer penalties. No objective, projection, solver parameter or price calculation changes. |
| #442 same-capture replay: local `543beda1`, remote `15ee7650` | A later publication clock changed the envelope digest and caused an otherwise identical advice record to conflict. | Ignore only the root `generated_at_utc` and each advice document's `published_sha256` when comparing replays. Preserve and compare payload digests, state, provenance, selected document, document count and any newly added fields. Keep the first record unchanged. A changed payload or other material field still conflicts. Builder, persistence and CLI tests cover the restored behavior. |
| #445 quote location: `a85c7bdd`, including the earlier `eed2d127` coding instrument | `club_news_coding.py` and `club_news_anthropic.py` are absent. The existing `club_news_claims.py` accepts and validates already located byte spans. | Leave quote-to-span integration to the coding-instrument work owned by the data lane. No adapter or model call is copied or enabled here. See the dependency below. |

The four local/remote correction pairs have equal stable patch IDs, including every
commit in #440's three-commit topic. Their different tip hashes are rebases, not evidence
of an additional unpublished behavior. Unrelated changes inherited from their different
bases were not transferred. The two aggregate trees differ substantially, so comparing or
copying whole tip trees would have reverted later work.

The name filtering change was adapted to the baseline's existing imports and builder
layout. The strategy-control regression was inserted into the later test suite without
restoring its old surrounding copy. The null-bound patch was omitted entirely. The
restored public-name policy is deliberately the archived one; it does not claim to be a
general-purpose HTML sanitizer for arbitrary consumers or a validation rule for other
unrelated free-text contracts.

## Replay evidence semantics

A replay leaves both the record and its manifest untouched. The retained
`published_sha256` therefore describes the first publication's envelope bytes; it does
not describe the later file whose generation clock changed. The retained
`advice_sha256` still identifies the unchanged canonical payload. The generation clock
on public files is not redefined as the capture instant, and historical records and public
documents are not rewritten.

Only the two named clock-derived fields are masked. Missing fields remain missing;
unknown fields are compared by default. The conflict message uses the same comparison,
so clock-only differences do not hide an actual state or payload disagreement.

## Quote integration dependency

The archived `locate_quote` helper in `club_news_coding.py:336` is pure and is intended to
locate a unique exact UTF-8 quote without the Anthropic SDK. Its overlapping-match defect
is recorded below. The SDK is not a technical
prerequisite for that helper. However, the current baseline has no quote-producing
coding caller to consume it. Copying the helper alone would create an unused second
contract; changing the existing bound-offset parser to accept quotes would change a
different established contract.

The remote delivery was rechecked at 2026-09-09 21:01 UTC with `git ls-remote`; no ref was
changed. `feat/club-news-model-call` remains at `e6c3b40b9cdeec535c58a2616ef67a22a650002c`
and `feat/per-club-model-provenance` at `40584600b4f1337f94279140d7c7ce49d10359dc`.
The coding/SDK modules and per-club provenance are delivered source, but are not integrated
into this transition. Both the remote exporter and current installed exporter still use a
fixture provider. The delivery does not demonstrate production document/club association,
durable raw-document/model-response capture, or offline replay from that capture.

Before integration, fix the locator's use of `content.count(needle)` at line 352: Python
counts non-overlapping occurrences, so `b'aaa'.count(b'aa') == 1` despite valid starts at
0 and 1. A unique-match claim must reject this ambiguity. The current offset parser is
unchanged; this finding concerns the delivered quote-conversion helper. Adapt the topic's
old script exporter to `application.rotation_export` when integrating, preserving the
frozen coding contract, requested/served model identity and club-to-response provenance.
Existing in-memory synthetic replay tests do not establish a persisted real capture.

Integrate the quote response schema, frozen coding prompt, unique-match conversion,
unlocatable-response rejection and offline tests together with the data lane's coding
instrument. Keep network/model activation a separate explicit decision. R01 neither
duplicates that package nor edits any active data-lane branch.

## Focused verification

- Before the implementation, the new clock-only replay and catalogue-superlative
  regressions both failed for the expected behavior: **2 failed in 2.64 s**.
- After implementation, `test_advice_record.py`, `test_strategy_catalog.py`,
  `test_public_probability_guards.py`, `test_league_views.py` and
  `test_build_league_site.py` passed: **71 passed in 64.03 s**.
- Strict mypy passed for `advice_record.py`, `league_views.py` and `strategies/catalog.py`.
  Ruff lint and formatting checks cover all eight changed Python files.
- The two focused web files produced **77 passed and 2 failed**. All 19 strategy-control
  tests passed, including the new TR/EN claim regression. Both failures are existing
  retry assertions expecting four `loadEntryAdvice` arguments while the concurrent
  request-cancellation change supplies a fifth `{ signal }` argument. This R01 patch
  does not alter that test or request API; the integration owner must update those
  expectations and verify the combined web change.
- The first web invocation stopped before collecting tests because Windows sandbox
  process creation returned `EPERM`. The recorded result above is the elevated run;
  both logs are retained.

Full-suite integration gates remain the responsibility of the combined enterprise
change. This focused verification neither publishes data nor claims that the entire
shared working tree was frozen. Exact commands, exit codes, comparison patch IDs and
logs are retained locally under `.pt/enterprise/archive-integration/`.

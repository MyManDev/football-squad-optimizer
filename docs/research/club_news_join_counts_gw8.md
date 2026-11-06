# Club-news join counts: GW8

Recorded on 5 November 2026 from the saved Friday decision run
`2026-27-gw08-friday-20261023T1058Z`, under the
[frozen protocol](club_news_join_counts_gw8_prereg.md). The
[JSON record](club_news_join_counts_gw8.json) is the reporter's unedited output.
This was an offline replay: no new source request or model call.

## Inputs and replay

- News capture: `club-news-20261023T110354Z-dd37130a1a4a`.
- Decision capture: `fpl-live-20261023T111647Z-a2cd55fde426`.
- Acquisition receipt: `2026-27-gw08-friday-20261023T1058Z.club-news.log`.
- Rotation table: `rotation_evidence_v4_2026-27_gw08_dd37130a1a4a_decision_a2cd55fde426.csv`.
- Clean export/reporter commit: `f69e68a8fb4e67cfedac369ba50ae40b3b142104`.
- Replayed table SHA-256: `bae4ff02e761c3f6e5a7b1e34de2201e0f768ecf76a39ff7782f6d7915f037b1`.

The reporter ran in a clean checkout of the export commit, with its `src` and repository
root on `PYTHONPATH`, using the held stores outside that checkout:

```text
python -m scripts.report_club_news_join_counts
  --club-news-log <store>/data/logs/weekly/2026-27-gw08-friday-20261023T1058Z.club-news.log
  --rotation-table <store>/artifacts/rotation/rotation_evidence_v4_2026-27_gw08_dd37130a1a4a_decision_a2cd55fde426.csv
  --snapshot-root <store>/data/snapshots
  --output <new-output-path>
```

The news capture precedes the decision capture; the source kind is `capture`. All reporter
checks pass, including byte-for-byte replay against the published table and the manifest.

## Counts and verdict

| Count | Result |
| --- | ---: |
| Real hosts asked / answered | 3 / 3 |
| Retained documents / verified publication | 33 / 30 |
| Provider calls attempted / failed | 3 / 0 |
| Raw claims / unique player joins | 5 / 5 |
| No-match / ambiguous player identities | 0 / 0 |
| Claims placed / unverifiable citations | 5 / 0 |
| Reader statements / unresolved words | 5 / 0 |
| Absence or doubt statements / constraining statements | 3 / 0 |
| Lost before table / lost unapplied | 0 / 3 |
| Lost unapplied: unverified publication | 0 |
| Lost unapplied: unverified fixture scope | 3 |

Crystal Palace, Liverpool and Newcastle each contributed eleven documents. The registered
placeholder is not a real host or a covered club. The three unapplied statements have
unverified fixture scope: two `ambiguous`, one `unspecified`. These are not ambiguous player
identities. There are no failed calls, unreadable claims lists, unresolved source citations,
publication precision failures or publication-after-fetch failures in this record.

The frozen verdict is **`statements_lost`**, with route **`route_items_3_7_4_10`**. Under the
protocol, #1006 remains open and items 3, 7, 4 and 10 proceed. No threshold, definition or
count was changed after reading the capture.

The real scheduled capture, located citations and required identity counts complete #524's
seam. The owner authorized completing and closing verified work on 5 November. This record
does not establish predictive benefit, a current absence, or #1140's live acceptance.

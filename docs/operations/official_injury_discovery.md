# Official injury discovery and current club-news selection

## Production status: central source disabled

The official league injury source is **disabled for production**. The
[Premier League terms and conditions](https://www.premierleague.com/en/terms-and-conditions)
were checked on 2026-10-02. They restrict reuse, database extraction,
redistribution and deep links without written approval. The repository owner
confirmed that no redistribution permission is held. The website robots allowed
the page; the API robots could not be verified in that review. Neither a robots
allowance nor a recent terms-reading date grants the missing rights.

The optional parser, capture adapter, bundle binding and UI remain prepared and
covered by synthetic tests. No real central capture or public activation was
performed. Release-shaped fixtures and current publication omit this source.
Do not run the central capture command or pass central artifacts into publication
without the required permission and a separate activation decision. The existing
FPL feed and the independently registered club sources remain separate paths.

The club-news acquisition does not depend on it. In a rehearsed run of
`python -m scripts.capture_club_news` without `--official-injury-capture`, every request
goes to a registered club host (`test_club_news_acquisition_report.py`, which also asserts
the capability constant is off). The same command given that option refuses before it reads
any input (`test_club_news_acquire.py`).

## Prepared optional capability

The official [league injury page](https://www.premierleague.com/en/latest-player-injuries)
was inspected on 2026-10-02. Its HTML declares an `injury-news/injury-news` widget;
the club rows are in the widget's detailed official playlist response, not in HTML
tables. That response currently embeds the club playlists and their injury rows.
The parser reads the page-declared numeric playlist identifier. It does not pin an
article identifier, execute JavaScript, crawl other sites, or assume that twenty
sections means twenty clubs have verified coach news.

The prepared command, currently disabled operationally, would capture these facts
separately from club-owned statements:

```text
python -m scripts.capture_official_injuries --snapshot-root <captures> --roster-snapshot <held-roster> --capture-root <new-captures> --terms-read-on <YYYY-MM-DD>
```

Written permission and a current terms reading for both official hosts are required
before any activation. A date supplied to the command alone does not satisfy the
permission requirement. The prepared collector checks
robots for each host, then requests the fixed official page and its declared
playlist. It makes at most four requests, has no redirects or automatic retries,
and limits each response to two MiB. It permits at most twenty club sections and
two hundred player rows. The ordinary immutable snapshot writer retains the raw
page, playlist, roster bytes and reproducible report. No provider is called.

Club titles match the captured roster exactly or through an explicit publisher
label mapping. Unknown clubs remain named as unknown. Players match exact captured
full or short names within that club; ambiguous and unmatched names stay unmapped.
The widget's SDP identifiers are not silently treated as FPL identifiers. Each row
retains the playlist digest, JSON pointer and exact byte span. Its source `date`,
`publishFrom` and `lastModified` remain distinct from the page's printed update and
the capture time. An empty club section states that no injury rows were listed;
it does not certify squad health, complete reporting or a probability of playing.

If permission is obtained, the optional integration can use a held central capture
to help the existing club reader find relevant articles. This route is not active:

```text
python -m scripts.capture_club_news --settings-file <private-settings> --snapshot-root <captures> --roster-snapshot <held-roster> --capture-root <new-captures> --club Liverpool --max-model-calls 1 --official-injury-capture <exact-central-capture-directory>
```

Only Details links for the exact selected club, on its already registered origin
and below its registered news path, are eligible. Other club hosts are not fetched
merely because the league links to them. The existing robots, terms, ten-article
host budget, source timestamp and claim validation rules remain in force. Central
injury descriptions themselves neither authorize an absence nor change minutes.

Before coding, explicit women's, youth, commercial, international-roundup and
match-report pages are withheld. A selected article takes precedence over its
index; unknown article content remains eligible, without acquiring verified match
scope. Verified publication instants must fall in the current seven-day window;
unknown dates are not filled in from fetch time. Selection has a versioned reuse
identity. The operator reports documents received, documents selected, clubs coded
and raw response claim count separately. Raw claims still require source validation
at export. A successful zero-claim response remains a successful zero-claim response.

New rotation artifacts can name both the news and decision captures. Legacy names
remain readable. One news capture reused for two decisions in the same gameweek
therefore cannot overwrite the first decision's evidence. Publishing these files
alone does not activate a new live decision bundle.

## Seal a prepared decision bundle

After the existing producers have written an immutable decision capture, retained
projection handoff, football forecast and fixture companion, exact news/rotation
pair, and generated public-data tree, the offline seal command validates those
inputs together:

```text
python -m scripts.prepare_football_bundle --snapshot-root <captures> --snapshot-id <decision> --artifact-root <artifacts> --handoff <exact-handoff> --site-data-root <public-data> --news-capture-id <exact-news> --rotation-table <exact-rotation.csv>
```

News and its rotation table are optional together. A successful empty news response
is accepted with its exact capture binding. Production sealing must omit the optional
central injury capture while permission is absent. Its synthetic binding tests require
that source to predate the decision and identify the same roster; editorial text never
becomes a coded coach statement merely by appearing in a bundle.

The seal checks the existing site members and every human entry against the exact
capture, season and gameweek. It retains their original bytes, the exact handoff,
and any rotation pair under `football/<decision>.bundle/`. Forecast and companion
remain their existing siblings. Every file is addressed by a relative filename and
its byte digest, and the source captures retain their original fingerprints.

The ready marker `football/<decision>.bundle.json` is written last with the existing
create-once writer. An interrupted operation may leave copies, but no incomplete
bundle becomes ready. An identical rerun can finish or replay; conflicting bytes
cannot replace a previous ready marker. The reader checks all digests and production
source contracts again. This command performs no acquisition, fitting, site build,
or runtime activation. Activation must separately select this validated bundle.

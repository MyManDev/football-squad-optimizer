# Data sources

This directory holds **metadata about external data, never the data itself.**

## Why the data is not committed

The historical archive we read, [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League),
licenses its *code* under MIT but does not own the data: its author states the data
is the property of fantasy.premierleague.com and understat.com.

Premier League terms permit downloading material "for your own private and personal
use" but state the site "must not be used in any other way, including for commercial
purposes", and that you "may not otherwise reproduce, re-utilise or redistribute it
(including, by way of example, creating a database … that includes material
downloaded … from the Website or App)" without prior written approval. Copyright and
database rights are reserved.

Reading the data locally for research sits in the private-use lane. Committing it to
a public repository would be redistribution. So it stays out, in git-ignored
`data/raw/`, and only the metadata needed to reproduce an identical download lives
here.

## How everyone still works from the same bytes

Not committing the data would normally make team results incomparable. Three things
prevent that:

1. **A pinned commit.** The archive is still updated — it already carries a `2026-27`
   directory. Two people fetching a week apart from `master` would hold different
   data and their benchmark numbers would not mean the same thing. Every fetch is
   tied to one commit SHA, recorded in `vaastav_fpl_manifest.json`.
2. **Checksums.** The manifest records a SHA-256 per file, so "do we have the same
   data?" is a verified fact rather than an assumption. The experiment contract
   requires compared configurations to share identical data snapshots; this is the
   proof.
3. **Loud failure.** A mismatch or a missing file stops the run instead of quietly
   producing numbers from different inputs.

```bash
python -m scripts.fetch_historical_data            # download, then verify
python -m scripts.fetch_historical_data --verify   # verify what is already local
```

Re-pinning to a newer archive commit changes the data every prior benchmark was
measured on, so it is deliberate: update `ARCHIVE_COMMIT` in
`squadopt/data/sources/vaastav.py`, then re-run with `--write-manifest`. The script
refuses to proceed silently when code and manifest disagree.

## The test suite does not need any of this

Every test is synthetic and offline, including the tests for this adapter — they
build a miniature archive on a temporary path. Real data is needed only for
calibration and benchmark runs, so CI stays independent of it.

## Files

| File | Contents |
| --- | --- |
| `vaastav_fpl_manifest.json` | Pinned commit and per-file SHA-256 for the archive files this project reads |

See [the data pipeline](../../docs/data_pipeline.md) for what happens to the data
after it is fetched, and [the data dictionary](../../docs/data_dictionary.md) for the
per-column semantics — including the two source-specific corrections this archive
needs.

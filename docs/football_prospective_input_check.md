# Outcome-free prospective input check

The existing football prospective protocol remains unchanged: football v1 versus
the current served handoff, with interim reading after GW20 and final after GW38.
The sequential-minute candidate is not added to it. No future results are read.

`scripts/check_football_prospective_inputs.py` checks an explicitly named offline
snapshot inventory. Supply snapshot, handoff and football artifact roots, season,
an aware `--as-of` instant, repeated `--snapshot-id` and `--gameweek` arguments.
It prints JSON to stdout and writes nothing, fits nothing and starts no service.

The operator must supply the complete relevant inventory. For each requested week
the checker selects the newest capture whose own target is that week, through the
same input reader as the backend. A missing/corrupt forecast at that capture never
borrows an older forecast. Tied capture instants are ambiguous. Football v1 must
pass the production reader, match the full roster and have a local write time
before the deadline. The current arm uses the backend handoff identity and live
projector, including the same availability adjustment. Both fingerprints and the
current model version are reported. No public report contains local paths.

`inputs_ready` is not a score or promotion verdict. Capture selection remains
provisional before the deadline. Local write time is a useful rejection check,
not independent proof of when a forecast existed. Keep the existing publication
and capture provenance for the eventual reading. This checker cannot prove that
the operator supplied every capture or that a forecast producer never changed
under the same version. Those checks remain in the frozen protocol's review.

Synthetic tests exercise the actual capture, football and handoff readers,
previous-week refusal, missing/late/corrupt newest artifacts, no fallback and
future-inventory refusal. No current or future outcome store is needed. The
full scoring runner described by the protocol is still due before GW20; this
change implements only the permitted between-reading input check.

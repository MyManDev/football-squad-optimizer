# Export Precision

- Contract: `export_precision_v1`
- Column: `predicted_points`
- Population: 101,447 rows, 58,855 non-zero

Rows whose written value changes when the underlying number is perturbed by the given relative amount. Zero means two machines write the same *values*. Writing the same *bytes* additionally needs the same line terminator — see "The half this measurement did not cover" below.

| Relative perturbation | unrounded | 12 dp | 9 dp | 6 dp |
| ---: | ---: | ---: | ---: | ---: |
| 1e-16 | 52,410 | 30 | 0 | 0 |
| 1e-15 | 58,855 | 240 | 0 | 0 |
| 1e-14 | 58,855 | 2,508 | 1 | 0 |
| 1e-12 | 58,855 | 53,237 | 267 | 1 |

## Reading

Double precision carries about 2.2e-16 of relative resolution, so a last-bit difference in a fitted coefficient reaches the output near 1e-16. The larger perturbations are headroom, not predictions: they say how far the arithmetic would have to degrade before a written precision stopped working.

**9 decimal places survives a 1e-15 perturbation with no row moving.**

Unrounded, every non-zero row moves. That is not bad luck — it is what a sixteen-significant-digit serialisation of a LAPACK result does when it crosses machines, and it is why two owners recorded different table hashes for the same export at the same commit.

## What was decided, and what changed

The table above is the evidence. **The export now writes nine decimals**
(`PREDICTED_POINTS_DECIMALS`, applied to both halves of the pair at the serialisation
boundary by `round_for_export`), and both manifests declare it as
`predicted_points_decimals`.

Rounding rather than publishing an equivalence tolerance beside the hash, for one reason:
a checksum's job is integrity. Attaching a tolerance turns it into an approximate-equality
test and loses the ability to detect a corrupted file, which is a different question from
whether two machines agree. Loading both onto one field would weaken both.

Two costs, recorded rather than discovered later.

**The control export's hash changes once.** It was
`1ed41f94f245b06d012293a895cdee755a5b1803cb19bcc3795e4a414767a22f`, stable across four
commits and two machines, and is now
`98b9dd20c912123d77d025b44634176337d6b185b8c4c80f6e480e772709c642`. The control has no
linear solve and never needed rounding, but a pair whose halves are written at different
precision is not a pair — a reader comparing them row by row would see nine decimals on
one side and seventeen on the other. What that hex string proved was reproducibility, and
reproducibility is what the new one proves going forward.

**The residual identity is no longer exact.** `residual` is recomputed from the *rounded*
projection, so it holds to float64's representation of a nine-decimal number — measured at
3.55e-15 across the real 101,447 rows, with 86,625 of them exact — rather than to the last
bit. Deriving it from the unrounded projection instead would leave a gap near 1e-9, five
orders worse and inside the range a reader might notice. The preflight's own tolerance is
1e-10, so the written table clears it with five orders to spare.

## Verified after the change

Re-measured against the rounded export, nine decimals moves **zero rows at every
perturbation tested, including 1e-12** — three orders beyond what double precision can
produce.

One side effect worth naming: at six decimals the rounded table moves 47–56 rows where the
unrounded one moved none. Rounding to nine creates values sitting exactly on a six-decimal
boundary, so a second, coarser rounding is *less* stable than one applied directly. An
argument against layering roundings, and a reason the precision is declared once and
applied once.

## The half this measurement did not cover

Rounding settles the values. It does not settle the bytes, and `table_sha256` digests the
raw file bytes.

`DataFrame.to_csv` defaults its line terminator to `os.linesep`, so the same rounded table
was written `\r\n` on Windows and `\n` on Linux. Two exports agreeing on every value to
nine decimals still produced different hashes across that boundary, for a reason this
measurement cannot see: it perturbs numbers, and the terminator is not a number.

The reason it stayed invisible is worth recording rather than glossing. Both owners who
compared hashes were on Windows. Their bytes agreed with each other, which read as
reproducibility, and would have disagreed with any Linux run. The claim "stable across four
commits and two machines" in the acceptance record is true and was never a claim about two
*operating systems*. It became load-bearing when CI started running on `ubuntu-latest`.

Exports are now written through `write_export_table`
(`src/squadopt/backtest/export_precision.py`), which sets the terminator explicitly, and
the four writers that produce recorded tables call it — the candidate and control residual
exports, the projection horizon table, and the horizon-decay residuals. A pinned digest in
`tests/unit/test_export_precision.py` holds the bytes to a known value on every platform.

Note what a test can and cannot prove here: on Linux the default and the explicit
terminator are the same bytes, so a regression fails on Windows and passes on Linux. The
pinned digest is the part that holds everywhere. Recorded hashes produced before this
change identify a table *and* the operating system that wrote it; a hash regenerated on a
different family will differ for that reason alone, and that is a fact about the old
records rather than a fault in the new ones.

### Measured on the real export

The control export was regenerated from the pinned archive on Windows, 147 folds and
101,447 rows, preflight 31/31:

| Bytes | Digest |
| --- | --- |
| `\n` (what is written now) | `b8d641cc80f0fdadc26ec4e7f013c00e9dcef1ae8c2e6b2202b6db586a5d0da1` |
| the same bytes with `\n` → `\r\n` | `1ed41f94f245b06d012293a895cdee755a5b1803cb19bcc3795e4a414767a22f` |

The second value is exactly what `control_residual_export.md` records. So the content is
byte-for-byte the table already recorded — not one value moved — and the recorded digest is
demonstrably its CRLF form. That is the whole defect, stated as arithmetic rather than as an
argument.

The recorded hashes are left as they are. They are honest records of runs that happened, on
the machines that happened, and rewriting them here would put a measurement change inside a
fix. A run that regenerates them belongs in its own pull request; the pair's control half
(`98b9dd20…`, rounded for the pair) and the candidate half will shift the same way and have
not been re-measured.

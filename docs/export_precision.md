# Export Precision

- Contract: `export_precision_v1`
- Column: `predicted_points`
- Population: 101,447 rows, 58,855 non-zero

Rows whose written value changes when the underlying number is perturbed by the given relative amount. Zero means two machines write the same bytes.

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

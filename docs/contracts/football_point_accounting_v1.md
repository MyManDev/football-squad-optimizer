# Raw football point accounting

Issue #1070 step1 introduces a shared leaf in
`squadopt.contracts.football_point_accounting`. It has no model, source, filesystem,
network, season, eligibility or fitting dependency. No existing caller changes in
this step. The separate experimental families remain subject to their own review,
source admission and actual merge gates.

## Declared mathematical scope

The caller supplies `ComponentMoments` for one explicitly declared scoring scope:

| Field | Meaning |
| --- | --- |
| `appearance_probability` | q, positive credited-minute appearance mass |
| `p60` | t, joint qualifying credited-minute mass |
| `goals`, `assists` | Unconditional expected action counts G and A |
| `clean_sheet_probability` | C, joint qualifying-minute and clean-sheet event mass |
| `defcon_probability` | D, unconditional qualifying award-event mass |
| `residual_expected_points` | R, already unconditional signed points |
| `support_roundoff` | Explicit caller-declared numerical budget for nested event mass; default 0 |

With explicitly supplied `PointCoefficients` s, l, g, a, c and d, the result is

```
raw = s * (q - t) + l * t + g * G + a * A + c * C + d * D + R
```

`raw_points` returns an immutable `RawPointResult` retaining the validated input
records and each named contribution. It sums the individual contributions with
`math.fsum`, preserving small signed gains through cancellation rather than
rounding an intermediate appearance subtotal. It does not multiply G, A, C, D or
R by q again. A native `residual_if_appearance` r is converted by the caller as
R = q * r, exactly once. The helper never decomposes the empirical residual into
cards, bonus, saves or goals conceded.

Each input probability is finite and lies in [0, 1]. With the default strict
numerical budget, the supplied moments satisfy t <= q, C <= t and D <= q.
Counts and coefficients are finite and nonnegative;
counts can exceed q because they count repeated actions. Positive goals or assists
at q = 0 are refused. No distribution is invented and no mass is normalized.
Booleans, unsupported number types, nonfinite inputs, unsupported event mass,
nonfinite products and overflowing sums raise named `ValueError` messages.

The accepted native producer can compute q = 1 - 0.8 as
0.19999999999999996, while its qualifying mass is 0.2. A caller can explicitly
declare `support_roundoff` between 0 and four `math.ulp(1.0)` units for these
nested comparisons. This fixed maximum is a finite binary-rounding allowance,
not an estimated event probability or a tolerance for missing source evidence.
Individual probability bounds remain strict. Zero q still requires zero positive
event/count support and zero t still requires zero C, regardless of the allowance.
Supplied moments stay unchanged, so a short-appearance contribution may be tiny
and negative within the declared numerical budget. The immutable input receipt
retains that budget. The helper never clamps it away or invents appearance mass.

An independently declared signed zero-minute residual may exist at q = 0, such as
a card-only contribution. This allowance does not declare FPL appearance or
autosub support. That policy and any wider accounting reconciliation belong to
the caller. Conditional residual conversion at q = 0 instead produces R = 0.

## Nonlinear moments and approximation

The primitive scores supplied moments; it does not infer them from a mean goal
rate, a mean minute value, or a single negative-binomial tail. In particular,
E[exp(-lambda)] generally differs from exp(-E[lambda]). State-mixture clean sheets,
DEFCON awards and exposure calculations must finish before this boundary.

Given exact first moments, the linear point formula is exact before clipping.
The implementation uses finite binary floats, not interval arithmetic. Floating
products and input moments already have rounding error. `math.fsum` improves sum
accuracy but does not undo upstream approximations, and its result can differ by
one or more rounding units from an old expression's operation order. This step
does not claim bitwise native identity and changes no native identity.

## Clipping and rule ownership

`clip_points(raw)` separately validates a finite real value and returns
max(raw, 0). The caller retains ownership of the aggregation and clipping level.
The accepted native football fixture calculation integrates component moments
first, computes a fixture raw mean and then clips that mean. It must retain that
scope in a later integration unless a separate declared policy change is accepted.

For equal-mass raw worlds -2 and +2, clipping the mean gives 0, whereas averaging
the clipped worlds gives 1. The helper neither averages worlds nor silently moves
clipping between them. Double-gameweek sums, cross-fixture dependence, eligibility,
captaincy, bench substitutions and the fixed15 optimizer remain caller concerns.

Scoring weights come from the caller's accepted, source-bound rule declaration.
No season comparison, source-position alias or coefficient default exists here.
For example, the captured rule reader uses GKP while native components use GK;
the verified caller explicitly translates that identity. Historical native parity
tests reproduce the accepted implementation's version boundaries using invented
inputs. They do not authenticate historical FPL rules or authorize new defaults.

## Validation and future integration

Focused checks cover independent action-world scoring, invented capture-derived
weights for all four positions, accepted native raw/clip parity across its season
boundaries, nonlinear moment preservation, signed residual conversion, zero-support
scope, cancellation, overflow and the clipping-order witness. Copied-source fault
checks and runtime evidence accompany the PR; original source bytes stay unchanged.
These checks validate accounting rather than a learned predictor's accuracy.

Actual combined native use is issue #1070 step2, in a separate reviewed PR after
the primitive and applicable predecessors actually merge. Dependencies include
#1048, #1051, #1053, #1054 and the six family issues #1057, #1059, #1061, #1063,
#1065 and #1067. Ibo reviews the shared domain and prediction integration. Each
family must preserve its declared minutes, residual, eligibility, resource and
clipping contracts and pass cumulative E2E after addition.

Real producer inputs require versioned rights, coverage, original availability
time, identity/club mapping and source receipts. FM datasets remain private and
outside Git. Actual train/validation/test readings and model admission also wait
for the owner decisions and frozen protocols under #1004, #1009 and #1016. This
primitive does not approve a source or perform a real fitting/readout.

# Observed tactical context

The separate `football_observed_tactical_marginal_context_v2` model accepts four observed
event channels and nullable FM traits. Its metadata declares this partial scope, the input v2 schema, the lagged-role policy
and the
`native_full_roster_marginal_context_v1` policy; the original tactical model retains its
separate contract (`src/squadopt/prediction/football_observed_tactical.py:45`,
`src/squadopt/prediction/football_observed_tactical.py:181`,
`src/squadopt/features/football_tactical_inputs.py:1`).

## Source scope

The four channels are cross attempts, through-ball attempts, headed shots and fast-break
shots. The reader counts pass event types 1 and 2 with qualifiers 2 or 4, and shot types
13 through 16 with qualifiers 15 or 23, excluding own goals marked by qualifier 28.
These identifiers follow the pinned [Panna Opta reference](https://github.com/peteowen1/panna/blob/947826b990f766efd323d81ce5287ee506198fc5/OPTA_REFERENCE.md#L67).
The implementation retains the complete selected fixture row population and unique event
identities; pressure and high-pass evidence remain unsupported
(`src/squadopt/features/football_observed_tactical_readers.py:155`,
`src/squadopt/features/football_observed_tactical_inputs.py:357`).

Style is the arithmetic count per enumerated observed fixture in the preceding 28 days.
Each admitted fixture must finish before the feature cutoff and belong to an earlier
gameweek. This is an observed provider population, with its count exposed as a feature;
an empty population yields unknown rates, while observed zero counts remain zero
(`src/squadopt/features/football_observed_tactical_inputs.py:134`,
`src/squadopt/features/football_observed_tactical_inputs.py:345`,
`src/squadopt/features/football_observed_tactical_inputs.py:559`).

FM inputs preserve exact row, name, birth-date and source-column mappings; blank traits
remain unknown. The typed profile retains the original identity and mapping reference.
The explicit `latest_confirmed_role_same_current_club_within28d_v1` policy uses the
latest confirmed prior role at the club in the exact supplied roster, within 28 days.
This lagged categorical predictor makes no continuous-registration or future-position claim.
A selected inventory declared complete requires its SHA256; an unknown or incomplete
inventory gives an unknown role. Equal latest timestamps with conflicting roles refuse.
The Panna mapping is explicitly versioned: Goalkeeper
maps to G; Defender and Wing Back to D; the three named midfield roles to M; Striker to F.
The map accepts the explicit spaced and camel-case labels declared in code.
Substitute supplies no positional role. FPL position is retained for scoring identity
and never substitutes for a provider role
(`src/squadopt/features/football_observed_tactical_readers.py:276`,
`src/squadopt/features/football_observed_tactical_readers.py:30`,
`src/squadopt/features/football_observed_tactical_readers.py:406`,
`src/squadopt/features/football_observed_tactical_inputs.py:214`).

## Context and model

The context contains the full supplied native roster, each player's expected minutes
between 0 and 90, and native goal and assist recipient shares. Those shares already
include native exposure. Goal and assist trait means use their respective shares once;
defensive and goalkeeper context uses expected minutes and supported provider roles.
Unknown traits and roles retain observed-weight fractions and known-player counts.
The contract imposes no realized XI, total-minute bound or learned dependence law
(`src/squadopt/features/football_observed_tactical_inputs.py:305`,
`src/squadopt/features/football_observed_tactical_inputs.py:573`,
`src/squadopt/prediction/football_observed_tactical.py:181`).

The model fits a paired Poisson rate adjustment and separate conditional recipient
multinomials at this declared marginal context. Native rates and shares are offsets.
This is an explicit plug-in context assumption; it does not integrate nonlinear effects
over a joint playing-state distribution. Numeric centering, scaling and observed masks
are learned solely from training inputs, using one-half weight per club for team context
and one-half native share for recipient context. Missing values occupy a neutral centered
numeric coordinate with a separate observed mask. A column with no observed training
support stays disabled at prediction, even if later evidence appears
(`src/squadopt/prediction/football_observed_tactical.py:92`,
`src/squadopt/prediction/football_observed_tactical.py:670`,
`src/squadopt/prediction/football_observed_tactical.py:534`).

Allocation returns paired physical goal rates and player goal/assist expectations only.
Clean-sheet calculations belong to a separately composed score and minute-law path.
Control preserves native rates and shares. Learned allocation refuses an unsupported
positive recipient head, broken full-club mass conservation or a player's G+A exceeding
physical goal intensity; it does not clip those cases
(`src/squadopt/prediction/football_observed_tactical.py:213`,
`src/squadopt/prediction/football_observed_tactical.py:778`).

`predict_recipients` is the separately versioned
`native_offset_observed_tactical_recipient_only_v1` inference path. It evaluates only
recipient transforms and coefficients and returns each player's goal and assist shares.
It does not evaluate the paired-rate head, return rates, or divide a full prediction by
its rate. Its compact receipt binds the full model digest, projection digest, cutoff
and supplied source hashes; it does not repeat training metadata or authenticate sources.
The path preserves exact native zero support, validates finite nonnegative normalized
shares, requires historical support for a positive credited head, and checks the player's
combined physical goal fraction. Native control returns the supplied shares unchanged.
These checks leave final team rates and score composition to the caller
(`src/squadopt/prediction/football_observed_tactical.py:48`,
`src/squadopt/prediction/football_observed_tactical.py:241`,
`src/squadopt/prediction/football_observed_tactical.py:389`,
`src/squadopt/prediction/football_observed_tactical.py:751`).

## Clocks, integrity and integration boundary

All training headers pass before any outcome labels are accessed. The whole target and
later gameweeks are excluded, and use of 2025-26 requires a strict explicit Boolean
opt-in. A retrospective record separates historical feature/decision clocks from actual
later retrieval and input-generation clocks. Current prediction refuses a replay record
(`src/squadopt/features/football_observed_tactical_inputs.py:193`,
`src/squadopt/features/football_observed_tactical_inputs.py:386`,
`src/squadopt/features/football_observed_tactical_inputs.py:481`,
`src/squadopt/prediction/football_observed_tactical.py:499`,
`src/squadopt/prediction/football_observed_tactical.py:778`).

The pure readers accept supplied bytes and compare their SHA256 with the caller's
expected value. Canonical envelope readers validate declared schemas, clocks, identities
and native/roster hash bindings. They do not open the historical Git revision, native
artifact, roster or teams files to authenticate those declarations. Likewise, event
bridge and complete-inventory hashes are retained declarations. Source hashes provide
byte integrity, not source authenticity or proof of permission
(`src/squadopt/features/football_observed_tactical_readers.py:45`,
`src/squadopt/features/football_observed_tactical_readers.py:82`,
`src/squadopt/features/football_observed_tactical_inputs.py:181`,
`src/squadopt/features/football_observed_tactical_inputs.py:433`).

Before a real fit or runtime integration, the producer must independently compare the
native values and complete paired roster with their retained original bytes, verify
fixture/person bridges and source populations, verify the whole selected role inventory
represented by each completeness declaration, and retain actual acquisition receipts.
The runtime composition must bind this context to its loaded native artifact and keep
the declared partial family scope. This page specifies that integration requirement;
the pure contracts and allocation are the implementation boundary here
(`src/squadopt/features/football_observed_tactical_inputs.py:134`,
`src/squadopt/features/football_observed_tactical_inputs.py:454`,
`src/squadopt/prediction/football_observed_tactical.py:229`).

The focused tests use invented fixtures to check independent feature arithmetic,
chronology, unknown evidence, strict readers, native control and allocation guards.
They are contract tests, with no predictive-accuracy or runtime-activation result
(`tests/unit/test_football_observed_tactical.py:1`).

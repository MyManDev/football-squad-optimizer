# Retained composite forecast basis

`build_composite_documents` constructs the served forecast and its companion from
already acquired native and flag documents, five compact model artifacts, the
complete weekly inventory and all paired fixture contexts. The producer accepts
values rather than paths and performs no training or source acquisition
(`src/squadopt/live/football_composite_basis.py:730`).

The recipe retains canonical source strings and their SHA256 identities. Document
inputs are bounded to 8 MiB each and the complete companion to 128 MiB. Typed
payloads use code-selected DTO readers; each compact family uses its own strict
reader, including the concrete tactical recipient serving class
(`src/squadopt/live/football_composite_basis.py:112`,
`src/squadopt/live/football_composite_basis.py:139`,
`src/squadopt/live/football_composite_basis.py:182`,
`src/squadopt/live/football_composite_basis.py:580`).

Original native and flag pairs pass the legacy reader. The new binding also checks
the captured roster positions and clubs, raw calendar hash, deadline clocks,
captured eligibility, exact original component atoms and their declared native
Cartesian product. The joint-law constructor's existing single normalization is
reproduced from the original atoms. The recipe preserves original source clocks,
distinct reconstruction clocks and implementation digest receipts. These checks
establish byte integrity and declared clock consistency. They do not authenticate
providers, inspect Git commits or prove publication time from a digest
(`src/squadopt/live/football_composite_basis.py:207`,
`src/squadopt/live/football_composite_basis.py:311`).
The two phase duty captures must match this inventory's snapshot, fingerprint
and capture clock. Each unit, score, tactical and phase model must name the first
forecast week and season; legacy unit v1 has no explicit target and is refused
by this recipe (`src/squadopt/live/football_composite_basis.py:280`,
`src/squadopt/live/football_composite_basis.py:293`).

The reader restores all compact models, composes the complete weekly population,
and recomputes every paired fixture. It compares the entire served document and
companion, including final laws, seven-state outputs and stage receipts. A changed
row or receipt is refused even when the outer document was rehashed. The public
metadata carries compact family and original-fit identities; full training
metadata is not copied into every allocation
(`src/squadopt/live/football_composite_basis.py:554`,
`src/squadopt/live/football_composite_basis.py:635`,
`src/squadopt/live/football_composite_basis.py:783`).

After initial validation the basis retains parsed models and baseline results.
Empty evidence returns the original fixture and weekly rows. Supported first-week
news is applied to the original retained laws, then every fixture covered by a
changed law is recomputed for both clubs. Other fixture results are reused.
Repeated identical evidence produces identical results and never compounds a
previous adjustment. LOAD and fitting do not rerun, and captured eligibility is
not multiplied a second time (`src/squadopt/live/football_composite_basis.py:500`,
`src/squadopt/live/football_composite_basis.py:843`,
`src/squadopt/live/football_composite_basis.py:881`).

The platform selects this reader before its legacy path and supplies positions,
deadlines and the actual captured calendar hash. Existing captured multiplier and
loaded weekly-row comparisons still run after dispatch
(`src/squadopt/platform/football_minute_basis.py:88`,
`src/squadopt/platform/football_minute_basis.py:107`,
`src/squadopt/platform/football_minute_basis.py:121`).

Portable tests cover strict canonical inputs, all five real compact readers,
redigested artifacts and clock declarations, immutable baseline reuse, news
reproducibility and exact outer-document reconstruction. The small orchestration
fixture executor is explicitly a test double, so those tests do not claim a fitted
physical-model result (`tests/unit/test_football_composite_basis.py:1`,
`tests/unit/test_football_composite_basis.py:108`,
`tests/unit/test_football_composite_basis.py:275`,
`tests/unit/test_football_composite_basis.py:386`,
`tests/unit/test_football_composite_basis.py:407`,
`tests/unit/test_football_composite_basis.py:510`).

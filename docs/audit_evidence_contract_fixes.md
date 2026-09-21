# Prediction evidence contract corrections

The September 2026 audit distinguished code defects from unproven model improvements.
This change fixes two evidence claims without fitting a new production predictor.

- The legacy capture-ordered advice reader now requires the recorded publication time
  as well as capture time to precede the deadline. A late publication cannot replace
  an older timely record. An absent or malformed publication clock is an error. The
  evaluation reader retains its separate publication-ordered selection contract.
- Both stale start-model explanations now distinguish available labels from an
  estimator promoted into the operational control. The conditional-start experiment
  remains separate; probabilities, allowed seasons and provenance are unchanged.

`tests/integration/test_component_decision_chain.py` runs the real component fit and
composition, serialized handoff, captured availability, member planner, published lineup
and official autosub/captain scorer together. One unmodelled row retains a missing
appearance probability and direct fallback. A captain no-show exercises the published
bench and vice-captain; hits are charged separately. Input features and capture are
synthetic. This proves wiring and the asserted arithmetic, not live forecast accuracy,
historical net-point improvement or an archive-ingestion end-to-end run.

The earlier audit's measurements remain unchanged. The appearance recalibration failed
its frozen gate, Top100 effect reading remains checkpoint-gated, and recovering future
fixture value from a blank first week needs a separately declared horizon candidate.
No calibration threshold, new model, holdout read or retrospective measurement is
introduced by these corrections.

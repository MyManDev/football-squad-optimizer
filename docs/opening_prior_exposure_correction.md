# Opening-prior exposure corrective run

The original `opening_prior_exposure` runner filtered the locked 2025-26 holdout out of
the in-memory panel, but called the archive loader without a season allow-list. Therefore
the holdout files were read before the filter, and the original artifact is non-binding.

The corrective run must load only 2020-21 through 2024-25 at the data-source boundary,
derive its provenance and holdout declaration from the seasons actually returned by that
bounded load, and abort before feature generation if the loader returns 2025-26. The
population, configurations, estimator, thresholds, and interpretation are unchanged. The
corrected artifact replaces the original evidence regardless of whether its scientific
values change.

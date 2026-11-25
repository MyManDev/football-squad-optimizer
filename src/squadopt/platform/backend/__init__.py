"""The API and worker cluster (ADR 0011, decision 3).

New preference execution lives here; the existing flat queue, cache, documents,
switches, worker and runtime retain their public entry points during migration.
"""

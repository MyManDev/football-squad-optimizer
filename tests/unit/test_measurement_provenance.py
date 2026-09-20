"""A record says which code produced it.

Of the 108 records committed under `docs/` on develop, 90 name the commit that produced them
and 18 do not. The gap is not a habit of any one author: `member_plan_determinism.json` was
written, reviewed by two people and merged on 2026-09-19 without anyone noticing that it names
no commit, and the runner that wrote it is the one this file tests.

Naming the commit is not decoration. A record is the only evidence that a measurement happened,
and a reader deciding whether to trust one asks which code produced it. A record that cannot
answer is not wrong, it is unfalsifiable, which is a worse thing for evidence to be.

The narrow helper exists because the wide one would overclaim. `artifact_metadata` stamps the
archive commit and the manifest digest along with the repository commit, which is right for a
measurement over the historical panel and false for one that never opens it. A record naming
inputs it did not read is worse than a record naming fewer of them.
"""

from __future__ import annotations

import re

from scripts._experiment_cli import artifact_metadata, repository_provenance
from scripts.measure_member_plan_determinism import _document

SHA = re.compile(r"^[0-9a-f]{40}$")


def test_the_repository_provenance_names_a_commit_and_whether_the_tree_was_clean() -> None:
    """Both fields, or the commit describes bytes that may not be the ones that ran."""

    provenance = repository_provenance()

    assert set(provenance) == {"repository_commit", "working_tree_dirty"}
    assert isinstance(provenance["repository_commit"], str)
    assert SHA.match(str(provenance["repository_commit"]))
    assert isinstance(provenance["working_tree_dirty"], bool)


def test_the_wide_metadata_still_carries_what_the_narrow_helper_returns() -> None:
    """The factoring must not have quietly dropped either field from the 90 that have them.

    `artifact_metadata` is the stamp on every panel measurement in this repository, so a
    regression here is a regression in most of the evidence the repository holds.
    """

    provenance = artifact_metadata(panel_rows=0)["provenance"]
    assert isinstance(provenance, dict)

    narrow = repository_provenance()
    assert provenance["repository_commit"] == narrow["repository_commit"]
    assert provenance["working_tree_dirty"] == narrow["working_tree_dirty"]
    # The wide stamp keeps naming the dataset; that is the difference between the two.
    assert "archive_commit" in provenance


def test_the_determinism_record_names_the_code_that_produced_it() -> None:
    """The defect this file was written for, asserted on the document rather than the source.

    Built with no cells and no members on purpose: the provenance does not depend on what was
    measured, so the emptiest document the runner can produce must still carry it.
    """

    document = _document(
        created_utc="2026-09-20T05:00:00+00:00",
        snapshot_id="capture-under-test",
        season="2026-27",
        gameweek=5,
        entries=[],
        arms=[],
        per_arm={},
        cells=[],
    )

    provenance = document["provenance"]
    assert isinstance(provenance, dict)
    assert SHA.match(str(provenance["repository_commit"]))
    assert provenance["working_tree_dirty"] in (True, False)


def test_the_determinism_record_does_not_claim_an_archive_it_never_reads() -> None:
    """The reason the narrow helper exists, pinned so a later edit cannot widen it by habit.

    This runner solves member plans from a live capture. It opens no seasonal archive, so an
    `archive_commit` here would name a dataset the run did not read, which is the failure the
    whole file is about pointed the other way.
    """

    document = _document(
        created_utc="2026-09-20T05:00:00+00:00",
        snapshot_id="capture-under-test",
        season="2026-27",
        gameweek=5,
        entries=[],
        arms=[],
        per_arm={},
        cells=[],
    )

    provenance = document["provenance"]
    assert isinstance(provenance, dict)
    assert set(provenance) == {"repository_commit", "working_tree_dirty"}

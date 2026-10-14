"""The storage ports of the use cases: what a use case asks of durable state, as Protocols.

ADR 0011 (decision 1) declares each storage port in the innermost ring that consumes it. The
ports only the use cases consume belong here, one module per port group and no barrel, so the
pull requests that land different groups never edit the same file: `archive`
(`ArchiveReader`), `publication` (`PublicationFiles` and `PublicationIdentity`), `artifacts`
(`ArtifactFiles`), `club_news` (`ClubNewsFixture`, `ClubNewsFixtureOpener` and
`ClubNewsSources`), `rotation_evidence` (`RotationEvidenceReader`), `advice_records`
(`AdviceRecordFiles`) and `revision` (`RevisionReader`). `CaptureReader` is declared in
`squadopt.data.capture`, because `live` consumes it as well, and `LedgerStore` in
`squadopt.live.ports`.

A port mirrors the existing `data` function one for one and is keyed by the root `Path` the
request already carries, so request types, command-line flags and the error messages that name
a root stay as they are. A use case takes its ports as required keyword-only arguments: not a
default value, not an import inside a function, not a registry. The file adapters are the
singletons of `squadopt.platform.storage`, wired at the composition roots, and
`tests/architecture/test_storage_ports.py` holds each adapter to its port. This package is a
source of the contract "The decision core imports no storage or source module", so nothing
here imports the storage half of `data`. It holds no port yet: each group lands in its own
pull request.
"""

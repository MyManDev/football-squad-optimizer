"""The file adapters behind the storage ports: the durable state the product keeps on disk.

ADR 0011 (decision 1) puts the adapters of the storage ports here, one module per port group,
matching the ports declared in `squadopt.application.ports`, `squadopt.data.capture` and
`squadopt.live.ports`: `captures`, `archive`, `publication`, `artifacts`, `club_news`,
`rotation_evidence`, `advice_records`, `revision` and `ledger`. Each adapter is a stateless
frozen slots dataclass, exported as a module-level singleton annotated with its Protocol, so
mypy proves that it conforms and the singleton pickles across the league stage's process pool.
It calls the `data` functions unchanged, or holds code moved verbatim and run in the original
order, and keeps the precedence and the text of every error.

The composition roots wire the singletons into the use cases:
`squadopt.platform.weekly_operations`, the `CliServices` object of `squadopt.platform.cli`,
`squadopt.platform.publication_workers` and the scripts that call a changed use case. Under
decision 3 this subpackage is the lowest of the seven platform deployment units, the shared
durable-state primitives every other unit may import.
`tests/architecture/test_storage_ports.py` holds each adapter to its port. It holds no adapter
yet: each group lands in its own pull request.
"""

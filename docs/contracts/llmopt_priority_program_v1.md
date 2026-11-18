# Internal priority program proposal

See [ADR 0019](../architecture/decisions/0019-llmopt-priority-budget.md).
`PriorityProgram` validates one through sixteen distinct rules, integer priorities 1 to 3
and integer total concession tenths 0 to 1000. Canonical rule identity determines build
order. `priority_program_schema()` generates the accompanying schema.

This is a planning-core interchange proposal, not an accepted public advice request or a
provider response schema. No key or run identity belongs in it. The core receives a
server-computed reference separately and certifies its decisions against the same rules.
See the [integration status](../research/llmopt_phase3_status.md) for unimplemented work.

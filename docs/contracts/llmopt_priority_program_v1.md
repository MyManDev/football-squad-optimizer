# Priority program

See [ADR 0019](../architecture/decisions/0019-llmopt-priority-budget.md).
`PriorityProgram` validates one through sixteen distinct rules, integer priorities 1 to 3
and integer total concession tenths 0 to 1000. Canonical rule identity determines build
order. `priority_program_schema()` generates the accompanying schema.

The program is contained in the public [preference execution](llmopt_preference_bundle_v1.md).
Optional priorities and the total allowance reach it through prompt/check and the
reviewed editor. No credential or run identity belongs in the program. The worker
retrieves the server-owned main answer and certifies its decisions in the same model;
a client never supplies J.

An explicit priority without a total allowance asks the member for that allowance.
A soft Wildcard with a total allowance is refused before admission. Fixed named chips
remain part of the main plan's mandatory domain. When the release setting is on,
omitting both fields retains individual pricing within one preference job. When
the setting is off, the original workflow submits individual prices separately.

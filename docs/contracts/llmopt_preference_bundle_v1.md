# One preference execution

ADR 0019 defines the execution after the main plan. The optional `preference_bundle`
field uses the existing advice POST and cache GET. The full backend advertises
`preference_bundles.version = llmopt_preference_bundle_v1` when the server enables
`SQUADOPT_BACKEND_LLMOPT_VNEXT`. A three-week bundle also requires
`llmopt_vnext_three_week: true` for its capture. A closed window uses the
original unbound pricing requests.
A restored confirmation checks the current server setting before starting another stage.
During rollback, clients can still poll jobs and read stored bundle results for the current capture.

The closed request contains at most two `slots`, sixteen `prices`, reachable price
`choices`, and an optional `program`. Component preferences override the main request;
null removes an inherited field. Frozen decisions are stored once. Every expanded
choice is validated before admission. An incomplete price graph or a component
removing required player, resource, frozen-week or objective rules is refused.
Legacy optional Wildcard can replace the compiler's implicit global chip hold while
explicit scoped holds are preserved. The complete POST body has a 4,096-byte limit.
The GET accepts a bundle of up to 4,096 decoded characters, enough for every compact
JSON bundle in an admitted POST. The standalone preferences query allows 3,000 characters.

Without a total allowance, the existing page compiler enumerates accepted-price
patterns, including different ceilings on rules sharing a price. There are at most
289 patterns for sixteen rules and two prices. The worker computes the original
single-price slots sequentially, derives acceptance from computed net-point costs
and selects at most one compiled combination. Individual ceilings, conflicts,
unpriced bounded rules and writing order retain their existing meaning.

With a total allowance, `program` contains the rules and priorities. `prices` and
`choices` are empty. The worker reconstructs the cached main decisions and resource
path, then executes count layers and a net-points tie break. Cost is the signed
difference between computed plans. A fixed-path certificate cannot upgrade global proof.
New answers place every rule identity in exactly one of `satisfied`, `left_out` or
`unsearched`. The first two lists cover completed count layers. The last list covers
all rules from unfinished layers, including incidental matches in the returned plan.
For older answers, readers use the program and `completed_priorities` to identify them.

POST requires an identified follow-up whose durable main key matches the key derived
by the server. A client cannot supply J, reference payload or allocation. The main
job reserves 21/122 units and the preference job 63/366, within 84/488 total. An
uncached ordinary component can use up to 21/122 units from the remaining parent work.
The total-allowance program shares the full remaining allocation across its count and
points searches. Actual receipts accumulate even on failure. A cache hit starts no solve;
no component creates a queue job. A completed component with its ordinary allocation
enters its own answer cache even if the initiating run closes. A component computed
with a smaller allocation is readable in the cached bundle.

The response retains the main payload and adds `preference_bundle_result`, containing
computed components, the selected payload, applied indexes and completion state.
Components cannot recursively contain bundles. Infeasibility diagnoses retain their
repair shape. The page checks every component with its ordinary advice checker before
displaying it. No computed number comes from a provider response.

Total allowances with counterfactual scenarios remain refused before new work; the
existing scenario comparison retains its confirmed transport. Device migration belongs
to the next phase. Provider credentials retain their existing route and stores.

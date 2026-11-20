# LLMOPT private device extensions

See [ADR 0020](../architecture/decisions/0020-llmopt-device-alternatives.md).

The private browser worker accepts optional checked `preferences` and an `alternatives`
boolean. Without them its prior behavior is preserved. The page and worker are shipped
together through the worker asset's content hash. This does not add fields to public
advice commands, their immutable job specs or their cache identity.

A computed device answer may carry persistent bank, free transfers before/after and at
most two further choices. Further choices are marked internally as restricted feasible
decisions. Their full published advice appears as `device_alternatives`, without nested
menus. The existing advice validator checks each option and rejects repeated transfer
decisions. Resource numbers and scores come from the solver and input arithmetic.

`device_input_fingerprint` is SHA-256 of the checked device table and member input block.
Session cache addresses include it and explicit request inputs, never a provider key.
An old answer from a replaced table is recomputed locally. A refused local solve does not
open a fallback alternative server job. An edited run aborts its worker and ignores its
result; unknown or server-backed runs retain the existing server cancellation path.

The confirmation pins `deviceRun` and `deviceAlternatives` before work starts. Legacy
confirmations retain server execution even when device inputs appear later. An unsupported
rule keeps the entire run on the service, preserving a common comparison basis.

Before a worker starts, a session receipt reserves **4 units**, the existing 120-second
shared worker ceiling divided by ADR 0018's 30-second native unit. A receipt retains its
binding, charged units and closure through reload; repeated completed answers cost zero.
The one-week ceiling stays 84. A rejected write refuses new local work before creating a
worker. Identity may still use the existing history fallback; an unrecordable capacity
receipt does not silently reset. The schema also defines these receipt/confirmation shapes.

The accompanying schema describes these optional extension fields; existing core device
and advice validators still validate their other fields. Generate it with
`device_extension_schema()` in `squadopt.contracts.llmopt_device`.

The optional private `preferenceBundle` request is the checked Phase 3 bundle. The
worker returns `preference_bundle` with at most two computed components and one
selected answer; answers cannot contain another bundle or alternatives. The adapter
publishes these as the existing `preference_bundle_result`. A total allowance returns
computed `priority_preferences`, including completed layers and signed total cost.
Every internal solve shares the same worker ceiling. No numeric reference is accepted.

The browser offers `devicePreferenceBundles` for one week after current server
capabilities grant `llmopt_vnext` and the matching device inputs are available.
A missing or disabled grant keeps fresh confirmations on the original service path.
The device capability applies only to one week. Confirmation `bundleMode`
and `deviceRun` are saved before work. Bundle identity extends only the private
device cache address. Public computation identities and provider credentials are unchanged.

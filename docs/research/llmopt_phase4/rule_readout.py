"""Classify every observed outcome and write the evidence with an English readout."""

import json
from collections import Counter

from docs.research.llmopt_phase4.rule_cases import FAMILIES


def comparison(server, device, expected_feasible, *, fixed_week=False):
    sd, dd = server["decision"], device["decision"]
    decisions = [p for p in (sd, dd, *device["alternatives"]) if p]
    errors = [str(issue) for d in decisions for issue in d["audit"]["errors"]]
    settings = server["settings"] or {}
    correct_profile = (
        server["allocation"] == 21
        and settings.get("deterministic_limit") == 20
        and settings.get("wall_seconds") == 1800
        and settings.get("linearization") == 2
        and settings.get("net_points") is True
        and settings.get("protect_hold") is True
        and server["cp_statuses"]
        and device["selection"] == "plain"
        and device["statuses"]
    )
    if not correct_profile:
        errors.append("missing or unexpected solver settings, receipt or device route")
    used = server["cp_used"]
    if not (
        isinstance(used, (int, float))
        and isinstance(server["allocation"], (int, float))
        and 0 <= used <= server["allocation"]
        and used == server["observed_cp_units"]
        and (used > 0 or not expected_feasible or fixed_week)
        and server["receipt_calls"] == len(server["cp_statuses"])
        and server["native_reserved"] == 0
        and not server["other_solver_calls"]
    ):
        errors.append("observed solver work and allocation receipt")
    ids = [tuple(d["squad"]) for d in (dd, *device["alternatives"]) if d]
    if len(ids) != len(set(ids)):
        errors.append("duplicate device transfer decision")
    objectives_equal = (
        sd is not None
        and dd is not None
        and not sd["audit"]["errors"]
        and not dd["audit"]["errors"]
        and sd["audit"]["net_scaled"] == dd["audit"]["net_scaled"]
    )
    feasible = server["status"] in ("OPTIMAL", "FEASIBLE") and device["status"] in (
        "OPTIMAL",
        "FEASIBLE",
    )
    infeasible = server["status"] == device["status"] == "INFEASIBLE" and not decisions
    if (expected_feasible and not feasible) or (not expected_feasible and not infeasible):
        errors.append("contradicts the fixture witness or required minimum hit")
    if not errors and feasible and objectives_equal:
        outcome = (
            "same_transfers" if sd["in"] == dd["in"] and sd["out"] == dd["out"] else "transfer_tie"
        )
    elif not errors and infeasible:
        outcome = "both_infeasible"
    else:
        outcome = "mismatch"
    return dict(
        outcome=outcome,
        objective_equal=objectives_equal,
        status_equal=server["status"] == device["status"],
        errors=errors,
    )


def write_results(provenance, rows, path):
    summary = {}
    for family in FAMILIES:
        group = [r for r in rows if r["family"] == family]
        counts = Counter(r["outcome"] for r in group)
        summary[family] = dict(
            cases=len(group),
            **counts,
            differing_status=sum(not r["status_equal"] for r in group),
            alternatives_checked=sum(len(r["device"]["alternatives"]) for r in group),
        )
    data = dict(
        contract_version="llmopt_one_week_hard_rule_comparison_v1",
        **provenance,
        summary=summary,
        cases=len(rows),
    )
    body = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    encoded_rows = ",\n".join(
        "    " + json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        for row in rows
    )
    path.write_text(
        body[:-2] + ',\n  "rows": [\n' + encoded_rows + "\n  ]\n}\n", encoding="utf-8", newline="\n"
    )
    member_weeks = len({row["case"] for row in rows})
    revision = provenance["producer_repository_commit"]
    lines = [
        "# One-week hard-rule comparison",
        "",
        f"The [machine-readable record]({path.name}) contains {len(rows)} paired solves across "
        f"{member_weeks} frozen GW8 and GW9 member-weeks. The producing commit is "
        f"`{revision}`. Each case uses the published Phase 1 "
        "points, prices, sale values, free transfers and effective bank, including both "
        "zero-bank controls.",
        "",
        "| Rule | Cases | Same transfer decisions and score | Different decisions, tied "
        "score | Both infeasible | Mismatches | Different proof statuses | Alternatives checked |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family, n in summary.items():
        lines.append(
            f"| {family.capitalize()} | {n['cases']} | {n.get('same_transfers', 0)} | "
            f"{n.get('transfer_tie', 0)} | {n.get('both_infeasible', 0)} | "
            f"{n.get('mismatch', 0)} | "
            f"{n['differing_status']} | {n['alternatives_checked']} |"
        )
    lines += [
        "",
        "## Inputs and scope",
        "",
        "Every comparison uses a confirmed device-eligible one-week pure-points request, "
        "without a chip, news, rival, Top100 weight, or soft preferences. The frozen "
        "captures and the original controls remain intact. The new probes replace the "
        "original scenario restrictions with one named hard-rule family. They retain the "
        "tight-bank scenario's zero bank. Named-chip and original contradictory controls "
        "have separate historical evidence.",
        "",
        "A cold, isolated in-process server API submits one run-bound job to the normal "
        "worker for each pair. The device selector dispatches the same eligible request to "
        "the installed WebAssembly solver, with the hard-rule alternatives option "
        "enabled and its normal cumulative worker ceiling. This compares the selected "
        "device main plan with the server main plan. Device alternatives are also checked "
        "against the submitted rules. This local replay measures predicted points.",
        "",
        "Rules are fixed before either solver runs. The archived unconstrained plan "
        "supplies a departing player to keep, an arriving player to avoid, a different "
        "legal player to buy and a bank floor one tenth above its closing bank. GW8 club "
        "probes require an exact squad count. GW9 probes require an exact incoming count. "
        "The frozen-week probe pins the archive's transfers, XI, captain and chip. All "
        "archived unrestricted plans used zero hits. The maximum-hit probes therefore "
        "require one purchase beyond the captured free transfers, then allow one hit in GW8 "
        "and zero in GW9. Every specified set of purchases has a constructive budget- and "
        "club-legal exchange sequence before imposing that ceiling. Each feasible fixture "
        "has an independently checked transfer set, XI and captain in the record. "
        "Ten GW9 hit fixtures instead require more paid arrivals than their zero ceiling allows. "
        "Expected feasibility is checked even if both solvers agree.",
        "",
        "The server receipt, actual optimizer settings and proof status are captured per "
        "request. Each CP call contributes its observed deterministic units to an independent "
        "sum checked against the receipt. Native calls and reservations are recorded separately. "
        "Independent verification rebuilds all squads from transfers, checks the "
        "XI and captain, club and position limits, bank after sales and purchases, the hit "
        "charge and each hard rule. The integer objective sums the frozen XI and captain "
        "coefficients and deducts hit points at the published scale. An equal score counts "
        "only when both reported values match this reconstruction. Transfer equality uses "
        "incoming and outgoing IDs. A different valid decision at the same score counts as "
        "a tie. Matching infeasibilities have no numeric objective. Every differing status "
        "or failed comparison is listed below.",
        "",
        "## Exceptions",
        "",
    ]
    exceptions = [r for r in rows if not r["status_equal"] or r["outcome"] == "mismatch"]
    if exceptions:
        for r in exceptions:

            def value(arm):
                d = arm["decision"]
                return f"{arm['status']} ({d['objective_scaled'] if d else 'no objective'})"

            lines.append(
                f"- `{r['case']}/{r['family']}` has server {value(r['server'])}, "
                f"device {value(r['device'])}, {r['outcome']}. " + ", ".join(r["errors"])
            )
    else:
        lines.append("All recorded proof statuses matched. No comparison failed.")
    lines += [
        "",
        "## Reproduction",
        "",
        "Check out the producing commit and install its locked Python and web dependencies. "
        "Run from the repository root with the package on the Python path. Keep tests and "
        "CI outside the measurement window.",
        "",
        "```sh",
        "python -m docs.research.llmopt_phase4.rule_measure --check-inputs",
        f"python -m docs.research.llmopt_phase4.rule_measure --producer {revision} --resume",
        "```",
        "",
        "A fresh checkpoint lives under `.codex-tmp/`. Resume checks the producer, input "
        "digests, source fingerprints and ordered request prefix before starting another pair.",
    ]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

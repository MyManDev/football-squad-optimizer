"""Serialization of preflight reports for records and command-line review."""

from squadopt.preflight.models import PreflightReport


def preflight_report_to_dict(report: PreflightReport) -> dict[str, object]:
    """Return a JSON-compatible document for one preflight report."""

    return {
        "contract_version": report.contract_version,
        "artifact_label": report.artifact_label,
        "passed": report.passed,
        "findings": [
            {
                "check": finding.check,
                "passed": finding.passed,
                "detail": finding.detail,
            }
            for finding in report.findings
        ],
    }


def preflight_report_to_markdown(report: PreflightReport) -> str:
    """Return a human-readable summary that names every check outcome."""

    verdict = "PASSED" if report.passed else "FAILED"
    lines = [
        f"# Preflight: {report.artifact_label}",
        "",
        f"- Contract: `{report.contract_version}`",
        f"- Verdict: **{verdict}** "
        f"({len(report.findings) - len(report.failures)}/{len(report.findings)} checks passed)",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for finding in report.findings:
        outcome = "pass" if finding.passed else "FAIL"
        detail = finding.detail.replace("|", "\\|")
        lines.append(f"| `{finding.check}` | {outcome} | {detail} |")
    return "\n".join(lines) + "\n"

"""The public CP-SAT driver: solver settings, the solve call and its status and work.

ADR 0011 (decision 5) gives the decision core one public port to CP-SAT. The constants and
the six functions here were the private driver of `optimization.optimizer`, which `planning`
and both `scenarios` solvers imported by their private names; the bodies are the same, only
the leading underscore is gone. Each consumer binds a public name to the module-level private
name it had, for example ``from squadopt.optimization.cpsat import solve as _solve``, so a test
that patches ``_solve`` on the consuming module keeps its seam. ``optimization.optimizer`` keeps
re-exporting ``configure_solver`` and the three constants.

The module imports only OR-Tools, the optimization configuration and the result models, so
nothing in this package imports it in a cycle. A solve sequence (probe, primary, tie-break)
stays with its caller: the four sequences differ in hints, linearization level and budget
arithmetic, and a shared runner would bypass the names the tests patch.
"""

from ortools.sat.python import cp_model

from squadopt.optimization.config import OptimizationConfig
from squadopt.optimization.models import SolverExecutionError, SolverStatus

CP_SAT_SAFE_INTEGER_MAX = (1 << 62) - 1
MIN_TIEBREAK_TIME_SECONDS = 0.001
MIN_TIEBREAK_DETERMINISTIC_TIME = 1e-9


def raw_status_name(raw_status: int) -> str:
    names: dict[int, str] = {
        int(cp_model.OPTIMAL): "OPTIMAL",
        int(cp_model.FEASIBLE): "FEASIBLE",
        int(cp_model.INFEASIBLE): "INFEASIBLE",
        int(cp_model.UNKNOWN): "UNKNOWN",
        int(cp_model.MODEL_INVALID): "MODEL_INVALID",
    }
    return names.get(raw_status, f"UNRECOGNIZED({raw_status})")


def map_solver_status(raw_status: int) -> SolverStatus:
    """Map a CP-SAT status to the solver-independent public status."""

    if raw_status == cp_model.OPTIMAL:
        return SolverStatus.OPTIMAL
    if raw_status == cp_model.FEASIBLE:
        return SolverStatus.FEASIBLE
    if raw_status == cp_model.INFEASIBLE:
        return SolverStatus.INFEASIBLE
    if raw_status == cp_model.UNKNOWN:
        return SolverStatus.UNKNOWN
    if raw_status == cp_model.MODEL_INVALID:
        raise SolverExecutionError("CP-SAT rejected the generated model as invalid.")
    raise SolverExecutionError(f"CP-SAT returned an unrecognized status: {raw_status!r}.")


def configure_solver(
    solver: cp_model.CpSolver,
    config: OptimizationConfig,
    time_limit_seconds: float,
    deterministic_time_limit: float | None,
) -> None:
    """Apply this repository's solver settings; the single place they are decided.

    Public because three packages outside this one call it (`planning`, and both
    `scenarios` solvers), and a name that three packages consume is not private.

    Single search worker: CP-SAT's parallel search is nondeterministic, so a repeated
    solve would not be a repeated answer. Callers that record what produced a result read
    the value back from the configured solver rather than writing `1` beside it, so a
    provenance record cannot go on claiming a property this function has stopped providing.
    """

    solver.parameters.max_time_in_seconds = time_limit_seconds
    if deterministic_time_limit is not None:
        solver.parameters.max_deterministic_time = deterministic_time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.deterministic_seed


def deterministic_time_used(solver: cp_model.CpSolver, raw_status: int) -> float:
    """Return CP-SAT deterministic work consumed by a completed solve."""

    try:
        return float(solver.response_proto.deterministic_time)
    except RuntimeError as error:
        # An UNKNOWN result can be injected by a solver boundary test before a response
        # exists. Real CP-SAT calls always attach a response, including UNKNOWN ones.
        if raw_status == cp_model.UNKNOWN:
            return 0.0
        raise SolverExecutionError(
            "CP-SAT returned a status without response diagnostics."
        ) from error


def remaining_deterministic_time(
    configured_limit: float | None,
    consumed: float,
) -> float | None:
    """Return the deterministic budget left for a secondary solve."""

    if configured_limit is None:
        return None
    return max(0.0, configured_limit - consumed)


def solve(model: cp_model.CpModel, solver: cp_model.CpSolver) -> int:
    validation_message = model.validate()
    if validation_message:
        raise SolverExecutionError(f"CP-SAT rejected the generated model: {validation_message}")
    try:
        return int(solver.solve(model))
    except Exception as error:
        raise SolverExecutionError("CP-SAT failed while solving the squad model.") from error

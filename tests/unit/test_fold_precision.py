import numpy as np
import pytest

from squadopt.experiments.fold_precision import compare_precision


def test_residual_variance_is_not_precision_of_the_sample_centered_mean() -> None:
    x = np.arange(60, dtype=float)
    d = 2 * x + np.sin(x)
    result = compare_precision(d.tolist(), {"projected": x.tolist()})
    row = result["covariates"][0]
    assert row["residual_variance_ratio"] == pytest.approx(1 - row["correlation"] ** 2)
    assert row["conditional_residual_precision"]["mean"] == pytest.approx(d.mean())
    assert row["unconditional_mean_precision"] == result["raw"]
    assert result["validated_unconditional_precision_gain"] is False
    rng = np.random.default_rng(17)
    for _ in range(20):
        sample = rng.integers(0, len(x), len(x))
        boot = compare_precision(d[sample].tolist(), {"projected": x[sample].tolist()})
        assert boot["covariates"][0]["conditional_residual_precision"]["mean"] == pytest.approx(
            d[sample].mean()
        )


def test_forward_fit_does_not_train_on_its_evaluation_target() -> None:
    x = list(range(27))
    d = [float(value) for value in x]
    a = compare_precision(d, {"x": x})["covariates"][0]["forward_diagnostic"]["adjusted"]["mean"]
    d[-1] += 90
    b = compare_precision(d, {"x": x})["covariates"][0]["forward_diagnostic"]["adjusted"]["mean"]
    assert b - a == pytest.approx(30)


@pytest.mark.parametrize("bad", [[1, 2], [1, 2, float("nan")], [1, 2, True]])
def test_invalid_measurements_are_rejected(bad) -> None:
    with pytest.raises(ValueError):
        compare_precision(bad, {})


def test_constant_covariate_has_no_invented_correlation() -> None:
    report = compare_precision([1, 2, 3], {"constant": [1, 1, 1]})
    assert report["covariates"][0]["correlation"] is None
    assert report["largest_absolute_correlation"] is None

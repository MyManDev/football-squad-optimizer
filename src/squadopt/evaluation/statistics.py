"""Deterministic paired bootstrap shared by benchmarks and experiments."""

import hashlib
import random
from collections import defaultdict
from collections.abc import Iterator, Sequence
from statistics import fmean

from squadopt.evaluation.promotion import PromotionPolicy


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _bootstrap_seed(base_seed: int, candidate_id: str) -> int:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
    return base_seed + int(digest[:8], 16)


def season_aware_moving_block_indices(
    seasons: Sequence[str], *, policy: PromotionPolicy, candidate_id: str
) -> Iterator[tuple[int, ...]]:
    """Yield the existing bootstrap's fold indices, preserving whole-fold clusters."""

    grouped: dict[str, list[int]] = defaultdict(list)
    for index, season in enumerate(seasons):
        grouped[season].append(index)
    generator = random.Random(_bootstrap_seed(policy.deterministic_seed, candidate_id))
    for _ in range(policy.bootstrap_resamples):
        sample: list[int] = []
        for season in sorted(grouped):
            indices = grouped[season]
            block_length = min(policy.moving_block_length, len(indices))
            starts = len(indices) - block_length + 1
            season_sample: list[int] = []
            while len(season_sample) < len(indices):
                start = generator.randrange(starts)
                season_sample.extend(indices[start : start + block_length])
            sample.extend(season_sample[: len(indices)])
        yield tuple(sample)


def season_aware_moving_block_interval(
    differences: list[tuple[str, float]],
    *,
    policy: PromotionPolicy,
    candidate_id: str,
) -> tuple[float, float]:
    """Interval on paired per-fold differences, resampling blocks within a season.

    Shared by benchmarks and experiment designs so both use the same inference.
    ``differences`` pairs each fold's season with that fold's paired difference, so a
    resampled block never spans the boundary between two seasons.
    """

    means = [
        fmean(differences[index][1] for index in indices)
        for indices in season_aware_moving_block_indices(
            [season for season, _ in differences], policy=policy, candidate_id=candidate_id
        )
    ]

    alpha = (1.0 - policy.confidence_level) / 2.0
    return _percentile(means, alpha), _percentile(means, 1.0 - alpha)

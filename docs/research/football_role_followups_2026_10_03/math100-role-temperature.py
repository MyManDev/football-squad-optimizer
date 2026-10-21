"""One preregistered research-only temperature experiment; no production changes.

Import is safe for synthetic tests. Real reads/fits are confined to main(), which
requires the exact clean source and the measurement02 immutable input receipts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import copy
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pandas as pd
from scipy.special import expit

OWNER = Path('C:/Users/ertug/Desktop/MyManDev/projects/football-squad-optimizer')
TREE = Path('C:/Users/ertug/.codex/worktrees/planning-shortlist/football-squad-optimizer')
ARCHIVE = OWNER / 'data/raw/vaastav-fpl'
CAPTURES = OWNER / '.codex-tmp/fpl-news-120-real-chain-20261001T233213858427Z-82b6dabd/snapshots'
SNAPSHOT = 'fpl-live-20261001T233218Z-7945d6b3c732'
REFERENCE = OWNER / '.codex-tmp/math100-role-measure02'
OUTPUT = OWNER / '.codex-tmp/math100-role-temperature01'
EXPECTED_COMMIT = '64362f2c06a1957ebaa12128ce74cd9157e0227f'
EXPERIMENT = 'conditional_role_temperature_research_v1'
ARM = 'joint_role_temperature_research'
sys.dont_write_bytecode = True
sys.path[:0] = [str(TREE), str(TREE / 'src')]
from scripts import measure_football_role_minutes as study
from squadopt.prediction.football import JointRoleFootballModel
from squadopt.prediction.football_minutes_role import _CategoricalHead


def temperature_probabilities(probabilities, beta):
    """Fixed endpoints survive; beta=1 returns the identical two-class law."""
    p = np.asarray(probabilities, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
        raise ValueError('A finite binary role law is required.')
    if (p < 0).any() or (p > 1).any() or not np.allclose(p.sum(1), 1, rtol=0, atol=1e-12):
        raise ValueError('Invalid binary role probabilities.')
    if not math.isfinite(beta) or not .5 <= beta <= 1:
        raise ValueError('Inverse temperature must remain in [.5,1].')
    if beta == 1:
        return p.copy()
    r = p[:, 1].copy()
    interior = (r > 0) & (r < 1)
    logits = np.log(r[interior]) - np.log1p(-r[interior])
    r[interior] = expit(beta * logits)
    return np.column_stack((1 - r, r))


def choose_beta(probabilities, labels):
    """One convex scalar objective, fixed bounds and 48 derivative bisections.

    Correct deterministic endpoints add zero and have zero derivative. A wrong
    deterministic endpoint cannot be repaired by temperature and is unavailable.
    The inner objective is stable unfloored NLL; external evaluation keeps the
    runner's unchanged numerical floor, not a newly selected score convention.
    """
    p = temperature_probabilities(probabilities, 1)
    y = np.asarray(labels, dtype=float)
    if y.shape != (len(p),) or not np.isin(y, [0, 1]).all() or not len(y):
        raise ValueError('Nonempty aligned binary validation labels are required.')
    r = p[:, 1]
    if ((r == 0) & (y == 1)).any() or ((r == 1) & (y == 0)).any():
        return {'beta': 1., 'temperature': 1., 'status': 'unavailable_wrong_exact_endpoint'}
    interior = (r > 0) & (r < 1)
    if not interior.any():
        return {'beta': 1., 'temperature': 1., 'status': 'unavailable_no_interior_probability'}
    z = np.log(r[interior]) - np.log1p(-r[interior])
    observed = y[interior]

    def derivative(beta):
        return float(np.sum((expit(beta * z) - observed) * z) / len(y))

    def objective(beta):
        scaled = beta * z
        return float(np.sum(np.logaddexp(0, scaled) - observed * scaled) / len(y))

    low, high = .5, 1.
    if derivative(high) <= 0:
        beta = high
    elif derivative(low) >= 0:
        beta = low
    else:
        for _ in range(48):
            middle = (low + high) / 2
            if derivative(middle) > 0:
                high = middle
            else:
                low = middle
        beta = (low + high) / 2
    return {'beta': beta, 'temperature': 1 / beta, 'status': 'available',
            'inner_base_nll': objective(1.), 'inner_candidate_nll': objective(beta)}


def inner_temperature(train, outer_cutoff, before_fit=lambda metadata: None,
                      head_factory=_CategoricalHead):
    """The only fit is a prefix role head; no target labels or minute heads fit."""
    if train.empty or outer_cutoff.tzinfo is None:
        return {'beta': 1., 'temperature': 1., 'status': 'unavailable_empty_train',
                'inner_role_fits': 0}
    if not (train.kickoff + pd.Timedelta(hours=3) < outer_cutoff).all():
        raise ValueError('Outer training includes unsettled/future outcomes.')
    groups = sorted(set(zip(train.season.astype(str), train.GW.astype(int))))
    fallback = {'beta': 1., 'temperature': 1., 'inner_role_fits': 0}
    if len(groups) <= 4:
        return {**fallback, 'status': 'unavailable_insufficient_groups'}
    validation_groups = set(groups[-4:])
    validation_mask = pd.Series(
        [(str(s), int(w)) in validation_groups for s, w in zip(train.season, train.GW)],
        index=train.index,
    )
    validation = train.loc[validation_mask]
    cutoff = validation.kickoff.min() - pd.Timedelta(minutes=90)
    prefix = train.loc[~validation_mask & (train.kickoff + pd.Timedelta(hours=3) < cutoff)]
    known = lambda frame: frame.loc[frame.minutes.gt(0) & frame.starts.isin([0, 1])]
    prefix, validation = known(prefix), known(validation)
    counts = [int(validation.starts.eq(label).sum()) for label in (0, 1)]
    metadata = {'validation_groups': [list(v) for v in sorted(validation_groups)],
                'inner_cutoff': cutoff.isoformat(), 'prefix_known_rows': len(prefix),
                'validation_known_rows': len(validation), 'validation_class_counts': counts}
    if len(prefix) < 100 or len(validation) < 100 or min(counts) < 10:
        return {**fallback, **metadata, 'status': 'unavailable_insufficient_support'}
    if prefix.starts.nunique() != 2:
        return {**fallback, **metadata, 'status': 'unavailable_constant_prefix'}
    before_fit(metadata)
    head = head_factory(prefix, prefix.starts.to_numpy(dtype=np.int64), 2)
    selected = choose_beta(head.predict(validation), validation.starts.to_numpy(float))
    return {**selected, **metadata, 'inner_role_fits': 1}


class TemperatureHead:
    def __init__(self, original, beta):
        self.original, self.beta = original, beta

    def predict(self, target):
        return temperature_probabilities(self.original.predict(target), self.beta)


def calibrated_prediction(model, target, beta, *, role_steps=0):
    """Score an isolated fitted-state copy, never mutate/refit the base object."""
    if role_steps:
        raise ValueError('The temperature experiment supports only role_steps=0.')
    candidate = copy.deepcopy(model)
    original = candidate.role_minutes.role
    if original is not None:
        candidate.role_minutes.role = TemperatureHead(original, beta)
    result = JointRoleFootballModel.predict(candidate, target)
    result['model_version'] = EXPERIMENT
    result['minute_role_version'] = EXPERIMENT
    return result


def acceptance(base, candidate):
    """All preregistered gates; report every metric, never select a winning subset."""
    pairs = {(x['fold'], x['position']): x for x in candidate}
    keys = {(x['fold'], x['position']) for x in base if x['arm'] == 'joint_role'}
    if len(pairs) != len(candidate) or set(pairs) != keys:
        raise ValueError('Acceptance requires one-to-one complete origin/position pairs.')
    rows, gates = [], []
    for cohort, match in [('historical', lambda f: not f.startswith('2026-27')),
                          ('current', lambda f: f.startswith('2026-27')),
                          ('overall', lambda f: True)]:
        for position in study.POSITIONS:
            selected = [x for x in base if x['arm'] == 'joint_role'
                        and x['position'] == position and match(x['fold'])]
            if len(selected) != {'historical': 8, 'current': 5, 'overall': 13}[cohort]:
                raise ValueError('Acceptance requires all declared origins and positions.')
            population = ('rows', 'role_known_rows', 'role_unknown_rows', 'role_scored_rows')
            equal_population = all(
                all(x.get(k) == pairs[(x['fold'], position)].get(k) for k in population)
                and x.get('role_scored_rows', 0) > 0
                for x in selected
            )
            gates.append({'cohort': cohort, 'position': position,
                          'gate': 'identical_nonempty_paired_role_population',
                          'pass': equal_population})
            for key in sorted(k for k in selected[0]
                              if k.endswith(('_mae', '_mse', '_nll', '_brier', '_bias'))):
                paired = [(x[key], pairs[(x['fold'], position)][key]) for x in selected]
                available = [(a, b) for a, b in paired if a is not None and b is not None]
                a = sum(x for x, _ in available) / len(available) if available else None
                b = sum(x for _, x in available) / len(available) if available else None
                row = {'cohort': cohort, 'position': position, 'metric': key,
                       'paired_origins': len(available), 'base': a, 'candidate': b,
                       'candidate_minus_base': b-a if available else None}
                rows.append(row)
                required = key in ('role_nll', 'role_brier')
                if required and len(available) != len(selected):
                    gates.append({**row, 'gate': 'required_role_support', 'pass': False})
                elif required:
                    limit = a if position == 'ALL' else a * 1.01
                    gates.append({**row, 'gate': 'nonworse_all_or_position_1percent',
                                  'pass': b <= limit})
                if position == 'ALL' and cohort in ('historical', 'current') and key in (
                    'points_mae', 'minutes_mae'
                ):
                    gates.append({**row, 'gate': 'nonworse_points_or_minutes',
                                  'pass': len(available) == len(selected)
                                  and a is not None and b is not None and b <= a})
                if position == 'ALL' and cohort == 'overall' and key == 'role_nll':
                    gates.append({**row, 'gate': 'strict_overall_role_nll_gain',
                                  'pass': a is not None and b is not None and b < a})
    return {'accepted': all(x['pass'] for x in gates), 'gates': gates, 'all_metrics': rows}


def main():
    started = time.perf_counter()
    git = lambda *args: subprocess.run(['git', '-C', str(TREE), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
    if git('rev-parse', 'HEAD') != EXPECTED_COMMIT or git('status', '--porcelain') or OUTPUT.exists():
        raise RuntimeError('Exact clean source and new experiment output are required.')
    code_files = (Path(__file__), Path(__file__).with_name('test_math100_role_temperature.py'))
    code_hashes = lambda: {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in code_files}
    initial_code_hashes = code_hashes()
    initial_source_hashes = study._hashes(TREE, study.SOURCE_FILES)
    expected = {name: json.loads((REFERENCE/name).read_text()) for name in (
        'input-hashes.json', 'current-evidence.json', 'folds.json')}
    if len(expected['folds.json']) != 13:
        raise RuntimeError('Exactly thirteen frozen origins are required.')
    allowed = {ARCHIVE.resolve()/'data'/s/name for s in study.SEASONS for name in study.ARCHIVE_FILES}
    opened = set()

    def audit(event, args):
        if event not in ('open', 'os.listdir', 'os.scandir') or not args:
            return
        if not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        raw = Path(os.fsdecode(args[0])).absolute()
        if '2025-26' in raw.parts:
            raise PermissionError('Excluded-season access is forbidden.')
        if not raw.is_relative_to(ARCHIVE.resolve()):
            return
        if raw.resolve() != raw:
            raise PermissionError('Redirected archive path refused.')
        if event != 'open':
            if not any(raw.is_relative_to(ARCHIVE/'data'/s) for s in study.SEASONS):
                raise PermissionError('Archive enumeration outside allowed seasons refused.')
            return
        mode, flags = args[1], args[2]
        if raw not in allowed or (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
        ):
            raise PermissionError('Only the twelve frozen archive files may be read.')
        opened.add(raw.relative_to(ARCHIVE).as_posix())

    sys.addaudithook(audit)
    protocol = {'contract': EXPERIMENT, 'source_commit': EXPECTED_COMMIT,
                'measured_code_commit': '49b451ae011eba21e59a0932e3deea9333a1ca7d',
                'full_gate_commit': '49b451ae011eba21e59a0932e3deea9333a1ca7d',
                'docs_head_commit': EXPECTED_COMMIT,
                'operator_and_test_sha256': initial_code_hashes,
                'source_sha256': initial_source_hashes,
                'outer_origins': expected['folds.json'],
                'inner_validation': 'last_four_settled_distinct_season_GW_groups_of_causal_train',
                'inner_prefix': 'before_first_validation_kickoff_minus_90m_and_plus3h_settled',
                'support': {'prefix_known_min': 100, 'validation_known_min': 100,
                            'validation_each_label_min': 10, 'prefix_classes_required': 2},
                'fallback': 'T1_unavailable_without_support_or_with_wrong_deterministic_endpoint',
                'objective': 'stable_unfloored_conditional_binary_NLL',
                'beta_bounds': [.5, 1.], 'temperature_bounds': [1., 2.], 'bisections': 48,
                'fit_cap': {'outer': 13, 'inner_role': 13}, 'additional_full_model_fits': 0,
                'acceptance': ['ALL historical/current roleNLL and Brier nonworse',
                               'overall ALL roleNLL strict gain',
                               'each position historical/current/overall roleNLL and Brier at most1percent worse',
                               'ALL historical/current pointsMAE and minutesMAE nonworse'],
                'no_retry_or_search_after_failure': True, 'promotion': False,
                'development_assumption': 'temperature learned on prefix role head transfers to refitted full outer role head',
                'shared_q_caveat': 'appearance error affects absolute NLL but cancels in paired conditional-role NLL differences',
                'unchanged': ['q', 'zero mass', 'role conditional minutes', 'other fitted heads'],
                'external_evaluation_log_floor': study.LOG_FLOOR}
    verified, candidates, diagnostics, calibrations = set(), [], [], []
    counts = {'outer': 0, 'inner_role': 0}
    durations = []
    original_write = study.write

    def write_guard(path, value):
        if path.name in expected:
            if value != expected[path.name]:
                raise RuntimeError('Frozen input identity mismatch before fits.')
            verified.add(path.name)
        original_write(path, value)
        if path.name == 'protocol.json':
            original_write(OUTPUT/'temperature-protocol.json', protocol)

    study.write = write_guard

    def log_fit(kind, fold, metadata):
        if len(verified) != 3 or counts[kind] >= 13:
            raise RuntimeError('Input guard or explicit fit budget violated.')
        counts[kind] += 1
        with (OUTPUT/'temperature-fit-attempts.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps({'kind': kind, 'attempt': counts[kind], 'fold': fold,
                                  'event': 'started', **metadata})+'\n')
            log.flush()

    def finished_fit(kind, fold, fit_started, successful):
        receipt = {'kind': kind, 'fold': fold, 'event': 'finished',
                   'seconds': time.perf_counter() - fit_started, 'successful': successful}
        durations.append(receipt)
        with (OUTPUT/'temperature-fit-attempts.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(receipt)+'\n')
            log.flush()

    class ExperimentModel(JointRoleFootballModel):
        def __init__(self, train, past, *, cutoff):
            self.fold = '-gw'.join((str(expected['folds.json'][counts['outer']][0]),
                                   str(expected['folds.json'][counts['outer']][1]).zfill(2)))
            log_fit('outer', self.fold, {'cutoff': cutoff.isoformat()})
            fit_started, successful = time.perf_counter(), False
            try:
                super().__init__(train, past, cutoff=cutoff)
                successful = True
            finally:
                finished_fit('outer', self.fold, fit_started, successful)

            def timed_inner_head(frame, labels, classes):
                fit_started, successful = time.perf_counter(), False
                try:
                    head = _CategoricalHead(frame, labels, classes)
                    successful = True
                    return head
                finally:
                    finished_fit('inner_role', self.fold, fit_started, successful)

            self.calibration = inner_temperature(
                train, cutoff, lambda metadata: log_fit('inner_role', self.fold, metadata),
                timed_inner_head)
            calibrations.append({'fold': self.fold, **self.calibration})

        def predict(self, target, *, role_steps=0):
            base = super().predict(target, role_steps=role_steps)
            changed = calibrated_prediction(self, target, self.calibration['beta'],
                                            role_steps=role_steps)
            for field in ('appearance_probability', 'zero_probability', 'availability_multiplier'):
                if not np.array_equal(base[field].to_numpy(), changed[field].to_numpy()):
                    raise ValueError('The candidate changed protected appearance/availability.')
            per_fold, per_diagnostic = [], []
            for position in study.POSITIONS:
                mask = pd.Series(True, index=target.index) if position == 'ALL' else target.position.eq(position)
                if mask.any():
                    identity = {'fold': self.fold, 'position': position, 'arm': ARM}
                    per_fold.append({**identity, **study.losses(target.loc[mask], changed.loc[mask])})
                    per_diagnostic.append({**identity, **study.role_diagnostics(
                        target.loc[mask], changed.loc[mask], base.loc[mask, 'appearance_probability'])})
            candidates.extend(per_fold)
            diagnostics.extend(per_diagnostic)
            return base  # The original runner receives the unchanged base forecast.

    study.JointRoleFootballModel = ExperimentModel
    ok = study.run(ARCHIVE, OUTPUT, training_seasons=study.SEASONS,
                   snapshot_root=CAPTURES, snapshot_id=SNAPSHOT)
    original_write(OUTPUT/'temperature-calibration.json', calibrations)
    original_write(OUTPUT/'temperature-scores.json', candidates)
    original_write(OUTPUT/'temperature-diagnostics.json', diagnostics)
    equality = {name: (OUTPUT/name).read_bytes() == (REFERENCE/name).read_bytes() for name in (
        'scores.json', 'comparison.json', 'role-scores.json', 'role-comparison.json', 'role-diagnostics.json')}
    guards = {'clean_expected_commit': git('rev-parse', 'HEAD') == EXPECTED_COMMIT
              and not git('status', '--porcelain'),
              'tracked_source_hashes_unchanged': study._hashes(TREE, study.SOURCE_FILES)
              == initial_source_hashes,
              'operator_and_test_hashes_unchanged': code_hashes() == initial_code_hashes}
    complete = (ok and all(equality.values()) and all(guards.values())
                and counts['outer'] == 13 and len(candidates) == 65)
    decision = acceptance(json.loads((OUTPUT/'scores.json').read_text()), candidates) if complete else None
    original_write(OUTPUT/'temperature-comparison.json', decision)
    original_write(OUTPUT/'temperature-result.json', {
        'contract': EXPERIMENT, 'status': 'complete' if complete else 'incomplete',
        'base_output_byte_equal': equality, 'fit_attempts': counts,
        'end_of_run_guards': guards, 'fit_durations': durations,
        'outer_fit_seconds': sum(x['seconds'] for x in durations if x['kind'] == 'outer'),
        'inner_role_fit_seconds': sum(x['seconds'] for x in durations if x['kind'] == 'inner_role'),
        'total_wall_seconds': time.perf_counter() - started,
        'candidate_accepted': decision['accepted'] if decision else False,
        'predictive_superiority_verified': False, 'promotion': False,
        'archive_files_opened': sorted(opened), 'excluded_season_access': False,
        'provider_calls': 0, 'live_changes': False,
    })
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""One unexecuted research candidate: retained-history indicator in the role head only.

No data is opened or model fitted on import. main() is a separately authorized,
fixed-readset operator; it is not a production model or promotion command.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import warnings

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

OWNER = Path('C:/Users/ertug/Desktop/MyManDev/projects/football-squad-optimizer')
TREE = Path('C:/Users/ertug/.codex/worktrees/planning-shortlist/football-squad-optimizer')
ARCHIVE = OWNER / 'data/raw/vaastav-fpl'
CAPTURES = OWNER / '.codex-tmp/fpl-news-120-real-chain-20261001T233213858427Z-82b6dabd/snapshots'
SNAPSHOT = 'fpl-live-20261001T233218Z-7945d6b3c732'
REFERENCE = OWNER / '.codex-tmp/math100-role-measure02'
OUTPUT = OWNER / '.codex-tmp/math100-role-retained-support01'
EXPECTED_COMMIT = '64362f2c06a1957ebaa12128ce74cd9157e0227f'
EXPERIMENT = 'conditional_role_retained_history_support_research_v1'
ARM = 'joint_role_retained_history_support_research'
INDICATOR = 'has_retained_player_history'
PREREGISTERED = Path(__file__).with_name('math100-role-retained-support-preregistered.json')
sys.dont_write_bytecode = True
sys.path[:0] = [str(TREE), str(TREE / 'src')]
from scripts import measure_football_role_minutes as study
from squadopt.prediction.football import JointRoleFootballModel
from squadopt.prediction.football_features import FEATURES


def retained_design(frame):
    """Existing causal features unchanged, plus one missing-vs-present indicator.

    past_rows includes retained older seasons and observed zero-minute rows. It
    does not assert recent fitness, current eligibility or why history is absent.
    """
    design = frame.loc[:, list(FEATURES)].to_numpy(float, copy=True)
    past = frame.past_rows.to_numpy(float)
    if not np.isfinite(design).all():
        raise ValueError('Role features must be finite.')
    if (past < 0).any() or not np.equal(past, np.floor(past)).all():
        raise ValueError('Retained history counts must be nonnegative integers.')
    return np.column_stack((design, (past > 0).astype(float)))


class RetainedHistoryHead:
    """Same native two-class fit and fallback, with exactly one extra column."""
    def __init__(self, frame, labels):
        labels = np.asarray(labels)
        if labels.shape != (len(frame),) or not np.isin(labels, [0, 1]).all():
            raise ValueError('Aligned binary recorded-start labels are required.')
        design = retained_design(frame)
        self.constant = None
        self.model = None
        if not len(frame):
            self.constant = np.zeros(2)
        elif len(np.unique(labels)) == 1:
            self.constant = np.eye(2)[int(labels[0])]
        else:
            self.model = make_pipeline(
                StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=0)
            )
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                try:
                    self.model.fit(design, labels)
                except ConvergenceWarning as error:
                    raise ValueError('Retained-support role fit did not converge.') from error

    def predict(self, frame):
        design = retained_design(frame)
        if self.constant is not None:
            return np.tile(self.constant, (len(frame), 1))
        output = np.zeros((len(frame), 2))
        output[:, self.model[-1].classes_.astype(int)] = self.model.predict_proba(design)
        return output


def candidate_model(base, train, before_fit=lambda metadata: None, head_factory=RetainedHistoryHead):
    """Never mutate the base model or share fitted candidate heads across experiments."""
    changed = deepcopy(base)
    labels = train.get('starts', pd.Series(np.nan, index=train.index))
    appeared = train.minutes.gt(0)
    if (labels.notna() & ~labels.isin([0, 1])).any() or (labels.eq(1) & ~appeared).any():
        raise ValueError('Recorded starts must be binary and require positive minutes.')
    known = appeared & labels.isin([0, 1])
    fitted = train.loc[known]
    metadata = {
        'feature_count': len(FEATURES) + 1,
        'added_feature': INDICATOR,
        'known_role_rows': int(known.sum()),
        'unknown_role_rows': int((appeared & labels.isna()).sum()),
        'known_without_retained_history': int(fitted.past_rows.eq(0).sum()),
        'known_with_retained_history': int(fitted.past_rows.gt(0).sum()),
        'head_fit_attempts': 0,
        'estimator_fit_attempts': 0,
    }
    if not len(fitted):
        if base.role_minutes.role is not None:
            raise ValueError('Native and candidate role support differ.')
        return changed, {**metadata, 'status': 'unavailable_no_known_start_labels'}
    if base.role_minutes.role is None:
        raise ValueError('Native and candidate role support differ.')
    metadata.update(head_fit_attempts=1, estimator_fit_attempts=int(labels.loc[known].nunique() > 1))
    before_fit(metadata)
    changed.role_minutes.role = head_factory(fitted, labels.loc[known].to_numpy(dtype=np.int64))
    metadata['status'] = 'fitted' if metadata['estimator_fit_attempts'] else 'constant_recorded_class'
    return changed, metadata


def acceptance(base, candidate):
    """Require all fixed origins and identical populations before comparing losses."""
    required = {(f'{s}-gw{w:02d}', p) for s, w in (
        *study.ORIGINS, *((study.CURRENT_SEASON, w) for w in range(1, 6))
    ) for p in study.POSITIONS}
    baseline = [r for r in base if r['arm'] == 'joint_role']
    before = {(r['fold'], r['position']): r for r in baseline}
    after = {(r['fold'], r['position']): r for r in candidate}
    if len(before) != len(baseline) or len(after) != len(candidate):
        raise ValueError('Duplicate origin/position records are refused.')
    if set(before) != required or set(after) != required or any(r['arm'] != ARM for r in candidate):
        raise ValueError('Exactly all thirteen origins and five positions are required.')
    counts = ('rows', 'role_known_rows', 'role_unknown_rows', 'role_scored_rows')
    for key in required:
        if any(before[key][c] != after[key][c] for c in counts):
            raise ValueError('Role comparison populations must be exactly equal.')
    rows, gates = [], []
    for cohort, match in (
        ('historical', lambda fold: not fold.startswith(study.CURRENT_SEASON)),
        ('current', lambda fold: fold.startswith(study.CURRENT_SEASON)),
        ('overall', lambda fold: True),
    ):
        for position in study.POSITIONS:
            selected = sorted(k for k in required if k[1] == position and match(k[0]))
            metrics = sorted(k for k in before[selected[0]] if k.endswith(('_mae', '_mse', '_nll', '_brier', '_bias')))
            for metric in metrics:
                pairs = [(before[k][metric], after[k][metric]) for k in selected]
                available = [(float(a), float(b)) for a, b in pairs if a is not None and b is not None]
                if available and not np.isfinite(available).all():
                    raise ValueError('Losses must be finite.')
                complete = len(available) == len(selected)
                a = sum(a for a, _ in available) / len(available) if available else None
                b = sum(b for _, b in available) / len(available) if available else None
                row = {'cohort': cohort, 'position': position, 'metric': metric,
                       'paired_origins': len(available), 'required_origins': len(selected),
                       'base': a, 'candidate': b, 'candidate_minus_base': b - a if available else None}
                rows.append(row)
                if metric in ('role_nll', 'role_brier'):
                    supported = complete and all(int(before[k]['role_scored_rows']) > 0 for k in selected)
                    limit = a if position == 'ALL' else a * 1.01 if a is not None else None
                    gates.append({**row, 'gate': 'complete_nonworse_ALL_or_position_1percent',
                                  'pass': bool(supported and a is not None and b is not None and b <= limit)})
                if position == 'ALL' and cohort in ('historical', 'current') and metric in ('points_mae', 'minutes_mae'):
                    gates.append({**row, 'gate': 'complete_nonworse_points_or_minutes',
                                  'pass': bool(complete and a is not None and b is not None and b <= a)})
                if position == 'ALL' and cohort == 'overall' and metric == 'role_nll':
                    gates.append({**row, 'gate': 'strict_overall_role_nll_gain',
                                  'pass': bool(complete and a is not None and b is not None and b < a)})
    if not gates:
        raise ValueError('No acceptance gates were evaluated.')
    return {'accepted': all(x['pass'] for x in gates), 'gates': gates, 'all_metrics': rows}


def main():
    started = time.perf_counter()
    def git(*args):
        return subprocess.run(['git', '-C', str(TREE), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    if git('rev-parse', 'HEAD') != EXPECTED_COMMIT or git('status', '--porcelain') or OUTPUT.exists():
        raise RuntimeError('Exact clean source and a new experiment output are required.')
    prereg = json.loads(PREREGISTERED.read_text(encoding='utf-8'))
    code_files = (Path(__file__), Path(__file__).with_name('test_math100_role_retained_support.py'),
                  Path(__file__).with_name('math100-role-retained-support.md'), PREREGISTERED)
    def code_hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files}
    initial_code = code_hashes()
    initial_source = study._hashes(TREE, study.SOURCE_FILES)
    if initial_source != prereg['source_sha256'] or prereg['source_commit'] != EXPECTED_COMMIT:
        raise RuntimeError('Preregistered source identity differs; no data access or fit allowed.')
    expected = {name: json.loads((REFERENCE / name).read_text()) for name in (
        'input-hashes.json', 'current-evidence.json', 'folds.json')}
    if expected != prereg['frozen_input_receipts'] or len(expected['folds.json']) != 13:
        raise RuntimeError('Preregistered immutable reference receipts differ.')
    archive = ARCHIVE.resolve()
    allowed = {archive / 'data' / season / name for season in study.SEASONS for name in study.ARCHIVE_FILES}
    opened = set()
    def audit(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            raise PermissionError('Network is not part of this experiment.')
        if event not in ('open', 'os.listdir', 'os.scandir') or not args:
            return
        if not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        raw = Path(os.fsdecode(args[0])).absolute()
        if '2025-26' in raw.parts:
            raise PermissionError('Excluded-season access is forbidden.')
        if not raw.is_relative_to(archive):
            return
        if raw.resolve() != raw:
            raise PermissionError('Redirected archive paths refused.')
        if event != 'open':
            if not any(raw.is_relative_to(archive / 'data' / season) for season in study.SEASONS):
                raise PermissionError('Archive enumeration outside selected seasons refused.')
            return
        mode, flags = args[1], args[2]
        if raw not in allowed or (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise PermissionError('Only the twelve declared archive files may be read.')
        opened.add(raw.relative_to(archive).as_posix())
    sys.addaudithook(audit)
    original_write = study.write
    original_model = study.JointRoleFootballModel
    verified, candidates, diagnostics, support, durations = set(), [], [], [], []
    counts = {'outer': 0, 'role_head': 0, 'role_estimator': 0}
    failed = False
    protocol = {**prereg, 'operator_inputs_sha256': initial_code,
                'raw_old_prediction_matrices_available': False,
                'saved_baseline_output_byte_equality_required': True,
                'same_run_baseline_predictions_exactly_unchanged_required': True}
    def guarded_write(path, value):
        if path.name in expected:
            if value != expected[path.name]:
                raise RuntimeError('Frozen input identity changed; no fit allowed.')
            verified.add(path.name)
        if path.name == 'failures.json' and value:
            nonlocal failed
            failed = True
        original_write(path, value)
        if path.name == 'protocol.json':
            original_write(OUTPUT / 'retained-support-protocol.json', protocol)
    study.write = guarded_write
    def log(record):
        with (OUTPUT / 'retained-support-fit-attempts.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, allow_nan=False) + '\n')
            stream.flush()
    def before_fit(kind, fold, metadata):
        if failed or len(verified) != 3 or counts[kind] >= 13:
            raise RuntimeError('Frozen-input, prior-failure or fixed fit-budget guard failed.')
        counts[kind] += 1
        log({'event': 'started', 'kind': kind, 'attempt': counts[kind], 'fold': fold, **metadata})
    def finished_fit(kind, fold, start, successful):
        receipt = {'event': 'finished', 'kind': kind, 'fold': fold,
                   'seconds': time.perf_counter() - start, 'successful': successful}
        durations.append(receipt)
        log(receipt)
    class ExperimentModel(JointRoleFootballModel):
        def __init__(self, train, past, *, cutoff):
            if counts['outer'] >= 13:
                raise RuntimeError('Outer fit budget exhausted.')
            season, week = expected['folds.json'][counts['outer']]
            self.fold = f'{season}-gw{week:02d}'
            before_fit('outer', self.fold, {'cutoff': cutoff.isoformat()})
            fit_started, successful = time.perf_counter(), False
            try:
                super().__init__(train, past, cutoff=cutoff)
                successful = True
            finally:
                finished_fit('outer', self.fold, fit_started, successful)
            def before_head(metadata):
                before_fit('role_head', self.fold, metadata)
                counts['role_estimator'] += metadata['estimator_fit_attempts']
            def timed_head(frame, labels):
                fit_started, successful = time.perf_counter(), False
                try:
                    result = RetainedHistoryHead(frame, labels)
                    successful = True
                    return result
                finally:
                    finished_fit('role_head', self.fold, fit_started, successful)
            self.changed, metadata = candidate_model(self, train, before_head, timed_head)
            support.append({'fold': self.fold, **metadata})
        def predict(self, target, *, role_steps=0):
            if role_steps or set(zip(target.season, target.GW)) != {
                (self.fold[:7], int(self.fold[-2:]))
            }:
                raise ValueError('Exact declared origin and role_steps=0 are required.')
            base = JointRoleFootballModel.predict(self, target)
            changed = JointRoleFootballModel.predict(self.changed, target)
            for field in ('appearance_probability', 'zero_probability', 'availability_multiplier'):
                if not np.array_equal(base[field].to_numpy(), changed[field].to_numpy()):
                    raise ValueError('Candidate changed protected appearance/eligibility.')
            assert_frame_equal(base, JointRoleFootballModel.predict(self, target), check_exact=True)
            changed['model_version'] = EXPERIMENT
            changed['minute_role_version'] = EXPERIMENT
            fold_scores, fold_diagnostics = [], []
            for position in study.POSITIONS:
                mask = pd.Series(True, index=target.index) if position == 'ALL' else target.position.eq(position)
                if mask.any():
                    identity = {'fold': self.fold, 'position': position, 'arm': ARM}
                    fold_scores.append({**identity, **study.losses(target.loc[mask], changed.loc[mask])})
                    fold_diagnostics.append({**identity, **study.role_diagnostics(
                        target.loc[mask], changed.loc[mask], base.loc[mask, 'appearance_probability'])})
            candidates.extend(fold_scores)
            diagnostics.extend(fold_diagnostics)
            original_write(OUTPUT / 'retained-support-scores.json', candidates)
            original_write(OUTPUT / 'retained-support-diagnostics.json', diagnostics)
            original_write(OUTPUT / 'retained-support-support.json', support)
            return base
    study.JointRoleFootballModel = ExperimentModel
    try:
        ok = study.run(ARCHIVE, OUTPUT, training_seasons=study.SEASONS,
                       snapshot_root=CAPTURES, snapshot_id=SNAPSHOT)
    finally:
        study.JointRoleFootballModel = original_model
        study.write = original_write
    names = ('scores.json', 'comparison.json', 'role-scores.json', 'role-comparison.json', 'role-diagnostics.json')
    equality = {name: (OUTPUT / name).read_bytes() == (REFERENCE / name).read_bytes() for name in names}
    guards = {'clean_expected_commit': git('rev-parse', 'HEAD') == EXPECTED_COMMIT and not git('status', '--porcelain'),
              'source_hashes_unchanged': study._hashes(TREE, study.SOURCE_FILES) == initial_source,
              'operator_inputs_unchanged': code_hashes() == initial_code}
    complete = ok and all(equality.values()) and all(guards.values()) and counts['outer'] == 13 and len(candidates) == 65
    decision = acceptance(json.loads((OUTPUT / 'scores.json').read_text()), candidates) if complete else None
    original_write(OUTPUT / 'retained-support-comparison.json', decision)
    original_write(OUTPUT / 'retained-support-result.json', {
        'contract': EXPERIMENT, 'status': 'complete' if complete else 'incomplete',
        'base_saved_output_byte_equal': equality, 'end_of_run_guards': guards,
        'fit_attempts': counts, 'fit_durations': durations,
        'total_wall_seconds': time.perf_counter() - started,
        'candidate_accepted': decision['accepted'] if decision else False,
        'predictive_superiority_verified': False, 'promotion': False,
        'archive_files_opened': sorted(opened), 'excluded_season_access': False,
        'provider_calls': 0, 'live_changes': False,
    })
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())

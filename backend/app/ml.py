"""The learning half of the roster builder.

Rostering has hard rules that a statistical model must never be allowed to
break, so the machine learning here does the part it is actually good at -
*preference*: given everything the team has done in previous months, how good
is each legal option? The optimiser in :mod:`app.solver` then picks the
highest-scoring combination that still satisfies every rule.

Two rankers are trained, one for shifts and one for week-off blocks. Both learn
from the uploaded rosters and are refit every time a new month arrives, so the
scores track how the team actually rotates. Until enough months have been
uploaded to trust them, their output is blended with transparent heuristic
priors - the blend weight moves towards the model as history accumulates, which
is what makes the behaviour "dynamic" rather than a fixed rule set.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import numpy as np

from .config import MODEL_DIR, OFF_DAYS_PER_WEEK, SHIFTS, SHIFT_INDEX
from .features import OFF_FEATURES, SHIFT_FEATURES, Aggregates
from .models import MonthRoster

#: How fast the blend moves from heuristics to the learned model.
_BLEND_HALFLIFE = 2.0
_MAX_BLEND = 0.85


@dataclass
class ModelMetrics:
    trained: bool = False
    estimator: str = "none"
    n_samples: int = 0
    n_months: int = 0
    top1_accuracy: Optional[float] = None
    roc_auc: Optional[float] = None
    evaluation: str = "not evaluated"
    blend_weight: float = 0.0
    top_features: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrainingReport:
    n_history_months: int
    months: list[str]
    shift: ModelMetrics
    off: ModelMetrics
    trained_at: str
    version: str

    def to_dict(self) -> dict:
        return {
            "n_history_months": self.n_history_months,
            "months": self.months,
            "shift_model": self.shift.to_dict(),
            "off_model": self.off.to_dict(),
            "trained_at": self.trained_at,
            "version": self.version,
        }


class CandidateRanker:
    """Scores one candidate at a time; the winner is whichever ranks highest."""

    def __init__(self, name: str, feature_names: list[str]):
        self.name = name
        self.feature_names = feature_names
        self.estimator = None
        self.metrics = ModelMetrics()

    # -- training ---------------------------------------------------------
    @staticmethod
    def _make_estimator(n_samples: int):
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        if n_samples >= 1500:
            return "HistGradientBoostingClassifier", HistGradientBoostingClassifier(
                max_depth=3, max_iter=200, learning_rate=0.08, min_samples_leaf=10,
                l2_regularization=1.0, random_state=0)
        # Small history: a regularised linear ranker generalises far better and
        # its coefficients double as an explanation of what was learned.
        return "LogisticRegression", Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced")),
        ])

    def fit(self, X: np.ndarray, y: np.ndarray, groups: list, month_index: list[int]) -> ModelMetrics:
        metrics = ModelMetrics(n_samples=int(len(y)),
                               n_months=len(set(month_index)) if len(month_index) else 0)
        if len(y) == 0 or len(set(y.tolist())) < 2:
            metrics.evaluation = ("not enough history yet - upload more months to "
                                  "start training this model")
            self.estimator = None
            self.metrics = metrics
            return metrics

        name, estimator = self._make_estimator(len(y))
        metrics.estimator = name

        # Time-ordered hold-out: train on the older months, score the newest one.
        unique_months = sorted(set(month_index))
        if len(unique_months) >= 2:
            last = unique_months[-1]
            train_mask = np.array([m != last for m in month_index])
            test_mask = ~train_mask
            if len(set(y[train_mask].tolist())) == 2 and test_mask.sum():
                holdout = self._make_estimator(int(train_mask.sum()))[1]
                holdout.fit(X[train_mask], y[train_mask])
                scores = holdout.predict_proba(X[test_mask])[:, 1]
                metrics.top1_accuracy = _top1_accuracy(
                    scores, y[test_mask], [g for g, keep in zip(groups, test_mask) if keep])
                metrics.roc_auc = _safe_auc(y[test_mask], scores)
                metrics.evaluation = (f"held out {len(unique_months) - 1} month(s) of history "
                                      f"to predict the newest one")
        if metrics.top1_accuracy is None:
            estimator.fit(X, y)
            scores = estimator.predict_proba(X)[:, 1]
            metrics.top1_accuracy = _top1_accuracy(scores, y, groups)
            metrics.roc_auc = _safe_auc(y, scores)
            metrics.evaluation = "in-sample only - one month of history"

        estimator.fit(X, y)
        self.estimator = estimator
        metrics.top_features = self._explain(estimator, X, y)
        metrics.trained = True
        metrics.blend_weight = blend_weight(metrics.n_months)
        self.metrics = metrics
        return metrics

    def _explain(self, estimator, X: np.ndarray, y: np.ndarray) -> list[tuple[str, float]]:
        """What the model actually keyed on - shown in the UI and the Model sheet.

        Linear models hand over signed coefficients directly; for the boosted
        model there are none, so fall back to permutation importance (unsigned:
        how much the ranking degrades when a feature is shuffled).
        """
        clf = estimator[-1] if hasattr(estimator, "steps") else estimator
        coefficients = getattr(clf, "coef_", None)
        if coefficients is not None:
            weights = list(zip(self.feature_names, coefficients[0].tolist()))
            weights.sort(key=lambda item: abs(item[1]), reverse=True)
            return [(name, round(value, 3)) for name, value in weights[:6]]

        try:
            from sklearn.inspection import permutation_importance

            # A sample is plenty, and keeps training snappy on long histories.
            limit = min(len(y), 2000)
            result = permutation_importance(estimator, X[:limit], y[:limit], n_repeats=5,
                                            random_state=0, scoring="roc_auc")
            weights = list(zip(self.feature_names, result.importances_mean.tolist()))
            weights.sort(key=lambda item: abs(item[1]), reverse=True)
            return [(name, round(value, 4)) for name, value in weights[:6]]
        except Exception:
            return []

    # -- scoring ----------------------------------------------------------
    def score(self, features: list[float]) -> Optional[float]:
        if self.estimator is None:
            return None
        return float(self.estimator.predict_proba(np.asarray([features]))[0, 1])

    def score_many(self, rows: list[list[float]]) -> Optional[np.ndarray]:
        if self.estimator is None or not rows:
            return None
        return self.estimator.predict_proba(np.asarray(rows))[:, 1]


def blend_weight(n_months: int) -> float:
    """0 with no history, rising towards :data:`_MAX_BLEND` as months accumulate."""
    if n_months <= 0:
        return 0.0
    return round(min(_MAX_BLEND, n_months / (n_months + _BLEND_HALFLIFE)), 3)


def _top1_accuracy(scores: np.ndarray, y: np.ndarray, groups: list) -> float:
    """Per decision (one employee, one month): did the true choice rank first?"""
    by_group: dict = {}
    for score, label, group in zip(scores, y, groups):
        by_group.setdefault(group, []).append((score, label))
    if not by_group:
        return 0.0
    hits = sum(1 for rows in by_group.values() if max(rows, key=lambda r: r[0])[1] == 1)
    return round(hits / len(by_group), 3)


def _matrix(rows: list[list[float]], n_features: int) -> np.ndarray:
    """An empty training set is normal on the first upload, not an error."""
    if not rows:
        return np.empty((0, n_features), dtype=float)
    return np.asarray(rows, dtype=float)


def _safe_auc(y: np.ndarray, scores: np.ndarray) -> Optional[float]:
    from sklearn.metrics import roc_auc_score
    if len(set(y.tolist())) < 2:
        return None
    return round(float(roc_auc_score(y, scores)), 3)


# ------------------------------------------------------------- priors ------
def prior_shift_score(aggregates: Aggregates, name: str, previous_shift: str,
                      candidate: str) -> float:
    """Transparent fallback: rotate forward, spread the Night load, vary shifts."""
    distance = (SHIFT_INDEX[candidate] - SHIFT_INDEX[previous_shift]) % len(SHIFTS)
    score = 0.5
    score += 0.25 if distance == 1 else (0.08 if distance == 2 else 0.0)
    share = aggregates._employee_share(name, candidate)
    score += 0.15 * (1.0 - share)
    if candidate == "Night":
        score -= 0.30 * aggregates.night_share(name)
    return float(min(1.0, max(0.0, score)))


def prior_off_score(aggregates: Aggregates, name: str, shift: str, start: int,
                    off_length: int) -> float:
    """Rotate the week-off away from last month's, and share out weekend offs."""
    from .config import off_block

    block = off_block(start, off_length)
    score = 0.5
    score += 0.20 * (1.0 - aggregates._start_share(name, start))
    if aggregates.employee_last_start.get(name) == start:
        score -= 0.25
    if any(day >= 5 for day in block):
        score += 0.20 * (1.0 - aggregates._weekend_off_share(name))
    return float(min(1.0, max(0.0, score)))


# ------------------------------------------------------------ learner ------
class RosterLearner:
    """Owns both rankers, the aggregates they read, and the blend with priors."""

    def __init__(self) -> None:
        self.shift_ranker = CandidateRanker("shift", SHIFT_FEATURES)
        self.off_ranker = CandidateRanker("off", OFF_FEATURES)
        self.aggregates = Aggregates()
        self.report: Optional[TrainingReport] = None

    # -- training ---------------------------------------------------------
    def train(self, months: list[MonthRoster]) -> TrainingReport:
        months = sorted(months, key=lambda m: m.month)
        aggregates = Aggregates()

        shift_X: list[list[float]] = []
        shift_y: list[int] = []
        shift_groups: list = []
        shift_month: list[int] = []
        off_X: list[list[float]] = []
        off_y: list[int] = []
        off_groups: list = []
        off_month: list[int] = []

        for index, roster in enumerate(months):
            for employee in roster.employees:
                clients = len(employee.clients)
                previous = aggregates.previous_shift(employee.name)
                # A shift decision is only a usable example when we know what
                # they moved from and they actually moved.
                if previous and employee.shift and employee.shift != previous:
                    for candidate in SHIFTS:
                        if candidate == previous:
                            continue
                        shift_X.append(aggregates.shift_features(
                            employee.name, previous, candidate, clients))
                        shift_y.append(1 if candidate == employee.shift else 0)
                        shift_groups.append((index, employee.name))
                        shift_month.append(index)

                if employee.shift and employee.off_start is not None:
                    off_length = employee.off_length or OFF_DAYS_PER_WEEK[employee.shift]
                    for start in range(7):
                        off_X.append(aggregates.off_features(
                            employee.name, employee.shift, start, off_length, clients))
                        off_y.append(1 if start == employee.off_start else 0)
                        off_groups.append((index, employee.name))
                        off_month.append(index)
            aggregates.update(roster)

        shift_metrics = self.shift_ranker.fit(
            _matrix(shift_X, len(SHIFT_FEATURES)),
            np.asarray(shift_y, dtype=int), shift_groups, shift_month)
        off_metrics = self.off_ranker.fit(
            _matrix(off_X, len(OFF_FEATURES)),
            np.asarray(off_y, dtype=int), off_groups, off_month)

        self.aggregates = aggregates
        self.report = TrainingReport(
            n_history_months=len(months),
            months=[m.month for m in months],
            shift=shift_metrics,
            off=off_metrics,
            trained_at=dt.datetime.now().isoformat(timespec="seconds"),
            version=f"{len(months)}m-{dt.datetime.now():%Y%m%d%H%M%S}",
        )
        return self.report

    # -- scoring ----------------------------------------------------------
    def score_shift(self, name: str, previous_shift: str, candidate: str,
                    client_count: int) -> tuple[float, float, Optional[float]]:
        """Returns (blended, prior, model) - all in 0..1."""
        prior = prior_shift_score(self.aggregates, name, previous_shift, candidate)
        model = None
        if self.shift_ranker.estimator is not None:
            model = self.shift_ranker.score(self.aggregates.shift_features(
                name, previous_shift, candidate, client_count))
        weight = self.shift_ranker.metrics.blend_weight if model is not None else 0.0
        blended = weight * (model or 0.0) + (1 - weight) * prior
        return blended, prior, model

    def score_off(self, name: str, shift: str, start: int, client_count: int
                  ) -> tuple[float, float, Optional[float]]:
        off_length = OFF_DAYS_PER_WEEK[shift]
        prior = prior_off_score(self.aggregates, name, shift, start, off_length)
        model = None
        if self.off_ranker.estimator is not None:
            model = self.off_ranker.score(self.aggregates.off_features(
                name, shift, start, off_length, client_count))
        weight = self.off_ranker.metrics.blend_weight if model is not None else 0.0
        blended = weight * (model or 0.0) + (1 - weight) * prior
        return blended, prior, model

    # -- persistence ------------------------------------------------------
    def save(self, directory: Path | str = MODEL_DIR) -> Path:
        import joblib

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "roster_model.joblib"
        joblib.dump({
            "shift_ranker": self.shift_ranker,
            "off_ranker": self.off_ranker,
            "aggregates": self.aggregates,
            "report": self.report,
        }, path)
        return path

    @classmethod
    def load(cls, directory: Path | str = MODEL_DIR) -> Optional["RosterLearner"]:
        import joblib

        path = Path(directory) / "roster_model.joblib"
        if not path.exists():
            return None
        payload = joblib.load(path)
        learner = cls()
        learner.shift_ranker = payload["shift_ranker"]
        learner.off_ranker = payload["off_ranker"]
        learner.aggregates = payload["aggregates"]
        learner.report = payload.get("report")
        return learner

"""The model has to be useful on day one and better by month four."""
from app.ml import RosterLearner, blend_weight
from conftest import month_roster


def test_cold_start_falls_back_to_heuristics(team):
    """First upload: nothing to learn from yet, so scores come from the priors."""
    learner = RosterLearner()
    report = learner.train([])

    blended, prior, model = learner.score_shift("Person 1", "Morning", "Afternoon", 3)
    assert model is None
    assert blended == prior > 0
    assert report.shift.trained is False
    assert "upload more months" in report.shift.evaluation


def test_one_month_teaches_week_offs_but_not_shift_moves(team):
    """A single month shows week-off blocks, but no shift *change* to learn from."""
    learner = RosterLearner()
    report = learner.train([month_roster(team, "2025-06")])

    assert report.shift.trained is False          # a move needs two months
    assert report.off.trained is True
    assert report.off.n_samples == len(team) * 7


def test_the_model_learns_the_rotation_the_team_actually_uses(team):
    """Four months of Morning->Afternoon->Evening->Night makes the model prefer it."""
    history = [month_roster(team, f"2025-{month:02d}", shift_offset=offset)
               for offset, month in enumerate(range(3, 7))]
    learner = RosterLearner()
    report = learner.train(history)

    assert report.shift.trained is True
    assert report.shift.top1_accuracy >= 0.9
    assert report.shift.blend_weight > 0.5

    forward, _, model_forward = learner.score_shift("Person 1", "Morning", "Afternoon", 3)
    backward, _, model_back = learner.score_shift("Person 1", "Morning", "Evening", 3)
    assert model_forward is not None and model_forward > model_back
    assert forward > backward

    names = [name for name, _ in report.shift.top_features]
    assert "is_forward_rotation" in names        # and it can say why


def test_more_history_shifts_weight_from_heuristics_to_the_model():
    assert blend_weight(0) == 0.0
    assert blend_weight(1) < blend_weight(3) < blend_weight(12) <= 0.85


def test_training_survives_a_restart(team, tmp_path):
    history = [month_roster(team, f"2025-{month:02d}", shift_offset=offset)
               for offset, month in enumerate(range(3, 7))]
    learner = RosterLearner()
    learner.train(history)
    learner.save(tmp_path)

    reloaded = RosterLearner.load(tmp_path)
    assert reloaded is not None
    assert reloaded.report.shift.top1_accuracy == learner.report.shift.top1_accuracy
    assert (reloaded.score_shift("Person 1", "Morning", "Afternoon", 3)
            == learner.score_shift("Person 1", "Morning", "Afternoon", 3))


def test_employees_who_join_mid_history_are_scored_without_error(team):
    history = [month_roster(team, "2025-05"), month_roster(team, "2025-06", shift_offset=1)]
    learner = RosterLearner()
    learner.train(history)

    blended, prior, _ = learner.score_shift("Brand New Joiner", "Morning", "Night", 2)
    assert 0.0 <= blended <= 1.0 and 0.0 <= prior <= 1.0

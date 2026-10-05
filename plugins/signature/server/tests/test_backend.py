"""How the plugin reads what Signature reports about a build."""

from signature_plugin.backend import _current_stage, _stage_labels  # pyright: ignore[reportPrivateUsage]


def test_the_current_stage_is_the_latest_still_running_even_when_listed_earlier() -> None:
    stages = [
        {'label': 'Reading sources', 'startedAt': '2026-10-03T07:55:29Z', 'completedAt': '2026-10-03T07:55:30Z'},
        {'label': 'Updating your model', 'startedAt': '2026-10-03T07:55:31Z'},
        {'label': 'Checking your model', 'startedAt': '2026-10-03T08:11:21Z', 'completedAt': '2026-10-03T08:11:22Z'},
    ]
    assert _current_stage(stages) == 'Updating your model'


def test_with_every_stage_complete_the_current_stage_is_the_latest_started() -> None:
    stages = [
        {'label': 'Checking your model', 'startedAt': '2026-10-03T08:11:21Z', 'completedAt': '2026-10-03T08:11:22Z'},
        {'label': 'Reading sources', 'startedAt': '2026-10-03T07:55:29Z', 'completedAt': '2026-10-03T07:55:30Z'},
    ]
    assert _current_stage(stages) == 'Checking your model'
    assert _current_stage([]) is None


def test_the_stages_a_build_entered_are_each_listed_once_in_the_order_it_first_entered_them() -> None:
    stages = [
        {'label': 'Checking your model', 'startedAt': '2026-10-03T08:11:21Z'},
        {'label': 'Reading sources', 'startedAt': '2026-10-03T07:55:29Z'},
        {'label': 'Updating your model', 'startedAt': '2026-10-03T07:55:31Z'},
        {'label': 'Updating your model', 'startedAt': '2026-10-03T08:12:00Z'},
    ]
    assert _stage_labels(stages) == ['Reading sources', 'Updating your model', 'Checking your model']

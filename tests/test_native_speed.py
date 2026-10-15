from copy import deepcopy

import pytest

from champions_practice.exact_search import score_exact_summary_breakdown
from champions_practice.native_speed import effective_speeds
from champions_practice.strategy_evidence import _favorable_speed_control


def summary(own_speed=150, enemy_speed=200, *, room=False, tailwind=False):
    def mon(speed):
        return {'species': 'Test', 'hp': 100, 'maxhp': 100, 'fainted': False,
                'effectiveSpeed': speed, 'actionOrderSpeed': -speed if room else speed,
                'speed': -999, 'cachedActionOrderSpeed': -999}
    own, foe = mon(own_speed), mon(enemy_speed)
    return {'field': {'pseudoWeather': ['trickroom'] if room else []},
        'p1': {'pokemon': [own], 'active': [own], 'sideConditions': ['tailwind'] if tailwind else []},
        'p2': {'pokemon': [foe], 'active': [foe], 'sideConditions': []}}


def test_effective_speed_inverts_once_for_room_and_ignores_stale_cache():
    normal, room = summary(), summary(room=True)
    assert score_exact_summary_breakdown(normal, 'p1').speed == -10
    assert score_exact_summary_breakdown(room, 'p1').speed == 10
    assert _favorable_speed_control(normal, 'p1') is False
    assert _favorable_speed_control(room, 'p1') is True
    other = deepcopy(room)
    other['p1']['active'][0]['actionOrderSpeed'] = 123456
    assert score_exact_summary_breakdown(other, 'p1') == score_exact_summary_breakdown(room, 'p1')


def test_tailwind_is_not_applied_twice_to_already_effective_speed():
    result = summary(150, 200, tailwind=True)
    assert _favorable_speed_control(result, 'p1') is False
    assert score_exact_summary_breakdown(result, 'p1').speed == -10
    result['p1']['active'][0]['effectiveSpeed'] = 300
    assert _favorable_speed_control(result, 'p1') is True


def test_legacy_or_partial_summaries_do_not_guess_speed_semantics():
    assert effective_speeds([{'speed': -100}]) is None
    assert effective_speeds([{'effectiveSpeed': 100}, {'speed': 50}]) is None
    assert effective_speeds([None, {'fainted': True, 'effectiveSpeed': 0}]) is None


@pytest.mark.parametrize('invalid', [-1, 0, True, float('nan'), float('inf')])
def test_invalid_effective_speed_is_rejected(invalid):
    with pytest.raises(ValueError):
        effective_speeds([{'effectiveSpeed': invalid}])

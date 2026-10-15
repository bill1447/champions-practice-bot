"""Offline root re-ranking of a frozen native consequence matrix.

Scenario averages are sensitivity tests, never calibrated opponent probabilities.
No move bonuses, simulator calls, hidden observations or branch expansion.
"""

from dataclasses import dataclass
import math
from statistics import fmean


@dataclass(frozen=True)
class Objective:
    name: str
    response_downside: float = 1.0
    world_downside: float = 1.0
    leaf: str = 'total'

    def __post_init__(self):
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in (self.response_downside, self.world_downside)):
            raise ValueError('downside coefficients must be finite and in [0, 1]')
        if self.leaf not in {'total', 'material_only', 'no_position', 'no_speed', 'no_hp', 'no_living'}:
            raise ValueError('unknown leaf sensitivity test')


OBJECTIVES = (
    Objective('min'), Objective('risk_75', .75), Objective('risk_50', .5),
    Objective('risk_25', .25), Objective('scenario_mean', 0),
    Objective('world_mean', world_downside=0),
    *(Objective(leaf, leaf=leaf) for leaf in ('material_only', 'no_position', 'no_speed', 'no_hp', 'no_living')),
)


def _utility(sample, leaf):
    if leaf == 'total':
        return sample['leaf_utility']
    parts = sample['leaf_breakdown']
    if leaf == 'material_only':
        return parts['terminal']+parts['material']
    return parts['total']-parts[leaf.removeprefix('no_')]


def rerank(ranking, objective):
    """Mix scenario mean with its downside, then independently aggregate worlds.

    lambda=1 is the existing minimum; lambda=0 is a scenario average. All
    subordinate replacement/continuation decisions stay frozen in the matrix.
    """
    if not ranking:
        raise ValueError('a complete native matrix is required')
    results = []
    for position, candidate in enumerate(ranking):
        worlds = []
        for world in candidate['worlds']:
            responses = [_utility(s, objective.leaf) for s in world['sampled_responses'].values()]
            if not responses or any(not math.isfinite(s) for s in responses) or world['weight'] <= 0:
                raise ValueError('finite complete scenarios and positive weights required')
            mean, worst = fmean(responses), min(responses)
            value = (1-objective.response_downside)*mean+objective.response_downside*worst
            worlds.append({'world': world['world'], 'weight': world['weight'], 'mean': mean,
                           'worst': worst, 'utility': value})
        if not worlds:
            raise ValueError('worlds required')
        weighted = sum(w['weight']*w['utility'] for w in worlds)/sum(w['weight'] for w in worlds)
        downside = min(w['utility'] for w in worlds)
        value = (1-objective.world_downside)*weighted+objective.world_downside*downside
        results.append({'action': candidate['action'], 'utility': value, 'weighted_utility': weighted,
                        'worlds': worlds, '_position': position})
    results.sort(key=lambda r: (-r['utility'], -r['weighted_utility'], r['_position']))
    for value in results:
        value.pop('_position')
    return results

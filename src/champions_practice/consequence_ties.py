"""Stable Pareto ordering only inside exact robust-score ties.

Dominance refers solely to supplied world/response means, not unseen replies,
individual RNG outcomes, or playing strength. No utility weights change.
"""

from itertools import groupby
from math import isfinite


def _bins(candidate):
    values = {}
    for index, world in enumerate(candidate['worlds']):
        if not world['sampled_responses']:
            return None
        for reply, sample in world['sampled_responses'].items():
            value = sample['leaf_utility']
            if not isfinite(value):
                return None
            values[index, world['world'], world['weight'], reply] = value
    return values or None


def order_exact_ties(ranking):
    """Return a new list; preserve primary scores and stable Pareto frontiers.

    Input must already be sorted by worst-world then weighted-world utility.
    Comparisons require identical nonempty hypothesis/response coverage. Exact
    scalar equality defines a tie; no tolerance silently changes the objective.
    """
    result = []
    for _, group in groupby(ranking, key=lambda row: (
            row['worst_world_utility'], row['weighted_utility'])):
        pending = list(group)
        vectors = {id(row): _bins(row) for row in pending}

        def dominates(left, right):
            a, b = vectors[id(left)], vectors[id(right)]
            return (a is not None and b is not None and a.keys() == b.keys()
                    and all(a[k] >= b[k] for k in a) and any(a[k] > b[k] for k in a))

        while pending:
            frontier = [row for row in pending
                        if not any(dominates(other, row) for other in pending)]
            result.extend(frontier)
            removed = {id(row) for row in frontier}
            pending = [row for row in pending if id(row) not in removed]
    return result

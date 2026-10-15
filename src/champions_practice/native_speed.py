"""Native summary speed contract, distinct from public cached Speed observations."""

from math import isfinite


def effective_speeds(active):
    """Return current modified Speed, or unknown for legacy/partial summaries.

    effectiveSpeed includes boosts, status, abilities and side effects exactly
    once. It excludes Trick Room ordering. Never reinterpret legacy `speed`,
    cachedActionOrderSpeed or actionOrderSpeed as an effective stat.
    """
    values = []
    for mon in active:
        if not mon or mon.get('fainted'):
            continue
        value = mon.get('effectiveSpeed')
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise ValueError('native effectiveSpeed must be finite and positive')
        values.append(value)
    return values or None

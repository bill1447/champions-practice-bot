"""A diagnostic catalogue must retain incompatible-capability uncertainty."""

from dataclasses import replace
from pathlib import Path

from champions_practice.beliefs import PublicPokemonBelief
from champions_practice.belief_worlds import compatible_public_sets
from champions_practice.persistent_support import static_support_issue


def test_public_earthquake_overlay_preserves_originals_and_requires_revelation(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from paired_native_continuation import continuation_priors
    baseline = continuation_priors('baseline')
    extended = continuation_priors('public-earthquake-coverage')
    for species in baseline:
        if species not in ('Garchomp', 'Metagross'):
            assert baseline[species] == extended[species]
            continue
        assert extended[species][:len(baseline[species])] == baseline[species]
        unknown = PublicPokemonBelief(species, 0, species, 100, False, True, None, (), (), (), ())
        candidates = compatible_public_sets(unknown, extended)
        assert len(candidates) == len(baseline[species])+1
        # The old unsupported active move remains possible before revelation.
        assert any(static_support_issue(ability=c.ability, item=c.item, moves=c.moves, opponent=True)
                   for c in candidates)
        known = replace(unknown, revealed_moves=('earthquake',))
        assert compatible_public_sets(known, baseline) == ()
        compatible = compatible_public_sets(known, extended)
        assert len(compatible) == 1 and 'Earthquake' in compatible[0].moves
        assert replace(compatible[0], moves=baseline[species][0].moves) == baseline[species][0]
        assert compatible_public_sets(replace(known, revealed_moves=('earthquake', 'stompingtantrum')), extended) == ()

from poke_env.battle import Move, Pokemon

from champions_practice.opponent.evaluator import _attack_value


def test_special_attacker_prefers_special_move_when_other_factors_are_similar() -> None:
    attacker = Pokemon(species="alakazam", gen=9)
    target = Pokemon(species="mew", gen=9)

    psychic = Move("psychic", gen=9)
    zen_headbutt = Move("zenheadbutt", gen=9)

    assert _attack_value(attacker, psychic, target) > _attack_value(
        attacker,
        zen_headbutt,
        target,
    )


def test_attack_boost_increases_physical_move_score() -> None:
    attacker = Pokemon(species="garchomp", gen=9)
    target = Pokemon(species="metagross", gen=9)
    earthquake = Move("earthquake", gen=9)

    before = _attack_value(attacker, earthquake, target)
    attacker.boosts["atk"] = 2
    after = _attack_value(attacker, earthquake, target)

    assert after > before


def test_defense_boost_reduces_physical_move_score() -> None:
    attacker = Pokemon(species="garchomp", gen=9)
    target = Pokemon(species="metagross", gen=9)
    earthquake = Move("earthquake", gen=9)

    before = _attack_value(attacker, earthquake, target)
    target.boosts["def"] = 2
    after = _attack_value(attacker, earthquake, target)

    assert after < before

from poke_env.battle import Move, Pokemon

from champions_practice.opponent.evaluator import _attack_value


def test_super_effective_attack_scores_above_resisted_attack() -> None:
    attacker = Pokemon(species="charizard", gen=9)
    ferrothorn = Pokemon(species="ferrothorn", gen=9)
    toxapex = Pokemon(species="toxapex", gen=9)
    flamethrower = Move("flamethrower", gen=9)

    assert _attack_value(attacker, flamethrower, ferrothorn) > _attack_value(
        attacker,
        flamethrower,
        toxapex,
    )


def test_immunity_is_strongly_penalized() -> None:
    attacker = Pokemon(species="garchomp", gen=9)
    corviknight = Pokemon(species="corviknight", gen=9)
    earthquake = Move("earthquake", gen=9)

    assert _attack_value(attacker, earthquake, corviknight) < 0

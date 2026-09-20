from poke_env.battle import Move, Pokemon
from poke_env.player.battle_order import SingleBattleOrder

from champions_practice.opponent.evaluator import score_single_order


class FakeDoubleBattle:
    OPPONENT_1_POSITION = 1
    OPPONENT_2_POSITION = 2
    POKEMON_1_POSITION = -1
    POKEMON_2_POSITION = -2
    EMPTY_TARGET_POSITION = 0

    def __init__(self, ally_one, ally_two, foe_one, foe_two):
        self.active_pokemon = [ally_one, ally_two]
        self.opponent_active_pokemon = [foe_one, foe_two]


def test_negative_target_is_not_treated_as_spread_attack() -> None:
    attacker = Pokemon(species="indeedee", gen=9)
    ally = Pokemon(species="metagross", gen=9)
    foe_one = Pokemon(species="rillaboom", gen=9)
    foe_two = Pokemon(species="armarouge", gen=9)
    battle = FakeDoubleBattle(attacker, ally, foe_one, foe_two)

    order = SingleBattleOrder(Move("psychic", gen=9), move_target=-2)
    score, reason = score_single_order(battle, attacker, order)

    assert score <= -500
    assert reason.startswith("friendly-fire:")


def test_positive_target_scores_as_foe_attack() -> None:
    attacker = Pokemon(species="indeedee", gen=9)
    ally = Pokemon(species="metagross", gen=9)
    foe_one = Pokemon(species="rillaboom", gen=9)
    foe_two = Pokemon(species="armarouge", gen=9)
    battle = FakeDoubleBattle(attacker, ally, foe_one, foe_two)

    order = SingleBattleOrder(Move("psychic", gen=9), move_target=2)
    score, reason = score_single_order(battle, attacker, order)

    assert score > -500
    assert "armarouge" in reason

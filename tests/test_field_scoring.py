from poke_env.battle import Field, Move, Pokemon
from poke_env.player.battle_order import SingleBattleOrder

from champions_practice.opponent.evaluator import score_single_order


class FakeBattle:
    OPPONENT_1_POSITION = 1
    OPPONENT_2_POSITION = 2
    POKEMON_1_POSITION = -1
    POKEMON_2_POSITION = -2
    EMPTY_TARGET_POSITION = 0

    def __init__(self, attacker, ally, foe_one, foe_two, fields=None):
        self.active_pokemon = [attacker, ally]
        self.opponent_active_pokemon = [foe_one, foe_two]
        self.fields = fields or {}


def _battle(fields=None):
    attacker = Pokemon(species="metagross", gen=9)
    ally = Pokemon(species="indeedee", gen=9)
    foe_one = Pokemon(species="rillaboom", gen=9)
    foe_two = Pokemon(species="armarouge", gen=9)
    return attacker, FakeBattle(attacker, ally, foe_one, foe_two, fields)


def test_steel_roller_is_rejected_without_terrain() -> None:
    attacker, battle = _battle()
    order = SingleBattleOrder(Move("steelroller", gen=9), move_target=1)

    score, reason = score_single_order(battle, attacker, order)

    assert score <= -800
    assert reason == "fail:steelroller-no-terrain"


def test_steel_roller_is_scored_normally_with_terrain() -> None:
    attacker, battle = _battle({Field.PSYCHIC_TERRAIN: 0})
    order = SingleBattleOrder(Move("steelroller", gen=9), move_target=1)

    score, reason = score_single_order(battle, attacker, order)

    assert score > 0
    assert reason.startswith("attack:steelroller")


def test_trick_room_is_not_blindly_reclicked_while_active() -> None:
    attacker, battle = _battle({Field.TRICK_ROOM: 0})
    order = SingleBattleOrder(Move("trickroom", gen=9))

    score, reason = score_single_order(battle, attacker, order)

    assert score < 0
    assert reason == "status:trickroom"

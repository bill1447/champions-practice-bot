from poke_env.battle import Move, Pokemon
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from champions_practice.opponent.response import (
    _revealed_response_risk,
    score_response_aware_order,
)


class FakeBattle:
    OPPONENT_1_POSITION = 1
    OPPONENT_2_POSITION = 2
    POKEMON_1_POSITION = -1
    POKEMON_2_POSITION = -2
    EMPTY_TARGET_POSITION = 0

    def __init__(self, ours, foes):
        self.active_pokemon = ours
        self.opponent_active_pokemon = foes
        self.fields = {}


def _mon(species: str, moves: list[str] | None = None) -> Pokemon:
    mon = Pokemon(species=species, gen=9)
    if moves:
        for move_id in moves:
            mon.moves[move_id] = Move(move_id, gen=9)
    return mon


def test_no_revealed_moves_adds_no_response_risk() -> None:
    ours = [_mon("rillaboom"), _mon("gardevoir")]
    foes = [_mon("garchomp"), _mon("pelipper")]
    battle = FakeBattle(ours, foes)

    order = DoubleBattleOrder(
        SingleBattleOrder(Move("woodhammer", gen=9), move_target=1),
        SingleBattleOrder(Move("psychic", gen=9), move_target=2),
    )

    risk, reasons = _revealed_response_risk(battle, order)

    assert risk == 0
    assert reasons == ()


def test_protect_reduces_revealed_response_risk() -> None:
    ours = [_mon("rillaboom"), _mon("gardevoir")]
    foes = [_mon("charizard", ["heatwave"]), _mon("pelipper")]
    battle = FakeBattle(ours, foes)

    attack_order = DoubleBattleOrder(
        SingleBattleOrder(Move("woodhammer", gen=9), move_target=1),
        SingleBattleOrder(Move("psychic", gen=9), move_target=1),
    )
    protect_order = DoubleBattleOrder(
        SingleBattleOrder(Move("protect", gen=9)),
        SingleBattleOrder(Move("psychic", gen=9), move_target=1),
    )

    attack_risk, _ = _revealed_response_risk(battle, attack_order)
    protect_risk, _ = _revealed_response_risk(battle, protect_order)

    assert protect_risk < attack_risk


def test_response_aware_score_penalizes_exposure_to_revealed_attack() -> None:
    ours = [_mon("rillaboom"), _mon("gardevoir")]
    foes = [_mon("charizard", ["heatwave"]), _mon("pelipper")]
    battle = FakeBattle(ours, foes)

    order = DoubleBattleOrder(
        SingleBattleOrder(Move("woodhammer", gen=9), move_target=1),
        SingleBattleOrder(Move("psychic", gen=9), move_target=1),
    )

    scored = score_response_aware_order(battle, order)

    assert any(reason.startswith("response-risk:") for reason in scored.reasons)

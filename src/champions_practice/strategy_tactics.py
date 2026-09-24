"""Translate strategic plans into soft tactical candidate guidance.

The strategy layer is allowed to reserve consideration for plan-compatible actions, but
it does not score or directly select the final Showdown command. Exact belief search
still decides among the bounded candidate set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from champions_practice.strategy import StrategicPlan

_PROTECT_MOVES = {
    "protect",
    "detect",
    "spikyshield",
    "kingsshield",
    "banefulbunker",
}
_SPEED_CONTROL_MOVES = {
    "trickroom",
    "tailwind",
    "icywind",
    "electroweb",
}


def _id(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


@dataclass(frozen=True)
class StrategicCandidateGuidance:
    """Soft constraints used only to preserve plan-compatible candidate diversity."""

    plan_name: str
    preferred_move_ids: tuple[str, ...] = ()
    prefer_switch: bool = False
    protected_slots: tuple[int, ...] = ()
    target_slots: tuple[int, ...] = ()
    switch_in_slots: tuple[int, ...] = ()
    reserved_bench_slots: tuple[int, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(
            self.preferred_move_ids
            or self.prefer_switch
            or self.protected_slots
            or self.target_slots
            or self.switch_in_slots
            or self.reserved_bench_slots
        )


def _active_species_slots(values: Any, *, opponent: bool) -> dict[str, int]:
    if not isinstance(values, list):
        return {}
    result: dict[str, int] = {}
    for slot, pokemon in enumerate(values, start=1):
        if not isinstance(pokemon, dict):
            continue
        species = pokemon.get("base_species") if opponent else pokemon.get("species")
        if not species:
            species = pokemon.get("species")
        if species:
            result[_id(species)] = slot
    return result


def _team_species_slots(values: Any) -> dict[str, int]:
    if not isinstance(values, list):
        return {}
    result: dict[str, int] = {}
    for slot, pokemon in enumerate(values, start=1):
        if not isinstance(pokemon, dict):
            continue
        species = pokemon.get("species")
        if species:
            result[_id(species)] = slot
    return result


def _own_speed_control_moves(view: dict[str, Any]) -> tuple[str, ...]:
    player = view.get("player")
    if not isinstance(player, dict):
        return ()
    active = player.get("active_details")
    if not isinstance(active, list):
        return ()
    moves: set[str] = set()
    for pokemon in active:
        if not isinstance(pokemon, dict):
            continue
        for move in pokemon.get("moves", []):
            move_id = _id(move)
            if move_id in _SPEED_CONTROL_MOVES:
                moves.add(move_id)
    return tuple(sorted(moves))


def guidance_from_plan(
    plan: StrategicPlan,
    *,
    view: dict[str, Any],
) -> StrategicCandidateGuidance:
    """Convert structured plan priorities into non-binding candidate guidance."""
    player = view.get("player")
    opponent = view.get("opponent")
    if not isinstance(player, dict) or not isinstance(opponent, dict):
        raise ValueError("public view is missing player or opponent data")

    own_slots = _active_species_slots(player.get("active_details"), opponent=False)
    opponent_slots = _active_species_slots(opponent.get("active"), opponent=True)
    team_slots = _team_species_slots(player.get("team"))

    preferred_moves: set[str] = set()
    protected_slots: set[int] = set()
    target_slots: set[int] = set()
    switch_in_slots: set[int] = set()
    reserved_bench_slots: set[int] = set()
    prefer_switch = False
    reasons: list[str] = []

    for priority in plan.tactical_priorities:
        if priority == "prefer-protect":
            preferred_moves.update(_PROTECT_MOVES)
            reasons.append("plan prefers consuming a turn with Protect-capable lines")
            continue
        if priority == "prefer-switch":
            prefer_switch = True
            reasons.append("plan prefers preserving tempo/resources through switching")
            continue
        if priority == "prefer-speed-control":
            moves = _own_speed_control_moves(view)
            preferred_moves.update(moves)
            if moves:
                reasons.append("plan prefers available speed-control moves")
            continue
        if priority.startswith("preserve:"):
            species = priority.split(":", 1)[1]
            slot = own_slots.get(_id(species))
            if slot is not None:
                protected_slots.add(slot)
                reasons.append(f"plan preserves active {species} in slot {slot}")
            continue
        if priority.startswith("target:"):
            species = priority.split(":", 1)[1]
            slot = opponent_slots.get(_id(species))
            if slot is not None:
                target_slots.add(slot)
                reasons.append(f"plan targets active {species} in opposing slot {slot}")
            continue

    for species in plan.desired_board.safe_entry_resources:
        slot = team_slots.get(_id(species))
        if slot is None:
            continue
        switch_in_slots.add(slot)
        reasons.append(
            f"plan requires switching {species} in from team slot {slot}"
        )

    for purpose in plan.desired_board.resource_purposes:
        if purpose.position != "bench":
            continue
        slot = team_slots.get(_id(purpose.species))
        if slot is None:
            continue
        reserved_bench_slots.add(slot)
        reasons.append(
            f"plan keeps {purpose.species} reserved on the bench in team slot {slot}"
        )

    return StrategicCandidateGuidance(
        plan_name=plan.name,
        preferred_move_ids=tuple(sorted(preferred_moves)),
        prefer_switch=prefer_switch,
        protected_slots=tuple(sorted(protected_slots)),
        target_slots=tuple(sorted(target_slots)),
        switch_in_slots=tuple(sorted(switch_in_slots)),
        reserved_bench_slots=tuple(sorted(reserved_bench_slots)),
        reasons=tuple(reasons),
    )


def _command_tokens(choice: str) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(command.strip().split()) for command in choice.split(","))


def choice_matches_guidance(
    choice: str,
    guidance: StrategicCandidateGuidance,
) -> bool:
    """Return whether a legal joint action advances at least one plan priority."""
    commands = _command_tokens(choice)
    switched_in_slots = {
        int(tokens[1])
        for tokens in commands
        if (
            len(tokens) >= 2
            and tokens[0] == "switch"
            and tokens[1].isdigit()
        )
    }

    if (
        guidance.switch_in_slots
        and not switched_in_slots.intersection(guidance.switch_in_slots)
    ):
        return False
    if switched_in_slots.intersection(guidance.reserved_bench_slots):
        return False
    if guidance.switch_in_slots:
        return True
    if guidance.reserved_bench_slots:
        return True

    for slot, tokens in enumerate(commands, start=1):
        if not tokens:
            continue
        if tokens[0] == "switch":
            if guidance.prefer_switch or slot in guidance.protected_slots:
                return True
            continue
        if tokens[0] != "move" or len(tokens) < 2:
            continue

        move_id = _id(tokens[1])
        if move_id in guidance.preferred_move_ids:
            return True
        if slot in guidance.protected_slots and move_id in _PROTECT_MOVES:
            return True

        for token in tokens[2:]:
            cleaned = token.removeprefix("+")
            if cleaned.isdigit() and int(cleaned) in guidance.target_slots:
                return True

    return False


def reserve_strategic_candidate(
    ranking: Iterable[Any],
    shortlist: Iterable[str],
    *,
    limit: int,
    guidance: StrategicCandidateGuidance | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Reserve one shortlist slot for the strongest plan-compatible action.

    The highest tactical candidate is never displaced. With a one-action shortlist,
    strategy has no reservation power at all. This makes guidance a diversity mechanism,
    not a direct move selector.
    """
    selected = list(shortlist)[:limit]
    if (
        guidance is None
        or not guidance.active
        or limit < 2
        or not selected
    ):
        return tuple(selected), ()

    if any(choice_matches_guidance(choice, guidance) for choice in selected):
        matching = tuple(
            choice for choice in selected if choice_matches_guidance(choice, guidance)
        )
        return tuple(selected), matching

    plan_candidate = next(
        (
            candidate.choice
            for candidate in ranking
            if candidate.choice not in selected
            and choice_matches_guidance(candidate.choice, guidance)
        ),
        None,
    )
    if plan_candidate is None:
        return tuple(selected), ()

    top_choice = selected[0]
    if len(selected) < limit:
        selected.append(plan_candidate)
    else:
        selected[-1] = plan_candidate

    if selected[0] != top_choice:
        raise RuntimeError("strategic reservation displaced the tactical top choice")
    return tuple(selected), (plan_candidate,)

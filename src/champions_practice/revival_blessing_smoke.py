"""Pinned-runtime Revival Blessing request and conditioning regression."""

from __future__ import annotations

from dataclasses import dataclass

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.observation_beliefs import BeliefParticle, condition_particles
from champions_practice.search_worker import ShowdownSearchWorker

SEED_HUMAN_REVIVES = "sodium,00000101000001020000010300000104"
SEED_AI_REVIVES = "sodium,00000201000002020000020300000204"
PREVIEW = "team 1234"

REVIVER_TURN_ONE = "move bodyslam +1, move protect"
ATTACKER_TURN_ONE = "move closecombat +1, move protect"
REPLACEMENT = "switch 3, pass"
REVIVAL_MOVE_TURN = "move protect, move revivalblessing"
DOUBLE_PROTECT = "move protect, move protect"
REVIVAL_SELECTION = "pass, switch 3"

REVIVER_TEAM = """Snorlax
Ability: Thick Fat
Level: 50
Calm Nature
- Body Slam
- Protect
- Rest
- Sleep Talk

Pawmot
Ability: Volt Absorb
Level: 50
Jolly Nature
- Revival Blessing
- Protect
- Thunder Punch
- Close Combat

Armarouge
Ability: Flash Fire
Level: 50
Modest Nature
- Psychic
- Armor Cannon
- Wide Guard
- Protect

Gardevoir @ Gardevoirite
Ability: Trace
Level: 50
Modest Nature
- Expanding Force
- Hyper Voice
- Mystical Fire
- Protect
"""

ATTACKER_TEAM = """Sneasler
Ability: Unburden
Level: 50
EVs: 2 HP / 32 Atk / 32 Spe
Adamant Nature
- Close Combat
- Dire Claw
- Rock Slide
- Protect

Indeedee-F
Ability: Synchronize
Level: 50
Relaxed Nature
- Psychic
- Follow Me
- Trick Room
- Protect

Armarouge
Ability: Flash Fire
Level: 50
Modest Nature
- Psychic
- Armor Cannon
- Wide Guard
- Protect

Gardevoir @ Gardevoirite
Ability: Trace
Level: 50
Modest Nature
- Expanding Force
- Hyper Voice
- Mystical Fire
- Protect
"""


@dataclass(frozen=True)
class RevivalCaseResult:
    label: str
    public_choices: tuple[str, ...]
    exact_choices: tuple[str, ...]
    matched: int
    posterior: int


def _side_choice(reviver_side: str, reviver: str, attacker: str) -> tuple[str, str]:
    if reviver_side == "p1":
        return reviver, attacker
    return attacker, reviver


def _assert_revival_request(view: dict, *, label: str) -> None:
    request = view.get("request")
    if not isinstance(request, dict):
        raise SystemExit(f"ERROR: {label} has no actionable revival request")
    if request.get("forceSwitch") != [False, True]:
        raise SystemExit(
            f"ERROR: {label} expected forceSwitch [false, true], "
            f"got {request.get('forceSwitch')!r}"
        )

    side = request.get("side")
    pokemon = side.get("pokemon") if isinstance(side, dict) else None
    if not isinstance(pokemon, list) or len(pokemon) < 3:
        raise SystemExit(f"ERROR: {label} request has incomplete party data")
    if not pokemon[1].get("reviving"):
        raise SystemExit(f"ERROR: {label} did not mark Pawmot reviving:true")
    if not str(pokemon[2].get("condition", "")).endswith(" fnt"):
        raise SystemExit(f"ERROR: {label} did not retain fainted Snorlax in slot 3")


def _assert_revived(view: dict, *, label: str) -> None:
    team = view["player"]["team"]
    snorlax = next(mon for mon in team if mon["species"] == "Snorlax")
    hp_percent = snorlax["hp_percent"]
    fainted = snorlax["fainted"]

    if fainted or hp_percent is None or hp_percent <= 0:
        raise SystemExit(
            f"ERROR: {label} selected Snorlax but it remained publicly fainted"
        )


def _run_case(
    worker: ShowdownSearchWorker,
    *,
    reviver_side: str,
    seed: str,
    label: str,
) -> RevivalCaseResult:
    if reviver_side == "p1":
        p1_team, p2_team = REVIVER_TEAM, ATTACKER_TEAM
    else:
        p1_team, p2_team = ATTACKER_TEAM, REVIVER_TEAM

    started = worker.start_session(
        battle_format=CHAMPIONS_FORMAT,
        p1_team=p1_team,
        p2_team=p2_team,
        p1_name="Human",
        p2_name="Practice AI",
        seed=seed,
    )
    session_id = started["session_id"]
    try:
        worker.choose_session(
            session_id,
            p1_choice=PREVIEW,
            p2_choice=PREVIEW,
        )
        preview_view = worker.session_view(session_id, side="p2")["view"]
        previews = {
            "p1": preview_view["opponent"]["preview_species"],
            "p2": [mon["species"] for mon in preview_view["player"]["team"]],
        }

        p1_choice, p2_choice = _side_choice(
            reviver_side,
            REVIVER_TURN_ONE,
            ATTACKER_TURN_ONE,
        )
        worker.choose_session(
            session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
        )

        reviver_choices = (
            worker.session_legal_choices(session_id, side=reviver_side)
        )
        if REPLACEMENT not in reviver_choices:
            raise SystemExit(
                f"ERROR: {label} did not reach ordinary replacement: "
                f"{reviver_choices}"
            )
        other_side = "p2" if reviver_side == "p1" else "p1"
        if worker.session_legal_choices(session_id, side=other_side) != [""]:
            raise SystemExit(f"ERROR: {label} opponent did not wait for replacement")

        p1_choice, p2_choice = _side_choice(
            reviver_side,
            REPLACEMENT,
            "",
        )
        worker.choose_session(
            session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
        )

        p1_choice, p2_choice = _side_choice(
            reviver_side,
            REVIVAL_MOVE_TURN,
            DOUBLE_PROTECT,
        )
        worker.choose_session(
            session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
        )

        reviver_view = worker.session_view(
            session_id,
            side=reviver_side,
        )["view"]
        _assert_revival_request(reviver_view, label=label)

        public_choices = tuple(
            worker.session_public_choices(session_id, side=reviver_side)
        )
        exact_choices = tuple(
            worker.session_legal_choices(session_id, side=reviver_side)
        )
        if REVIVAL_SELECTION not in public_choices:
            raise SystemExit(
                f"ERROR: {label} public enumerator omitted Revival Blessing target: "
                f"{public_choices}"
            )
        if REVIVAL_SELECTION not in exact_choices:
            raise SystemExit(
                f"ERROR: {label} exact enumerator omitted Revival Blessing target: "
                f"{exact_choices}"
            )
        if worker.session_public_choices(session_id, side=other_side) != [""]:
            raise SystemExit(f"ERROR: {label} other side did not expose public wait")
        if worker.session_legal_choices(session_id, side=other_side) != [""]:
            raise SystemExit(f"ERROR: {label} other side did not expose exact wait")

        pre_selection_state = worker.session_snapshot(session_id)["state"]
        before_selection = worker.session_view(session_id, side="p2")["view"]

        p1_choice, p2_choice = _side_choice(
            reviver_side,
            REVIVAL_SELECTION,
            "",
        )
        worker.choose_session(
            session_id,
            p1_choice=p1_choice,
            p2_choice=p2_choice,
        )
        actual_view = worker.session_view(session_id, side="p2")["view"]
        reviver_after = worker.session_view(
            session_id,
            side=reviver_side,
        )["view"]
        _assert_revived(reviver_after, label=label)

        if reviver_side == "p1":
            ai_choice = ""
            resolved_human_choice = REVIVAL_SELECTION
        else:
            ai_choice = REVIVAL_SELECTION
            resolved_human_choice = ""

        update = condition_particles(
            worker,
            particles=(
                BeliefParticle(
                    state=pre_selection_state,
                    weight=1.0,
                    world_id=label,
                    history_id="before-revival-selection",
                ),
            ),
            ai_side="p2",
            ai_choice=ai_choice,
            actual_public_view=actual_view,
            previous_public_view=before_selection,
            resolved_opponent_choice=resolved_human_choice,
            rng_seeds=(None,),
            previews=previews,
        )
        if not update.particles or update.matched <= 0:
            raise SystemExit(
                f"ERROR: {label} real particle conditioning rejected revival selection"
            )

        return RevivalCaseResult(
            label=label,
            public_choices=public_choices,
            exact_choices=exact_choices,
            matched=update.matched,
            posterior=len(update.particles),
        )
    finally:
        worker.close_session(session_id)


def main() -> None:
    with ShowdownSearchWorker() as worker:
        human = _run_case(
            worker,
            reviver_side="p1",
            seed=SEED_HUMAN_REVIVES,
            label="human-revival-ai-wait",
        )
        ai = _run_case(
            worker,
            reviver_side="p2",
            seed=SEED_AI_REVIVES,
            label="ai-revival-human-wait",
        )

    print("Revival Blessing request and conditioning")
    for result in (human, ai):
        print(
            f"{result.label}: public={result.public_choices}, "
            f"exact={result.exact_choices}"
        )
        print(
            f"{result.label}: matched={result.matched}, "
            f"posterior={result.posterior}"
        )
    print("RESULT: Revival Blessing targets enumerate and condition in both directions")


if __name__ == "__main__":
    main()

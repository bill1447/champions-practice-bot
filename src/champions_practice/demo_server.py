"""Local browser demo built directly on the sealed battle facade."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock
from typing import Callable
import webbrowser

from champions_practice.belief_controller import (
    BeliefDecision,
    SealedBattleFacade,
    SealedTurnResult,
)
from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.demo_fixture import (
    DEMO_AI_PREVIEW_CHOICE,
    DEMO_AI_TEAM,
    DEMO_HUMAN_TEAM,
    DEMO_PRESET_NAME,
    demo_public_priors,
)


FacadeFactory = Callable[[], SealedBattleFacade]


def _decision_payload(decision: BeliefDecision) -> dict[str, object]:
    return {
        "choice": decision.choice,
        "mode": decision.mode,
        "particle_count": decision.particle_count,
        "candidate_count": decision.candidate_count,
        "branch_count": decision.branch_count,
        "elapsed_seconds": decision.elapsed_seconds,
        "fallback_reason": decision.fallback_reason,
        "strategic_plan": decision.strategic_plan,
        "strategic_probe_count": decision.strategic_probe_count,
        "strategic_branch_count": decision.strategic_branch_count,
        "strategic_rng_sample_count": decision.strategic_rng_sample_count,
        "worst_response": decision.worst_response,
        "worst_world_score": decision.worst_world_score,
        "weighted_score": decision.weighted_score,
        "searched_responses": list(decision.searched_responses),
        "evaluated_choices": list(decision.evaluated_choices),
        "candidate_scores": [
            {
                "choice": choice,
                "worst_world_score": worst_world_score,
                "weighted_score": weighted_score,
            }
            for choice, worst_world_score, weighted_score
            in decision.candidate_scores
        ],
    }


def _result_payload(
    result: SealedTurnResult,
    *,
    decision_turn: int | None = None,
) -> dict[str, object]:
    return {
        "turn": (
            decision_turn
            if decision_turn is not None
            else result.public_view.get("turn")
        ),
        "decision": _decision_payload(result.decision),
        "conditioning": {
            "particles_before": result.particles_before,
            "particles_after": result.particles_after,
            "generated_branches": result.generated_branches,
            "matched_branches": result.matched_branches,
            "seconds": result.conditioning_seconds,
            "over_budget": result.conditioning_over_budget,
            "degraded": result.degraded,
        },
        "terminal": result.terminal,
        "winner": result.winner,
    }


def _normalize_id(value: object) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _player_team(view: dict | None) -> list[dict]:
    if not isinstance(view, dict):
        return []
    player = view.get("player")
    if not isinstance(player, dict):
        return []
    team = player.get("team")
    return [pokemon for pokemon in team if isinstance(pokemon, dict)] if isinstance(team, list) else []


def _team_species(view: dict | None, slot: int) -> str:
    team = _player_team(view)
    if 1 <= slot <= len(team):
        species = team[slot - 1].get("species")
        if isinstance(species, str) and species:
            return species
    return f"slot {slot}"


def _active_species(view: dict | None, slot_index: int) -> str:
    if not isinstance(view, dict):
        return f"Slot {slot_index + 1}"
    player = view.get("player")
    if not isinstance(player, dict):
        return f"Slot {slot_index + 1}"
    active = player.get("active")
    if isinstance(active, list) and slot_index < len(active):
        species = active[slot_index]
        if isinstance(species, str) and species:
            return species
    return f"Slot {slot_index + 1}"


def _preview_choice_label(choice: str, view: dict | None) -> str:
    slots = [int(character) for character in choice[5:] if character.isdigit()]
    if not slots:
        return choice

    names = [_team_species(view, slot) for slot in slots]
    if len(names) <= 2:
        return "Lead: " + " + ".join(names)
    return f"Lead: {' + '.join(names[:2])} | Back: {' + '.join(names[2:])}"


def _move_name(view: dict | None, slot_index: int, move_id: str) -> str:
    if not isinstance(view, dict):
        return move_id
    request = view.get("request")
    if not isinstance(request, dict):
        return move_id
    active = request.get("active")
    if not isinstance(active, list) or slot_index >= len(active):
        return move_id
    slot = active[slot_index]
    if not isinstance(slot, dict):
        return move_id
    moves = slot.get("moves")
    if not isinstance(moves, list):
        return move_id

    wanted = _normalize_id(move_id)
    for move in moves:
        if not isinstance(move, dict):
            continue
        if _normalize_id(move.get("id")) != wanted:
            continue
        name = move.get("move")
        if isinstance(name, str) and name:
            return name
    return move_id


def _opponent_active_species(view: dict | None, slot_index: int) -> str | None:
    if not isinstance(view, dict):
        return None
    opponent = view.get("opponent")
    if not isinstance(opponent, dict):
        return None
    active = opponent.get("active")
    if not isinstance(active, list) or slot_index >= len(active):
        return None
    pokemon = active[slot_index]
    if isinstance(pokemon, dict):
        species = pokemon.get("species")
        if isinstance(species, str) and species:
            return species
    if isinstance(pokemon, str) and pokemon:
        return pokemon
    return None


def _target_label(location: int, view: dict | None) -> str:
    if location > 0:
        species = _opponent_active_species(view, location - 1)
        return f"foe {species}" if species else f"foe slot {location}"
    if location < 0:
        slot = abs(location)
        species = _active_species(view, slot - 1)
        return f"ally {species}" if species else f"ally slot {slot}"
    return "field"


def _action_part_label(part: str, slot_index: int, view: dict | None) -> str:
    actor = _active_species(view, slot_index)
    tokens = part.split()
    if not tokens:
        return part
    if tokens[0] == "pass":
        return f"{actor}: pass"
    if tokens[0] == "switch" and len(tokens) >= 2 and tokens[1].isdigit():
        return f"{actor}: switch → {_team_species(view, int(tokens[1]))}"
    if tokens[0] != "move" or len(tokens) < 2:
        return f"{actor}: {part}"

    move_name = _move_name(view, slot_index, tokens[1])
    suffixes: list[str] = []
    for token in tokens[2:]:
        try:
            location = int(token)
        except ValueError:
            location = 0
        if location:
            suffixes.append(f"→ {_target_label(location, view)}")
            continue
        if token in {"mega", "megax", "megay"}:
            suffixes.append("[Mega]")
        elif token == "ultra":
            suffixes.append("[Ultra Burst]")
        else:
            suffixes.append(f"[{token}]")

    suffix = " " + " ".join(suffixes) if suffixes else ""
    return f"{actor}: {move_name}{suffix}"


def _choice_label(choice: str, view: dict | None) -> str:
    if choice.startswith("team "):
        return _preview_choice_label(choice, view)
    parts = choice.split(", ")
    return " | ".join(
        _action_part_label(part, index, view)
        for index, part in enumerate(parts)
    )


def _legal_action_payload(
    legal_choices: list[str],
    view: dict | None,
) -> list[dict[str, str]]:
    return [
        {"value": choice, "label": _choice_label(choice, view)}
        for choice in legal_choices
    ]


_FIELD_LABELS = {
    "electricterrain": "Electric Terrain",
    "grassyterrain": "Grassy Terrain",
    "mistyterrain": "Misty Terrain",
    "psychicterrain": "Psychic Terrain",
    "raindance": "Rain",
    "sunnyday": "Sun",
    "sandstorm": "Sandstorm",
    "snow": "Snow",
    "hail": "Hail",
    "trickroom": "Trick Room",
    "gravity": "Gravity",
    "magicroom": "Magic Room",
    "wonderroom": "Wonder Room",
}


def _field_status(view: dict | None) -> str:
    if not isinstance(view, dict):
        return "Field: —"
    field = view.get("field")
    if not isinstance(field, dict):
        return "Field: —"

    active: list[str] = []
    for key in ("terrain", "weather"):
        value = field.get(key)
        if isinstance(value, str) and value:
            active.append(_FIELD_LABELS.get(value, value))

    pseudo_weather = field.get("pseudo_weather")
    if isinstance(pseudo_weather, list):
        active.extend(
            _FIELD_LABELS.get(value, value)
            for value in pseudo_weather
            if isinstance(value, str) and value
        )

    return "Field: " + (" · ".join(active) if active else "Neutral")


def _default_facade() -> SealedBattleFacade:
    return SealedBattleFacade(
        battle_format=CHAMPIONS_FORMAT,
        ai_team=DEMO_AI_TEAM,
        ai_preview_choice=DEMO_AI_PREVIEW_CHOICE,
        opponent_priors=demo_public_priors(),
        candidate_limit=4,
        decision_budget_seconds=10.0,
    )


class DemoBattleSession:
    """Own one browser-visible battle without exposing the sealed decision token."""

    def __init__(self, facade_factory: FacadeFactory = _default_facade) -> None:
        self._facade_factory = facade_factory
        self._facade: SealedBattleFacade | None = None
        self._ready_token: str | None = None
        self._ready_turn: int | None = None
        self._last_public_view: dict | None = None
        self._history: list[dict[str, object]] = []
        self._ended_manually = False
        self._lock = RLock()

    def _require_facade(self) -> SealedBattleFacade:
        if self._facade is None:
            raise RuntimeError("start a battle first")
        return self._facade

    def _snapshot_locked(self) -> dict[str, object]:
        if self._facade is None:
            return {
                "started": False,
                "preset": DEMO_PRESET_NAME,
                "turn_state": "ended" if self._ended_manually else "new",
                "ai_ready": False,
                "can_reconcile": False,
                "public_view": None,
                "field_status": "Field: —",
                "legal_choices": [],
                "legal_actions": [],
                "history": list(self._history),
            }

        facade = self._facade
        turn_state = facade.turn_state.value
        public_view_error: str | None = None
        try:
            self._last_public_view = facade.public_state()
        except Exception as error:
            public_view_error = f"{type(error).__name__}: {error}"

        try:
            legal_choices = list(facade.legal_human_choices())
        except Exception:
            legal_choices = []

        return {
            "started": True,
            "preset": DEMO_PRESET_NAME,
            "turn_state": turn_state,
            "ai_ready": self._ready_token is not None,
            "can_reconcile": (
                self._ready_token is not None and turn_state == "failed"
            ),
            "public_view": self._last_public_view,
            "field_status": _field_status(self._last_public_view),
            "public_view_error": public_view_error,
            "legal_choices": legal_choices,
            "legal_actions": _legal_action_payload(
                legal_choices,
                self._last_public_view,
            ),
            "history": list(self._history),
        }

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_locked()

    def start(self) -> dict[str, object]:
        with self._lock:
            old = self._facade
            self._facade = None
            self._ready_token = None
            self._ready_turn = None
            self._last_public_view = None
            self._history = []
            self._ended_manually = False
            if old is not None:
                old.close()

            facade = self._facade_factory()
            try:
                self._last_public_view = facade.start(
                    opponent_team=DEMO_HUMAN_TEAM,
                    p1_name="Human",
                    p2_name="Practice AI",
                )
            except Exception:
                facade.close()
                raise

            self._facade = facade
            return self._snapshot_locked()

    def commit_preview(self, human_choice: str) -> dict[str, object]:
        with self._lock:
            facade = self._require_facade()
            self._last_public_view = facade.commit_preview(
                human_choice=human_choice
            )
            self._ready_token = None
            self._ready_turn = None
            return self._snapshot_locked()

    def lock_ai_action(self) -> dict[str, object]:
        with self._lock:
            facade = self._require_facade()
            ready = facade.lock_ai_action()
            self._ready_token = ready.token
            turn = (
                self._last_public_view.get("turn")
                if isinstance(self._last_public_view, dict)
                else None
            )
            self._ready_turn = turn if isinstance(turn, int) else None
            return self._snapshot_locked()

    def commit_human_action(self, human_choice: str) -> dict[str, object]:
        with self._lock:
            facade = self._require_facade()
            if self._ready_token is None:
                raise RuntimeError("AI action is not locked")
            result = facade.commit_human_action(
                token=self._ready_token,
                human_choice=human_choice,
            )
            decision_turn = self._ready_turn
            self._ready_token = None
            self._ready_turn = None
            self._last_public_view = result.public_view
            self._history.append(
                _result_payload(result, decision_turn=decision_turn)
            )
            return self._snapshot_locked()

    def reconcile_failed_turn(self) -> dict[str, object]:
        with self._lock:
            facade = self._require_facade()
            if self._ready_token is None:
                raise RuntimeError("no sealed action is available for reconciliation")
            result = facade.reconcile_failed_turn(token=self._ready_token)
            decision_turn = self._ready_turn
            self._ready_token = None
            self._ready_turn = None
            self._last_public_view = result.public_view
            self._history.append(
                _result_payload(result, decision_turn=decision_turn)
            )
            return self._snapshot_locked()

    def end_battle(self) -> dict[str, object]:
        """Close the current live battle while leaving the demo server running."""
        with self._lock:
            facade = self._require_facade()
            self._facade = None
            self._ready_token = None
            self._ready_turn = None
            self._last_public_view = None
            self._ended_manually = True
            facade.close()
            return self._snapshot_locked()

    def close(self) -> None:
        with self._lock:
            facade = self._facade
            self._facade = None
            self._ready_token = None
            self._ready_turn = None
            self._last_public_view = None
            if facade is not None:
                facade.close()


DEMO_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Champions Practice Bot</title>
<style>
:root {
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  background: #0c1118;
  color: #e7edf5;
}
* { box-sizing: border-box; }
body { margin: 0; background: #0c1118; }
main { max-width: 1200px; margin: 0 auto; padding: 24px; }
header { display: flex; gap: 16px; align-items: center; justify-content: space-between; }
h1, h2, h3 { margin: 0; }
button, select {
  font: inherit;
  border-radius: 8px;
  border: 1px solid #3b4655;
  background: #182230;
  color: #e7edf5;
  padding: 10px 12px;
}
button { cursor: pointer; }
button:disabled { opacity: .45; cursor: not-allowed; }
.panel {
  margin-top: 18px;
  background: #121a24;
  border: 1px solid #283445;
  border-radius: 12px;
  padding: 16px;
}
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.cards { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.card {
  min-width: 150px;
  background: #182230;
  border: 1px solid #334156;
  border-radius: 9px;
  padding: 10px;
}
.card small { color: #9fb0c3; display: block; margin-top: 4px; }
.status { font-weight: 700; color: #9dc4ff; }
.muted { color: #9fb0c3; }
.error { color: #ff9b9b; white-space: pre-wrap; }
.controls { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 12px; }
.controls select { min-width: min(760px, 100%); flex: 1; }
.reveal {
  border-left: 4px solid #8eb8ff;
  padding-left: 12px;
  margin-top: 12px;
}
pre {
  overflow: auto;
  max-height: 420px;
  background: #080c12;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
}
@media (max-width: 800px) {
  .grid { grid-template-columns: 1fr; }
  header { align-items: flex-start; flex-direction: column; }
}
</style>
</head>
<body>
<main>
<header>
  <div>
    <h1>Champions Practice Bot</h1>
    <div class="muted">Playable sealed-choice v0 · preset mirror match</div>
  </div>
  <div class="controls">
    <button id="newBattle">New battle</button>
    <button id="endBattle">End battle</button>
  </div>
</header>

<section class="panel">
  <div>Status: <span id="status" class="status">loading</span></div>
  <div id="fieldState" class="muted">Field: —</div>
  <div id="error" class="error"></div>
  <div id="hint" class="muted"></div>
</section>

<section class="panel grid">
  <div>
    <h2>Opponent</h2>
    <div id="opponent" class="cards"></div>
  </div>
  <div>
    <h2>Your side</h2>
    <div id="player" class="cards"></div>
  </div>
</section>

<section class="panel">
  <h2>Choose action</h2>
  <div class="controls">
    <select id="choice"></select>
    <button id="preview">Commit preview</button>
    <button id="commit">Submit action</button>
    <button id="reconcile">Reconcile</button>
  </div>
</section>

<section class="panel">
  <h2>Revealed decision trace</h2>
  <div id="history" class="muted">No committed turns yet.</div>
</section>

<details class="panel">
  <summary>Raw sanitized public state</summary>
  <pre id="raw"></pre>
</details>
</main>

<script>
let state = null;
let aiLockPending = false;

function monName(mon) {
  if (!mon) return "Unknown";
  return mon.species || mon.base_species || mon.name || mon.ident || mon.details || "Unknown";
}

function monDetail(mon) {
  if (!mon) return "";
  const parts = [];
  if (mon.condition) parts.push(mon.condition);
  if (mon.status) parts.push(mon.status);
  if (mon.active) parts.push("active");
  return parts.join(" · ");
}

function card(mon) {
  const div = document.createElement("div");
  div.className = "card";
  const name = document.createElement("strong");
  name.textContent = typeof mon === "string" ? mon : monName(mon);
  div.appendChild(name);
  if (typeof mon !== "string") {
    const small = document.createElement("small");
    small.textContent = monDetail(mon);
    div.appendChild(small);
  }
  return div;
}

function renderSide(targetId, side, previewFallback) {
  const target = document.getElementById(targetId);
  target.replaceChildren();
  const active = Array.isArray(side?.active) ? side.active : [];
  const team = Array.isArray(side?.team) ? side.team : [];
  const preview = Array.isArray(side?.preview_species) ? side.preview_species : [];
  const mons = active.length ? active : (team.length ? team : preview);
  if (!mons.length && previewFallback) mons.push(...previewFallback);
  if (!mons.length) {
    target.textContent = "No public data yet.";
    return;
  }
  mons.forEach(mon => target.appendChild(card(mon)));
}

function hintFor(turnState) {
  if (aiLockPending) {
    return "AI is thinking. Your move controls unlock once its action is sealed.";
  }
  if (!state?.started && turnState === "ended") {
    return "Battle ended. Start a new battle when ready.";
  }
  if (!state?.started) return "Start a battle. v0 uses the current-roster mirror fixture.";
  if (turnState === "preview") return "Choose your bring-four and lead order.";
  if (turnState === "idle" || turnState === "resolved") {
    return "AI action is being prepared automatically.";
  }
  if (turnState === "computing") return "AI is thinking.";
  if (turnState === "locked") return "AI is sealed. Submit your human command.";
  if (turnState === "failed") return "Live turn needs reconciliation; do not resubmit it.";
  if (turnState === "terminal") return "Battle complete.";
  return "";
}

function renderHistory(history) {
  const target = document.getElementById("history");
  target.replaceChildren();
  if (!history?.length) {
    target.textContent = "No committed turns yet.";
    target.className = "muted";
    return;
  }
  target.className = "";
  history.slice().reverse().forEach(entry => {
    const box = document.createElement("div");
    box.className = "reveal";
    const d = entry.decision;
    const title = document.createElement("strong");
    title.textContent = `Turn ${entry.turn ?? "?"}: ${d.choice}`;
    box.appendChild(title);
    const detail = document.createElement("div");
    detail.className = "muted";
    const plan = d.strategic_plan ? ` · plan ${d.strategic_plan}` : "";
    detail.textContent =
      `${d.mode} · ${d.branch_count} branches · ${d.elapsed_seconds.toFixed(3)}s${plan}`;
    box.appendChild(detail);

    if (d.worst_response) {
      const worst = document.createElement("div");
      worst.className = "muted";
      const score = Number.isFinite(d.worst_world_score) ?
        ` · score ${d.worst_world_score.toFixed(1)}` : "";
      worst.textContent = `Worst searched reply: ${d.worst_response}${score}`;
      box.appendChild(worst);
    }

    if (d.candidate_scores?.length) {
      const candidates = document.createElement("details");
      candidates.className = "muted";
      const summary = document.createElement("summary");
      summary.textContent = `AI candidate ranking (${d.candidate_scores.length})`;
      candidates.appendChild(summary);
      const candidateList = document.createElement("pre");
      candidateList.textContent = d.candidate_scores.map((candidate, index) =>
        `${index + 1}. ${candidate.choice} | worst ${candidate.worst_world_score.toFixed(1)} | weighted ${candidate.weighted_score.toFixed(1)}`
      ).join("\n");
      candidates.appendChild(candidateList);
      box.appendChild(candidates);
    }

    if (d.searched_responses?.length) {
      const searched = document.createElement("details");
      searched.className = "muted";
      const summary = document.createElement("summary");
      summary.textContent = `Searched opponent replies (${d.searched_responses.length})`;
      searched.appendChild(summary);
      const responseList = document.createElement("pre");
      responseList.textContent = d.searched_responses.join("\n");
      searched.appendChild(responseList);
      box.appendChild(searched);
    }
    target.appendChild(box);
  });
}

function render(next) {
  state = next;
  const turnState = state.turn_state || "new";
  document.getElementById("status").textContent =
    aiLockPending ? "AI THINKING" :
    (state.started ? turnState.toUpperCase() : "NOT STARTED");
  document.getElementById("fieldState").textContent =
    state.field_status || "Field: —";
  const viewError = state.public_view_error ? ` · view read: ${state.public_view_error}` : "";
  document.getElementById("hint").textContent = hintFor(turnState) + viewError;
  document.getElementById("raw").textContent =
    JSON.stringify(state.public_view, null, 2);

  const view = state.public_view || {};
  renderSide("opponent", view.opponent, view.opponent?.preview_species || []);
  renderSide("player", view.player, []);

  const select = document.getElementById("choice");
  const previous = select.value;
  select.replaceChildren();
  const actions = state.legal_actions ||
    (state.legal_choices || []).map(choice => ({value: choice, label: choice}));
  actions.forEach(action => {
    const option = document.createElement("option");
    option.value = action.value;
    option.textContent = action.label;
    select.appendChild(option);
  });
  if ([...select.options].some(option => option.value === previous)) {
    select.value = previous;
  }

  select.disabled =
    aiLockPending || !(turnState === "preview" || turnState === "locked");
  document.getElementById("preview").disabled =
    aiLockPending || turnState !== "preview";
  document.getElementById("commit").disabled =
    aiLockPending || !(turnState === "locked" && state.ai_ready && select.value);
  document.getElementById("reconcile").disabled =
    aiLockPending || !state.can_reconcile;
  document.getElementById("endBattle").disabled = !state.started;
  renderHistory(state.history || []);
}

async function request(path, method="GET", body=null) {
  document.getElementById("error").textContent = "";
  const options = {method, headers: {}};
  if (body !== null) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function run(action) {
  try {
    await action();
  } catch (error) {
    document.getElementById("error").textContent = String(error.message || error);
    try { render(await request("/api/state")); } catch (_) {}
  }
}

async function renderAndAutoLock(next) {
  render(next);
  const turnState = next.turn_state || "new";
  if (
    !next.started ||
    next.ai_ready ||
    !(turnState === "idle" || turnState === "resolved")
  ) {
    return;
  }

  aiLockPending = true;
  render(next);
  try {
    const locked = await request("/api/lock", "POST", {});
    aiLockPending = false;
    render(locked);
  } catch (error) {
    aiLockPending = false;
    throw error;
  }
}

document.getElementById("newBattle").onclick = () => run(async () => {
  render(await request("/api/start", "POST", {}));
});

document.getElementById("endBattle").onclick = () => run(async () => {
  if (!window.confirm("End the current battle?")) return;
  render(await request("/api/end", "POST", {}));
});

document.getElementById("preview").onclick = () => run(async () => {
  const next = await request("/api/preview", "POST", {
    choice: document.getElementById("choice").value
  });
  await renderAndAutoLock(next);
});

document.getElementById("commit").onclick = () => run(async () => {
  document.getElementById("status").textContent = "RESOLVING";
  const next = await request("/api/commit", "POST", {
    choice: document.getElementById("choice").value
  });
  await renderAndAutoLock(next);
});

document.getElementById("reconcile").onclick = () => run(async () => {
  const next = await request("/api/reconcile", "POST", {});
  await renderAndAutoLock(next);
});

request("/api/state").then(renderAndAutoLock).catch(error => {
  document.getElementById("error").textContent = String(error);
});
</script>
</body>
</html>
"""


class DemoRequestHandler(BaseHTTPRequestHandler):
    server_version = "ChampionsPracticeDemo/0.1"

    @property
    def app(self) -> DemoBattleSession:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print(f"[demo] {self.address_string()} - {format % args}")

    def _send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_html(self) -> None:
        encoded = DEMO_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    @staticmethod
    def _choice(payload: dict[str, object]) -> str:
        choice = payload.get("choice")
        if not isinstance(choice, str) or not choice.strip():
            raise ValueError("choice must be a non-empty string")
        return choice

    def do_GET(self) -> None:
        if self.path == "/":
            self._send_html()
            return
        if self.path == "/api/state":
            self._send_json(self.app.snapshot())
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/start":
                result = self.app.start()
            elif self.path == "/api/preview":
                result = self.app.commit_preview(self._choice(payload))
            elif self.path == "/api/lock":
                result = self.app.lock_ai_action()
            elif self.path == "/api/commit":
                result = self.app.commit_human_action(self._choice(payload))
            elif self.path == "/api/reconcile":
                result = self.app.reconcile_failed_turn()
            elif self.path == "/api/end":
                result = self.app.end_battle()
            else:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
        except (ValueError, RuntimeError) as error:
            self._send_json(
                {"error": str(error)},
                status=HTTPStatus.CONFLICT,
            )
            return
        except json.JSONDecodeError:
            self._send_json(
                {"error": "invalid JSON request body"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception as error:
            self._send_json(
                {"error": f"{type(error).__name__}: {error}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        self._send_json(result)


class DemoHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        app: DemoBattleSession,
    ) -> None:
        super().__init__(server_address, DemoRequestHandler)
        self.app = app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Champions practice demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Refusing non-localhost binding for the practice demo.")

    app = DemoBattleSession()
    server = DemoHTTPServer((args.host, args.port), app)
    url = f"http://{args.host}:{args.port}/"
    print(f"Champions practice demo: {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()


if __name__ == "__main__":
    main()

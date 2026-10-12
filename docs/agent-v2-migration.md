# Independent V2 player: controlled migration

The next development priority is a competent public-state player. Continuous
native-state maintenance remains isolated research, not a prerequisite for policy
development. Keep the pinned mechanics engine, protocol, privacy boundaries,
legal menus, replay/team tools, regression fixtures and existing production bot.
Do not weaken admission or add fresh-state reconstruction support to enable V2.

The first slice lives in `src/champions_practice/agent_v2/`, outside the large
belief controller. It takes immutable public and owned facts, an authoritative
legal menu and an absolute monotonic deadline. The adapter copies an explicit
allowlist and retains neither a raw request nor a native state. Opponent active
facts cannot contain private moves, items, abilities, speeds or exact HP. Future
revealed-set evidence needs a separately typed public-evidence channel; it is
not inferred from private sets here.

The policy establishes a legal incumbent, then ranks complete joint commands.
Its heuristic uses static public move data, species typing assumptions, visible
health, target identity, own STAB, burn, switches, support and redundant Tailwind.
It penalizes deliberate damaging ally targets.
It also discounts partner exposure for moves whose pinned target is
`allAdjacent`; `allAdjacentFoes` does not receive this penalty. Partner Protect,
switching or assumed typing immunity cannot certify safety in this heuristic.
It does not calculate damage,
KO likelihood, threat responses, protection history or win probability. Utility
and score margin are uncalibrated. Typing, ability effects, variable-power moves
and other interactions can make its pressure proxy wrong; explanations disclose
these assumptions. This is a baseline to improve, not a finished strategy model.

The clock is cooperative, checked between action evaluations. Metadata loading
is a startup operation outside that clock. An already expired deadline returns
the first authoritative action. Wait, replacement and preview actions remain
legal. Pilot battles fix preview selections to `1234` to isolate move selection;
team selection intelligence is not demonstrated.

Static metadata comes from the pinned Champions Dex through
`tools/agent-v2-catalog.js`. That tool accepts no battle inputs and imports no
Battle/session API. `policy.py` calls neither reconstruction nor simulator search.
The separate audit driver owns simulator sessions and seeds; none enters the
decision input. Shadow decisions are recorded on baseline battles without
changing submitted actions. Actual V2 decisions are used only in offline pilot
battles. No live production hook is enabled.

## Run and evaluate

```powershell
.\.venv\Scripts\python.exe -m champions_practice.agent_v2.audit --seeds 2 --output runs/agent-v2/pilot.json
```

The paired pilot reverses sides, uses balance/rain/sand as both own and opponent
teams, three opponent policies, and independent battle seeds. Baseline is exactly
`choose_public_fallback`, not the production bot with tactical search. Each
baseline game records V2 shadow decisions. Reports include legal menus, typed
facts, candidate reasons, score margins, coverage, timing, commands and terminal
outcomes. Opponent policies receive only their own legal command menu. Candidate
games use the same seeds/configuration; divergent actions naturally change rolls
consumed and subsequent observations.

Do not call a favorable small synthetic pilot competitive strength. Next freeze
this policy and expand held-out teams, seed ranges, opponent policies and paired
outcome analysis before connecting it to the production fallback path. A model
ranking signal, damage advisor and certified native search remain optional later
capabilities. Promote each only after on/off gameplay evidence and privacy,
legality and latency gates; keep a legal policy decision available throughout.

## Migration sequence

1. Freeze production baseline and fixture/source identities; establish typed V2
   interface and offline shadow/actual-play pilot (this slice).
2. Expand adversarial and held-out evaluation and measure paired outcomes,
   resource budgets and decision failures; establish a promotion criterion.
3. Add a persistent public-evidence uncertainty model with explicit unknowns
   and calibration. Surprising evidence must not prevent legal decisions.
4. Add independently verified tactical advice and then optional learned ranking,
   target-aware policy/value models and anytime search, with component ablations.
5. Build self-play champion/challenger training after evaluations support it.

No language rewrite, deletions, PyTorch runtime or production promotion is part
of this slice. PR #244 passed CI but remains a separate offline frontier
experiment; its additional-suite regression reinforces this migration decision.

# Public weather-duration admission — 2026-10-15

The eight retained positions previously rejected for public effect duration now pass that gate. **Usable native positions remain 0/12.** The next unsupported mechanics are Earthquake (7), owned Unburden (2), Stomping Tantrum (2), and confusion (1). This repairs a specific admission gap, not full-game native availability or playing strength.

## Bounded change

Rain/Drizzle and sand/Sand Stream now use a public activation/residual timeline alongside existing terrain and Trick Room plans. A complete turn-one opening plus continuous public weather snapshots can establish an opening origin even in legacy archives whose opening activation delta is omitted. Later activations require a disclosed source and ability. Explicit upkeep boundaries establish elapsed residuals; missing boundaries, unknown starts, unsupported weather or weather-extender inventory changes remain unresolved.

Each fresh native source-set hypothesis determines its own initial duration. The constructor calls pinned native weather start and residual handlers; it never writes a timer. Independent admission checks verify source identity, source side where disclosed, and the native duration expected from that hypothetical source's item. An unrevealed item is never replaced with the live opponent's item.

Native testing uncovered a second hazard: `fieldEvent('Residual', [])` excludes ordinary Pokémon residual handlers, but Sandstorm's field callback independently calls `eachEvent('Weather')`. That damaged already reconstructed Pokémon a second time. The field-only construction timeline now temporarily detaches native active-slot arrays during each residual and restores their references in `finally`. Native field callbacks still age and expire effects, with no Pokémon weather targets. Exact own request, public projection, native round-trip and legal-menu admission checks remain required.

## Native controls and uncertainty

Both six-member test teams and both source-item alternatives pass the pinned Champions team validator. Damp Rock and Smooth Rock are format-legal here; their native callbacks extend rain/sand from five to eight turns. Added only these two stateless items to the persistent support allowlist.

Against the **same public observation**, independently submitted ordinary-item and extender-item priors produce remaining-duration hypotheses **4 and 7** after one residual. Both rain and sand pass complete request/projection/legal-menu checks. Corrupting each admitted timer by one is rejected. The sand control also verifies construction does not apply duplicate weather damage. Existing native terrain uncertainty and persistent admission controls still pass.

The control submits item domains separately. The existing bounded global proposal sampler can spend its root budget on roster alternatives and omit an item alternative; **this is not exhaustive duration-domain coverage**. No production claim is made that both worlds are always retained within a two-particle budget.

## Validation and reproduction

- New public timeline tests cover continuous openings, missing boundaries, disclosed restarts after upkeep, unknown sources, expiration messages, item changes, unsupported weather, and incomplete history.
- Full suite at validation time: **1,701 passed** (includes concurrent objective investigation tests).
- Native weather controls and existing `persistent_admission_smoke` pass; Ruff and Node syntax check pass.
- Original historical report and archives are untouched. New source/archive hashes and case outcomes are in the companion JSON.

With `PYTHONPATH=src`, use the existing environment Python:

```powershell
../champions-practice-bot/.venv/Scripts/python.exe scripts/public_duration_controls.py
../champions-practice-bot/.venv/Scripts/python.exe scripts/public_duration_probe.py
../champions-practice-bot/.venv/Scripts/python.exe -m champions_practice.persistent_admission_smoke
```

New raw outputs are in `runs/v2-public-durations/`. The probe retains the original 12 public checkpoints, own known actions, eight-second preparation budget, and admission limits. It receives no actual opponent command, live native snapshot, or battle seed.

No leaf scoring, response aggregation, candidate limits, search horizon, default V2 policy, or PR #249 changes belong to this investigation. Further admissions require separately justified persistent-mechanics support; these blockers were deliberately not whitelisted to improve the headline count.

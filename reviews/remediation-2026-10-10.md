# First correctness remediation — October 10, 2026

Base: merge #236, `ddfea3a84221ebf40a3a4f81625f98509ca36aea`.
Runtime source fingerprint after changes:
`2b4713b8dd689cb661a744619fbd47af8c62f4de5d7b539fa279738519213829`.
The implementation is uncommitted; benchmark reports explicitly record that fact.

## Implemented

- The production decision engine rejects fresh midgame hypotheses containing
  unsupported effect durations or protection history before worker startup.
  Old particles cannot bypass the gate. Decisions remain legal fallbacks with
  specific public-only reasons.
- Native negative controls now reproduce the terrain 4-to-5 timer mismatch and
  missing repeat-Protect counter, then verify that the actual production engine
  refuses both. CI runs this smoke in addition to the existing diagnostic tests.
- Benchmark run identities bind runtime source content, including new modules
  and uncommitted edits. A change during gameplay prevents a complete report.
  Cached and refreshed dirty-tree runs receive appropriate identities.
- Parallel report writes use distinct temporary files and bounded retries for
  Windows sharing/access failures. The shared `.part` collision encountered
  during paired benchmarks is covered by a concurrent regression test.
- Local demo mutations validate Host, browser Origin, JSON content type and an
  unpredictable per-server token. Foreign Host reads are rejected too.
  Malformed JSON returns 400, oversized requests 413 and unsupported content
  types 415. Battle-state conflicts still return 409.
- The browser sends the request token automatically. Refresh an existing tab
  after restarting the server.
- Status, support limitations and review-milestone documentation are updated.

## Validation

**1,473 tests passed**, including live localhost HTTP requests, malicious-origin
controls, counter support gates, dirty-source caching and simultaneous report
writers. Ruff, Node syntax and Git whitespace checks passed.

Pinned native smokes passed: production latent-mechanics gate, sealed controller,
forced-switch/terminal transitions, human turn-one Mega public ledger, worker
lifecycle hardening, Unburden lifecycle, fainted active-slot construction, and
session/exact-fork parity. The complete CI smoke matrix was not run locally.

The Mega smoke retains its original low-search regression check for supported
states. New safety fallbacks are allowed only when independently predicted from
the pre-decision public checkpoint and matched exactly to the reported reason.
Diagnostic constructor smokes continue to isolate individual mechanics; they
do not certify production support for missing timer/protection domains.

## Paired benchmark evidence

Both runs use the same runtime fingerprint, pinned Showdown, eight games,
seed 15601 and the original eight-second decision budget. Reports are local,
immutable and under the gitignored `runs/` directory.

| Fixture | Before | After | Before search / decisions | After search / decisions | Before fallback | After fallback |
|---|---:|---:|---:|---:|---:|---:|
| Mirror | 7–1 | 7–1 | 32 / 51 | 8 / 65 | 5 / 51 | 44 / 65 |
| Synthetic uncertainty | 6–2 | 2–6 | 67 / 92 | 8 / 88 | 13 / 92 | 68 / 88 |

After run IDs:

- Mirror: `a80b64e22f25dd4ec37d` — 8,128 simulated branches, 13 forced waits,
  44 effect-duration fallbacks; mean decision time 0.957 seconds.
- Synthetic: `250a0bcb4d56ef1a6acb` — 8,128 simulated branches, 12 forced waits,
  67 effect-duration fallbacks and one exact-own-item failure; mean decision
  time 0.711 seconds.

All after-search decisions were turn-one searches. Faster averages primarily
reflect fallback, not improved search efficiency. The uncertainty result is a
real gameplay regression on this fixture and must remain visible.

## Remaining work

**Subsequent recovery:** public terrain age reconstruction now restores midgame
search. Mirror fallback fell to 6/51 (11.8%) and synthetic to 25/72 (34.7%). The
containment results above remain historical evidence of its coverage cost.
See `reviews/recovery-2026-10-10.md` for implementation, paired evidence and
remaining recovery priorities. The following original next steps are partly
superseded for terrain, but remain applicable to other timers and protection.

This change blocks the reproduced unsafe production admission path. It does
**not** restore native timer or protection counter domains. The experimental
offline constructor still reproduces those gaps and cannot be used as an
alternative production route.

Next implement public start/end/reset/extension evidence and protection-chain
domains, then supported native construction with expiration, failed-attempt,
switch, called-move and serialization controls. Re-enable each mechanic only
after those controls pass, and repeat these exact paired benchmark settings.
See `docs/present-mechanics-support.md` for acceptance criteria.

Forced-switch tactical search, remaining own Mega/ability/item restoration,
stronger baselines, learned-prior integration, broader team practice and module
refactoring remain outstanding. This is the first safety milestone, not a
claim that the entire project roadmap or all review findings are complete.

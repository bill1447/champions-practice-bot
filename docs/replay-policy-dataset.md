# Replay legal-menu policy adapter

The replay trajectory layer records only action identity that a public replay can actually
support. Policy training eventually needs something stricter: one observed human action must
map to one member of the same complete joint-action menu used by the live search.

This adapter performs that mapping without upgrading incomplete replay evidence into an exact
Showdown command.

## Inputs

A policy example requires three separate ingredients:

1. the public replay decision row produced by `replay_trajectories.py`;
2. the choosing side's exact legal joint-action menu from pinned Showdown;
3. the choosing side's party-slot species order for resolving `switch N` commands.

The legal menu is an explicit authority input. The adapter does not derive it from the replay
trajectory and will reject a policy row whose menu is not tagged
`pinned-showdown-legal-choices`.

That distinction matters because a normal public replay does not expose the choosing player's
complete request. It may reveal team-preview species and actions as they occur, but it does
not prove every unrevealed move, disabled move, trapping state, party-slot ordering after team
preview, or transformation option required to enumerate the exact menu.

## Matching rules

The adapter parses the exact Showdown choice strings already used by search, including
two-slot combinations such as:

```text
move protect, move followme
switch 3, move direclaw +1
move expandingforce +2 mega, move protect
```

It then matches only authority-safe replay identity:

- move ID must match;
- public transformation identity must match;
- a switch is matched through the supplied player-side party-slot species mapping;
- pass must match pass;
- called moves are already excluded by trajectory extraction;
- incomplete replay labels remain abstentions.

### Selected targets

A public `|move|` event gives the resolved target, not necessarily the target originally
selected by the player. Follow Me, redirection abilities, and other mechanics can change it.

For that reason the adapter deliberately ignores the replay's resolved target when selecting
a legal command.

If two legal menu entries differ only by selected target, the result is:

```text
trainable = false
reason = selected-target-ambiguous
```

If only one legal target variant exists, the semantic replay action can map to that unique
menu entry without claiming that the replay itself revealed a private command token.

### Mega variants

The replay trajectory currently records the public `-mega` event as generic Mega evidence.
If the exact menu contains multiple Mega variants such as `megax` and `megay`, the adapter
does not guess which one was submitted. It abstains with `gimmick-variant-ambiguous`.

## Output

A policy example preserves:

- replay ID and replay-disjoint `game_group`;
- turn and side;
- the public decision-time state;
- the replay action identity;
- the complete exact legal menu;
- the player-side party species order used for switch resolution;
- Showdown revision and legal-menu authority;
- exact matched menu index/choice when unique;
- explicit abstention reason and candidate indices when not unique.

Only rows with `trainable=true` are suitable as exact-menu behavior-cloning labels.

## Important limitation

PR #146 made public replay action extraction sound, but public replay data by itself is not
enough to recreate the actor's complete legal menu. This adapter intentionally exposes that
gap instead of silently filling it with inferred moves or hidden-state guesses.

The next policy-data step must choose an authority-safe source for player-side menu context.
Possible sources include positions for which the player's exact own team/request is genuinely
known, or a policy design that trains on semantic action identity and applies the exact legal
menu only at inference/evaluation time.

Opponent private information must never be used merely to make a replay row easier to label.

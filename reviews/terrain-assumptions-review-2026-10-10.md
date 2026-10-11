# Additional terrain assumptions review

This is a focused follow-up review by the implementing agent, with additional
pinned native controls. It is not an independently staffed milestone audit.

## Findings and changes

1. **Final slot identity is not activation identity.** The earlier helper read
   source species from the snapshot's final active occupant. A later switch can
   replace that occupant while terrain persists. The producer now retains ordered
   public switch/drag and move/cant events. Source species is resolved at the
   activation event, using only that public timeline.
2. **Identical starts are separate occurrences.** Deduplicating by turn and event
   text can collapse separate activations. Ordered event positions and verified
   growing prefixes now preserve each occurrence. An overwrite and subsequent
   activation use the latest observed start, not an earlier matching identity.
3. **Same-terrain Surge entry is not a refresh.** Pinned `Field.setTerrain` returns
   false when the same terrain is already active. The native control switches a
   Surge user out/back without another terrain in between: remaining durations
   are four, then three. The public reconstruction matches both.
4. **Overwrite/reactivation resets through the native setter.** A native Grass →
   Psychic → Grass fixture leaves four turns after each activation and the
   reconstructed counters match. Retained Terrain Extender controls match seven,
   then six, with native serialization roundtrips.
5. **Completion matters.** A forced-replacement snapshot can contain only a
   prefix of that turn's events. Every completed source turn now requires an
   observation at the next move phase. Missing turns or changed prefixes are
   unresolved rather than timing authority.
   The replay also checks the final terrain against public ends and overwrites;
   a current identity cannot resurrect an effect after its last observed end.
6. **Extension inventory and borrowed abilities remain limited.** Public extender
   loss/acquisition can invalidate a static-set duration assumption. Those events
   reject terrain support for now. Trace can produce a public Surge source whose
   static native ability differs; the native constructor rejects that source
   rather than impersonating a permanent Surge ability.

Opening source/extension hypotheses still depend on approved hypothetical sets;
the source chosen by a native opening is not a public proof of a unique source
or private extension item. No hypothesis receives negative exclusion authority.
Broader source/extension domain coverage remains a follow-up requirement.

## Validation and support claim

Unit controls include activation identity surviving a later slot replacement,
identical starts around an intervening overwrite, missing/partial history and
public extender loss. Native controls compare timer counters only as offline
oracles; those counters never enter production plans.

The supported subset is continuous opening terrain or a complete, public,
ordered native Surge start with a constructible source and extension assumption.
Do **not** describe terrain reconstruction as fully supported.

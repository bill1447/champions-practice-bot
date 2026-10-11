"""Isolated 11B validator. Oracle state/verdicts are never tracker inputs."""

from copy import deepcopy
import json
import hashlib

from champions_practice.observation_beliefs import public_observation_signature

# Protocol history is checked through the sanitized public signature. Internal
# log/bookkeeping and PRNG are not current mechanics. Everything else is compared.
NON_MECHANICAL = frozenset(("prng", "prngSeed", "inputLog", "log", "messageLog",
                           "sentLogPos", "sentEnd", "sentRequests", "hints"))
FUTURE_SEEDS = ("sodium," + "4" * 64, "sodium," + "5" * 64)


def mechanical_projection(state):
    return {key: deepcopy(value) for key, value in state.items() if key not in NON_MECHANICAL}


def mechanical_fingerprint(state):
    payload = json.dumps(mechanical_projection(state), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def first_difference(left, right, path="$"):
    if type(left) is not type(right):
        return path + ":type"
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path + ":keys"
        for key in sorted(left):
            found = first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return path + ":length"
        for i, (a, b) in enumerate(zip(left, right, strict=True)):
            found = first_difference(a, b, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if left == right else path


def continuous_witness_lineages(previous, witnesses, *, opening=False):
    """A later matching state cannot restore a lost matching ancestry chain."""
    return {witness["lineage"] for witness in witnesses
            if opening or witness["parent_lineage"] in previous}


def validate_checkpoint(oracle, session_id, inspection, public_view, previews,
                        next_commands=None):
    if not inspection["current"]:
        return {"mechanical_witnesses": 0, "future_comparisons": 0,
                "stale_hypotheses_not_validated": True, "native_mismatch_paths": {}}
    reference = oracle.session_snapshot(session_id)["state"]
    paths = {}
    matches = []
    ancestry = []
    for particle in inspection["particles"]:
        state = particle["state"]
        actual_view = oracle.state_view(state=state, side="p1", previews=previews)
        if public_observation_signature(actual_view) != public_observation_signature(public_view):
            difference = first_difference(json.loads(public_observation_signature(public_view)),
                                          json.loads(public_observation_signature(actual_view)))
            raise AssertionError("retained particle violates public evidence or own request: " + str(difference))
        if sorted(oracle.legal_choices(state=state, side="p1")) != sorted(oracle.session_legal_choices(session_id, side="p1")):
            raise AssertionError("retained particle violates authoritative own legal menu")
        mismatch = first_difference(mechanical_projection(reference), mechanical_projection(state))
        if mismatch:
            paths[mismatch] = paths.get(mismatch, 0) + 1
        else:
            matches.append(state)
            ancestry.append({"lineage": particle["lineage"], "root": particle["root"],
                             "parent_lineage": particle.get("parent_lineage")})
    future_checks = 0
    if matches and next_commands and not reference.get("ended"):
        for seed in FUTURE_SEEDS:
            branch = {"p1_choice": next_commands[0], "p2_choice": next_commands[1],
                      "rng_seed": seed, "include_state": True}
            expected = oracle.branch_many(state=reference, branches=[branch])[0]["state"]
            actual = oracle.branch_many(state=matches[0], branches=[branch])[0]["state"]
            difference = first_difference(mechanical_projection(expected), mechanical_projection(actual))
            if difference:
                raise AssertionError("coupled hypothetical future diverged: " + difference)
            future_checks += 1
    return {"mechanical_witnesses": len(matches), "future_comparisons": future_checks,
            "witness_ancestry": ancestry,
            "oracle_mechanical_fingerprint": mechanical_fingerprint(reference),
            "native_mismatch_paths": paths,
            "rng_serialization_differs": bool(matches) and json.dumps(reference.get("prng")) != json.dumps(matches[0].get("prng")),
            "current_mechanics_equivalent": bool(matches),
            "actual_next_roll_predicted": False}

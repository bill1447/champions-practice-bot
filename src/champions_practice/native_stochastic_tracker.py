"""Offline 11B tracker capability: known sets/actions, public evidence only.

No oracle imports, seed argument, inbound serialized state or session capability.
Finite chance inputs drive native mechanics; stored PRNG is a hypothetical future,
not an inferred oracle stream. Sampling establishes witnesses, never disproof.
"""

from pathlib import Path

from champions_practice.config import CHAMPIONS_FORMAT
from champions_practice.search_worker import ShowdownSearchWorker

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class NativeStochasticTracker:
    def __init__(self):
        self.__transport = ShowdownSearchWorker(
            worker_script=PROJECT_ROOT / "tools/native-stochastic-worker.js",
            request_timeout_seconds=8,
        )

    def canonical_team(self, team: str) -> str:
        return self.__transport.request("canonical_team", team=team, format=CHAMPIONS_FORMAT)["team"]

    def initialize(self, *, p1_team, p2_team, p1_preview, p2_preview, public_view,
                   max_particles=12):
        return self.__transport.request(
            "initialize", format=CHAMPIONS_FORMAT, p1_team=p1_team, p2_team=p2_team,
            p1_preview=p1_preview, p2_preview=p2_preview, view=public_view,
            max_particles=max_particles,
        )

    def advance(self, *, p1_choice, p2_choice, public_view, samples=96,
                max_particles=12, milliseconds=600, max_bytes=2 * 1024 * 1024,
                force_chance_false=False, generation="sampled"):
        return self.__transport.request(
            "advance", p1_choice=p1_choice, p2_choice=p2_choice, view=public_view,
            samples=samples, max_particles=max_particles, milliseconds=milliseconds,
            max_bytes=max_bytes, force_chance_false=force_chance_false,
            generation=generation,
        )

    def inspection_for_validator(self):
        """Outbound hypotheses only; cannot accept a validator's state or verdict."""
        return self.__transport.request("inspect")

    def finite_control(self, *, p1_choice, p2_choice, public_view, max_nodes=4096,
                       milliseconds=1000):
        return self.__transport.request(
            "finite_control", p1_choice=p1_choice, p2_choice=p2_choice,
            view=public_view, max_nodes=max_nodes, milliseconds=milliseconds,
        )

    def close(self):
        self.__transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

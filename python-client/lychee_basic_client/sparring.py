"""Aggressive sparring opponent for LOCAL adversarial testing.

The official l1-demo never guards or contests, so it can't validate our PvP
handling. This bot, run on the real referee server as the other player, does what
the strong intranet opponents do: as it passes the map's choke point on its way
to the gate it SETS A GUARD there to lock us out, then finishes a normal delivery.
If our main client can still deliver and score well against it, our guard handling
really works.

It subclasses the main Strategy, so navigation / process / obstacle / delivery all
reuse the proven logic -- a competent opponent, not just a griefer. It only injects
one SET_GUARD when standing on the choke.
"""
from typing import Any, Optional

from . import messages as M
from .strategy import Strategy

GUARD_MIN_FRUIT = 4      # keep enough good fruit to still deliver
MAX_GUARD_TRIES = 6      # give up guarding if it won't take (avoid a loop)


class AggressiveStrategy(Strategy):
    def __init__(self, player_id: int) -> None:
        super().__init__(player_id)
        self._choke: Optional[str] = None
        self._guard_done = False
        self._guard_tries = 0

    def ingest_start(self, start_data: dict[str, Any]) -> None:
        super().ingest_start(start_data)
        chokes = self.graph.choke_points(self.start_node, self.gate_node)
        # hold the choke nearest the gate that ISN'T a process station (so SET_GUARD
        # isn't tangled with a mandatory process); fall back to any choke.
        non_proc = [c for c in chokes if c not in self.graph.process_rounds]
        self._choke = (non_proc or chokes or [None])[0]
        # rush the choke to guard it first, and take a divergent route off the start
        # so we don't collide with our opponent at the first process station (which,
        # in self-play with identical clients, dead-locks on a mutual draw).
        self.collect_tasks = False
        first = self.graph.next_hop(self.start_node, self.gate_node)
        if first:
            self.route_avoid = {first}

    def decide(self, inquire_data: dict[str, Any]) -> list[dict[str, Any]]:
        me = self._find_me(inquire_data.get("players", []))
        if me is not None and self._choke and not self._guard_done:
            for e in inquire_data.get("events") or []:
                if e.get("type") == "GUARD_SET" and (e.get("payload") or {}).get("playerId") == self.player_id:
                    self._guard_done = True
            if (
                not self._guard_done
                and me.get("currentNodeId") == self._choke
                and me.get("state") in ("IDLE", "WAITING")
                and not me.get("routeEdgeId")
                and me.get("goodFruit", 0) > GUARD_MIN_FRUIT
            ):
                if self._guard_tries < MAX_GUARD_TRIES:
                    self._guard_tries += 1
                    return [M.set_guard(self._choke, extra_good_fruit=2)]
                self._guard_done = True  # couldn't set it -> just play on
        return super().decide(inquire_data)

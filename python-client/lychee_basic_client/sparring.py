"""Sparring opponent for LOCAL adversarial testing (--strategy aggressive).

A plain delivery rusher: race the robust-fastest route to the gate, VERIFY in
RUSH, then deliver -- no tasks, no guards. It reuses the base navigation, so it
handles process stations and road obstacles competently. It exists so our
blockade strategy has a real "opponent trying to deliver" to shut out on the
local referee server.
"""
from typing import Any

from .strategy import Strategy


class AggressiveStrategy(Strategy):
    def _blockade(self, me, opp, node, state, phase, round_no, tasks, nodes_by_id):
        dest = self.terminal_node if me.get("verified") else self.gate_node
        return self._advance_to(dest, me, node, state, phase, nodes_by_id)

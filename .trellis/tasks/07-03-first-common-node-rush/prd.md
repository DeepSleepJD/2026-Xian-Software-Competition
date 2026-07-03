# 抢第一个公共节点并取消拦截蹲守

## Goal

When our route and the opponent's route converge, the client should prioritize reaching the first actionable common guard point before the opponent. This is an aggressive tempo change: before that node is secured, economy should yield and delivery should drive toward it as a temporary hard objective.

## Requirements

- Compute a "first common node" target from current map state without hard-coded node IDs.
- Prefer a common node that is useful for interception: currently `KEY_PASS` / `PASS`, reachable by both sides, and reachable by us early enough to finish `SET_GUARD` before the opponent arrives.
- Before reaching that target, suppress non-critical economy detours so delivery can rush the target.
- Remove the existing long camp behavior: standing on an interception node must not by itself suppress delivery movement.
- After setting a guard, delivery should continue forward toward the next objective/terminal instead of waiting on the same node.
- Preserve hard delivery safety gates: if `delivery_deadline_hit` / `must_rush` applies, rush the terminal.
- Keep validation lightweight for fast iteration: focused unit tests plus the existing interception integration slice.

## Acceptance Criteria

- [x] A safety helper returns the first actionable common/interception node in a synthetic route race.
- [x] Economy returns no task/resource move while a first-common-node rush target is pending.
- [x] Delivery does not camp merely because `interception_node(state) == current_node`.
- [x] Existing set-on-commit / rolling guard behavior can still emit `SET_GUARD` at the common node.
- [x] Focused regression tests pass for `test_safety.py`, `test_delivery.py`, `test_economy.py`, and `test_interception_integration.py`.

## Notes

- User preference: fast iteration over exhaustive regression in this pass.
- User correction: remove "arrive then camp"; the client should set the guard when possible and then move on.

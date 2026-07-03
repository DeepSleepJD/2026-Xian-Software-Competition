# 抢第一个公共节点并取消拦截蹲守

## Goal

When our route and the opponent's route converge, the client should prioritize reaching the first actionable common guard point before the opponent. This is an aggressive tempo change: before that node is secured, economy should yield and delivery should drive toward it as a temporary hard objective.

## Requirements

- Compute a "first common node" target from current map state without hard-coded node IDs.
- Prefer the first useful interception node on the map-theoretical frames-shortest route: currently `KEY_PASS` / `PASS`, reachable by both sides, and not excluded by map roles.
- Once that target is selected, keep rushing it until arrival / friendly guard / deadline release. Current-frame ETA disadvantage must not cancel the target.
- Before reaching that target, suppress non-critical economy detours so delivery can rush the target by frames-first shortest path.
- Remove the existing long camp behavior: standing on an interception node must not by itself suppress delivery movement.
- After setting a guard, delivery should continue forward toward the next objective/terminal instead of waiting on the same node.
- Preserve hard delivery safety gates: if `delivery_deadline_hit` / `must_rush` applies, rush the terminal.
- Keep validation lightweight for fast iteration: focused unit tests plus the existing interception integration slice.

## Acceptance Criteria

- [x] A safety helper returns the first actionable common/interception node in a synthetic route race.
- [x] The safety helper keeps the map-derived target even when current ETA later flips against us.
- [x] Economy returns no task/resource move while a first-common-node rush target is pending.
- [x] Delivery does not camp merely because `interception_node(state) == current_node`.
- [x] Delivery rush movement is frames-first and not suppressed by `hold_before_choke` before arrival.
- [x] Existing set-on-commit / rolling guard behavior can still emit `SET_GUARD` at the common node.
- [x] Focused regression tests pass for `test_safety.py`, `test_delivery.py`, `test_economy.py`, and `test_interception_integration.py`.

## Notes

- User preference: fast iteration over exhaustive regression in this pass.
- User correction: remove "arrive then camp"; the client should set the guard when possible and then move on.

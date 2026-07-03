# Design

## Scope

Touch only strategy helpers and their direct callers:

- `client/lychee/strategy/safety.py`
- `client/lychee/strategy/delivery.py`
- `client/lychee/strategy/economy.py`
- `client/lychee/strategy/combat.py`
- focused tests under `client/tests/`

## Behavior

Add a shared safety helper for the aggressive rush target. The helper should reuse existing ETA and pathing primitives:

1. Determine the nearest terminal anchor.
2. From the start/map role, compute the frames-first theoretical shortest route to that terminal.
3. Pick the earliest actionable guard node (`KEY_PASS` / `PASS`) on that theoretical route, excluding map `rushExcludedNodeIds`.
4. Latch the target for the current `GameState`; do not drop it merely because current-frame ETA later flips against us.
5. Return `None` if the opponent is absent, retired, delivered, a delivery deadline is active, a friendly guard already secures the target, the opponent is already locked by our guard, the target has been passed, or no actionable common node exists.

This intentionally keeps the target guard-oriented. Non-guard common nodes are not useful enough for this fast pass because they cannot create the decisive set-guard tempo swing.

## Callers

- `economy`: when a rush target exists, suppress non-critical economy proposals. Already-held rush-helpful resource use may still fire by priority; new task/resource claims yield.
- `delivery`: do not camp merely because the current node is an interception node. Existing movement and `combat._propose_set_guard` decide whether the node gets guarded. Before arrival, rush movement uses a frames-first path and is not suppressed by `hold_before_choke`. If combat sets a guard, arbiter priority suppresses same-frame MOVE; next frame delivery continues forward.
- `combat`: treat the first-common rush node as a valid guard target so the client actually
  completes the "arrive, set, move on" sequence even when the node is a fastest-path common
  point rather than a strict topology cut.

## Compatibility

Existing `interception_node()` stays available for combat / locked-state logic. The new helper can wrap or reuse it where the semantics align, but it must not reintroduce indefinite camp.

## Rollback

All changes are isolated to strategy helpers/callers. Reverting the helper and the economy/delivery call sites restores previous behavior.

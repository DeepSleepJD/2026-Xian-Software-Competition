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
2. Compare our remaining route and the opponent's remaining route by frames-first ETA.
3. Pick the earliest common actionable guard node (`KEY_PASS` / `PASS`) that we can reach with enough time to complete the 4-frame guard setup before the opponent arrives.
4. Return `None` if the opponent is absent, retired, delivered, a delivery deadline is active, or no actionable common node exists.

This intentionally keeps the target guard-oriented. Non-guard common nodes are not useful enough for this fast pass because they cannot create the decisive set-guard tempo swing.

## Callers

- `economy`: when a rush target exists and we are not already at it, suppress non-critical economy proposals. Critical delivery resources remain governed by existing hard-need logic in future iterations; this pass favors speed and simplicity.
- `delivery`: do not camp merely because the current node is an interception node. Existing movement and `combat._propose_set_guard` decide whether the node gets guarded. If combat sets a guard, arbiter priority suppresses same-frame MOVE; next frame delivery continues forward.
- `combat`: treat the first-common rush node as a valid guard target so the client actually
  completes the "arrive, set, move on" sequence even when the node is a fastest-path common
  point rather than a strict topology cut.

## Compatibility

Existing `interception_node()` stays available for combat / locked-state logic. The new helper can wrap or reuse it where the semantics align, but it must not reintroduce indefinite camp.

## Rollback

All changes are isolated to strategy helpers/callers. Reverting the helper and the economy/delivery call sites restores previous behavior.

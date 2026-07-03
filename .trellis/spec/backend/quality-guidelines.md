# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

### Lychee Client Strategy Contracts

**Scope**: `client/lychee/strategy/*`, `client/lychee/pathing.py`, and `client/lychee/state.py`.

**Signatures**:

```python
class Strategy:
    def propose(self, state: GameState) -> list[Intent]:
        ...

@dataclass
class Intent:
    kind: str
    priority: int
    actions: list[dict]
    note: str = ""
```

**Contracts**:
- Strategies are read-only consumers of `GameState`; they must not send messages, mutate connection state, or call each other.
- Strategies express behavior only by returning `Intent` objects. Main-action conflicts are resolved by `arbiter.merge_intents()`, so new actions must use a deliberate priority relative to delivery/economy/combat.
- Shared route cost behavior belongs in `pathing.py`, not in individual strategies. Keep `edge_frames()` as the weather-free base formula; stateful effects such as guard penalties and weather belong in the state-aware path cost helpers.
- Resource claiming semantics belong in one economy resource table. Do not add separate hard-coded loops for each new resource type.
- Protocol payload parsing belongs in `GameState`; strategies should consume parsed fields and helper methods rather than re-decoding raw payload dictionaries.

**Good/Base/Bad Cases**:
- Good: adding weather impact in `pathing._step_cost()` so delivery, economy, and combat all see the same route estimate.
- Base: a strategy-specific heuristic may choose whether to act, but it should call shared pathing helpers for route frames/cost.
- Bad: duplicating `HEAVY_RAIN` or horse movement formulas inside both delivery and economy.

**Tests Required**:
- New strategy action: add a positive proposal test and negative guardrail tests for invalid state, insufficient resource, and priority interaction when relevant.
- New resource type: add claim behavior, active-use behavior if any, and rejection/backoff tests for active use.
- New pathing cost factor: add no-effect baseline and affected-route tests.

### Contract: Choke Trap Hold Gate

**Scope**: `client/lychee/strategy/safety.py`, callers in `delivery.py` and `economy.py`.

**Signature**:

```python
def hold_before_choke(state: GameState, next_node: str) -> bool:
    ...
```

**Contract**:
- Return `True` only to suppress a `MOVE` into `next_node`; callers should simply emit no move for that frame.
- The gate must be disabled when `must_rush(state)` is true, when an enemy guard is already visible at `next_node`, or when `state.me.squad_available >= pathing.guard_max_defense(state, next_node)`.
- The target must be a choke node on the current route to any terminal (`pathing.choke_nodes(state, cur, terminal)`); do not hard-code map node IDs such as `S10` or `S11`.
- Treat the opponent as a guard threat when it has `guardActionPoint >= 1` and either:
  - it is already stopped on `next_node`, or
  - it is moving toward `next_node` and `opponent_remaining_edge_frames + GUARD_SETUP_FRAMES <= my_edge_frames_to(next_node)`.

**Good/Base/Bad Cases**:
- Good: holding at `S10` when the opponent is already ahead on `S10 -> S11`, has guard points, and can arrive plus finish the 4-frame guard setup before us.
- Base: not holding when the opponent is moving away from `next_node`; the guard window for that node has passed.
- Bad: checking only `opponent.currentNodeId == next_node`; that misses the real double-guard failure mode where the opponent is still en route but will finish setup before our arrival.

**Tests Required**:
- Positive regression for a moving opponent that will reach the choke first and finish setup before us.
- Negative regression for a moving opponent whose arrival plus setup is too late.
- Negative regressions for no guard points, visible guard, enough squads, must-rush, non-choke, and delivered opponent.

### Contract: First Common Rush Target

**Scope**: `client/lychee/strategy/safety.py`, callers in `delivery.py`, `economy.py`, and `combat.py`.

**Signature**:

```python
def first_common_rush_node(state: GameState) -> str | None:
    ...
```

**Contracts**:
- Return the first map-derived guard point on the frames-shortest route from the start node to the selected terminal; do not hard-code map node IDs.
- The returned node must be actionable for interception: currently `KEY_PASS` or `PASS`, no active friendly guard already on it, and not listed in `rushExcludedNodeIds`.
- Once a target is selected for a `GameState`, keep returning it while it remains ahead on our frames-shortest route. Do not cancel it just because current `me_eta(node) + GUARD_SETUP_FRAMES > opp_eta(node)` after economy or movement has shifted the race.
- The helper is a rush target, not a camp order. `economy` should yield while the target is pending; `delivery` should route toward it by frames-first shortest path, but once `current_node_id == target`, delivery must continue forward instead of suppressing movement.
- `combat` may treat the returned node as a valid guard target so the sequence is "arrive, set guard, move on" even when the node is a fastest-path common point rather than a strict topology cut.
- Disable the target when a delivery deadline is active, the opponent is absent/delivered/retired, `opponent_locked(state)` is already true, a friendly guard is active on the target, or the target is no longer ahead on our frames-shortest route.

**Good/Base/Bad Cases**:
- Good: skipping an on-node 30-point task at `B` because `C` is the first common `KEY_PASS`, even if the opponent's current ETA to `C` has become better.
- Base: after `SET_GUARD` succeeds at the common node, delivery continues toward the terminal on the next frame.
- Base: active use of held rush-helpful resources (`ICE_BOX`, horses, `INTEL` on its true consumer) may still compete by priority; claiming new resources/tasks must yield.
- Bad: returning `""` from delivery just because `interception_node(state) == cur`; that recreates the old long-camp/self-freeze behavior.
- Bad: recomputing the target from current ETA every frame and releasing it when the opponent briefly appears closer; that recreates the 22:50 loss where `S10` was dropped at round 80.

**Tests Required**:
- Safety regression for a common fastest-path `KEY_PASS` / `PASS` that is not necessarily a topology choke.
- Safety regression proving current ETA disadvantage does not cancel the map-derived rush target.
- Economy regression proving task/resource claims yield before the rush target.
- Delivery regression proving arrival at the target does not camp.
- Delivery regression proving the rush target overrides `hold_before_choke` before arrival.
- Integration regression proving `SET_GUARD` still wins same-frame arbitration over delivery movement.

### Lychee Resource And Tempo Contracts

**Scope**: `client/lychee/strategy/economy.py`, `client/lychee/strategy/combat.py`, and `client/lychee/state.py`.

**Contracts**:
- `USE_RESOURCE` actions must be built through a whitelist helper. Active use is limited to `ICE_BOX`, `FAST_HORSE`, `SHORT_HORSE`, and `INTEL`; `PASS_TOKEN` and `OFFICIAL_PERMIT` must never be actively used because the rules consume documents automatically only when playing `YAN_DIE`.
- Low-value resources need a real consumer before claiming. Documents may be claimed for an active window contest or hard map requirement. `INTEL` should not be claimed speculatively; using an already-held `INTEL` on the current `VERIFY` node is allowed.
- Process-node hard requirements come from `ProcessNode.required_resource_types`. If a resource required by a process node lies on the current delivery path, economy should treat that resource as a hard need even if its base value is low.
- Ice boxes are tempo/freshness reserves, not top-band polish. Do not spend an `ICE_BOX` while freshness is still in the `90+` band only because heat is active or forecast; preserve it for the lower freshness band where the full +10 freshness is retained.
- Scout marker and window-card event payloads belong in `GameState` projections (`scout_marker_events()`, `window_card_reveals()`), not in strategy-local raw payload parsing.

**Good/Base/Bad Cases**:
- Good: `{"action": "USE_RESOURCE", "resourceType": "INTEL", "targetNodeId": cur}` when parked on a `VERIFY` process node with held `INTEL` and no same-team marker.
- Good: Playing `YAN_DIE` from held `PASS_TOKEN` / `OFFICIAL_PERMIT` without emitting a separate `USE_RESOURCE`.
- Base: Claim `BOAT_RIGHT` when a process node on the delivery path lists `requiredResourceTypes=["BOAT_RIGHT"]`.
- Bad: Claiming `INTEL` at a zero-detour node with no hard requirement, then spending a claim read bar and a use frame for break-even or worse tempo.
- Bad: Spending `ICE_BOX` at freshness `94.x`; this recovered no score in demo regression and reduced final freshness score.

**Tests Required**:
- Resource claim tests for low-value no-consumer rejection and hard requirement override.
- Active-use tests for the document whitelist and `INTEL` current-node `VERIFY` use.
- Regression tests proving `ICE_BOX` is not spent in the top freshness band, while lower-band threshold and long-edge predictive use still work.
- State projection tests for any newly consumed event or start-map field.

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)

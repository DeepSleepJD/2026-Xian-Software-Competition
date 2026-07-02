# P4 Combat Backlog Design

## Scope

This task extends the current combat/economy/pathing stack with three features:

- proactive friendly guard placement;
- semantic resource claiming and selected resource use beyond ice boxes;
- weather-aware path and preservation estimates.

The implementation stays inside the existing single-client strategy architecture:

- `CombatStrategy` proposes adversarial actions above economy/delivery priority.
- `EconomyStrategy` proposes task/resource/utility actions above delivery during safe windows.
- `pathing` remains the shared read-only estimator for route cost.
- `GameState` remains the parser and convenience-query layer.

## Friendly Guard Placement

Guard placement belongs in `CombatStrategy` because it is adversarial, consumes the main action slot, and must outrank normal economy moves while staying below immediate self-defense:

1. Keep `BREAK_GUARD` as the highest combat main-action decision.
2. Add `_propose_set_guard()` after break-guard and before squad/window actions.
3. Require stationary state, no current process, current node present, current node not terminal/S15, and no current friendly active guard at the same node.
4. Count friendly active guards from `state.node_states`; if count is already 2, do not place another guard.
5. Estimate whether we are ahead by comparing our remaining path frames to the opponent remaining path frames. If the opponent has already delivered/retired or no path exists, skip.
6. Require current node to be a choke point on the opponent's current-node-to-terminal path, or be the next node on every cheapest opponent route.
7. Compute extra good fruit conservatively:
   - prefer 2 only when `state.my_good` remains above the delivery floor after base/extra guard cost;
   - prefer 1 on key passes when 2 would violate the floor;
   - skip when the resulting defense is too low to justify the 4-frame setup.

The exact score model can be simple and deterministic: estimated delay is guard weathering duration for the expected defense, value is opponent-delay frames minus our setup/cost penalty. This avoids overfitting to S10 while preserving the P4 insight that a key pass guard is usually decisive.

## Resource Generalization

`EconomyStrategy._candidates()` already represents tasks and resources as `_Target` objects and scores them through one shared net-value path. Replace the hard-coded ice-box branch with a resource semantic table.

Resource categories:

- `ICE_BOX`: preservation resource, existing value and max-hold behavior.
- `FAST_HORSE` / `SHORT_HORSE`: mobility resource. Claim value is estimated from likely saved frames on the remaining route and the freshness/time value of those frames.
- `PASS_TOKEN` / `OFFICIAL_PERMIT`: document resources. Claim value is low but positive because they enable `YAN_DIE`; never actively `USE_RESOURCE`.
- `INTEL`: scout resource. Claim value is low-to-moderate when on-route; active use is optional and should target upcoming process nodes where a scout marker can reduce processing.
- `BOAT_RIGHT`: can be claimed if free/on-route but has no active use; keep value low unless later logic consumes it.

The candidate generator should:

- iterate visible `node_states[].resource_stock`;
- skip resources at or above per-type inventory caps;
- create `_Target` with the resource's `claim_round` from `state.resource_specs` when available, falling back to the existing 2-frame constant;
- use the shared feasibility/deadline/backtracking logic.

For active resource use:

- keep ice usage in the existing `_propose_ice_use()`, but make the threshold weather-sensitive;
- add `_propose_horse_use()` with priority high enough to pair with or precede movement. It should not fire when a horse buff or conflicting rush speed is active;
- optionally add `_propose_intel_use()` after horse/ice only for stationary states and targets within path-distance 15.

## Weather-Aware Pathing

Path cost is centralized in `pathing._step_cost()`, so weather should be handled there rather than in each strategy.

Weather model:

- Active weather affects the current estimate immediately.
- Forecast weather should affect a step only when the estimated traversal/processing window overlaps the forecast start. A simple first pass may add a near-future penalty when `forecast.start_round - state.round <= 30` and the edge route type matches.
- `HOT`: freshness multiplier `1.5` globally, movement frames unchanged.
- `HEAVY_RAIN`: route type `WATER` movement uses effective move per frame based on weather multiplier 1350; freshness multiplier `1.3` for water movement and relevant water/board processing.
- `MOUNTAIN_FOG`: route type `MOUNTAIN` movement uses effective move per frame based on weather multiplier 1100; freshness multiplier unchanged.

`edge_frames()` should remain a pure base helper for existing tests. Add a wrapper such as `edge_frames_for_state(state, edge, offset=0)` or fold stateful logic into `_step_cost()` while preserving direct `edge_frames()` behavior.

## Compatibility

- Existing delivery/economy callers should keep using `shortest_path`, `path_cost`, and `path_frames` without signature changes.
- New helper functions must be read-only and tolerant of missing fields.
- Existing tests for ice boxes, guard breaking, and path costs should continue to pass; update expected values only where weather is explicitly present.

## Risks

- Proactive guards can hurt us if they consume good fruit or four frames while we are not truly ahead. The floor and lead checks are the main rollback lever.
- Horse use can conflict with rush speed or overwrite a better horse. Use buff inspection and rejection backoff.
- Weather-aware pathing changes every strategy's route estimates. Tests need isolated no-weather cases to prove baseline costs stay stable.

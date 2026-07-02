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

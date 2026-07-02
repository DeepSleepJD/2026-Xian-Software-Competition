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

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)

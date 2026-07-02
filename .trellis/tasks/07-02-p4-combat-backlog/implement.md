# P4 Combat Backlog Implementation Plan

## Checklist

1. Combat guard placement
   - [x] Add friendly-guard helpers to `CombatStrategy` or `GameState` as needed: friendly active guard count, current-node guard ownership, terminal path selection for opponent.
   - [x] Implement `_propose_set_guard()` with lead check, choke check, good-fruit floor, guard-count cap, and `SET_GUARD` action.
   - [x] Add `test_combat.py` cases for positive key-pass guard placement and negative cases: S15/terminal, not ahead, too many guards, insufficient good fruit, existing friendly guard.

2. Resource semantic table
   - [x] Replace hard-coded `ICE_BOX` candidate generation in `EconomyStrategy._candidates()` with a table for `ICE_BOX`, horse, document, intel, and low-value passive resources.
   - [x] Use `state.resource_specs` claim rounds when available.
   - [x] Preserve `ICE_BOX_MAX_HOLD` behavior and existing ice tests.
   - [x] Add `test_economy.py` coverage for claiming `SHORT_HORSE`, `FAST_HORSE`, `PASS_TOKEN`, `OFFICIAL_PERMIT`, and `INTEL`.

3. Active resource use
   - [x] Add horse-use proposal and rejection backoff.
   - [x] Keep document resources passive.
   - [x] Decide whether to add active `INTEL` use in this iteration; if yes, target upcoming processing nodes within path distance 15 and add tests. If no, document it as intentionally claim-only for this task.

4. Weather-aware pathing and ice thresholds
   - [x] Add weather helpers in `pathing.py` for active/forecast weather effects without changing `edge_frames()` baseline behavior.
   - [x] Apply HOT freshness multiplier, HEAVY_RAIN water movement/freshness multiplier, and MOUNTAIN_FOG mountain movement multiplier in `_step_cost()`.
   - [x] Make `_propose_ice_use()` use a larger margin during active or imminent HOT.
   - [x] Add `test_pathing.py` weather cases and `test_economy.py` HOT ice-use case.

5. Regression pass
   - [x] Run targeted tests after each layer if needed.
   - [x] Run full unit suite.

## Validation

- `cd client && python -m unittest tests.test_combat tests.test_pathing tests.test_economy`
- `cd client && python -m unittest discover -s tests`

Optional if time remains:

- Run a local match with `tools/run_match.py` and inspect delivery/score regressions.
- Add a simple sparring guard scenario only after the unit-level behavior is stable.

## Risky Files

- `client/lychee/pathing.py`: weather changes are shared by delivery/economy/combat path estimates.
- `client/lychee/strategy/economy.py`: resource candidates and active use share the main action slot with tasks and delivery.
- `client/lychee/strategy/combat.py`: proactive guard priority must not suppress emergency break-guard behavior.

## Start Gate

- Archived `implement.md` Next Session Backlog read.
- `docs/P4-对抗层改动清单.md` read.
- Rule originals read for 2.5, 3.3.3, 3.3.4, 6.2, and resource action formats.
- Planning artifacts created for this complex task.

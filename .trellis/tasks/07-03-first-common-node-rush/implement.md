# Implementation Plan

- [x] Add `first_common_rush_node(state)` in `safety.py` using existing ETA/pathing helpers.
- [x] Rework `first_common_rush_node(state)` to latch the map-theoretical frames-first target instead of rechecking current ETA every frame.
- [x] Add `pathing.min_frame_path()` and use it for first-common rush movement.
- [x] Change delivery so `_should_camp` no longer suppresses movement at the interception node.
- [x] Change delivery so rush movement is not suppressed by `hold_before_choke` before arrival.
- [x] Gate economy proposals while the rush target is ahead and not yet reached.
- [x] Add focused safety/delivery/economy tests and adjust interception integration expectations if needed.
- [x] Run a quick test slice:
  `python -m unittest client.tests.test_safety client.tests.test_delivery client.tests.test_economy client.tests.test_interception_integration`

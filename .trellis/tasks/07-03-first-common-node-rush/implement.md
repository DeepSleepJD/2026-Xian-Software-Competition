# Implementation Plan

- [x] Add `first_common_rush_node(state)` in `safety.py` using existing ETA/pathing helpers.
- [x] Change delivery so `_should_camp` no longer suppresses movement at the interception node.
- [x] Gate economy proposals while the rush target is ahead and not yet reached.
- [x] Add focused safety/delivery/economy tests and adjust interception integration expectations if needed.
- [x] Run a quick test slice:
  `python -m unittest client.tests.test_safety client.tests.test_delivery client.tests.test_economy client.tests.test_interception_integration`

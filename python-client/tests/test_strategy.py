import time
import unittest

from lychee_basic_client.strategy import MovementStrategy


class MovementStrategyTests(unittest.TestCase):
    def test_idle_player_moves_toward_terminal_instead_of_first_neighbor(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"gateNodeId": "S04", "terminalNodeIds": ["S05"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False},
                    {"nodeId": "S03", "hasObstacle": False},
                    {"nodeId": "S04", "hasObstacle": False, "processType": "VERIFY"},
                    {"nodeId": "S05", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02"},
                    {"edgeId": "E02", "fromNodeId": "S01", "toNodeId": "S03"},
                    {"edgeId": "E03", "fromNodeId": "S03", "toNodeId": "S04"},
                    {"edgeId": "E04", "fromNodeId": "S04", "toNodeId": "S05"},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S01", "verified": False}],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], action)

    def test_path_uses_route_cost_not_fewest_edges(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S04"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False},
                    {"nodeId": "S03", "hasObstacle": False},
                    {"nodeId": "S04", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "MOUNTAIN", "distance": 200},
                    {"edgeId": "E02", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "WATER", "distance": 20},
                    {"edgeId": "E03", "fromNodeId": "S03", "toNodeId": "S04", "routeType": "WATER", "distance": 20},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S01", "verified": True}],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], action)

    def test_path_avoids_opponent_guard_when_alternative_exists(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S04"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False, "guard": {"ownerTeamId": "BLUE"}},
                    {"nodeId": "S03", "hasObstacle": False},
                    {"nodeId": "S04", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 10},
                    {"edgeId": "E03", "fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 20},
                    {"edgeId": "E04", "fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "teamId": "RED",
                        "state": "IDLE",
                        "currentNodeId": "S01",
                        "verified": True,
                    }
                ],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], action)

    def test_breaks_adjacent_enemy_guard_when_it_blocks_only_delivery_path(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S03"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False, "guard": {"ownerTeamId": "BLUE", "defense": 5}},
                    {"nodeId": "S03", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 10},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "teamId": "RED",
                        "state": "IDLE",
                        "currentNodeId": "S01",
                        "verified": True,
                        "goodFruit": 20,
                        "badFruit": 2,
                    }
                ],
            }
        )

        self.assertEqual(
            [{"action": "BREAK_GUARD", "targetNodeId": "S02", "goodFruit": 0, "badFruit": 2}],
            action,
        )

    def test_forced_passes_enemy_guard_when_break_resources_are_insufficient(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S03"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False, "guard": {"ownerTeamId": "BLUE", "defense": 6}},
                    {"nodeId": "S03", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 10},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "teamId": "RED",
                        "state": "IDLE",
                        "currentNodeId": "S01",
                        "verified": True,
                        "goodFruit": 1,
                        "badFruit": 0,
                    }
                ],
            }
        )

        self.assertEqual([{"action": "FORCED_PASS", "targetNodeId": "S02"}], action)

    def test_window_card_is_played_for_own_pending_contest(self) -> None:
        strategy = MovementStrategy(player_id=1001)

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "contests": [
                    {
                        "contestId": "C_001",
                        "contestType": "PASS",
                        "redPlayerId": 1001,
                        "bluePlayerId": 2002,
                        "resolved": False,
                        "cards": {},
                    }
                ],
                "players": [
                    {
                        "playerId": 1001,
                        "teamId": "RED",
                        "state": "RESTING",
                        "guardActionPoint": 1,
                        "freshness": 75,
                        "goodFruit": 20,
                        "resources": {},
                    }
                ],
            }
        )

        self.assertEqual([{"action": "WINDOW_CARD", "contestId": "C_001", "card": "BING_ZHENG"}], action)

    def test_task_node_can_become_temporary_goal_when_detour_is_small(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S04"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False},
                    {"nodeId": "S03", "hasObstacle": False},
                    {"nodeId": "S04", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 20},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
                    {"edgeId": "E03", "fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 5},
                    {"edgeId": "E04", "fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD", "distance": 5},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "round": 120,
                "phase": "NORMAL",
                "tasks": [
                    {"taskId": "T_001", "nodeId": "S03", "score": 30, "active": True, "completed": False, "failed": False}
                ],
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S01", "verified": True, "taskScore": 0}
                ],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S02"}], action)

    def test_adjacent_obstacle_on_delivery_path_is_cleared(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"gateNodeId": "S03", "terminalNodeIds": ["S04"]}}},
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": True},
                    {"nodeId": "S03", "hasObstacle": False, "processType": "VERIFY"},
                    {"nodeId": "S04", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02"},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03"},
                    {"edgeId": "E03", "fromNodeId": "S03", "toNodeId": "S04"},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S01", "goodFruit": 100, "verified": False}
                ],
            }
        )

        self.assertEqual([{"action": "CLEAR", "targetNodeId": "S02"}], action)

    def test_gate_waits_until_rush_then_verifies(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
                "nodes": [{"nodeId": "S14", "processType": "VERIFY"}],
            }
        )

        normal_action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S14", "verified": False}],
            }
        )
        rush_action = strategy.choose_action(
            {
                "phase": "RUSH",
                "players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S14", "verified": False}],
            }
        )

        self.assertEqual([], normal_action)
        self.assertEqual([{"action": "VERIFY_GATE", "targetNodeId": "S14"}], rush_action)

    def test_gate_verification_binds_break_order_when_ready(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"gateNodeId": "S14", "terminalNodeIds": ["S15"]}}},
                "nodes": [{"nodeId": "S14", "processType": "VERIFY"}],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "RUSH",
                "players": [
                    {
                        "playerId": 1001,
                        "state": "IDLE",
                        "currentNodeId": "S14",
                        "verified": False,
                        "breakOrderReady": True,
                    }
                ],
            }
        )

        self.assertEqual([{"action": "VERIFY_GATE", "targetNodeId": "S14", "rushTactic": "BREAK_ORDER"}], action)

    def test_verified_player_delivers_at_terminal(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
                "nodes": [{"nodeId": "S15", "terminal": True}],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "RUSH",
                "players": [
                    {
                        "playerId": 1001,
                        "state": "IDLE",
                        "currentNodeId": "S15",
                        "verified": True,
                        "goodFruit": 80,
                        "freshness": 70,
                    }
                ],
            }
        )

        self.assertEqual([{"action": "DELIVER"}], action)

    def test_player_claims_useful_resource_on_current_node_once(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
                "nodes": [
                    {"nodeId": "S08", "resourceStock": {"SHORT_HORSE": 1}, "hasObstacle": False},
                    {"nodeId": "S15", "terminal": True},
                ],
                "edges": [{"edgeId": "E01", "fromNodeId": "S08", "toNodeId": "S15"}],
            }
        )

        first = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "state": "IDLE",
                        "currentNodeId": "S08",
                        "resources": {"SHORT_HORSE": 0},
                    }
                ],
            }
        )
        second = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "state": "IDLE",
                        "currentNodeId": "S08",
                        "resources": {"SHORT_HORSE": 0},
                    }
                ],
            }
        )

        self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "S08", "resourceType": "SHORT_HORSE"}], first)
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S15"}], second)

    def test_player_uses_horse_resource_before_moving(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
                "nodes": [
                    {"nodeId": "S08", "hasObstacle": False},
                    {"nodeId": "S15", "terminal": True},
                ],
                "edges": [{"edgeId": "E01", "fromNodeId": "S08", "toNodeId": "S15"}],
            }
        )

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "state": "IDLE",
                        "currentNodeId": "S08",
                        "resources": {"SHORT_HORSE": 1},
                        "buffs": [],
                    }
                ],
            }
        )

        self.assertEqual([{"action": "USE_RESOURCE", "resourceType": "SHORT_HORSE"}], action)

    def test_player_uses_ice_box_when_freshness_is_low(self) -> None:
        strategy = MovementStrategy(player_id=1001)

        action = strategy.choose_action(
            {
                "phase": "NORMAL",
                "players": [
                    {
                        "playerId": 1001,
                        "state": "IDLE",
                        "currentNodeId": "S08",
                        "freshness": 80,
                        "resources": {"ICE_BOX": 1},
                    }
                ],
            }
        )

        self.assertEqual([{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}], action)

    def test_player_claims_active_task_on_current_node_once_before_resource(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
                "nodes": [
                    {"nodeId": "S08", "resourceStock": {"SHORT_HORSE": 1}, "hasObstacle": False},
                    {"nodeId": "S15", "terminal": True},
                ],
                "edges": [{"edgeId": "E01", "fromNodeId": "S08", "toNodeId": "S15"}],
            }
        )

        first = strategy.choose_action(
            {
                "round": 120,
                "phase": "NORMAL",
                "tasks": [
                    {"taskId": "T_001", "nodeId": "S08", "active": True, "completed": False, "failed": False}
                ],
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S08", "resources": {"SHORT_HORSE": 0}}
                ],
            }
        )
        second = strategy.choose_action(
            {
                "round": 120,
                "phase": "NORMAL",
                "tasks": [
                    {"taskId": "T_001", "nodeId": "S08", "active": True, "completed": False, "failed": False}
                ],
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S08", "resources": {"SHORT_HORSE": 0}}
                ],
            }
        )

        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_001"}], first)
        self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "S08", "resourceType": "SHORT_HORSE"}], second)

    def test_player_skips_new_task_late_to_protect_delivery(self) -> None:
        strategy = MovementStrategy(player_id=1001)

        action = strategy.choose_action(
            {
                "round": 380,
                "phase": "NORMAL",
                "tasks": [
                    {"taskId": "T_001", "nodeId": "S08", "active": True, "completed": False, "failed": False}
                ],
                "players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S08"}],
            }
        )

        self.assertEqual([], action)

    def test_idle_player_moves_to_unblocked_neighbor(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False},
                ],
                "edges": [
                    {
                        "edgeId": "E01",
                        "fromNodeId": "S01",
                        "toNodeId": "S02",
                        "bidirectional": True,
                    }
                ],
            }
        )

        action = strategy.choose_action(
            {
                "round": 1,
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S01"},
                ],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S02"}], action)

    def test_non_idle_player_uses_empty_action_heartbeat(self) -> None:
        strategy = MovementStrategy(player_id=1001)

        action = strategy.choose_action(
            {
                "round": 2,
                "players": [
                    {"playerId": 1001, "state": "PROCESSING", "currentNodeId": "S02"},
                ],
            }
        )

        self.assertEqual([], action)

    def test_waiting_player_resumes_moving_to_current_target(self) -> None:
        strategy = MovementStrategy(player_id=1001)

        action = strategy.choose_action(
            {
                "round": 240,
                "players": [
                    {"playerId": 1001, "state": "WAITING", "currentNodeId": "S09", "nextNodeId": "S10"},
                ],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S10"}], action)

    def test_stationary_waiting_player_plans_from_current_node(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "map": {"gameplay": {"roles": {"terminalNodeIds": ["S10"]}}},
                "nodes": [
                    {"nodeId": "S09", "hasObstacle": False},
                    {"nodeId": "S10", "hasObstacle": False, "terminal": True},
                ],
                "edges": [
                    {"edgeId": "E05", "fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD", "distance": 40},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "round": 240,
                "players": [
                    {
                        "playerId": 1001,
                        "state": "WAITING",
                        "currentNodeId": "S09",
                        "nextNodeId": None,
                        "routeEdgeId": None,
                        "edgeTotalMs": 0,
                        "verified": True,
                    },
                ],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S10"}], action)

    def test_idle_player_processes_current_process_node_before_moving(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "nodes": [
                    {"nodeId": "S02", "processType": "TRANSFER", "hasObstacle": False},
                    {"nodeId": "S03", "hasObstacle": False},
                ],
                "edges": [
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03"},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "round": 5,
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S02"},
                ],
            }
        )

        self.assertEqual([{"action": "PROCESS", "targetNodeId": "S02"}], action)

    def test_revisiting_process_node_requires_processing_again(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "processType": "TRANSFER", "hasObstacle": False},
                    {"nodeId": "S03", "hasObstacle": False},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02"},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03"},
                ],
            }
        )

        strategy.choose_action({"players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S02"}]})
        strategy.choose_action({"players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S03"}]})
        action = strategy.choose_action(
            {"players": [{"playerId": 1001, "state": "IDLE", "currentNodeId": "S02"}]}
        )

        self.assertEqual([{"action": "PROCESS", "targetNodeId": "S02"}], action)

    def test_player_avoids_immediate_reverse_when_another_neighbor_exists(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False},
                    {"nodeId": "S03", "hasObstacle": False},
                ],
                "edges": [
                    {"edgeId": "E01", "fromNodeId": "S01", "toNodeId": "S02"},
                    {"edgeId": "E02", "fromNodeId": "S02", "toNodeId": "S03"},
                ],
            }
        )
        strategy.choose_action(
            {
                "round": 1,
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S01"},
                ],
            }
        )

        action = strategy.choose_action(
            {
                "round": 8,
                "players": [
                    {"playerId": 1001, "state": "IDLE", "currentNodeId": "S02"},
                ],
            }
        )

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], action)

    def test_one_hundred_rounds_stay_fast_and_keep_producing_moves(self) -> None:
        strategy = MovementStrategy(player_id=1001)
        strategy.update_start(
            {
                "nodes": [
                    {"nodeId": "S01", "hasObstacle": False},
                    {"nodeId": "S02", "hasObstacle": False},
                ],
                "edges": [
                    {
                        "edgeId": "E01",
                        "fromNodeId": "S01",
                        "toNodeId": "S02",
                        "bidirectional": True,
                    }
                ],
            }
        )

        started = time.perf_counter()
        actions = [
            strategy.choose_action(
                {
                    "round": round_no,
                    "players": [
                        {"playerId": 1001, "state": "IDLE", "currentNodeId": "S01"},
                    ],
                }
            )
            for round_no in range(1, 101)
        ]
        elapsed = time.perf_counter() - started

        self.assertTrue(all(action[0]["action"] == "MOVE" for action in actions))
        self.assertLess(elapsed, 0.05)


if __name__ == "__main__":
    unittest.main()

import unittest

from lychee_basic_client.messages import action_message, heartbeat_action, move


class MessageTests(unittest.TestCase):
    def test_heartbeat_action_uses_empty_actions(self) -> None:
        self.assertEqual(
            {
                "msg_name": "action",
                "msg_data": {
                    "matchId": "match-1",
                    "round": 7,
                    "playerId": 1006,
                    "actions": [],
                },
            },
            heartbeat_action("match-1", 7, 1006),
        )

    def test_action_message_wraps_move_builder(self) -> None:
        self.assertEqual(
            {
                "msg_name": "action",
                "msg_data": {
                    "matchId": "match-1",
                    "round": 7,
                    "playerId": 1006,
                    "actions": [
                        {
                            "action": "MOVE",
                            "targetNodeId": "S10",
                        }
                    ],
                },
            },
            action_message("match-1", 7, 1006, [move("S10")]),
        )


if __name__ == "__main__":
    unittest.main()

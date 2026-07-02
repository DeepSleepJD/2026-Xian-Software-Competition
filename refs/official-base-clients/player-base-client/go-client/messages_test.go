package main

import "testing"

func TestHeartbeatActionUsesEmptyActions(t *testing.T) {
	msg := heartbeatAction("match-1", 7, 1003)
	data, ok := msg["msg_data"].(map[string]any)
	if !ok {
		t.Fatalf("msg_data has type %T", msg["msg_data"])
	}

	if data["matchId"] != "match-1" {
		t.Fatalf("matchId = %v, want match-1", data["matchId"])
	}
	if data["round"] != 7 {
		t.Fatalf("round = %v, want 7", data["round"])
	}
	if data["playerId"] != 1003 {
		t.Fatalf("playerId = %v, want 1003", data["playerId"])
	}
	if actions, ok := data["actions"].([]any); !ok || len(actions) != 0 {
		t.Fatalf("actions = %#v, want empty slice", data["actions"])
	}
}

func TestMoveActionUsesTargetNodeID(t *testing.T) {
	msg := moveAction("match-1", 7, 1003, "S10")
	data, ok := msg["msg_data"].(map[string]any)
	if !ok {
		t.Fatalf("msg_data has type %T", msg["msg_data"])
	}
	actions, ok := data["actions"].([]any)
	if !ok || len(actions) != 1 {
		t.Fatalf("actions = %#v, want one action", data["actions"])
	}
	action, ok := actions[0].(map[string]any)
	if !ok {
		t.Fatalf("action has type %T", actions[0])
	}
	if action["action"] != "MOVE" {
		t.Fatalf("action = %v, want MOVE", action["action"])
	}
	if action["targetNodeId"] != "S10" {
		t.Fatalf("targetNodeId = %v, want S10", action["targetNodeId"])
	}
	if _, exists := action["target"]; exists {
		t.Fatalf("unexpected target field: %#v", action)
	}
}

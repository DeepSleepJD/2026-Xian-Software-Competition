package main

import "encoding/json"

type envelope struct {
	MsgName string          `json:"msg_name"`
	MsgData json.RawMessage `json:"msg_data"`
}

type startData struct {
	MatchID string `json:"matchId"`
	Round   int    `json:"round"`
}

type inquireData struct {
	Round int `json:"round"`
}

func registrationMessage(cfg config) map[string]any {
	return map[string]any{
		"msg_name": "registration",
		"msg_data": map[string]any{
			"playerId":   cfg.playerID,
			"playerName": cfg.playerName,
			"version":    cfg.version,
		},
	}
}

func readyMessage(matchID string, round int, playerID int) map[string]any {
	return map[string]any{
		"msg_name": "ready",
		"msg_data": map[string]any{
			"matchId":  matchID,
			"round":    round,
			"playerId": playerID,
		},
	}
}

func heartbeatAction(matchID string, round int, playerID int) map[string]any {
	return map[string]any{
		"msg_name": "action",
		"msg_data": map[string]any{
			"matchId":  matchID,
			"round":    round,
			"playerId": playerID,
			"actions":  []any{},
		},
	}
}

func moveAction(matchID string, round int, playerID int, targetNodeID string) map[string]any {
	return map[string]any{
		"msg_name": "action",
		"msg_data": map[string]any{
			"matchId":  matchID,
			"round":    round,
			"playerId": playerID,
			"actions": []any{
				map[string]any{
					"action":       "MOVE",
					"targetNodeId": targetNodeID,
				},
			},
		},
	}
}

from typing import Any, Optional

from .config import Config


def registration_message(config: Config) -> dict[str, Any]:
    return {
        "msg_name": "registration",
        "msg_data": {
            "playerId": config.player_id,
            "playerName": config.player_name,
            "version": config.version,
        },
    }


def ready_message(match_id: str, round_no: int, player_id: int) -> dict[str, Any]:
    return {
        "msg_name": "ready",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
        },
    }


def action_message(
    match_id: str, round_no: int, player_id: int, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "msg_name": "action",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
            "actions": actions,
        },
    }


def heartbeat_action(match_id: str, round_no: int, player_id: int) -> dict[str, Any]:
    """Empty action list: a valid heartbeat / system wait."""
    return action_message(match_id, round_no, player_id, [])


# --- single-action builders (each returns one entry for actions[]) ---

def move(target_node_id: str) -> dict[str, Any]:
    return {"action": "MOVE", "targetNodeId": target_node_id}


def wait() -> dict[str, Any]:
    return {"action": "WAIT"}


def process(target_node_id: Optional[str] = None) -> dict[str, Any]:
    a: dict[str, Any] = {"action": "PROCESS"}
    if target_node_id:
        a["targetNodeId"] = target_node_id
    return a


def verify_gate(rush_tactic: Optional[str] = None) -> dict[str, Any]:
    a: dict[str, Any] = {"action": "VERIFY_GATE"}
    if rush_tactic:
        a["rushTactic"] = rush_tactic
    return a


def deliver() -> dict[str, Any]:
    return {"action": "DELIVER"}


def claim_resource(target_node_id: str, resource_type: str) -> dict[str, Any]:
    return {
        "action": "CLAIM_RESOURCE",
        "targetNodeId": target_node_id,
        "resourceType": resource_type,
    }


def use_resource(resource_type: str, target_node_id: Optional[str] = None) -> dict[str, Any]:
    a: dict[str, Any] = {"action": "USE_RESOURCE", "resourceType": resource_type}
    if target_node_id:
        a["targetNodeId"] = target_node_id
    return a


def claim_task(task_id: str) -> dict[str, Any]:
    return {"action": "CLAIM_TASK", "taskId": task_id}


def clear(target_node_id: str) -> dict[str, Any]:
    return {"action": "CLEAR", "targetNodeId": target_node_id}


def forced_pass(target_node_id: str) -> dict[str, Any]:
    return {"action": "FORCED_PASS", "targetNodeId": target_node_id}


def window_card(contest_id: str, card: str) -> dict[str, Any]:
    return {"action": "WINDOW_CARD", "contestId": contest_id, "card": card}

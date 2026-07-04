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


def rush_protect() -> dict[str, Any]:
    """护果令: 30 frames of x0.2 freshness loss (rush tactic, once per match)."""
    return {"action": "RUSH_PROTECT"}


def rush_speed() -> dict[str, Any]:
    """疾行令: 15 frames of x1.3 movement speed (rush tactic, once per match)."""
    return {"action": "RUSH_SPEED"}


def squad_clear(target_node_id: str) -> dict[str, Any]:
    """小分队清障: delayed remote obstacle clear (2 squad members, no window)."""
    return {"action": "SQUAD_CLEAR", "targetNodeId": target_node_id}


def squad_scout(target_node_id: str) -> dict[str, Any]:
    """小分队探路: delayed scout marker on a target node (1 squad member)."""
    return {"action": "SQUAD_SCOUT", "targetNodeId": target_node_id}


def squad_reinforce(target_node_id: str) -> dict[str, Any]:
    """小分队增援: +2 defense to our own guard, any distance (2 squad members)."""
    return {"action": "SQUAD_REINFORCE", "targetNodeId": target_node_id}


def squad_weaken(target_node_id: str) -> dict[str, Any]:
    """小分队削卡: -2 defense to an enemy guard, any distance (2 squad members)."""
    return {"action": "SQUAD_WEAKEN", "targetNodeId": target_node_id}


def set_guard(target_node_id: str, extra_good_fruit: int = 0) -> dict[str, Any]:
    """设卡: build a guard on the current node (extra fruit 0-2 raises defense)."""
    return {
        "action": "SET_GUARD",
        "targetNodeId": target_node_id,
        "extraGoodFruit": extra_good_fruit,
    }


def break_guard(target_node_id: str, good_fruit: int = 0, bad_fruit: int = 0) -> dict[str, Any]:
    """攻坚破卡: attack an enemy guard on an adjacent node. Always send both fruit
    fields (the server treats a missing field as an invalid action)."""
    return {
        "action": "BREAK_GUARD",
        "targetNodeId": target_node_id,
        "goodFruit": good_fruit,
        "badFruit": bad_fruit,
    }

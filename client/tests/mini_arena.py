"""极简本地竞技场：无 exe 驱动真实策略栈跑完整局，检验换图泛化性。

调试包 exe 无法加载外部/变种地图（外部 JSON 撞 GraalVM native-image 的 fastjson
反射墙 "default constructor not found. class GameStartMap"，classpath 内置图烧死在
二进制里；实测三种加载路径均失败）。而真正需要泛化的是**客户端**——它通过 start
消息收地图。故本模拟器直接用真实策略栈（与 main.py 同装配）逐帧决策，本地建模
移动/固定处理/宫门验核/交付/资源领取，让客户端在任意变体图上真的把荔枝送到终点。

保真锚点：先在真实样例图（identity 变体）上跑，客户端应正常交付；交付成功即证明
模拟器保真度足够，再跑其余变体才有意义（见 test_map_generalization.py）。

刻意简化（并在文档中声明）：对手停在起点不动（只验证我方送达能力，不复现对抗）；
鲜度线性衰减；RUSH 阶段按 rush_start 提前触发（真实约 390 帧，此处提前以缩短模拟）；
非主线动作（SET_GUARD/SQUAD_*/RUSH_*/窗口出牌等）一律受理为无副作用，只为让
客户端不因"动作没被受理"而重试卡死。
"""

from lychee import arbiter, pathing
from lychee.state import GameState
from lychee.strategy.combat import CombatStrategy
from lychee.strategy.delivery import DeliveryStrategy
from lychee.strategy.economy import EconomyStrategy

MY_ID = 1001
OPP_ID = 2002
_CLAIM_ACTIONS = {"CLAIM_RESOURCE", "CLAIM_TASK"}
# 受理为无副作用的动作（对抗/急策/窗口/小分队等，非交付主线）
_NOOP_ACCEPT = {
    "SET_GUARD", "BREAK_GUARD", "SQUAD_SCOUT", "SQUAD_CLEAR", "SQUAD_REINFORCE",
    "SQUAD_WEAKEN", "RUSH_SPEED", "RUSH_PROTECT", "WINDOW_CARD", "USE_RESOURCE",
    "CLEAR_OBSTACLE", "FORCED_PASS", "DOCK", "BOARD", "WATER_TRANSFER", "WAIT",
}


class Me:
    """我方世界模型（模拟器权威状态，每帧投影成 inquire 的 player 字段）。"""

    def __init__(self, start_node: str) -> None:
        self.current_node_id = start_node
        self.next_node_id = ""
        self.state = "IDLE"                 # IDLE / MOVING / PROCESSING
        self.move_remaining = 0             # MOVING 剩余帧
        self.edge_total = 0                 # 当前边总帧
        self.proc_remaining = 0            # PROCESSING 剩余帧
        self.proc_action = ""               # 读条动作名（PROCESS / VERIFY_GATE）
        self.freshness = 100.0
        self.good_fruit = 100
        self.verified = False
        self.delivered = False
        self.resources: dict[str, int] = {}


class LycheeSim:
    def __init__(self, msg_data: dict, *, max_rounds: int = 600, rush_start: int = 40,
                 stuck_limit: int = 90, move_per_frame: int = pathing.BASE_MOVE_PER_FRAME) -> None:
        self.md = msg_data
        self.max_rounds = max_rounds
        self.rush_start = rush_start
        self.stuck_limit = stuck_limit
        self.move_per_frame = move_per_frame

        self.state = GameState(MY_ID)
        self.state.update_start(msg_data)
        self.start_node = self.state.roles.start_node_id or self._first_start()
        self.terminals = self.state.roles.terminal_node_ids or \
            [n.node_id for n in self.state.nodes.values() if n.is_terminal]
        self.gate = self.state.roles.gate_node_id
        self.me = Me(self.start_node)

        # 节点资源库存（供经济层领取；领完置 0）
        self.stock: dict[str, dict[str, int]] = {}
        for r in msg_data["map"]["gameplay"].get("resources") or []:
            self.stock.setdefault(r["nodeId"], {})[r["resourceType"]] = r.get("count", 1)

        self.strategies = [CombatStrategy(economy=(econ := EconomyStrategy())),
                           DeliveryStrategy(), econ]
        self._last_results: list[dict] = []
        self.illegal: list[str] = []        # 引用不存在节点 / MOVE 非相邻 = 泛化 bug
        self.trace: list[str] = []

    def _first_start(self) -> str:
        for n in self.state.nodes.values():
            if n.is_start:
                return n.node_id
        return next(iter(self.state.nodes))

    # ----- 主循环 -----

    def run(self) -> dict:
        last_progress_round = 0
        progress_key = self._progress_key()
        for rnd in range(1, self.max_rounds + 1):
            inq = self._build_inquire(rnd)
            actions = self._decide(inq)
            self._apply(actions, rnd)
            self._advance()

            key = self._progress_key()
            if key != progress_key:
                progress_key, last_progress_round = key, rnd
            if self.me.delivered:
                return self._result(True, rnd, "delivered")
            if rnd - last_progress_round > self.stuck_limit:
                return self._result(False, rnd,
                                    f"stuck {self.stuck_limit}帧无进展 @ {self.me.current_node_id}"
                                    f"/{self.me.state}")
        return self._result(False, self.max_rounds, "未在时限内交付")

    def _progress_key(self):
        # 含 move_remaining/proc_remaining：正常走长边/长读条每帧都算进展，
        # 只有真正原地空转（状态与倒计时都不动）才触发卡死判定
        return (self.me.current_node_id, self.me.next_node_id, self.me.state,
                self.me.verified, self.me.move_remaining, self.me.proc_remaining,
                self.me.delivered)

    def _decide(self, inq: dict) -> list[dict]:
        self.state.update_inquire(inq)
        intents: list = []
        for strat in self.strategies:
            intents.extend(strat.propose(self.state) or [])
        return arbiter.merge_intents(intents, self.state.me)

    # ----- 动作应用 -----

    def _apply(self, actions: list[dict], rnd: int) -> None:
        results = []
        main_done = False
        node_ids = set(self.state.nodes)
        for act in actions:
            name = act.get("action", "")
            target = act.get("targetNodeId") or ""
            # 泛化红旗：动作引用了不存在的节点
            if target and target not in node_ids:
                self.illegal.append(f"r{rnd} {name} 目标 {target} 不在地图节点中")
            if name in arbiter._SQUAD_ACTIONS or name in arbiter._RUSH_ACTIONS \
                    or name == "WINDOW_CARD":
                results.append(self._ok(rnd, name))   # 非主车队类别：受理无副作用
                continue
            if main_done:
                continue                               # 每帧仅应用一个主车队动作
            main_done = True
            results.append(self._apply_main(name, act, target, rnd))
        self._last_results = results

    def _apply_main(self, name: str, act: dict, target: str, rnd: int) -> dict:
        me = self.me
        if name == "MOVE":
            return self._do_move(me, target, rnd)
        if name == "PROCESS":
            return self._do_process(me, target or me.current_node_id, rnd)
        if name == "VERIFY_GATE":
            if me.current_node_id == self.gate and self.state.phase == "RUSH":
                me.proc_remaining = max(1, self._proc_round(me.current_node_id))
                me.proc_action = "VERIFY_GATE"
                me.state = "PROCESSING"
                me._verify_on_done = True   # 读条完成时置 verified
                return self._ok(rnd, name)
            return self._fail(rnd, name, "GATE_NOT_OPEN")
        if name == "DELIVER":
            if (me.current_node_id in self.terminals and me.verified
                    and me.good_fruit > 0 and me.freshness > 0):
                me.delivered = True
                return self._ok(rnd, name)
            return self._fail(rnd, name, "DELIVER_NOT_READY")
        if name in _CLAIM_ACTIONS:
            self._grant_resource(me, target or me.current_node_id, act)
            return self._ok(rnd, name)
        if name in _NOOP_ACCEPT:
            return self._ok(rnd, name)
        return self._ok(rnd, name)   # 未知主动作：受理，避免客户端重试卡死

    def _do_move(self, me, target: str, rnd: int) -> dict:
        if me.state != "IDLE":
            return self._fail(rnd, "MOVE", "BUSY")
        neighbors = {nid for nid, _ in self.state.neighbors(me.current_node_id)}
        if target not in neighbors:
            self.illegal.append(f"r{rnd} MOVE 目标 {target} 非 {me.current_node_id} 的相邻节点")
            return self._fail(rnd, "MOVE", "MOVE_EDGE_NOT_FOUND")
        edge = self._edge_between(me.current_node_id, target)
        frames = pathing.edge_frames_for_state(self.state, edge, self.move_per_frame) if edge else 1
        me.next_node_id = target
        me.state = "MOVING"
        me.move_remaining = max(1, frames)
        me.edge_total = me.move_remaining
        return self._ok(rnd, "MOVE")

    def _do_process(self, me, node: str, rnd: int) -> dict:
        if node != me.current_node_id or me.state != "IDLE":
            return self._fail(rnd, "PROCESS", "PROCESS_NOT_AVAILABLE")
        if node not in self.state.process_nodes:
            return self._fail(rnd, "PROCESS", "PROCESS_NOT_AVAILABLE")
        me.proc_remaining = max(1, self._proc_round(node))
        me.proc_action = "PROCESS"
        me.state = "PROCESSING"
        return self._ok(rnd, "PROCESS")

    def _grant_resource(self, me, node: str, act: dict) -> None:
        rtype = act.get("resourceType") or ""
        avail = self.stock.get(node, {})
        if not rtype:
            rtype = next((k for k, v in avail.items() if v > 0), "")
        if rtype:
            me.resources[rtype] = me.resources.get(rtype, 0) + 1
            if avail.get(rtype, 0) > 0:
                avail[rtype] -= 1

    def _proc_round(self, node: str) -> int:
        proc = self.state.process_nodes.get(node)
        return proc.process_round if proc else 4

    def _edge_between(self, a: str, b: str):
        for nid, edge in self.state.neighbors(a):
            if nid == b:
                return edge
        return None

    # ----- 时间推进 -----

    def _advance(self) -> None:
        me = self.me
        me.freshness = max(0.0, me.freshness - 0.06)
        if me.state == "MOVING":
            me.move_remaining -= 1
            if me.move_remaining <= 0:
                me.current_node_id, me.next_node_id = me.next_node_id, ""
                me.state = "IDLE"
                me.edge_total = 0
        elif me.state == "PROCESSING":
            me.proc_remaining -= 1
            if me.proc_remaining <= 0:
                if getattr(me, "_verify_on_done", False):
                    me.verified = True
                    me._verify_on_done = False
                me.state = "IDLE"
                me.proc_action = ""

    # ----- inquire 投影 -----

    def _build_inquire(self, rnd: int) -> dict:
        me = self.me
        phase = "RUSH" if rnd >= self.rush_start else "NORMAL"
        my_player = {
            "playerId": MY_ID, "teamId": "RED", "online": True, "state": me.state,
            "currentNodeId": me.current_node_id, "nextNodeId": me.next_node_id,
            "moveDirection": "FORWARD" if me.state == "MOVING" else "NONE",
            "edgeProgressMs": (me.edge_total - me.move_remaining) * 1000 if me.edge_total else 0,
            "edgeTotalMs": me.edge_total * 1000,
            "freshness": round(me.freshness, 2), "goodFruit": me.good_fruit, "badFruit": 0,
            "verified": me.verified, "delivered": me.delivered,
            "squadAvailable": 8, "guardActionPoint": 4, "resources": dict(me.resources),
            "totalScore": 0, "taskScore": 0,
        }
        if me.state == "PROCESSING":
            my_player["currentProcess"] = {
                "action": me.proc_action, "targetNodeId": me.current_node_id,
                "totalRound": 1, "remainRound": me.proc_remaining}
        # 对手：停在起点不动（只验证送达能力，不复现对抗）
        opp = {"playerId": OPP_ID, "teamId": "BLUE", "online": True, "state": "IDLE",
               "currentNodeId": self.start_node, "nextNodeId": "", "freshness": 100.0,
               "goodFruit": 100, "verified": False, "delivered": False,
               "squadAvailable": 8, "guardActionPoint": 4, "totalScore": 0}
        node_states = []
        for nid in self.state.nodes:
            ns = {"nodeId": nid, "hasObstacle": False}
            stock = {k: v for k, v in self.stock.get(nid, {}).items() if v > 0}
            if stock:
                ns["resourceStock"] = stock
            node_states.append(ns)
        return {
            "round": rnd, "phase": phase, "players": [my_player, opp],
            "nodes": node_states, "edges": self.md.get("edges"),
            "weather": {"active": [], "forecast": []},
            "tasks": [], "bounties": [], "contests": [], "events": [],
            "actionResults": self._last_results, "scorePreview": {},
        }

    # ----- 结果构造 -----

    def _ok(self, rnd: int, action: str) -> dict:
        return {"round": rnd, "playerId": MY_ID, "action": action, "accepted": True,
                "result": "OK"}

    def _fail(self, rnd: int, action: str, code: str) -> dict:
        return {"round": rnd, "playerId": MY_ID, "action": action, "accepted": False,
                "result": "REJECTED", "errorCode": code}

    def _result(self, delivered: bool, rnd: int, reason: str) -> dict:
        return {
            "delivered": delivered, "round": rnd, "reason": reason,
            "at": self.me.current_node_id, "verified": self.me.verified,
            "freshness": round(self.me.freshness, 1), "illegal": list(self.illegal),
        }

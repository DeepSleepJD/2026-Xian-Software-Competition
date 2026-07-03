"""P4m-M2 一次性实验探针（LYCHEE_FROZEN_PROBE=1 时由 main.py 注册，平时不激活）。

目的：实测"半路被敌卡冻结"（13:22 现网局形态：state=WAITING + nextNodeId 保留 +
每帧 WAIT 被拒 MOVE_BLOCKED_BY_GUARD，被钉 193 帧）状态下，服务器对三种候选
逃生动作的真实裁决：

  ① BREAK_GUARD    —— P4d 结论是半路视同 MOVING 会拒（MOVING_ACTION_FORBIDDEN），复核
  ② FORCED_PASS    —— 任务书 6.3.2"从当前节点强行进入相邻阻挡节点"；冻结时协议字段
                       currentNodeId 仍是本段起点，形式上满足
  ③ 改道 MOVE      —— 任务书 4.2：边上 MOVE 可提交"本段路线起点的其他合法相邻节点"，
                       只禁原路回起点本身；被冻状态下是否仍受理未知

发包顺序 ①→②→③ 循环：先测大概率被拒项——③一旦被受理会离开冻结态，放最后。
探针模式下 main.py 不注册 CombatStrategy（防小分队削卡拆掉陪练的卡、冻结窗口关闭；
也无窗口出牌层，FORCED_PASS 若开通行窗口会自动弃权，只看受理裁决）。
结果人工读 tools/logs 控制台日志（[PROBE] 行）。
"""

from ..state import GameState
from . import Intent, Strategy

PROBE_PRIORITY = 999


class FrozenProbeStrategy(Strategy):
    def __init__(self) -> None:
        self._probe_step = 0
        self._was_frozen = False

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        for r in state.my_action_results():
            print(f"[PROBE] r{state.round} 上帧裁决: action={r.action} "
                  f"accepted={r.accepted} code={r.error_code}", flush=True)

        # 冻结形态三变体：WAITING+next 保留（现网 13:22）、WAITING+PAUSED（P4d）、
        # MOVING+进度冻死（P4e/本地陪练实测 r273 起 449‰ 不再推进）。对探针而言
        # "下一跳有敌卡"时 MOVE 必被拒，直接视为冻结开测即可。
        frozen = (bool(me.next_node_id)
                  and state.enemy_guard_at(me.next_node_id) is not None
                  and (me.state in ("WAITING", "MOVING")
                       or me.move_direction == "PAUSED"))
        if not frozen:
            if self._was_frozen:
                print(f"[PROBE] r{state.round} 离开冻结态: state={me.state} "
                      f"cur={me.current_node_id} next={me.next_node_id} "
                      f"dir={me.move_direction}", flush=True)
            self._was_frozen = False
            return []

        self._was_frozen = True
        target = me.next_node_id
        guard = state.enemy_guard_at(target)
        step = self._probe_step % 3
        self._probe_step += 1

        if step == 0:
            bad = min(2, state.my_bad)
            good = min(2, state.my_good)
            action = {"action": "BREAK_GUARD", "targetNodeId": target,
                      "goodFruit": good, "badFruit": bad}
            note = f"①BREAK_GUARD→{target}(good={good},bad={bad})"
        elif step == 1:
            action = {"action": "FORCED_PASS", "targetNodeId": target}
            note = f"②FORCED_PASS→{target}"
        else:
            alts = [n for n, _ in state.neighbors(me.current_node_id) if n != target]
            if not alts:
                print(f"[PROBE] r{state.round} 无改道邻居可测(割点尽头)", flush=True)
                return []
            action = {"action": "MOVE", "targetNodeId": alts[0]}
            note = f"③改道MOVE→{alts[0]}"

        print(f"[PROBE] r{state.round} 冻结中(cur={me.current_node_id} next={target} "
              f"state={me.state} dir={me.move_direction} def={guard.defense}) 发: {note}",
              flush=True)
        return [Intent(kind="probe", priority=PROBE_PRIORITY, actions=[action], note=note)]

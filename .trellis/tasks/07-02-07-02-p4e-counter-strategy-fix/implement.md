# P4e 执行清单

- [x] 1. `pathing.py`：新增 `guard_max_defense(state, node_id)`（combat 静态方法迁入）
- [x] 2. `safety.py`：新增 `ahead_of_opponent(state, margin=0)` 与 `hold_before_choke(state, next_node)`
- [x] 3. `delivery.py`：`_pick_move_target` 出口过闸门
- [x] 4. `economy.py`：赶路 MOVE 过闸门；慢边禁令（初版帧数上限实测否决，见 design.md R2）；蹲守加领先条件
- [x] 5. `combat.py`：`_guard_max_defense` 改引 pathing；`SQUAD_RESERVE_FOR_WEAKEN=6`；`_ahead_of_opponent` 改包装 safety（`_best_path_frames` 随之移除）
- [x] 6. 单测：166 例全绿（新增 18：R1 防陷阱 8 + ahead 3 + delivery 集成 1 + R2 慢边 3 + R3 蹲守 2 + R4 保留量 1）
- [x] 7. 对局验证：
  - seed 20260618 vs demo：**773**（demo 458），ROAD 主线，鲜度 90.49，mountain_rounds=0，100% 交付
  - seed 12345 vs demo：**773**（demo 458），同上
  - vs adversary_guard 陪练：**766**，100% 交付（=P4d 基线）
  - 归因实验记录：初版帧数上限 740（路线翻转水路）→ 禁用复跑 773 → 定案慢边禁令 773
- [ ] 8. 更新 CLAUDE.md 进度 + journal + commit

验证命令：
```bash
cd client && python -m unittest discover -s tests
python tools/run_match.py --no-ui --seed 20260618 --client-cmd "python client/main.py {player_id} {host} {port}"
python tools/run_match.py --no-ui --seed 12345 --client-cmd "python client/main.py {player_id} {host} {port}"
python tools/run_match.py --no-ui --seed 20260618 --client-cmd "python client/main.py {player_id} {host} {port}" --demo-cmd "python tools/adversary_guard.py {player_id} {host} {port}"
```

回滚点：单一 commit，revert 即回 P4d 基线。

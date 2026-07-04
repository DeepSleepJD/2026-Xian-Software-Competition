"""换图泛化测试：在 8 张结构迥异的地图变体上驱动真实策略栈跑完整局。

背景：赛方明确会换地图变体（CLAUDE.md 硬约束"不得写死地图，一切以 start/inquire
下发为准"）。调试包 exe 无法加载外部/变种图（外部 JSON 撞 GraalVM native-image
fastjson 反射墙，实测三路径全失败），故用 mini_arena 无 exe 驱动真实策略栈，在
variant_maps 生成的变体上端到端验证客户端仍能合法决策并送达。

变体覆盖的泛化风险（见 variant_maps 各变换 docstring）：
  identity  基线（保真锚点）      coords   坐标全重排（证伪几何依赖）
  reweight  边权翻转（路线换线）  resources 资源/任务改点
  topology  增节点+新捷径         roles    宫门·终点换位
  minimal   8节点极简特征缺失     stress   全维叠加

判据：①保真锚点 identity 必须交付；②每个变体都交付、零非法动作（不引用不存在的
节点、不 MOVE 到非相邻节点）；③解析/寻路/角色派生对所有变体成立。
"""

import unittest

try:                                    # 兼容 discover（tests 为包）与直接运行
    from tests import variant_maps as V
    from tests.mini_arena import LycheeSim
except ImportError:                     # pragma: no cover
    import variant_maps as V
    from mini_arena import LycheeSim

from lychee import pathing
from lychee.state import GameState


class VariantGenerationTests(unittest.TestCase):
    """变体本身合法性：解析、角色派生、起点→终点可达。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.variants = V.build_all()

    def test_all_variants_build_and_validate(self) -> None:
        # build_all 内已逐个 validate()；此处断言集合非空且含关键变体
        self.assertEqual(set(self.variants), set(V.VARIANTS))
        self.assertGreaterEqual(len(self.variants), 8)

    def test_parse_roles_and_pathfind(self) -> None:
        for name, md in self.variants.items():
            with self.subTest(variant=name):
                st = GameState(1001)
                st.update_start(md)
                self.assertTrue(st.nodes, "节点解析为空")
                self.assertTrue(st.edges, "边解析为空")
                start = st.roles.start_node_id or next(
                    (n.node_id for n in st.nodes.values() if n.is_start), "")
                terminals = st.roles.terminal_node_ids or \
                    [n.node_id for n in st.nodes.values() if n.is_terminal]
                self.assertTrue(start, "无法派生起点")
                self.assertTrue(terminals, "无法派生终点")
                for term in terminals:
                    path = pathing.shortest_path(st, start, term)
                    self.assertIsNotNone(path, f"起点 {start} 不可达终点 {term}")
                    self.assertEqual(path[0], start)
                    self.assertEqual(path[-1], term)
                # 割点计算不得抛异常（拓扑/角色变体重点考验）
                pathing.choke_nodes(st, start, terminals[0])

    def test_topology_variant_changes_node_count(self) -> None:
        st = GameState(1001)
        st.update_start(self.variants["topology"])
        self.assertIn("S16", st.nodes, "拓扑变体应插入新节点 S16")
        self.assertEqual(len(st.nodes), 16)

    def test_roles_variant_reassigns_gate_and_finish(self) -> None:
        st = GameState(1001)
        st.update_start(self.variants["roles"])
        self.assertEqual(st.roles.gate_node_id, "S15", "宫门应改派到 S15")
        self.assertEqual(st.roles.terminal_node_ids, ["S16"], "终点应改派到 S16")

    def test_reweight_variant_flips_optimal_route(self) -> None:
        base = GameState(1001); base.update_start(self.variants["identity"])
        rew = GameState(1001); rew.update_start(self.variants["reweight"])
        p_base = pathing.shortest_path(base, "S01", "S15")
        p_rew = pathing.shortest_path(rew, "S01", "S15")
        self.assertNotEqual(p_base, p_rew, "边权翻转后鲜度最优路线应改变")


class VariantDeliveryTests(unittest.TestCase):
    """端到端：真实策略栈在每个变体上合法决策并送达终点。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.variants = V.build_all()

    def test_fidelity_anchor_baseline_delivers(self) -> None:
        # 保真锚点：客户端在真实样例图（identity）上必须正常交付，
        # 否则模拟器保真度不足，变体结果不可信
        r = LycheeSim(self.variants["identity"]).run()
        self.assertTrue(r["delivered"], f"保真锚点未交付: {r}")
        self.assertTrue(r["verified"])
        self.assertEqual(r["illegal"], [])

    def test_every_variant_delivers_without_illegal_actions(self) -> None:
        failures = []
        for name, md in self.variants.items():
            with self.subTest(variant=name):
                r = LycheeSim(md).run()
                self.assertEqual(r["illegal"], [],
                                 f"[{name}] 出现非法动作（泛化 bug）: {r['illegal'][:5]}")
                self.assertTrue(r["delivered"],
                                f"[{name}] 未交付: reason={r['reason']} at={r['at']} "
                                f"verified={r['verified']}")
                if not r["delivered"] or r["illegal"]:
                    failures.append(name)
        self.assertFalse(failures, f"以下变体泛化失败: {failures}")

    def test_delivery_reaches_declared_terminal(self) -> None:
        # roles 变体的终点是 S16：交付点必须是该图声明的终点，而非写死 S15
        r = LycheeSim(self.variants["roles"]).run()
        self.assertTrue(r["delivered"])
        self.assertEqual(r["at"], "S16", "roles 变体应交付到改派后的终点 S16")


if __name__ == "__main__":
    unittest.main()

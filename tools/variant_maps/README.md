# tools/variant_maps/ — 换图变体图

换图泛化测试用的地图文件。完整说明见 `docs/地图泛化测试.md`。

## 文件

- `server_embedded_variant_1.json` — **Unity 变体生成模板**：从裁判 exe 内置图抠出的 Unity
  格式地图（15 节点 / 21 边）。`gen_variant_maps.py` 以它为模板。**入库保留**（无 exe 无法重建）。
- `server_embedded_variant_2.json` / `_3.json` — 同一张内置图的近乎相同快照（仅个别 distance
  序列化舍入差异），**冗余，可删**。留作交叉核对。
- `unity_*.json` — `python tools/gen_variant_maps.py` 生成的可加载 Unity 变体图（reweight /
  resources / coords / combo）。**已 .gitignore**（随时可重建，不入库）。

## 用法

```bash
python tools/gen_variant_maps.py                                   # 重建 unity_*.json
python tools/run_match.py --map tools/variant_maps/unity_reweight.json --no-ui   # 真实裁判跑变体图
```

> 手段 A（无 exe，覆盖最全）：`cd client && python -m unittest tests.test_map_generalization`

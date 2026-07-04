#!/usr/bin/env python3
"""Build a standalone HTML viewer for embedded map variants."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAP_DIR = ROOT / "tools" / "variant_maps"
SERVER_EXE = ROOT / "refs" / "debug-kit-v1" / "arena" / "server" / "lychee-arena-server.exe"
OUTPUT = MAP_DIR / "variant_map_viewer.html"


def _extract_json_objects_from_exe(path: Path) -> list[dict]:
    data = path.read_bytes()
    markers: list[int] = []
    start = 0
    while True:
        pos = data.find(b'"schemaVersion"', start)
        if pos < 0:
            break
        markers.append(pos)
        start = pos + 1

    def extract(pos: int) -> dict:
        candidates: list[int] = []
        scan = max(0, pos - 4096)
        brace = data.find(b"{", scan)
        while 0 <= brace < pos:
            candidates.append(brace)
            brace = data.find(b"{", brace + 1)

        for obj_start in reversed(candidates):
            depth = 0
            in_string = False
            escaped = False
            for index in range(obj_start, len(data)):
                byte = data[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif byte == 92:
                        escaped = True
                    elif byte == 34:
                        in_string = False
                else:
                    if byte == 34:
                        in_string = True
                    elif byte == 123:
                        depth += 1
                    elif byte == 125:
                        depth -= 1
                        if depth == 0:
                            raw = data[obj_start : index + 1]
                            return json.loads(raw.decode("utf-8"))
        raise RuntimeError(f"Could not extract JSON object around offset {pos}")

    return [extract(marker) for marker in markers]


def _load_maps() -> list[dict]:
    embedded = _extract_json_objects_from_exe(SERVER_EXE)
    if len(embedded) < 4:
        raise RuntimeError(f"Expected at least 4 embedded maps, got {len(embedded)}")

    maps = [{"label": "Base", "source": "server embedded base", "map": embedded[3]}]
    for index in range(1, 4):
        path = MAP_DIR / f"server_embedded_variant_{index}.json"
        maps.append(
            {
                "label": f"Variant {index}",
                "source": path.name,
                "map": json.loads(path.read_text(encoding="utf-8")),
            }
        )
    return maps


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lychee Variant Map Viewer</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --ink: #172126;
      --muted: #5b6970;
      --line: #cfd8dc;
      --panel: #ffffff;
      --accent: #d83b35;
      --road: #c9822b;
      --water: #2477b3;
      --mountain: #40845a;
      --branch: #6f7782;
      --safe: #1f9d6a;
      --warn: #d34d37;
      --gold: #c99a1f;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      line-height: 1.45;
    }

    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 20px 12px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }

    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 720;
      letter-spacing: 0;
    }

    .tabs {
      display: inline-grid;
      grid-template-columns: repeat(4, minmax(88px, 1fr));
      gap: 4px;
      padding: 4px;
      border: 1px solid var(--line);
      background: #eef3f5;
      border-radius: 8px;
    }

    .tabs button {
      height: 36px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-size: 14px;
      cursor: pointer;
    }

    .tabs button[aria-pressed="true"] {
      background: #ffffff;
      color: var(--ink);
      box-shadow: 0 1px 2px rgba(15, 25, 35, 0.12);
    }

    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 0;
      min-height: 0;
    }

    .map-wrap {
      padding: 18px;
      min-width: 0;
    }

    .map-frame {
      height: calc(100vh - 96px);
      min-height: 560px;
      border: 1px solid var(--line);
      background: #fbfcfc;
      overflow: hidden;
      position: relative;
    }

    svg {
      width: 100%;
      height: 100%;
      display: block;
      background-image:
        linear-gradient(to right, rgba(107, 122, 132, 0.12) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(107, 122, 132, 0.12) 1px, transparent 1px);
      background-size: 5% 8.333%;
    }

    .edge {
      fill: none;
      stroke-width: 0.62;
      stroke-linecap: round;
      stroke-linejoin: round;
      opacity: 0.72;
      vector-effect: non-scaling-stroke;
    }

    .edge.route {
      stroke: var(--accent);
      stroke-width: 1.35;
      opacity: 0.95;
    }

    .node-ring {
      fill: #ffffff;
      stroke: #2f3b42;
      stroke-width: 0.45;
      vector-effect: non-scaling-stroke;
    }

    .node.is-process .node-ring { stroke: var(--gold); stroke-width: 0.85; }
    .node.is-obstacle .node-ring { stroke: var(--warn); stroke-dasharray: 1.1 0.7; stroke-width: 0.8; }
    .node.is-target .node-ring { stroke: #111820; stroke-width: 1.1; }

    .node-dot { stroke: #ffffff; stroke-width: 0.3; vector-effect: non-scaling-stroke; }
    .node text {
      font-size: 1.55px;
      font-weight: 780;
      text-anchor: middle;
      dominant-baseline: central;
      fill: #ffffff;
      pointer-events: none;
      letter-spacing: 0;
    }

    .node:hover .node-ring,
    .node.is-selected .node-ring {
      stroke: #111820;
      stroke-width: 1.35;
    }

    aside {
      min-width: 0;
      padding: 18px 18px 18px 0;
    }

    .panel {
      height: calc(100vh - 96px);
      min-height: 560px;
      border: 1px solid var(--line);
      background: var(--panel);
      overflow: auto;
    }

    .section {
      padding: 15px 16px;
      border-bottom: 1px solid var(--line);
    }

    .section:last-child { border-bottom: 0; }

    .eyebrow {
      margin: 0 0 4px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    h2 {
      margin: 0;
      font-size: 18px;
      line-height: 1.25;
      letter-spacing: 0;
    }

    .meta {
      margin-top: 8px;
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 13px;
    }

    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .stat {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 10px;
      background: #f9fbfb;
    }

    .stat b {
      display: block;
      font-size: 18px;
      line-height: 1.1;
    }

    .stat span {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }

    .path {
      margin: 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f9fbfb;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 12px;
      white-space: normal;
      overflow-wrap: anywhere;
    }

    .legend {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 10px;
      font-size: 13px;
    }

    .legend-item {
      display: flex;
      align-items: center;
      min-width: 0;
      gap: 8px;
      color: var(--muted);
    }

    .swatch {
      width: 22px;
      height: 4px;
      border-radius: 2px;
      flex: 0 0 auto;
    }

    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 7px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #f9fbfb;
      font-size: 12px;
      color: #27343a;
    }

    .list {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 7px;
      font-size: 13px;
    }

    .list li {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px dashed #dde4e7;
      padding-bottom: 6px;
    }

    .list li:last-child { border-bottom: 0; padding-bottom: 0; }
    .list code { color: #263238; font-family: "Cascadia Mono", Consolas, monospace; }
    .muted { color: var(--muted); }

    @media (max-width: 980px) {
      header {
        align-items: stretch;
        flex-direction: column;
      }

      .tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main { grid-template-columns: 1fr; }
      aside { padding: 0 18px 18px; }
      .map-frame, .panel { height: auto; min-height: 520px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <h1>Lychee Variant Map Viewer</h1>
      <nav class="tabs" id="tabs" aria-label="Map variants"></nav>
    </header>

    <main>
      <section class="map-wrap">
        <div class="map-frame">
          <svg id="map" viewBox="-3 -3 86 66" role="img" aria-label="variant map"></svg>
        </div>
      </section>
      <aside>
        <div class="panel" id="details"></div>
      </aside>
    </main>
  </div>

  <script id="maps-data" type="application/json">__MAPS_JSON__</script>
  <script>
    const maps = JSON.parse(document.getElementById("maps-data").textContent);
    const svg = document.getElementById("map");
    const tabs = document.getElementById("tabs");
    const details = document.getElementById("details");
    const NS = "http://www.w3.org/2000/svg";

    const routeColors = {
      ROAD: "var(--road)",
      WATER: "var(--water)",
      MOUNTAIN: "var(--mountain)",
      BRANCH: "var(--branch)"
    };

    const nodeColors = {
      START: "#1f9d6a",
      FINISH: "#7a4fb3",
      GATE: "#2d5d99",
      KEY_PASS: "#d34d37",
      PASS: "#b56826",
      DOCK: "#2477b3",
      WATER_STATION: "#2587aa",
      MOUNTAIN_NODE: "#40845a",
      MOUNTAIN_PASS: "#3f7350",
      PALACE_STATION: "#8b5f1c",
      JUNCTION: "#697780",
      STATION: "#53626b",
      CHECKPOINT: "#53626b"
    };

    let selectedMapIndex = 0;
    let selectedNodeId = null;

    function byId(map) {
      return Object.fromEntries(map.nodes.map(node => [node.nodeId, node]));
    }

    function edgeEndpoints(edge) {
      return [edge.fromNodeId || edge.fromNode, edge.toNodeId || edge.toNode];
    }

    function buildGraph(map) {
      const graph = new Map();
      for (const edge of map.edges) {
        const [from, to] = edgeEndpoints(edge);
        if (!graph.has(from)) graph.set(from, []);
        if (!graph.has(to)) graph.set(to, []);
        graph.get(from).push({ to, distance: edge.distance, edge });
        if (edge.bidirectional !== false) {
          graph.get(to).push({ to: from, distance: edge.distance, edge });
        }
      }
      return graph;
    }

    function shortestPath(map) {
      const roles = map.gameplay?.roles || {};
      const start = roles.startNodeId || "S01";
      const terminal = (roles.terminalNodeIds || ["S15"])[0];
      const graph = buildGraph(map);
      const queue = [{ node: start, distance: 0, path: [start], edges: [] }];
      const seen = new Set();

      while (queue.length) {
        queue.sort((a, b) => a.distance - b.distance || a.path.length - b.path.length);
        const current = queue.shift();
        if (seen.has(current.node)) continue;
        seen.add(current.node);
        if (current.node === terminal) return current;
        for (const next of graph.get(current.node) || []) {
          if (seen.has(next.to)) continue;
          queue.push({
            node: next.to,
            distance: current.distance + next.distance,
            path: current.path.concat(next.to),
            edges: current.edges.concat(next.edge.edgeId)
          });
        }
      }

      return { node: terminal, distance: 0, path: [], edges: [] };
    }

    function firstGuardTarget(map, path) {
      const excluded = new Set(map.gameplay?.roles?.rushExcludedNodeIds || []);
      const types = Object.fromEntries(map.nodes.map(node => [node.nodeId, node.type || node.nodeType]));
      for (const nodeId of path.slice(1)) {
        if ((types[nodeId] === "KEY_PASS" || types[nodeId] === "PASS") && !excluded.has(nodeId)) {
          return nodeId;
        }
      }
      return null;
    }

    function resourceGroups(map) {
      const rows = map.gameplay?.resources || [];
      const groups = new Map();
      for (const row of rows) {
        if (!groups.has(row.nodeId)) groups.set(row.nodeId, []);
        groups.get(row.nodeId).push(row.resourceType);
      }
      return groups;
    }

    function processGroups(map) {
      const groups = new Map();
      for (const row of map.gameplay?.processNodes || []) {
        groups.set(row.nodeId, row);
      }
      return groups;
    }

    function pathPoints(map, edge, nodes) {
      const path = (map.routePaths || []).find(item => item.edgeId === edge.edgeId);
      if (path?.points?.length) {
        return path.points.map(point => `${point.x},${point.y}`).join(" ");
      }
      const [from, to] = edgeEndpoints(edge);
      return `${nodes[from].x},${nodes[from].y} ${nodes[to].x},${nodes[to].y}`;
    }

    function changedEdges(map) {
      const base = maps[0].map;
      const baseEdges = new Map(base.edges.map(edge => [edge.edgeId, edge]));
      const changed = [];
      for (const edge of map.edges) {
        const baseEdge = baseEdges.get(edge.edgeId);
        if (!baseEdge) {
          changed.push(`${edge.edgeId}: new`);
          continue;
        }
        const [from, to] = edgeEndpoints(edge);
        const [baseFrom, baseTo] = edgeEndpoints(baseEdge);
        if (from !== baseFrom || to !== baseTo || edge.routeType !== baseEdge.routeType || edge.distance !== baseEdge.distance) {
          changed.push(`${edge.edgeId}: ${from}-${to} ${edge.routeType} ${edge.distance}`);
        }
      }
      return changed;
    }

    function pill(text) {
      return `<span class="pill">${escapeHtml(text)}</span>`;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function renderTabs() {
      tabs.innerHTML = "";
      maps.forEach((entry, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = entry.label;
        button.setAttribute("aria-pressed", String(index === selectedMapIndex));
        button.addEventListener("click", () => {
          selectedMapIndex = index;
          selectedNodeId = null;
          render();
        });
        tabs.appendChild(button);
      });
    }

    function renderMap(entry) {
      const map = entry.map;
      const nodes = byId(map);
      const route = shortestPath(map);
      const routeEdges = new Set(route.edges);
      const obstacleNodes = new Set(map.gameplay?.obstacleCandidateNodeIds || []);
      const processNodes = processGroups(map);
      const target = firstGuardTarget(map, route.path);

      svg.innerHTML = "";

      for (const edge of map.edges) {
        const polyline = document.createElementNS(NS, "polyline");
        polyline.setAttribute("points", pathPoints(map, edge, nodes));
        polyline.setAttribute("class", `edge${routeEdges.has(edge.edgeId) ? " route" : ""}`);
        polyline.style.stroke = routeEdges.has(edge.edgeId) ? "var(--accent)" : (routeColors[edge.routeType] || routeColors.BRANCH);
        const [from, to] = edgeEndpoints(edge);
        const title = document.createElementNS(NS, "title");
        title.textContent = `${edge.edgeId} ${from}-${to} ${edge.routeType} ${edge.distance}`;
        polyline.appendChild(title);
        svg.appendChild(polyline);
      }

      for (const node of map.nodes) {
        const group = document.createElementNS(NS, "g");
        const classes = ["node"];
        if (processNodes.has(node.nodeId)) classes.push("is-process");
        if (obstacleNodes.has(node.nodeId)) classes.push("is-obstacle");
        if (node.nodeId === target) classes.push("is-target");
        if (node.nodeId === selectedNodeId) classes.push("is-selected");
        group.setAttribute("class", classes.join(" "));
        group.setAttribute("transform", `translate(${node.x} ${node.y})`);
        group.addEventListener("click", () => {
          selectedNodeId = node.nodeId;
          render();
        });

        const ring = document.createElementNS(NS, "circle");
        ring.setAttribute("class", "node-ring");
        ring.setAttribute("r", node.nodeId === target ? "2.15" : "1.95");
        group.appendChild(ring);

        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("class", "node-dot");
        dot.setAttribute("r", "1.45");
        dot.style.fill = nodeColors[node.type || node.nodeType] || "#53626b";
        group.appendChild(dot);

        const text = document.createElementNS(NS, "text");
        text.textContent = node.nodeId.slice(1);
        group.appendChild(text);

        const title = document.createElementNS(NS, "title");
        const process = processNodes.get(node.nodeId);
        title.textContent = `${node.nodeId} ${node.name} ${node.type || node.nodeType}${process ? ` / ${process.processType}@${process.processRound}` : ""}`;
        group.appendChild(title);
        svg.appendChild(group);
      }
    }

    function renderDetails(entry) {
      const map = entry.map;
      const route = shortestPath(map);
      const target = firstGuardTarget(map, route.path);
      const resources = resourceGroups(map);
      const processNodes = map.gameplay?.processNodes || [];
      const obstacleNodes = map.gameplay?.obstacleCandidateNodeIds || [];
      const selected = selectedNodeId ? map.nodes.find(node => node.nodeId === selectedNodeId) : null;
      const selectedResources = selected ? resources.get(selected.nodeId) || [] : [];
      const selectedProcess = selected ? processNodes.find(row => row.nodeId === selected.nodeId) : null;
      const edgeChanges = selectedMapIndex === 0 ? [] : changedEdges(map);

      details.innerHTML = `
        <div class="section">
          <p class="eyebrow">${escapeHtml(entry.source)}</p>
          <h2>${escapeHtml(entry.label)} · ${escapeHtml(map.designVersion || "")}</h2>
          <div class="meta">
            <span>${escapeHtml(map.mapId || "")}</span>
            <span>${escapeHtml(map.mapName || "")}</span>
          </div>
        </div>
        <div class="section">
          <div class="stat-grid">
            <div class="stat"><b>${map.nodes.length}</b><span>nodes</span></div>
            <div class="stat"><b>${map.edges.length}</b><span>edges</span></div>
            <div class="stat"><b>${route.distance}</b><span>shortest cost</span></div>
            <div class="stat"><b>${target || "None"}</b><span>first guard target</span></div>
          </div>
        </div>
        <div class="section">
          <p class="eyebrow">Shortest Route</p>
          <p class="path">${escapeHtml(route.path.join(" -> "))}</p>
        </div>
        <div class="section">
          <p class="eyebrow">Legend</p>
          <div class="legend">
            <span class="legend-item"><i class="swatch" style="background:var(--road)"></i>ROAD</span>
            <span class="legend-item"><i class="swatch" style="background:var(--water)"></i>WATER</span>
            <span class="legend-item"><i class="swatch" style="background:var(--mountain)"></i>MOUNTAIN</span>
            <span class="legend-item"><i class="swatch" style="background:var(--branch)"></i>BRANCH</span>
            <span class="legend-item"><i class="swatch" style="background:var(--accent)"></i>shortest</span>
            <span class="legend-item"><i class="swatch" style="background:var(--gold)"></i>process</span>
          </div>
        </div>
        <div class="section">
          <p class="eyebrow">Selected Node</p>
          ${selected ? `
            <ul class="list">
              <li><code>${escapeHtml(selected.nodeId)}</code><span>${escapeHtml(selected.name)}</span></li>
              <li><span class="muted">type</span><code>${escapeHtml(selected.type || selected.nodeType)}</code></li>
              <li><span class="muted">coord</span><code>${selected.x}, ${selected.y}</code></li>
              <li><span class="muted">process</span><code>${selectedProcess ? `${selectedProcess.processType}@${selectedProcess.processRound}` : "-"}</code></li>
            </ul>
            <div class="pill-row" style="margin-top:10px">${selectedResources.length ? selectedResources.map(pill).join("") : pill("no resource")}</div>
          ` : `<p class="muted">No node selected</p>`}
        </div>
        <div class="section">
          <p class="eyebrow">Process Nodes</p>
          <div class="pill-row">${processNodes.map(row => pill(`${row.nodeId}:${row.processType}@${row.processRound}`)).join("")}</div>
        </div>
        <div class="section">
          <p class="eyebrow">Obstacle Candidates</p>
          <div class="pill-row">${obstacleNodes.map(pill).join("")}</div>
        </div>
        <div class="section">
          <p class="eyebrow">Resources</p>
          <ul class="list">
            ${[...resources.entries()].map(([nodeId, items]) => `<li><code>${escapeHtml(nodeId)}</code><span>${escapeHtml(items.join(", "))}</span></li>`).join("")}
          </ul>
        </div>
        <div class="section">
          <p class="eyebrow">Changed Edges vs Base</p>
          ${edgeChanges.length ? `<div class="pill-row">${edgeChanges.map(pill).join("")}</div>` : `<p class="muted">Base reference</p>`}
        </div>
      `;
    }

    function render() {
      renderTabs();
      const entry = maps[selectedMapIndex];
      renderMap(entry);
      renderDetails(entry);
    }

    render();
  </script>
</body>
</html>
"""


def main() -> None:
    maps = _load_maps()
    maps_json = json.dumps(maps, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT.write_text(HTML_TEMPLATE.replace("__MAPS_JSON__", maps_json), encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()

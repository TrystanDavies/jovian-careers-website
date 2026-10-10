"""Automatic drawing layout for flowsheets that have no positions yet.

Equipment is arranged left to right in layers (longest path from the
supplies, ignoring recycle connections), and ordered within each layer to
reduce crossings (barycentre heuristic).
"""

from __future__ import annotations

from collections import defaultdict

X0, Y0 = 140.0, 120.0
DX, DY = 240.0, 150.0


def _connections(blocks: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    src, dst = {}, {}
    for b in blocks:
        for key, mapping in (("outlets", src), ("inlets", dst)):
            for v in (b.get(key) or {}).values():
                for n in (v if isinstance(v, list) else [v]):
                    if n:
                        mapping[n] = b["name"]
    return src, dst


def auto_layout(data: dict) -> dict:
    """Return {"nodes": {name: {"x", "y", "rot", "flip"}}, "streams": {}} for a flowsheet dict."""
    blocks = data.get("blocks", [])
    names = [b["name"] for b in blocks]
    src, dst = _connections(blocks)
    succ: dict[str, list[str]] = defaultdict(list)
    pred: dict[str, list[str]] = defaultdict(list)
    for s, a in src.items():
        b = dst.get(s)
        if b and b != a:
            succ[a].append(b)
            pred[b].append(a)

    # remove back edges with a DFS from the sources (blocks without inputs first)
    order = sorted(names, key=lambda n: (len(pred[n]) > 0, names.index(n)))
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()

    def dfs(u: str) -> None:
        state[u] = 1
        for v in succ[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2

    for n in order:
        if n not in state:
            dfs(n)

    # longest-path layering on the acyclic graph
    layer: dict[str, int] = {}

    def depth(u: str, seen: set[str]) -> int:
        if u in layer:
            return layer[u]
        seen.add(u)
        ps = [p for p in pred[u] if (p, u) not in back and p not in seen]
        layer[u] = 0 if not ps else 1 + max(depth(p, seen) for p in ps)
        return layer[u]

    port_less = [b["name"] for b in blocks if not (b.get("inlets") or b.get("outlets"))]
    for n in names:
        if n not in port_less:
            depth(n, set())

    layers: dict[int, list[str]] = defaultdict(list)
    for n in names:
        if n not in port_less:
            layers[layer[n]].append(n)
    pos: dict[str, float] = {}
    for li in sorted(layers):
        for i, n in enumerate(layers[li]):
            pos[n] = i
    for _ in range(4):  # barycentre ordering sweeps
        for li in sorted(layers):
            if li == 0:
                continue

            def bary(n: str) -> float:
                ps = [pos[p] for p in pred[n] if p in pos and (p, n) not in back]
                return sum(ps) / len(ps) if ps else pos[n]

            layers[li].sort(key=bary)
            for i, n in enumerate(layers[li]):
                pos[n] = i

    nodes = {}
    for li, members in layers.items():
        for i, n in enumerate(members):
            nodes[n] = {"x": X0 + li * DX, "y": Y0 + i * DY, "rot": 0, "flip": False}
    max_y = max((v["y"] for v in nodes.values()), default=Y0)
    # equipment without connections (relief valves, Adjust) go near what they refer to, else along the bottom
    spare_x = X0
    for b in blocks:
        n = b["name"]
        if n not in port_less:
            continue
        p = b.get("params") or {}
        ref = src.get(p.get("stream", "")) or p.get("var_block") or p.get("target_block")
        if ref in nodes:
            nodes[n] = {"x": nodes[ref]["x"] + 90, "y": nodes[ref]["y"] - 90, "rot": 0, "flip": False}
        else:
            nodes[n] = {"x": spare_x, "y": max_y + DY, "rot": 0, "flip": False}
            spare_x += 160
    return {"nodes": nodes, "streams": {}}


def ensure_layout(data: dict) -> dict:
    """Fill in positions for any equipment that has none (keeps existing ones)."""
    layout = dict(data.get("layout") or {})
    nodes = dict(layout.get("nodes") or {})
    missing = [b["name"] for b in data.get("blocks", []) if b["name"] not in nodes]
    if missing:
        auto = auto_layout(data)["nodes"]
        if not nodes:
            nodes = auto
        else:
            max_y = max((v["y"] for v in nodes.values()), default=0.0)
            for i, n in enumerate(missing):
                nodes[n] = {"x": X0 + i * 180, "y": max_y + DY, "rot": 0, "flip": False}
    layout["nodes"] = nodes
    layout.setdefault("streams", {})
    return {**data, "layout": layout}

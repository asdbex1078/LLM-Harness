"""图分析：pageRank 与环检测（零第三方依赖，结果写进 index.json，2D / 3D / CLI 共用）。

为什么放在数据层而不是前端：
- pageRank 决定节点视觉权重，两个视图要一致，算一次存进 index 最省事也最稳定；
- 环检测是**数据质量问题**（"互相包含"这类方向矛盾），必须能在 `knowrary check` 里报出来，
  而不是只有打开网页才看得到。
社区发现（louvain）不在这里：它是"建议分组"，属于提议性质，放前端交互层。
"""
from __future__ import annotations

from collections import defaultdict

DAMPING = 0.85
ITERATIONS = 40
# 这些族里出现环就是知识建模错误：A 包含 B 又 B 包含 A、A 依赖 B 又 B 依赖 A
CYCLE_FAMILIES = ("结构", "依赖")


def pagerank(node_ids: list[str], edges: list[dict]) -> dict[str, float]:
    """pageRank（幂迭代），**按无向图算**。

    有向版会把"只进不出"的叶子顶到最高（实测 `栈帧` 排第一但度数很低），
    而我们要的是"骨干知识点"——知识网络里关系是双向可达的，无向更贴近直觉。
    悬挂节点的权重均分给全图，保证总和为 1。
    """
    if not node_ids:
        return {}
    ids = sorted(node_ids)
    n = len(ids)
    known = set(node_ids)
    out_links: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e["source"] in known and e["target"] in known:
            out_links[e["source"]].append(e["target"])
            out_links[e["target"]].append(e["source"])
    rank = {i: 1.0 / n for i in ids}
    for _ in range(ITERATIONS):
        nxt = {i: (1 - DAMPING) / n for i in ids}
        dangling = 0.0
        for node in ids:
            targets = out_links.get(node)
            if not targets:
                dangling += rank[node]
                continue
            share = DAMPING * rank[node] / len(targets)
            for target in targets:
                nxt[target] += share
        if dangling:
            spread = DAMPING * dangling / n
            for node in ids:
                nxt[node] += spread
        rank = nxt
    return rank


def find_cycles(edges: list[dict], families: tuple[str, ...] = CYCLE_FAMILIES,
                limit: int = 50, max_len: int = 3) -> list[dict]:
    """找**同族内的短环**：A 包含 B 又 B 包含 A 这种方向矛盾。

    只在单个族内部找、且限制长度（默认 ≤3），因为跨族的长环（CPU → … 17 个节点 → CPU）
    在知识网络里是正常的，报出来只会淹没真正的错误。
    """
    out: list[dict] = []
    for family in families:
        for cycle in _cycles_in_family(edges, family, max_len):
            if len(out) >= limit:
                return out
            out.append({"family": family, "path": cycle})
    return out


def _cycles_in_family(edges: list[dict], family: str, max_len: int) -> list[list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e["family"] == family:
            graph[e["source"]].append(e["target"])
    for node in graph:
        graph[node].sort()

    # 长度受限，直接枚举所有 ≤max_len 的回路，比着色 DFS 更直观也更好去重
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def walk(start: str, node: str, path: list[str]) -> None:
        for nxt in graph.get(node, []):
            if nxt == start and len(path) >= 2:
                key = tuple(_normalize_cycle(path + [start]))
                if key not in seen:
                    seen.add(key)
                    cycles.append(path + [start])
            elif nxt not in path and len(path) < max_len:
                walk(start, nxt, path + [nxt])

    for start in sorted(graph):
        walk(start, start, [start])
    return cycles


def _normalize_cycle(cycle: list[str]) -> list[str]:
    """环的起点无所谓：旋转到字典序最小的节点开头，方便去重。"""
    body = cycle[:-1]
    if not body:
        return cycle
    start = body.index(min(body))
    return body[start:] + body[:start]

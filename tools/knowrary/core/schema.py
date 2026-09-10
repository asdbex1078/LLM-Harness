"""index.json 契约校验：生成器的自检，也是前端/服务读到 index 时的第一道闸。

这里查的是**结构不变量**（字段齐全、边两端存在、邻接表与边一致、stub 集合正确），
而不是知识层的对错——知识层诊断在 index 的 errors/warnings 里。
"""
from __future__ import annotations

from .index import INDEX_SCHEMA_VERSION, content_hash

TOP_KEYS = {
    "schema_version": int, "revision": int, "generated_at": str, "content_hash": str,
    "nodes": list, "edges": list, "families": list, "stubs": list,
    "stats": dict, "errors": list, "warnings": list,
}
NODE_KEYS = {"id": str, "out": list, "in": list, "degree": int}
EDGE_KEYS = {"id": str, "source": str, "target": str, "type": str, "family": str, "declared_in": list}


def validate_index(data: dict) -> list[str]:
    """返回问题列表，空列表表示契约合法。"""
    problems = _check_top(data)
    if problems:
        return problems
    nodes, edges = data["nodes"], data["edges"]
    problems += _check_records(nodes, NODE_KEYS, "node")
    problems += _check_records(edges, EDGE_KEYS, "edge")
    if problems:
        return problems
    problems += _check_graph(nodes, edges, data)
    problems += _check_derived(data)
    return problems


def _check_top(data: dict) -> list[str]:
    problems = []
    for key, typ in TOP_KEYS.items():
        if key not in data:
            problems.append(f"缺少顶层字段 `{key}`")
        elif not isinstance(data[key], typ):
            problems.append(f"顶层字段 `{key}` 类型应为 {typ.__name__}")
    if not problems and data["schema_version"] != INDEX_SCHEMA_VERSION:
        problems.append(f"schema_version {data['schema_version']} != {INDEX_SCHEMA_VERSION}")
    if not problems and data["revision"] < 1:
        problems.append("revision 必须从 1 开始")
    return problems


def _check_records(records: list, spec: dict, kind: str) -> list[str]:
    problems = []
    seen = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            problems.append(f"{kind}[{i}] 不是对象")
            continue
        for key, typ in spec.items():
            if key not in rec:
                problems.append(f"{kind}[{i}] 缺少 `{key}`")
            elif not isinstance(rec[key], typ):
                problems.append(f"{kind} `{rec.get('id', i)}` 的 `{key}` 类型应为 {typ.__name__}")
        rid = rec.get("id")
        if rid in seen:
            problems.append(f"{kind} id 重复：`{rid}`")
        seen.add(rid)
    return problems


def _check_graph(nodes: list[dict], edges: list[dict], data: dict) -> list[str]:
    problems = []
    by_id = {n["id"]: n for n in nodes}
    for e in edges:
        if e["id"] != f"{e['source']}->{e['target']}#{e['type']}":
            problems.append(f"edge id 与端点不一致：`{e['id']}`")
        for endpoint, side in ((e["source"], "out"), (e["target"], "in")):
            node = by_id.get(endpoint)
            if node is None:
                problems.append(f"edge `{e['id']}` 的端点 `{endpoint}` 不在 nodes 中")
            elif e["id"] not in node[side]:
                problems.append(f"edge `{e['id']}` 未出现在节点 `{endpoint}` 的 {side} 邻接表")
        if not e["declared_in"]:
            problems.append(f"edge `{e['id']}` 没有 declared_in")
    edge_ids = {e["id"] for e in edges}
    for n in nodes:
        for side in ("out", "in"):
            for eid in n[side]:
                if eid not in edge_ids:
                    problems.append(f"节点 `{n['id']}` 的 {side} 指向不存在的边 `{eid}`")
        if n["degree"] != len(n["out"]) + len(n["in"]):
            problems.append(f"节点 `{n['id']}` 的 degree 与邻接表不一致")
    if sorted(data["stubs"]) != sorted(n["id"] for n in nodes if n.get("stub")):
        problems.append("stubs 列表与 nodes 上的 stub 标记不一致")
    return problems


def _check_derived(data: dict) -> list[str]:
    problems = []
    if content_hash(data) != data["content_hash"]:
        problems.append("content_hash 与内容不匹配")
    stats = data["stats"]
    for key, expect in (("nodes", len(data["nodes"])), ("edges", len(data["edges"])),
                        ("stubs", len(data["stubs"])), ("errors", len(data["errors"])),
                        ("warnings", len(data["warnings"]))):
        if stats.get(key) != expect:
            problems.append(f"stats.{key}={stats.get(key)} 与实际 {expect} 不符")
    families = {f["name"] for f in data["families"]}
    for e in data["edges"]:
        if e["family"] not in families:
            problems.append(f"edge `{e['id']}` 的族 `{e['family']}` 未登记在 families")
    return problems

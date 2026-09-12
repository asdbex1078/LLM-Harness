"""index.json 生成：vault 全量重建，方向归一 + 反链邻接 + stub 识别 + 诊断。

契约见设计文档 3.4.1。要点：
- index.json 是**派生缓存**，可以随时删掉重建；知识真相源只有 md。
- 内容哈希决定 revision：同一份 vault 重复生成结果逐字节一致，revision 与
  generated_at 都不动，避免无谓触发 layout 的乐观并发校验。
- 边只存归一化后的正向边，反链通过节点上的 in/out 邻接表表达，不重复存储。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .analysis import find_cycles, pagerank
from .diagnostics import Diagnostics
from .mdio import RE_LINK, json_safe, load_json
from .parser import Node, load_vault, validate_frontmatter
from .relations import NormalizedEdge, RelationTypes, load_relation_types, normalize_direction

INDEX_SCHEMA_VERSION = 1
NODE_FM_FIELDS = ("name", "field", "type", "status", "desc", "year", "start_year", "end_year",
                  "aliases", "tags", "learned", "source")


@dataclass
class BuildContext:
    """一次索引构建的全部中间产物，避免在辅助函数间传 6 个参数。"""

    vault: Path
    rt: RelationTypes
    diags: Diagnostics
    nodes: dict[str, Node]
    edges: dict[str, NormalizedEdge]
    virtual: dict[str, list[str]]   # 被引用但无 md 文件的节点 → 引用它的文件


@dataclass
class IndexResult:
    data: dict
    diags: Diagnostics
    changed: bool          # 与磁盘上的 index.json 相比内容是否变化

    @property
    def stats(self) -> dict:
        return self.data["stats"]


def build_index(vault: Path, previous: dict | None = None) -> IndexResult:
    """全量解析 vault 并生成 index 数据结构（不写盘）。"""
    nodes, diags = load_vault(vault)
    ctx = BuildContext(vault, load_relation_types(vault), diags, nodes, {}, {})
    for node in nodes.values():
        validate_frontmatter(vault, node, diags)
    _collect_edges(ctx)
    _resolve_targets(ctx)
    _warn_history_gaps(ctx)
    _warn_dead_body_links(ctx)
    payload = _assemble(ctx)
    _warn_cycles(payload, ctx)
    return _finalize(payload, diags, previous)


def _collect_edges(ctx: BuildContext) -> None:
    """归一方向、按 (源,目标,类型) 去重，把"两侧都写"合并成一条边并记录声明文件。"""
    rt, diags, out = ctx.rt, ctx.diags, ctx.edges
    for node in sorted(ctx.nodes.values(), key=lambda n: n.id):
        rel = node.path.relative_to(ctx.vault).as_posix()
        for raw in node.edges:
            src, tgt, typ = normalize_direction(raw, rt)
            if not rt.known(raw.type):
                diags.warn("unknown_type", f"未登记类型 `{raw.type}` → [[{raw.target}]]，"
                                           f"按 {rt.default_family} 渲染", file=rel, node=node.id)
            if src == tgt:
                diags.warn("self_loop", f"自环关系 `{raw.type} [[{raw.target}]]`，已忽略",
                           file=rel, node=node.id)
                continue
            edge = NormalizedEdge(src, tgt, typ, rt.family(typ), symmetric=rt.symmetric(typ))
            existing = out.get(edge.id)
            if existing is None:
                edge.raw_types = [raw.type]
                edge.year, edge.note, edge.declared_in = raw.year, raw.note, [rel]
                out[edge.id] = edge
            else:
                _merge_edge(existing, raw, rel, diags, node.id)


def _merge_edge(existing: NormalizedEdge, raw, rel: str, diags: Diagnostics, node_id: str) -> None:
    """同一条归一化边被第二次声明：合并年份/说明，重复维护给警告。"""
    if raw.type not in existing.raw_types:
        existing.raw_types.append(raw.type)
    if existing.year is None:
        existing.year = raw.year
    if not existing.note:
        existing.note = raw.note
    if rel in existing.declared_in:
        diags.warn("duplicate_relation", f"同一文件重复声明 `{raw.type} [[{raw.target}]]`",
                   file=rel, node=node_id, edge=existing.id)
        return
    existing.declared_in.append(rel)
    kind = "对称关系两侧都写了" if existing.symmetric else "与对方的互逆关系重复维护"
    diags.warn("duplicate_relation", f"{kind}：`{raw.type} [[{raw.target}]]`（另一侧 "
                                     f"{existing.declared_in[0]}），索引已合并为一条边",
               file=rel, node=node_id, edge=existing.id)


def _resolve_targets(ctx: BuildContext) -> None:
    """未创建的引用目标 → 虚拟 stub 节点（不丢边），记录 {stub id: 引用来源文件}。"""
    virtual: dict[str, list[str]] = defaultdict(list)
    for edge in ctx.edges.values():
        for endpoint in (edge.source, edge.target):
            if endpoint in ctx.nodes:
                continue
            for rel in edge.declared_in:
                if rel not in virtual[endpoint]:
                    virtual[endpoint].append(rel)
                    ctx.diags.error("unknown_target", f"关系目标 [[{endpoint}]] 不存在（{edge.type}），"
                                                      f"已按 stub 占位", file=rel, edge=edge.id)
    ctx.virtual = dict(virtual)


def _warn_history_gaps(ctx: BuildContext) -> None:
    """演化族边两端都没有年份时进不了历史视图，提前提示。"""
    def year_of(nid: str):
        node = ctx.nodes.get(nid)
        return node.fm.get("year") if node else None

    for edge in ctx.edges.values():
        if edge.family != "演化" or edge.year is not None:
            continue
        if year_of(edge.source) is None and year_of(edge.target) is None:
            ctx.diags.warn("evolution_without_year",
                       f"演化边 `{edge.source} {edge.type} {edge.target}` 两端都无 year，"
                           f"不会进入历史视图", file=edge.declared_in[0], edge=edge.id)


def _warn_dead_body_links(ctx: BuildContext) -> None:
    for node in ctx.nodes.values():
        rel = node.path.relative_to(ctx.vault).as_posix()
        for link in sorted(set(RE_LINK.findall(node.body))):
            if link not in ctx.nodes and link not in ctx.virtual:
                ctx.diags.warn("dead_body_link", f"正文链接 [[{link}]] 不存在", file=rel, node=node.id)


def _node_payload(vault: Path, node: Node) -> dict:
    d = {"id": node.id, "path": node.path.relative_to(vault).as_posix(), "digest": node.digest}
    for k in NODE_FM_FIELDS:
        v = node.fm.get(k)
        if v not in (None, "", []):
            d[k] = json_safe(v)
    d.setdefault("status", "active")
    if node.is_stub:
        d["stub"] = True
    return d


def _virtual_payload(nid: str, referrers: list[str]) -> dict:
    """被引用但没有 md 文件的节点：占位进图，标记 virtual，等待补写。"""
    return {"id": nid, "name": nid, "desc": "待补充", "status": "stub",
            "stub": True, "virtual": True, "referrers": sorted(referrers)}


def _assemble(ctx: BuildContext) -> dict:
    """拼装 nodes/edges/families/stubs/stats，并挂上 in/out 邻接。"""
    payloads = [_node_payload(ctx.vault, n) for n in ctx.nodes.values()]
    payloads += [_virtual_payload(nid, refs) for nid, refs in ctx.virtual.items()]
    payloads.sort(key=lambda d: d["id"])
    edge_list = [e.to_dict() for e in sorted(ctx.edges.values(), key=lambda e: e.id)]
    out_map, in_map = defaultdict(list), defaultdict(list)
    for e in edge_list:
        out_map[e["source"]].append(e["id"])
        in_map[e["target"]].append(e["id"])
    ranks = pagerank([d["id"] for d in payloads], edge_list)
    top = max(ranks.values(), default=1) or 1
    for d in payloads:
        d["out"], d["in"] = out_map.get(d["id"], []), in_map.get(d["id"], [])
        d["degree"] = len(d["out"]) + len(d["in"])
        # rank：pageRank 原值（总和 1）；weight：归一到 0~1，前端直接拿来定节点大小
        d["rank"] = round(ranks.get(d["id"], 0), 6)
        d["weight"] = round(ranks.get(d["id"], 0) / top, 4)
    return {
        "nodes": payloads,
        "edges": edge_list,
        "families": _families_payload(ctx.rt, edge_list),
        "stubs": sorted(d["id"] for d in payloads if d.get("stub")),
        "stats": _stats(payloads, edge_list, ctx.virtual, ctx.diags),
        "errors": ctx.diags.sorted_dicts("error"),
        "warnings": ctx.diags.sorted_dicts("warning"),
    }


def _warn_cycles(payload: dict, ctx: BuildContext) -> None:
    """同族短环 = 方向矛盾（A 包含 B 又 B 包含 A），写进警告，`knowrary check` 能直接看到。"""
    declared = {e["id"]: e.get("declared_in", [""])[0] for e in payload["edges"]}
    for cycle in find_cycles(payload["edges"]):
        path = cycle["path"]
        first = f"{path[0]}->{path[1]}#"
        file = next((f for eid, f in declared.items() if eid.startswith(first)), "")
        ctx.diags.warn("relation_cycle",
                       f"{cycle['family']}族存在环：{' → '.join(path)}（方向矛盾，需要删掉其中一条）",
                       file=file)
    payload["errors"] = ctx.diags.sorted_dicts("error")
    payload["warnings"] = ctx.diags.sorted_dicts("warning")
    payload["stats"]["warnings"] = len(ctx.diags.warnings)
    payload["stats"]["cycles"] = len(find_cycles(payload["edges"]))


def _families_payload(rt: RelationTypes, edge_list: list[dict]) -> list[dict]:
    per_family: dict[str, Counter] = defaultdict(Counter)
    for e in edge_list:
        per_family[e["family"]][e["type"]] += 1
    known: dict[str, list[str]] = defaultdict(list)
    for t, meta in rt.types.items():
        known[meta["family"]].append(t)
    families = list(dict.fromkeys(list(rt.families) + sorted(per_family)))
    return [{"name": fam,
             "default": fam == rt.default_family,
             "types": sorted(set(known.get(fam, [])) | set(per_family[fam])),
             "edge_count": sum(per_family[fam].values())} for fam in families]


def _stats(payloads: list[dict], edge_list: list[dict], virtual: dict, diags: Diagnostics) -> dict:
    return {
        "nodes": len(payloads),
        "edges": len(edge_list),
        "stubs": sum(1 for d in payloads if d.get("stub")),
        "missing_targets": len(virtual),
        "with_year": sum(1 for d in payloads if d.get("year")),
        "errors": len(diags.errors),
        "warnings": len(diags.warnings),
        "by_family": dict(sorted(Counter(e["family"] for e in edge_list).items())),
        "by_field": dict(sorted(Counter(d.get("field", "(未指定)") for d in payloads).items())),
    }


def content_hash(payload: dict) -> str:
    body = {k: v for k, v in payload.items()
            if k not in ("schema_version", "revision", "generated_at", "content_hash")}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finalize(payload: dict, diags: Diagnostics, previous: dict | None) -> IndexResult:
    """内容哈希相同 → 沿用旧 revision 与 generated_at（幂等）；不同 → revision +1。"""
    digest = content_hash(payload)
    prev_rev = int(previous.get("revision", 0)) if previous else 0
    unchanged = bool(previous) and previous.get("content_hash") == digest
    head = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "revision": prev_rev if unchanged else prev_rev + 1,
        "generated_at": previous["generated_at"] if unchanged and previous.get("generated_at")
                        else dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "content_hash": digest,
    }
    return IndexResult({**head, **payload}, diags, changed=not unchanged)


def load_previous(path: Path) -> dict | None:
    """读磁盘上的 index.json；损坏或缺失都当"没有"，下次全量重建。"""
    if not path.exists():
        return None
    try:
        data = load_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def index_path(vault: Path) -> Path:
    return vault / ".knowrary" / "index.json"

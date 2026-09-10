"""layout.json：初始布局生成与结构常量（零第三方依赖，CLI 与服务层共用）。

layout 是"结构视图的用户数据"，与 md（知识真相源）、index（派生缓存）三者互不覆盖。
这里只负责首次生成一张能看的图：按 field 建顶层分组、按 nodes/ 子目录建二级分组、
组内网格排列。之后所有位置都由人工拖拽决定，不做自动重排。
虚拟 stub（被引用但没有 md 文件）不进 layout——它们还不是文件，等补写后再进。
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Iterable

LAYOUT_SCHEMA_VERSION = 2
NODE_W, NODE_H = 160.0, 60.0
CELL_W, CELL_H = NODE_W + 40, NODE_H + 40      # 节点格子（含间距）
PAD_X, PAD_TOP, PAD_BOT = 24.0, 44.0, 24.0     # 分组内边距（顶部留标题位）
GROUP_GAP, FIELD_GAP = 80.0, 200.0
MAX_COLS = 6
MAX_ROW_W = 2600.0                             # 二级分组换行的行宽上限


def layout_path(vault: Path) -> Path:
    return vault / ".knowrary" / "layout.json"


def empty_layout() -> dict:
    return {"schema_version": LAYOUT_SCHEMA_VERSION, "revision": 0, "updated_at": None,
            "viewport": {"zoom": 0.8, "cx": 0.0, "cy": 0.0},
            "groups": {}, "nodes": {}, "refs": [], "notes": [], "images": [], "edges": {}}


def bucket_nodes(index: dict) -> dict[str, dict[str, list[str]]]:
    """{field: {子目录: [节点 id]}}。fields/ 与 nodes/ 根下的文件归入 "" 桶（直接挂顶层分组）。"""
    out: dict[str, dict[str, list[str]]] = {}
    for node in index["nodes"]:
        if node.get("virtual"):
            continue
        field = node.get("field") or "(未指定)"
        parts = (node.get("path") or "").split("/")
        sub = parts[1] if len(parts) > 2 and parts[0] == "nodes" else ""
        out.setdefault(field, {}).setdefault(sub, []).append(node["id"])
    for subs in out.values():
        for ids in subs.values():
            ids.sort()
    return out


def grid_shape(count: int) -> tuple[int, int]:
    cols = max(1, min(MAX_COLS, math.ceil(math.sqrt(count))))
    return cols, math.ceil(count / cols)


def group_size(count: int) -> tuple[float, float]:
    cols, rows = grid_shape(count)
    return cols * CELL_W - 40 + 2 * PAD_X, rows * CELL_H - 40 + PAD_TOP + PAD_BOT


def place_grid(ids: Iterable[str], x0: float, y0: float, doc: dict, group: str | None) -> None:
    """把一批节点按网格放进 (x0, y0) 起点的分组内。"""
    ids = list(ids)
    cols, _ = grid_shape(len(ids))
    for i, nid in enumerate(ids):
        doc["nodes"][nid] = {"x": x0 + PAD_X + (i % cols) * CELL_W,
                             "y": y0 + PAD_TOP + (i // cols) * CELL_H,
                             "w": NODE_W, "h": NODE_H, "group": group, "state": "final"}


def _merge_same_name_sub(field: str, subs: dict[str, list[str]]) -> dict[str, list[str]]:
    """与 field 同名的子目录（如 nodes/AI-Agent 在 field AI-Agent 下）不再套一层同名分组。"""
    if field not in subs:
        return subs
    merged = {k: v for k, v in subs.items() if k != field}
    merged[""] = sorted(merged.get("", []) + subs[field])
    return merged


def _add_child_groups(field: str, subs: dict[str, list[str]], top_id: str,
                      origin: tuple[float, float], doc: dict) -> tuple[float, float]:
    """在顶层分组里横向摆放二级分组，超过行宽换行。返回顶层分组的内容尺寸。"""
    x0, y0 = origin
    cx, cy, row_h, used_w = x0 + PAD_X, y0 + PAD_TOP, 0.0, 0.0
    for sub, ids in sorted(subs.items()):
        w, h = group_size(len(ids))
        if cx > x0 + PAD_X and cx + w > x0 + MAX_ROW_W:
            cx, cy, row_h = x0 + PAD_X, cy + row_h + GROUP_GAP, 0.0
        gid = f"g-{field}--{sub}" if sub else top_id
        if sub:
            doc["groups"][gid] = {"name": sub, "x": cx, "y": cy, "w": w, "h": h, "parent": top_id,
                                  "collapsed": False, "pinned": None, "color": None}
        place_grid(ids, cx, cy, doc, gid)
        cx, row_h = cx + w + GROUP_GAP, max(row_h, h)
        used_w = max(used_w, cx - x0 - GROUP_GAP)
    return used_w + PAD_X, (cy + row_h) - y0 + PAD_BOT


def build_initial_layout(index: dict) -> dict:
    """按 field / 子目录两级分组生成初始布局，顶层分组自上而下排列。"""
    doc = empty_layout()
    y = 0.0
    for field, subs in sorted(bucket_nodes(index).items()):
        top_id = f"g-{field}"
        subs = _merge_same_name_sub(field, subs)
        doc["groups"][top_id] = {"name": field, "x": 0.0, "y": y, "w": 0.0, "h": 0.0, "parent": None,
                                 "collapsed": False, "pinned": None, "color": "#eef2f8"}
        w, h = _add_child_groups(field, subs, top_id, (0.0, y), doc)
        doc["groups"][top_id]["w"], doc["groups"][top_id]["h"] = w, h
        y += h + FIELD_GAP
    return doc


def find_orphans(doc: dict, index: dict, vault: Path) -> list[dict]:
    """layout 里引用不到的记录：只报告，不删除（md 删了节点也要留住用户的位置数据）。"""
    real = {n["id"] for n in index["nodes"] if not n.get("virtual")}
    edges = {e["id"] for e in index["edges"]}
    out: list[dict] = []
    for nid in sorted(set(doc.get("nodes", {})) - real):
        out.append({"kind": "node", "id": nid, "reason": "索引里没有这个节点（md 可能已删除或改名）"})
    for ref in doc.get("refs", []):
        if ref.get("target") not in real:
            out.append({"kind": "ref", "id": ref.get("id"), "reason": f"引用卡指向的节点 `{ref.get('target')}` 不存在"})
    for key in sorted(set(doc.get("edges", {})) - edges):
        out.append({"kind": "edge", "id": key, "reason": "这条边已不在索引中，手工拐点悬空"})
    for image in doc.get("images", []):
        if not (vault / str(image.get("file", ""))).exists():
            out.append({"kind": "image", "id": image.get("id"), "reason": f"图片文件不存在：{image.get('file')}"})
    groups = set(doc.get("groups", {}))
    for gid, group in doc.get("groups", {}).items():
        if group.get("parent") and group["parent"] not in groups:
            out.append({"kind": "group", "id": gid, "reason": f"父分组 `{group['parent']}` 不存在"})
    for nid, node in doc.get("nodes", {}).items():
        if node.get("group") and node["group"] not in groups:
            out.append({"kind": "node_group", "id": nid, "reason": f"所属分组 `{node['group']}` 不存在"})
    return out


def stamp(doc: dict) -> dict:
    """revision +1 并更新时间戳（写盘前调用）。"""
    doc["schema_version"] = LAYOUT_SCHEMA_VERSION
    doc["revision"] = int(doc.get("revision", 0)) + 1
    doc["updated_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return doc

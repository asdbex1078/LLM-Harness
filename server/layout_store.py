"""layout.json 的读写：初始生成、部分合并（PATCH）、revision 乐观并发、原子写、孤立引用诊断。

三条硬约束（设计文档 3.4.2）：
1. 客户端必须带 base_revision；与服务端不一致就拒绝，不做"最后写入者赢"。
2. 写盘走临时文件 + rename（core.write_json_atomic），崩溃不会留半个 JSON。
3. 引用不到的节点/分组/图片只进诊断列表，绝不自动删除用户数据。
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

from .contracts import LAYOUT_SCHEMA_VERSION, EdgeStyle, GroupBox, LayoutDoc, LayoutPatch, NodeBox
from .paths import core, layout_path

_LOCK = threading.Lock()   # layout.json 的写串行化（读-改-写必须原子）


class LayoutBroken(Exception):
    """layout.json 存在但读不出来：保留原文件，交给人处理，不覆盖。"""


class RevisionConflict(Exception):
    def __init__(self, current: LayoutDoc):
        super().__init__(f"base_revision 过期，当前 revision {current.revision}")
        self.current = current


class PatchRejected(Exception):
    """客户端补丁本身不合法（新增条目缺必填字段、引用了不存在的分组等）。"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_layout(vault: Path) -> LayoutDoc | None:
    """读 layout.json；文件不存在返回 None，内容坏了抛 LayoutBroken。"""
    path = layout_path(vault)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise LayoutBroken(f"{path} 解析失败：{exc}") from exc
    try:
        return LayoutDoc.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        raise LayoutBroken(f"{path} 不符合 layout 契约：{exc}") from exc


def initial_layout(index: dict) -> LayoutDoc:
    """core 生成的初始布局（纯 dict）→ 过一遍契约校验，保证服务端产出的也合法。"""
    return LayoutDoc.model_validate(core.build_initial_layout(index))


def write_layout(vault: Path, doc: LayoutDoc) -> LayoutDoc:
    """revision +1、更新时间戳后原子写盘。"""
    doc.schema_version = LAYOUT_SCHEMA_VERSION
    doc.revision += 1
    doc.updated_at = _now()
    core.write_json_atomic(layout_path(vault), doc.model_dump())
    return doc


def load_or_init(vault: Path, index: dict) -> tuple[LayoutDoc, bool]:
    """没有 layout.json 时按 field / 子目录生成初始布局并落盘。返回 (布局, 是否刚生成)。"""
    with _LOCK:
        doc = read_layout(vault)
        if doc is not None:
            return doc, False
        return write_layout(vault, initial_layout(index)), True


def apply_patch(vault: Path, patch: LayoutPatch, index: dict) -> tuple[LayoutDoc, list[dict[str, Any]]]:
    """读-校验-合并-写，全程持锁。返回 (新布局, 孤立引用诊断)。"""
    with _LOCK:
        doc = read_layout(vault)
        if doc is None:
            doc = initial_layout(index)
        if patch.base_revision != doc.revision:
            raise RevisionConflict(doc)
        _merge(doc, patch)
        _assert_group_refs(doc)
        return write_layout(vault, doc), find_orphans(doc, index, vault)


def _merge(doc: LayoutDoc, patch: LayoutPatch) -> None:
    """按 JSON Merge Patch 语义合并：条目为 null 删除，否则字段级合并。"""
    if patch.viewport is not None:
        doc.viewport = patch.viewport
    _merge_entries(doc.groups, patch.groups, GroupBox, "分组")
    _merge_entries(doc.nodes, patch.nodes, NodeBox, "节点")
    _merge_entries(doc.edges, patch.edges, EdgeStyle, "边")
    for name in ("refs", "notes", "images"):
        given = getattr(patch, name)
        if given is not None:
            setattr(doc, name, given)


def _merge_entries(target: dict, given: dict | None, model, label: str) -> None:
    if not given:
        return
    for key, value in given.items():
        if value is None:
            target.pop(key, None)
            continue
        fields = value.model_dump(exclude_unset=True)
        if key in target:
            target[key] = model.model_validate({**target[key].model_dump(), **fields})
            continue
        try:
            target[key] = model.model_validate(fields)
        except Exception as exc:
            raise PatchRejected(f"新增{label} `{key}` 的字段不完整：{exc}") from exc


def _assert_group_refs(doc: LayoutDoc) -> None:
    """分组引用必须闭合：父分组、节点所属分组都得存在，否则画布会渲染出悬空元素。"""
    known = set(doc.groups)
    for gid, group in doc.groups.items():
        if group.parent and group.parent not in known:
            raise PatchRejected(f"分组 `{gid}` 的父分组 `{group.parent}` 不存在")
        if group.parent == gid:
            raise PatchRejected(f"分组 `{gid}` 不能以自己为父分组")
    for nid, node in doc.nodes.items():
        if node.group and node.group not in known:
            raise PatchRejected(f"节点 `{nid}` 的分组 `{node.group}` 不存在")


def find_orphans(doc: LayoutDoc, index: dict, vault: Path) -> list[dict[str, Any]]:
    """委托给 core：CLI 的 `knowrary layout check` 与服务端用同一套判定。"""
    return core.find_orphans(doc.model_dump(), index, vault)
